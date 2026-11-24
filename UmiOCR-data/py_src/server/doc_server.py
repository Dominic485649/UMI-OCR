from ..utils.runtime_i18n import tr
import os
import re
import json
import math
import threading
import time
import shutil
import zipfile
from urllib.parse import urlparse
from uuid import uuid4
from PySide6.QtCore import QMutex
from typing import Dict

from umi_log import logger
from call_func import CallFunc
from bottle import request, static_file, HTTPError
from .ocr_server import _apply_preset_options, get_ocr_options
from ..ocr.output import output_factories
from ..mission.mission_doc import MissionDOC, DocSuf
from ..utils.utils import initConfigDict
from ..ocr.output.tools import getDataText

UPLOAD_DIR = "./temp_doc/http-doc"  # 仅本 HTTP 模块创建的任务目录
TEMP_FILE_RETENTION_DURATION = 24  # 任务临时文件保留时长，小时
TEMP_FILE_CLEANUP_INTERVAL = 0.5  # 自动清理临时文件的间隔，小时


# 获取参数模板字典
def get_doc_options(backend_id="current", local_options=None):
    opts = get_ocr_options(is_format=False, backend_id=backend_id, local_options=local_options)
    opts["tbpu.ignoreRangeStart"] = {
        "title": tr('忽略区域起始'),
        "toolTip": tr('忽略区域生效的页数范围起始。从1开始。'),
        "default": 1,
        "isInt": True,
    }
    opts["tbpu.ignoreRangeEnd"] = {
        "title": tr('忽略区域结束'),
        "toolTip": tr('忽略区域生效的页数范围结束。可以用负数表示倒数第X页。'),
        "default": -1,
        "isInt": True,
    }
    opts["pageRangeStart"] = {
        "title": tr('OCR页数起始'),
        "toolTip": tr('OCR的页数范围起始。从1开始。'),
        "default": 1,
        "isInt": True,
    }
    opts["pageRangeEnd"] = {
        "title": tr('OCR页数结束'),
        "toolTip": tr('OCR的页数范围结束。可以用负数表示倒数第X页。'),
        "default": -1,
        "isInt": True,
    }
    opts["pageList"] = {
        "title": tr('OCR页数列表'),
        "toolTip": tr('数组，可指定单个或多个页数。例：[1,2,5]表示对第1、2、5页进行OCR。如果与页数范围同时填写，则 pageList 优先。'),
        "default": [],
        "type": "var",
    }
    opts["password"] = {
        "title": tr('密码'),
        "toolTip": tr('如果文档已加密，则填写文档密码。'),
        "default": "",
    }
    opts["doc.extractionMode"] = {
        "title": tr('内容提取模式'),
        "toolTip": tr('若一页文档既存在图片又存在文本，如何进行处理。'),
        "optionsList": [
            ["mixed", tr('混合OCR/原文本')],
            ["fullPage", tr('整页强制OCR')],
            ["imageOnly", tr('仅OCR图片')],
            ["textOnly", tr('仅拷贝原有文本')],
        ],
    }
    opts = initConfigDict(opts)  # 格式化
    return opts


UPLOAD_DIR = os.path.realpath(UPLOAD_DIR)  # 路径转绝对并解析符号链接
TEMP_FILE_RETENTION_DURATION *= 3600  # 小时转为秒
TEMP_FILE_CLEANUP_INTERVAL *= 3600


# 异常类
class DocUnitError(Exception):
    def __init__(self, data):
        self.data = data


# 单个任务单元
class _DocUnit:
    def __init__(self, dir_id, dir_path, origin_path, origin_name, origin_prefix,
                 options, backend_id="current"):
        from .backend_router import select_backend
        from .request_validation import validate_options, validate_visual_budget
        from ..mission.backend_runtime import BackendRuntime
        doc_info = MissionDOC.getDocInfo(origin_path)
        if "error" in doc_info:
            raise DocUnitError({"code": 201, "data": str(doc_info["error"])})
        self._selection = None
        try:
            if options.get("doc.extractionMode", "mixed") != "textOnly":
                # current 且未配置 OCR 时仍允许混合模式提取已有文本；只有真的
                # 遇到图片，旧 MissionOCR 才按既有契约返回未配置后端的错误。
                self._selection = select_backend("ocr", backend_id)
            definitions = get_doc_options(
                self._selection.backend_id if self._selection else backend_id,
                self._selection.local_options if self._selection else None)
            _apply_preset_options(options, definitions)
            options = validate_options(options, definitions)
            page_range = [options["pageRangeStart"], options["pageRangeEnd"]]
            page_list = options["pageList"]
            count = doc_info["page_count"]
            if page_list and (len(page_list) > 500 or any(type(page) is not int or page < 1 or page > count for page in page_list)):
                raise DocUnitError({"code": 204, "data": tr('页数列表无效或超过预算。')})
            start = page_range[0] if page_range[0] > 0 else count + page_range[0] + 1
            end = page_range[1] if page_range[1] > 0 else count + page_range[1] + 1
            if not page_list and (start < 1 or end < start or end > count or end - start >= 500):
                raise DocUnitError({"code": 204, "data": tr('页范围无效或一次超过 500 页。')})
            page_list = [page - 1 for page in page_list]
            password = options["password"]
            if not password and doc_info["is_encrypted"]:
                raise DocUnitError({"code": 202, "data": tr('文档已加密，请提供密码。')})
            if self._selection:
                validate_visual_budget(self._selection.backend_id, self._selection.config,
                                       options.get("ocr.maxOutputTokens", 4096))
                if self._selection.private:
                    self._selection.manager._retain_runtime = True
        except BaseException:
            if self._selection:
                self._selection.close()
            raise
        # 接纳前建立回调状态，支持任务立即完成。
        self.password, self.dir_id, self.dir_path = password, dir_id, dir_path
        self.origin_prefix, self.origin_name, self.origin_path = origin_prefix, origin_name, origin_path
        self.msnID = str(uuid4())
        self.results, self.unread_list = {}, []
        self.pages_count = len(page_list) if page_list else end - start + 1
        self.processed_count, self.is_done = 0, False
        self.state, self.message = "waiting", ""
        self.start_timestamp = self.end_timestamp = time.time()
        self._mutex = QMutex()
        doc_argd = {key: value for key, value in options.items()
                    if key.startswith(("ocr.", "doc.", "tbpu."))}
        msnInfo = {"_reserved_msnID": self.msnID, "onStart": self._onStart,
                   "onGet": self._onGet, "onEnd": self._onEnd, "argd": doc_argd}
        if self._selection:
            msnInfo["ocrManager"] = self._selection.manager
            if self._selection.private:
                BackendRuntime.reserve(self.msnID, self._selection.backend_id)
        try:
            msg = MissionDOC.addMission(msnInfo, origin_path, page_range, page_list, password)
            if not msg or msg.startswith("["):
                raise DocUnitError({"code": 204, "data": msg or tr('提交文档任务失败。')})
            self.pages_count = len(msnInfo["pageList"])
        except BaseException:
            BackendRuntime.unreserve(self.msnID)
            if self._selection:
                self._selection.close()
            raise

    # ========================= 【接口】 =========================

    # 获取结果
    def get_result(
        self,
        is_data=False,  # True 时返回识别内容data
        format="dict",  # 识别内容格式， "dict", "text"
        is_unread=False,  # True 时只返回未读过的识别内容
    ):
        self._mutex.lock()
        data = {
            "code": 100,
            "processed_count": self.processed_count,  # 已处理的数量
            "pages_count": self.pages_count,  # 总页数
            "is_done": self.is_done,  # 是否已结束
            "state": self.state,  # 任务状态
            "data": [],  # 结果
        }
        if self.state == "failure":
            data["message"] = self.message
        # 需要返回识别内容
        if is_data:
            datas = []
            # 增量式
            if is_unread:
                for page in self.unread_list:
                    datas.append(self.results[page])
                self.unread_list = []
            # 全量式
            else:
                for _, res in self.results.items():
                    datas.append(res)
            # 需要转为纯文本
            if format == "text":
                datas_text = ""
                for res in datas:
                    if res["code"] == 100:
                        datas_text += getDataText(res["data"])
                datas = datas_text
            data["data"] = datas
        self._mutex.unlock()
        return data

    # 获取文件
    def get_files(
        self,
        base_url,  # 下载基础url
        file_types=["pdfLayered"],  # 输出文件类型，可选：
        # md, txt/txtPlain（Markdown .md.txt 兼容别名）, jsonl, csv, pdfLayered, pdfOneLayer
        ignore_blank=True,  # 忽略空白页数
    ):
        if not self.is_done:
            return {"code": 201, "data": tr('{msnid} 任务尚未结束，无法获取文件', msnid=self.msnID)}
        if not self.state == "success":
            return {"code": 201, "data": tr('{msnid} 任务处理失败，无法获取文件', msnid=self.msnID)}
        if not isinstance(file_types, list) or not isinstance(ignore_blank, bool):
            return {
                "code": 202,
                "data": tr('参数类型错误： file_types={file_types} , ignore_blank={ignore_blank}', file_types=file_types, ignore_blank=ignore_blank),
            }

        # 删除旧的文件
        for filename in os.listdir(self.dir_path):
            file_path = os.path.join(self.dir_path, filename)
            if filename != self.origin_name and os.path.isfile(file_path):
                os.remove(file_path)

        # 准备参数
        startDatetime = time.strftime(  # 日期时间字符串（标准格式）
            r"%Y-%m-%d %H:%M:%S", time.localtime(self.start_timestamp)
        )
        outputArgd = {
            "outputDir": self.dir_path,  # 输出路径
            "outputDirType": "specify",
            "outputFileName": "[OCR]_" + self.origin_prefix,  # 输出文件名（前缀）
            "startDatetime": startDatetime,  # 开始日期
            "ignoreBlank": ignore_blank,  # 忽略空白页数
            "originPath": self.origin_path,  # 原始文件
            "password": self.password,  # 文档密码
        }

        # 创建输出器
        output = []
        try:
            for _key, factory in output_factories(file_types, compatibility=True):
                output.append(factory(outputArgd))
        except Exception as e:
            return {"code": 203, "data": tr('初始化输出器失败。{e}', e=e)}

        # 输出
        for o in output:
            for _, res in self.results.items():
                try:
                    o.print(res)
                except Exception as e:
                    return {"code": 204, "data": tr('输出失败：{o}\n{e}', o=o, e=e)}
            try:
                o.onEnd()  # 保存
            except Exception as e:
                return {"code": 205, "data": tr('保存失败：{o}\n{e}', o=o, e=e)}

        # 收集新的文件
        download_paths = []
        for filename in os.listdir(self.dir_path):
            file_path = os.path.join(self.dir_path, filename)
            if filename != self.origin_name and os.path.isfile(file_path):
                download_paths.append(file_path)
        # 如果文件多，则打包zip
        if not download_paths:
            return {"code": 206, "data": tr('未找到生成的文件')}
        elif len(download_paths) == 1:
            download_name = os.path.basename(download_paths[0])
        else:
            download_name = f"[OCR]_{self.origin_prefix}.zip"
            zip_path = os.path.join(self.dir_path, download_name)
            # 将 download_list 中的所有文件打包为 zip
            try:
                with zipfile.ZipFile(zip_path, "w") as zipf:
                    for p in download_paths:
                        zipf.write(p, os.path.basename(p))
            except Exception as e:
                return {"code": 207, "data": tr('无法打包zip：{e}', e=e)}

        # 组合下载地址
        url = f"{base_url}/api/doc/download/{self.dir_id}/{download_name}"

        return {"code": 100, "data": url, "name": download_name}

    # 清理任务
    def clear(self):
        if not self.is_done:
            MissionDOC.stopMissionList([self.msnID])
            if self._selection:
                self._selection.manager.stopAllMissions()
            return False  # 取消完成前不删除仍可能由 worker 使用的输入。
        from .structured_document_server import _safe_path
        root = _safe_path(self.dir_path, UPLOAD_DIR)
        if root.name != self.dir_id:
            return False
        if any(path.is_symlink() or path.is_junction() for path in root.rglob("*")):
            return False
        try:
            if root.exists():
                shutil.rmtree(root)
        except OSError:
            return False
        return True

    # ========================= 【任务控制器的异步回调】 =========================

    def _onStart(self, msnInfo):  # 一个文档 开始
        self.state = "running"

    def _onGet(self, msnInfo, page, res):  # 一个文档的一页 获取结果
        page += 1
        res["page"] = page
        res["path"] = f"{self.origin_name} - {page}"
        res["fileName"] = f"{self.origin_name} - {page}"

        # 记录信息
        self._mutex.lock()
        self.results[page] = res
        self.processed_count += 1
        self.unread_list.append(page)
        self._mutex.unlock()

    def _onEnd(self, msnInfo, msg):
        from ..mission.backend_runtime import BackendRuntime
        self._mutex.lock()
        try:
            self.is_done = True
            incomplete = any(result.get("code") not in (100, 101) or result.get("partial")
                             for result in self.results.values())
            if msg == "[Success]" and not incomplete:
                self.state = "success"
            else:
                self.state = "failure"
                self.message = msg if msg != "[Success]" else tr('部分页或区域未完整识别，请检查逐页结果。')
            self.end_timestamp = time.time()
        finally:
            self._mutex.unlock()
            BackendRuntime.unreserve(self.msnID)
            if self._selection:
                if self._selection.private:
                    self._selection.manager._retain_runtime = False
                self._selection.close()


# 管理所有任务单元
class _DocUnitManagerClass:
    def __init__(self):
        self.doc_units: Dict[str, _DocUnit] = {}
        self._lock = threading.RLock()

    # 添加一个任务单元
    def add(self, id: str, unit: _DocUnit):
        with self._lock:
            self.doc_units[id] = unit

    # 获取一个任务单元
    def get(self, id: str):
        with self._lock:
            return self.doc_units.get(id)

    # 手动清理一个任务
    def clear(self, id: str):
        with self._lock:
            unit = self.doc_units.get(id)
        if unit is None or not unit.clear():
            return False
        with self._lock:
            if self.doc_units.get(id) is unit:
                self.doc_units.pop(id, None)
        return True

    # 自动清理
    def auto_clear(self):
        now = time.time()
        with self._lock:
            expired = [id for id, unit in self.doc_units.items()
                       if unit.is_done and now - unit.end_timestamp > TEMP_FILE_RETENTION_DURATION]
        for identifier in expired:
            if self.clear(identifier):
                logger.info(tr('超时自动清理 {identifier}', identifier=identifier))
        CallFunc.delay(self.auto_clear, TEMP_FILE_CLEANUP_INTERVAL)


_DocUnitManager = _DocUnitManagerClass()


# 路由函数
def init(UmiWeb):
    # 不删除历史目录或其他任务数据；只管理本进程登记的 HTTP 任务。
    from .structured_document_server import _safe_path
    _safe_path(UPLOAD_DIR)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    # 启动自动清理循环
    _DocUnitManager.auto_clear()

    @UmiWeb.route("/api/doc/get_options")
    def _get_options_json():
        try:
            opts = get_doc_options(request.query.get("backendId", "current"))
            return json.dumps(opts)
        except ValueError as exc:
            return {"code": 804, "data": str(exc)}

    '\n    上传文档，方法：POST\n    参数：文档内容\n    返回值：\n    成功： {"code": 100, "data": "任务id"}\n    失败： {"code": 不是100的值, "data": "失败原因"}\n    '

    @UmiWeb.route("/api/doc/upload", method="POST")
    def _upload():
        # 1. 获取上传文件
        upload = request.files.get("file")
        if not upload:
            return {"code": 101, "data": "[Error] No file was uploaded."}

        # 2. 获取文件名，检查文件后缀
        # origin_name = upload.filename
        # 将原始文件名转为合法文件名
        def filename_convert(raw_filename: str):
            # 去除前后的空格
            raw_filename = raw_filename.strip()
            # 定义非法字符
            illegal_chars = r'[\\/:*?"<>|]'
            # 替换非法字符
            sanitized_filename = re.sub(illegal_chars, "_", raw_filename)
            # 限制文件名长度为255个字符
            max_length = 255
            if len(sanitized_filename) > max_length:
                sanitized_filename = sanitized_filename[:max_length]
            return sanitized_filename

        try:
            origin_name = filename_convert(upload.raw_filename)
            origin_prefix, ext = os.path.splitext(origin_name)
            ext = ext.lower()
        except Exception as e:
            return {"code": 102, "data": f"[Error] Unable to obtain raw_filename: {e}"}
        if ext not in DocSuf:
            return {
                "code": 103,
                "data": f"[Error] File extension '{ext}' is not allowed.",
            }

        try:
            options = {}
            raw_options = request.forms.get("json")
            if raw_options:
                options = json.loads(raw_options)
                if not isinstance(options, dict):
                    return {"code": 107, "data": "[Error] Options must be a JSON object."}
                if "tbpu.ignoreArea" in options:
                    areas = options["tbpu.ignoreArea"]
                    if not isinstance(areas, list):
                        return {"code": 107, "data": "[Error] Invalid tbpu.ignoreArea."}
                    ignore_area = []
                    for area in areas:
                        if (
                            not isinstance(area, list)
                            or len(area) != 2
                            or any(not isinstance(point, list) or len(point) != 2 for point in area)
                            or any(
                                not isinstance(coord, (int, float))
                                or isinstance(coord, bool)
                                or (isinstance(coord, float) and not math.isfinite(coord))
                                for point in area
                                for coord in point
                            )
                        ):
                            return {"code": 107, "data": "[Error] Invalid tbpu.ignoreArea."}
                        ignore_area.append([
                            [area[0][0], area[0][1]],
                            [area[1][0], area[0][1]],
                            [area[1][0], area[1][1]],
                            [area[0][0], area[1][1]],
                        ])
                    options["tbpu.ignoreArea"] = ignore_area
        except Exception as e:
            return {"code": 107, "data": f"[Error] Invalid options: {e}"}

        with _DocUnitManager._lock:
            if len(_DocUnitManager.doc_units) >= 32:
                return {"code": 109, "data": tr('HTTP 文档任务数量已达到上限。')}
        # 每次只新建唯一目录，不删除或覆盖历史数据。
        dir_id = str(uuid4())
        dir_path = os.path.realpath(os.path.join(UPLOAD_DIR, dir_id))
        file_path = os.path.realpath(os.path.join(dir_path, origin_name))
        try:
            within_upload = os.path.commonpath([UPLOAD_DIR, dir_path]) == UPLOAD_DIR
            within_task = os.path.commonpath([dir_path, file_path]) == dir_path
        except ValueError:
            within_upload = within_task = False
        if not within_upload or not within_task or os.path.dirname(file_path) != dir_path:
            return {"code": 104, "data": "[Error] Unauthorized path"}

        try:
            from .structured_document_server import _safe_path
            _safe_path(dir_path, UPLOAD_DIR)
            os.makedirs(dir_path, exist_ok=False)
        except Exception as e:
            return {"code": 105, "data": f"[Error] Failed to create dir_id: {e}"}
        try:
            from .structured_document_server import MAX_UPLOAD_BYTES
            size = 0
            with open(file_path, "xb") as stream:
                while True:
                    chunk = upload.file.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise ValueError(tr('上传文件超过大小预算。'))
                    stream.write(chunk)
            if not size:
                raise ValueError(tr('上传文件为空。'))
        except Exception as e:
            try:
                shutil.rmtree(_safe_path(dir_path, UPLOAD_DIR))
            except OSError:
                pass
            return {"code": 106, "data": f"[Error] Failed to save file: {e}"}

        # 5. 构造任务对象
        try:
            doc_unit = _DocUnit(
                dir_id, dir_path, file_path, origin_name, origin_prefix, options,
                backend_id=request.forms.get("backendId", "current")
            )
            msnID = doc_unit.msnID
            _DocUnitManager.add(msnID, doc_unit)
            logger.info(tr('添加 HTTP 文档任务: {origin_name}', origin_name=origin_name))
            return {"code": 100, "data": msnID}
        except DocUnitError as e:
            shutil.rmtree(dir_path)
            return e.data
        except Exception as e:
            shutil.rmtree(dir_path)
            return {"code": 108, "data": f"[Error] Failed to submit mission: {e}"}

    '\n    获取结果，方法：POST\n    json参数：\n    "id"="",  # 任务ID\n    "is_data"=False,  # True 时返回识别内容data\n    "format"="dict",  # 识别内容格式， "dict", "text"\n    "is_unread"=False,  # True 时只返回未读过的识别内容\n\n    返回值： {}\n    '

    @UmiWeb.route("/api/doc/result", method="POST")
    def _result():
        try:
            user_data = request.json
        except Exception as e:
            return {"code": 101, "data": tr('请求无法解析为json。')}
        if not isinstance(user_data, dict):
            return {"code": 104, "data": tr('请求必须为JSON对象。')}
        if "id" not in user_data:
            return {"code": 102, "data": tr('未填写id。')}
        msnID = user_data["id"]
        if not isinstance(msnID, str) or not msnID:
            return {"code": 104, "data": tr('id 必须为非空字符串。')}
        doc_unit = _DocUnitManager.get(msnID)
        if not doc_unit:
            return {"code": 103, "data": tr('任务 {msnid} 不存在。', msnid=msnID)}
        is_data = user_data.get("is_data", False)
        format = user_data.get("format", "dict")
        is_unread = user_data.get("is_unread", True)
        if (
            not isinstance(is_data, bool)
            or not isinstance(is_unread, bool)
            or format not in ("dict", "text")
        ):
            return {"code": 104, "data": tr('is_data、is_unread 必须为布尔值，format 必须为 dict 或 text。')}
        return doc_unit.get_result(is_data, format, is_unread)

    '\n    获取文件，方法：POST\n    json参数：\n    "id"="",  # 任务ID\n    "file_types"=["pdfLayered"],  # 输出文件类型，可选：\n    # ["md", "txt", "txtPlain", "jsonl", "csv", "pdfLayered", "pdfOneLayer"]\n    "ignore_blank"=True,  # 忽略空白页数\n\n    返回值： {}\n    '

    @UmiWeb.route("/api/doc/download", method="POST")
    def _download_build():
        try:
            user_data = request.json
        except Exception as e:
            return {"code": 101, "data": tr('请求无法解析为json。')}
        if not isinstance(user_data, dict):
            return {"code": 104, "data": tr('请求必须为JSON对象。')}
        if "id" not in user_data:
            return {"code": 102, "data": tr('未填写id。')}
        msnID = user_data["id"]
        if not isinstance(msnID, str) or not msnID:
            return {"code": 104, "data": tr('id 必须为非空字符串。')}
        doc_unit = _DocUnitManager.get(msnID)
        if not doc_unit:
            return {"code": 103, "data": tr('任务 {msnid} 不存在。', msnid=msnID)}

        file_types = user_data.get("file_types", ["pdfLayered"])
        ignore_blank = user_data.get("ignore_blank", True)
        parsed_url = urlparse(request.url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        return doc_unit.get_files(base_url, file_types, ignore_blank)

    # 下载文件
    @UmiWeb.route("/api/doc/download/<id>/<download_name>")
    def _download_get(id, download_name):
        root = os.path.realpath(UPLOAD_DIR)
        dir_path = os.path.realpath(os.path.join(root, id))
        path = os.path.realpath(os.path.join(dir_path, download_name))
        try:
            within_task = (
                os.path.commonpath([root, dir_path]) == root
                and os.path.commonpath([dir_path, path]) == dir_path
            )
        except ValueError:
            within_task = False
        if not within_task or os.path.dirname(dir_path) != root:
            raise HTTPError(403, "[Error] Unauthorized path.")
        return static_file(download_name, root=dir_path)

    # 清理任务
    @UmiWeb.route("/api/doc/clear/<id>")
    def _clear(id):
        flag = _DocUnitManager.clear(id)
        if flag:
            return {"code": 100, "data": "Success"}
        return {"code": 101, "data": f"{id} does not exist."}
