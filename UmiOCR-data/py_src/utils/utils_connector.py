# 通用工具连接器

from threading import Lock
from typing import List
from PySide6.QtCore import QCoreApplication, QObject, QTimer, Slot

from umi_log import logger
from . import utils
from . import file_finder  # 文件搜索器
from ..platform import Platform  # 跨平台
from .thread_pool import threadRun  # 异步执行函数


class UtilsConnector(QObject):
    def __init__(self):
        super().__init__()

    # 将文本写入剪贴板
    @Slot(str)
    def copyText(self, text):
        utils.copyText(text)

    # 用系统应用打开文件或目录
    @Slot(str)
    def startfile(self, path):
        Platform.startfile(path)

    @Slot()
    def quitApp(self):
        app = QCoreApplication.instance()
        if app is not None:
            logger.info("收到退出请求，准备关闭 Qt 事件循环。")
            QTimer.singleShot(0, lambda: app.exit(0))

    # 硬件控制
    @Slot(str)
    def hardwareCtrl(self, key):
        if key == "shutdown":  # 关机
            Platform.HardwareCtrl.shutdown()
        elif key == "hibernate":  # 休眠
            Platform.HardwareCtrl.hibernate()

    # 同步搜索文件，返回合法的文件路径列表
    @Slot("QVariant", bool, str, result="QVariant")
    def findFiles(self, paths, sufType, isRecurrence):
        return file_finder.findFiles(paths, sufType, isRecurrence)

    # 异步搜索文件
    @Slot("QVariant", str, bool, str, str, float)
    def asynFindFiles(
        self,
        paths: List,  # 初始路径列表
        sufType: str,  # 后缀类型，FileSuf的key
        isRecurrence: bool,  # 若为True，则递归搜索
        completeKey: str,  # 唯一终态事件key。向事件传入 (合法路径列表, 诊断列表)。
        updateKey: str,  # 加载中刷新进度的key，不填则无。向事件传入 (已完成的路径数量, 最近一条路径)
        updateTime: float,  # 刷新进度的间距
    ):
        gate = Lock()
        state = "pending"

        def run():
            nonlocal state
            with gate:
                if state != "pending":
                    return
                state = "running"
            file_finder.asynFindFiles(
                paths, sufType, isRecurrence, completeKey, updateKey, updateTime
            )

        try:
            threadRun(run)
        except Exception as exc:
            # 调度失败也必须释放导入票据；已开始的任务由 finder 的 finally 结算。
            # 若线程池在报错后才交付 runnable，pending 状态门禁避免第二次终态。
            with gate:
                if state != "pending":
                    return
                state = "cancelled"
            message = f"无法启动文件扫描（{type(exc).__name__}）。"
            logger.error(message)
            file_finder.PubSubService.publish(
                completeKey, [], [{"kind": "scanerror", "path": "", "message": message}]
            )

    # QUrl列表 转 String列表
    @Slot("QVariant", result="QVariant")
    def QUrl2String(self, fileUrls):
        return utils.QUrl2String(fileUrls)
