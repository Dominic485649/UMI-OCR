# =========================================================
# =======                 Web服务器                 ========
# ======= http接口可复用于跨进程命令行、防止多开等方面 ========
# =========================================================

import json
import ipaddress
from urllib.parse import urlsplit

from PySide6.QtCore import QThreadPool, QRunnable
from PySide6.QtQml import QJSValue
from wsgiref.simple_server import make_server, WSGIServer

from umi_log import logger
from ..utils import pre_configs
from ..utils.call_func import CallFunc
from bottle import Bottle, ServerAdapter, request, HTTPResponse, response, BaseRequest
from .cmd_server import CmdServer
from . import ocr_server
from . import qrcode_server
from . import doc_server

BaseRequest.MEMFILE_MAX = 104857600  # 超过100 MB后将上传内容转存临时文件
MAX_REQUEST_SIZE = 104857600

UmiWeb = Bottle()
Host = "127.0.0.1"  # 由qml设置


# 允许跨域
@UmiWeb.hook("before_request")
def _limit_request_body():
    if request.content_length > MAX_REQUEST_SIZE:
        raise HTTPResponse("Request body exceeds the 100 MB limit.", status=413)


@UmiWeb.hook("after_request")
def _validate_after():
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, OPTIONS"


@UmiWeb.route("/", method="OPTIONS")
@UmiWeb.route("/<path:path>", method="OPTIONS")
def _preflight(path=None):
    requested_method = request.environ.get("HTTP_ACCESS_CONTROL_REQUEST_METHOD")
    allowed_methods = {"GET", "POST", "PUT", "OPTIONS"}
    if requested_method and requested_method.upper() not in allowed_methods:
        return HTTPResponse(status=405)
    return HTTPResponse(status=204)


# ============================== 基础路由 ==============================


@UmiWeb.route("/")
@UmiWeb.route("/umiocr")
def _umiocr():
    from umi_about import UmiAbout  # 项目信息

    return UmiAbout["fullname"]


# 跨进程接收命令行参数
@UmiWeb.route("/argv", method="POST")
def _argv():
    addr = request.environ.get("REMOTE_ADDR")
    try:
        is_loopback = ipaddress.ip_address(addr).is_loopback
    except (TypeError, ValueError):
        is_loopback = False
    if not is_loopback:
        msg = "Unauthorized access. Only local requests are allowed.\n此接口只允许本机访问。"
        return HTTPResponse(msg, status=401)
    # A remote website's fetch also connects from loopback.  The network
    # address alone does not authenticate it as a local CLI invocation.
    # Keep ordinary CLI clients without Origin working, but require browsers
    # to originate from this service itself before dispatching commands.
    origin = request.environ.get("HTTP_ORIGIN")
    if origin is not None:
        try:
            source = urlsplit(origin)
            target = urlsplit(request.url)
            source_port = source.port or (443 if source.scheme == "https" else 80)
            target_port = target.port or (443 if target.scheme == "https" else 80)
            same_origin = (
                source.scheme in ("http", "https")
                and source.scheme == target.scheme
                and source.hostname == target.hostname
                and source_port == target_port
                and not source.username and not source.password
                and not source.path and not source.query and not source.fragment
            )
        except ValueError:
            same_origin = False
        if not same_origin:
            return HTTPResponse("Browser command requests must use the service's own origin.", status=403)
    try:
        data = request.json
    except Exception:
        return HTTPResponse("Invalid JSON request.", status=400)
    if not isinstance(data, list) or any(not isinstance(arg, str) for arg in data):
        return HTTPResponse("Command arguments must be a JSON array of strings.", status=400)
    res = CmdServer.execute(data)
    if isinstance(res, QJSValue):
        res = res.toVariant()
    return res if isinstance(res, str) else json.dumps(res, ensure_ascii=False)


ocr_server.init(UmiWeb)
qrcode_server.init(UmiWeb)
doc_server.init(UmiWeb)

# =============== 自定义服务器适配器，方便控制服务终止 ==============================
QmlCallback = None  # qml回调函数


class _WSGIRefServer(ServerAdapter):
    # https://stackoverflow.com/questions/11282218/bottle-web-framework-how-to-stop

    class CustomWSGIServer(WSGIServer):  # 定制服务器
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.activeConnections = set()  # 当前活跃连接

        def process_request(self, request, client_address):
            # 记录活跃的连接
            self.activeConnections.add(request)
            try:
                super().process_request(request, client_address)
            finally:
                self.activeConnections.discard(request)

        def close_all_request(self):  # 关闭所有活跃的连接
            import socket

            for request in tuple(self.activeConnections):
                try:
                    request.shutdown(socket.SHUT_RDWR)
                    request.close()
                    logger.info(f"强制关闭连接。 request: {request}")
                except OSError:
                    pass
                except Exception:
                    logger.error(
                        f"强制连接异常。 request: {request}",
                        exc_info=True,
                        stack_info=True,
                    )

    def run(self, handler):
        import atexit  # 退出处理

        atexit.register(self.stop)  # 注册程序终止时停止线程
        self.port = pre_configs.getValue("server_port")  # 提取记录的端口号
        self.host = Host
        # 找到一个可用的端口号
        while True:
            try:
                self.server = make_server(
                    self.host,
                    self.port,
                    handler,
                    server_class=self.CustomWSGIServer,
                    **self.options,
                )
                break
            except OSError:  # 当前端口号已占用，测试下一位端口号
                logger.warning(f"服务器端口号 {self.port} 已被占用")
                self.port += 1
                if self.port > 65535:
                    self.port = 1024
                pre_configs.setValue("server_port", self.port)  # 写入记录

        logger.info(f"Listening on http://{self.host}:{self.port}")
        print(f"Listening on http://{self.host}:{self.port}")
        CallFunc.now(QmlCallback, self.port)  # 在主线程中调用回调函数，告知实际端口号
        self.server.serve_forever(poll_interval=0.1)

    def stop(self):  # 服务终止
        # self.server.server_close() # 备选方案，但会导致 bad fd 异常
        logger.debug("WEB服务器准备关闭！")
        self.server.close_all_request()  # 强制关闭客户端连接
        self.server.shutdown()  # 关闭服务器
        import atexit
        atexit.unregister(self.stop)
        logger.info("WEB服务器已关闭！")


# ============================== 线程类 ==============================
class _WorkerClass(QRunnable):
    def run(self):
        from threading import Event
        self._server = _WSGIRefServer()
        UmiWeb.run(server=self._server)


_Worker = None
from threading import Lock
_ConfigLock = Lock()


# ============================== 控制接口 ==============================


# 启动web服务。传入qml对象，回调函数名，主机地址
def runUmiWeb(qmlObj, callback, host):
    configureHttp(qmlObj, callback, True, host, pre_configs.getValue("server_port"))


def configureHttp(qmlObj, callback, enabled, host, port):
    from ..utils.thread_pool import threadRun
    handler = getattr(qmlObj, callback, None)
    def configure():
        global _Worker, QmlCallback, Host
        with _ConfigLock:
            if _Worker is not None:
                # A previous listener may still be completing startup.
                import time
                for _ in range(100):
                    server = getattr(getattr(_Worker, "_server", None), "server", None)
                    if server is not None: break
                    time.sleep(0.05)
                else: raise RuntimeError("HTTP 服务启动超时")
                _Worker._server.stop()
                _Worker._server.server.server_close()
                _Worker = None
            pre_configs.setValue("server_port", int(port))
            Host, QmlCallback = host, handler
            if enabled:
                _Worker = _WorkerClass()
                _Worker.setAutoDelete(False)
                QThreadPool.globalInstance().start(_Worker)
    threadRun(configure)


def setPort(port):
    pre_configs.setValue("server_port", int(port))
