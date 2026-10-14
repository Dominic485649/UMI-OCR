# ==========================================================
# =============== 结构化文档 - 任务管理器 ===============
# ==========================================================

"""
document 能力的全局任务管理器，与 MissionOCR 平级。

刻意【不复用】MissionOCR：
- 单位任务是整份文档而不是单张图片，耗时量级不同；
- 后端可能是外部服务，前处理要做连接与健康检查而不只是模型参数更新；
- 失败需要给出可操作提示（服务未启动 / 模型目录缺失 / 协议不匹配），
  而不是 OCR 的"引擎启动失败"。

调度模式取 "1234"（顺序）：文档解析往往独占后端显存或独占一个外部
服务连接，轮询调度会让多份文档互相拖慢并放大显存峰值。
"""

import os

from umi_log import logger

from .mission import Mission
from ..document.api import getApiDocument, getLocalOptions
from ..utils.utils import argdIntConvert

# 合法文件后缀：图片 + PDF 。具体后端可以再收窄。
DocumentSuf = [
    ".pdf",
    ".png",
    ".jpg",
    ".jpe",
    ".jpeg",
    ".jfif",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
]

_UNAVAILABLE = {"state": "unavailable", "idleSeconds": 0, "error": ""}


class __MissionDocumentClass(Mission):
    def __init__(self):
        super().__init__()
        self._apiKey = ""
        self._api = None
        self._schedulingMode = "1234"  # 顺序调度，见模块说明

    # ========================= 【重载】 =========================

    def addMissionList(self, msnInfo, msnList):
        if not self._api:
            return (
                "[Error] MissionDocument: 尚未选择结构化文档后端。"
                "请先在【全局设置 - 结构化文档】中安装并启用一个 document 插件。"
            )
        for i in range(len(msnList) - 1, -1, -1):
            path = msnList[i].get("path", "")
            if not path:
                logger.warning(f"添加文档任务时，第{i}项不含 path")
                del msnList[i]
                continue
            if os.path.splitext(path)[-1].lower() not in DocumentSuf:
                logger.warning(f"添加文档任务时，第{i}项不是受支持的文档：{path}")
                del msnList[i]
                continue
            if not os.path.isfile(path):
                logger.warning(f"添加文档任务时，第{i}项文件不存在：{path}")
                del msnList[i]
        return super().addMissionList(msnInfo, msnList)

    def msnPreTask(self, msnInfo):
        if not self._api:
            return "[Error] MissionDocument: API object is None."
        startInfo = self._dictShortKey(msnInfo.get("argd", {}))
        argdIntConvert(startInfo)
        progress = msnInfo.get("onProgress", lambda *args: None)
        self._api.on_progress = lambda stage: progress(stage)
        progress("准备输入")
        try:
            msg = self._api.start(startInfo)
        except Exception as e:
            logger.error("结构化文档后端启动失败。", exc_info=True, stack_info=True)
            return f"[Error] 结构化文档后端启动失败：{e}"
        if isinstance(msg, str) and msg.startswith("[Error]"):
            logger.error(f"结构化文档后端启动失败： {msg}")
            return msg
        return ""

    def msnTask(self, msnInfo, msn):
        try:
            res = self._api.parseDoc(msn)
        except Exception as e:
            logger.error("结构化文档解析失败。", exc_info=True, stack_info=True)
            return {"code": 902, "data": f"[Error] 解析文档失败：{e}"}
        if not isinstance(res, dict) or "code" not in res:
            return {
                "code": 903,
                "data": "[Error] document 后端返回了不符合契约的结果，缺少 code 字段。",
            }
        res["path"] = msn.get("path", "")
        return res

    # ========================= 【qml接口】 =========================

    def getStatus(self):
        return {
            "apiKey": self._apiKey,
            "missionListsLength": self.getMissionListsLength(),
            "apiState": self._api.get_status() if self._api else dict(_UNAVAILABLE),
        }

    def setApi(self, apiKey, info):
        """设置后端。成功返回 [Success] ，失败返回 [Error] 开头的字符串。"""
        if self.getMissionListsLength():
            return "[Error] 当前任务尚未完成，请稍后切换。"
        if not apiKey:
            self.shutdown()
            self._api = None
            self._apiKey = ""
            return "[Success]"
        self._apiKey = apiKey
        info = self._dictShortKey(info)
        if self._api:
            try:
                self._api.stop()
            except Exception:
                logger.error("停止旧的结构化文档后端失败。", exc_info=True)
        res = getApiDocument(apiKey, info)
        if isinstance(res, str):
            self._apiKey = ""
            self._api = None
            return res
        self._api = res
        return "[Success]"

    def health(self, info):
        """健康检查。返回 {"ok", "message", "details"} 。

        UI 只有在这里返回 ok=True 之后，才允许显示该后端为"可用"。
        """
        if not self._api:
            return {
                "ok": False,
                "message": "尚未选择结构化文档后端。",
                "details": {},
            }
        shortInfo = self._dictShortKey(info)
        argdIntConvert(shortInfo)
        try:
            res = self._api.health(shortInfo)
        except Exception as e:
            logger.error("结构化文档健康检查失败。", exc_info=True, stack_info=True)
            return {"ok": False, "message": f"健康检查异常：{e}", "details": {}}
        if not isinstance(res, dict):
            return {"ok": False, "message": "后端返回了不符合契约的健康检查结果。", "details": {}}
        return {
            "ok": bool(res.get("ok")),
            "message": str(res.get("message") or ""),
            "details": res.get("details") or {},
        }

    def releaseModel(self):
        if not self._api:
            return "[Error] MissionDocument: API object is None."
        if self.getMissionListsLength():
            return "[Error] 文档任务正在运行，不能清理后台。"
        try:
            return self._api.release()
        except Exception as e:
            logger.error("清理结构化文档后台失败。", exc_info=True, stack_info=True)
            return f"[Error] 清理失败：{e}"

    def stopMissionList(self, msnIDs):
        ids = msnIDs if isinstance(msnIDs, list) else [msnIDs]
        active = getattr(self, "_activeMsnID", None) in ids
        if self._api and active:
            cancel = getattr(self._api, "cancel", None)
            if callable(cancel): cancel()
        return super().stopMissionList(msnIDs)

    def stopAllMissions(self):
        if self._api:
            cancel = getattr(self._api, "cancel", None)
            if callable(cancel): cancel()
        return super().stopAllMissions()

    def shutdown(self):
        if self._api:
            try:
                self._api.stop()
            except Exception:
                logger.error("关闭结构化文档后端失败。", exc_info=True)

    def getLocalOptions(self):
        if self._apiKey:
            return getLocalOptions(self._apiKey)
        return {}

    # 将字典中配置项的长key转为短key
    # 如： document.win32_XXX_1_6.service.host → service.host
    def _dictShortKey(self, d):
        newD = {}
        key1 = "document."
        key2 = key1 + self._apiKey + "."
        servicePrefix = "pluginServices." + self._apiKey + "."
        for k in d:
            if k.startswith(key2):
                newD[k[len(key2) :]] = d[k]
            elif k.startswith(key1):
                newD[k[len(key1) :]] = d[k]
            elif k.startswith(servicePrefix):
                # Shared model-service settings are persisted under the
                # global plugin namespace; expose them to the capability as
                # short keys such as ``service.host``.
                rest = k[len(servicePrefix) :]
                separator = rest.find(".")
                if separator > 0 and separator + 1 < len(rest):
                    newD[rest[separator + 1 :]] = d[k]
            elif not k.startswith("document."):
                # Shared service configuration is already de-prefixed by the
                # global service panel.  Preserve it for the document API.
                newD[k] = d[k]
        return newD


# 全局 结构化文档任务管理器
MissionDocument = __MissionDocumentClass()
