# ===============================================
# =============== 文档预览 - 连接器 ===============
# ===============================================

from copy import deepcopy

from PySide6.QtCore import QObject, Slot, Signal
from PySide6.QtGui import QPixmap, QImage

from umi_log import logger
from .simple_mission import SimpleMission
from ..image_controller.image_provider import PixmapProvider
from ..utils.call_func import CallFunc

MinSize = 0  # 最小渲染分辨率


# 文档预览连接器
class DocPreviewConnector(QObject):
    previewImg = Signal(str)  # imgID
    previewOcr = Signal("QVariant")  # [path, page, res]
    # 注：信号中含多个变量可能导致崩溃？

    def __init__(self, *args):
        super().__init__(*args)
        self._previewMission = SimpleMission(self._previewTask)
        # 请求代次仅在主线程递增，工作线程不直接向界面发送结果。
        self._renderRevision = 0
        self._ocrRevision = 0
        self._documentSession = 0
        self._zooms = {}  # 主线程保存当前渲染代次的页面缩放系数
        # 以下文档缓存仅由串行渲染工作线程使用。
        self._previewDoc = None
        self._previewKey = None  # (会话, 路径, 密码)

    @Slot(str, int, str)
    def preview(self, path, page, password):
        self._renderRevision += 1
        self._ocrRevision += 1  # 换页、换文档或刷新后，旧 OCR 也不能回写。
        self._zooms.clear()
        request = (self._renderRevision, self._documentSession, path, page - 1, password)
        self._previewMission.addMissionList([request], replace=True)

    def _closePreviewDoc(self):
        doc, self._previewDoc = self._previewDoc, None
        self._previewKey = None
        if doc is not None:
            try:
                doc.close()
            except Exception:
                logger.warning("关闭文档预览缓存失败。", exc_info=True)

    def _previewTask(self, request):
        import fitz

        revision, session, path, page, password = request
        if path is None:
            self._closePreviewDoc()
            return
        if revision != self._renderRevision:
            return
        try:
            key = (session, path, password)
            if key != self._previewKey:
                self._closePreviewDoc()
                self._previewDoc = fitz.open(path)
                self._previewKey = key
                if self._previewDoc.is_encrypted and not self._previewDoc.authenticate(password):
                    self._closePreviewDoc()
                    CallFunc.now(self._deliverPreview, revision, "[Warning] is_encrypted")
                    return
            doc = self._previewDoc
            if page < 0 or page >= doc.page_count:
                raise ValueError(f"页数 {page} 超出范围 0-{doc.page_count} 。")
            rect = doc[page].rect
            width, height = abs(rect[2] - rect[0]), abs(rect[3] - rect[1])
            minimum = min(width, height)
            zoom = MinSize / max(minimum, 1) if minimum < MinSize else 1
            matrix = fitz.Matrix(zoom, zoom) if zoom != 1 else fitz.Identity
            pixmap = doc[page].get_pixmap(matrix=matrix)
            samples = pixmap.samples
            # 跨线程交付必须复制外部 samples；QPixmap 和图片缓存只在主线程创建。
            image = QImage(
                samples, pixmap.width, pixmap.height, pixmap.stride, QImage.Format.Format_RGB888
            ).copy()
            CallFunc.now(self._deliverPreview, revision, image, page, zoom)
        except Exception as exc:
            self._closePreviewDoc()
            CallFunc.now(self._deliverPreview, revision, f"[Error] 打开文档失败：{path} {exc}")
        finally:
            # replace 不能取消已在执行的渲染，结束时仍要释放其旧文档资源。
            if revision != self._renderRevision:
                self._closePreviewDoc()

    def _deliverPreview(self, revision, result, page=-1, zoom=1):
        # 必须在主线程实际交付时复核，不能只在 worker emit 前判断。
        if revision != self._renderRevision:
            return
        if isinstance(result, str):
            self.previewImg.emit(result)
            return
        self._zooms[page] = zoom
        imgID = PixmapProvider.addPixmap(QPixmap.fromImage(result))
        self.previewImg.emit(imgID)

    @Slot(str, int, str, "QVariant")
    def ocr(self, path, page, password, argd):
        from .mission_doc import MissionDOC
        from ..plugins_controller.services import _to_python_value

        self._ocrRevision += 1
        revision, renderRevision = self._ocrRevision, self._renderRevision
        argd = _to_python_value(argd)

        def _onGet(msnInfo, page_, res):
            # 冻结结果，避免任务线程在主线程取走之前继续修改同一字典。
            CallFunc.now(self._deliverOcr, revision, renderRevision, path, page_, deepcopy(res))

        def _onEnd(msnInfo, msg):
            if not msg.startswith("[Success]"):
                CallFunc.now(
                    self._deliverOcr, revision, renderRevision, path, -1,
                    {"code": 103, "data": msg},
                )

        msnInfo = {"argd": argd, "onGet": _onGet, "onEnd": _onEnd}
        MissionDOC.addMission(msnInfo, path, (page, page), password=password)

    def _deliverOcr(self, revision, renderRevision, path, page, res):
        if revision != self._ocrRevision or renderRevision != self._renderRevision:
            return
        if res["code"] == 100:
            zoom = self._zooms.get(page, 1)
            if zoom != 1:
                for block in res["data"]:
                    for point in block["box"]:
                        point[0] *= zoom
                        point[1] *= zoom
        self.previewOcr.emit([path, page + 1 if page >= 0 else -1, res])

    @Slot()
    def clear(self):
        self._renderRevision += 1
        self._ocrRevision += 1
        self._documentSession += 1
        self._zooms.clear()
        # 若此清理被下一次 preview 的 replace 替换，会话号仍强制重新打开文档。
        request = (self._renderRevision, self._documentSession, None, 0, "")
        self._previewMission.addMissionList([request], replace=True)
