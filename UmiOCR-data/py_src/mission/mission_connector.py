# =====================================================================
# =============== qml与【后端Python任务控制器们】的连接器 ===============
# =====================================================================

from PySide6.QtCore import QObject, Slot, Signal

# 本模块内定义的任务控制器单例
from .mission_ocr import MissionOCR
from .mission_document import MissionDocument
from umi_log import logger

# 控制器字典。键名与插件能力类型一一对应：
# 每种能力类型都有自己独立的任务管理器，不共用 OCR 的队列与错误路径。
MsnObjDict = {
    "ocr": MissionOCR,
    "document": MissionDocument,
}


# 任务连接器类（不限制单例）
class MissionConnector(QObject):
    operationFinished = Signal(str, str, "QVariant")
    _pending = 0

    @Slot(result=bool)
    def isBusy(self):
        return self._pending > 0

    @Slot(str, str, "QVariant")
    def requestCall(self, msnKey, funcName, args):
        from ..utils.thread_pool import threadRun
        from ..plugins_controller.services import _to_python_value
        values = _to_python_value(args)
        self._pending += 1
        def run():
            try:
                result = self.callPy(msnKey, funcName, values)
            except Exception as exc:
                result = {"ok": False, "message": str(exc)}
            finally:
                self._pending -= 1
            self.operationFinished.emit(msnKey, funcName, result)
        threadRun(run)

    # qml访问某个Python任务控制器的方法（同步）
    # qml调用ctrlKey的方法funcName，入参为列表（对应参数顺序），返回值为可变类型。
    @Slot(str, str, list, result="QVariant")
    def callPy(self, msnKey, funcName, args=()):
        if msnKey not in MsnObjDict:
            logger.error(f"qml访问不存在的任务控制器 {msnKey} 。")
            return None
        # 获取方法的引用
        msnObj = MsnObjDict[msnKey]
        method = getattr(msnObj, funcName, None)
        # 查询失败
        if not callable(method):
            logger.error(f"qml调用了 {msnKey} 的不存在的py方法 {funcName} 。")
            return None
        # 调用方法，参数不对的话让系统抛出错误
        from ..plugins_controller.services import _to_python_value

        return method(*_to_python_value(args))
