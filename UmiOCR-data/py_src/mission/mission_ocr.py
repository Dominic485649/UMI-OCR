# ===============================================
# =============== OCR - 任务管理器 ===============
# ===============================================

"""
一种任务管理器为全局单例，不同标签页要执行同一种任务，要访问对应的任务管理器。
任务管理器中有一个引擎API实例，所有任务均使用该API。
标签页可以向任务管理器提交一组任务队列，其中包含了每一项任务的信息，及总体的参数和回调。
"""

import os

from umi_log import logger
from .mission import Mission
from ..ocr.tbpu import getParser, IgnoreArea
from ..ocr.api import getApiOcr, getLocalOptions
from ..ocr.score import averageScore
from ..utils.utils import argdIntConvert

# 合法文件后缀
ImageSuf = [
    ".jpg",
    ".jpe",
    ".jpeg",
    ".jfif",
    ".png",
    ".avif",
    ".webp",
    ".jxl",
    ".jxr",
    ".wdp",
    ".hdp",
    ".bmp",
    ".tif",
    ".tiff",
]


class __MissionOcrClass(Mission):
    def __init__(self):
        super().__init__()
        self._apiKey = ""  # 当前api类型
        self._api = None  # 当前引擎api对象

    # ========================= 【重载】 =========================

    # msnInfo: { 回调函数"onXX", 参数"argd":{"tbpu.xx", "ocr.xx"} }
    # msnList: [ { "path", "bytes", "base64" } ]
    def addMissionList(self, msnInfo, msnList):  # 添加任务列表
        # 实例化 tbpu 文本后处理模块
        msnInfo["tbpu"] = []
        argd = msnInfo["argd"]
        # 忽略区域
        if "tbpu.ignoreArea" in argd:
            iArea = argd["tbpu.ignoreArea"]
            if isinstance(iArea, list) and len(iArea) > 0:
                msnInfo["tbpu"].append(IgnoreArea(iArea))
        # 获取排版解析器对象
        if "tbpu.parser" in argd:
            msnInfo["tbpu"].append(getParser(argd["tbpu.parser"]))
        # 检查任务合法性
        for i in range(len(msnList) - 1, -1, -1):
            if "path" in msnList[i]:
                p = msnList[i]["path"]
                if os.path.splitext(p)[-1].lower() not in ImageSuf:
                    logger.warning(f"添加OCR任务时，第{i}项的路径path不是图片：{p}")
                    del msnList[i]
            elif "bytes" not in msnList[i] and "base64" not in msnList[i]:
                logger.warning(f"添加OCR任务时，第{i}项不含 path、bytes、base64")
                del msnList[i]
        return super().addMissionList(msnInfo, msnList)

    def msnPreTask(self, msnInfo):  # 用于更新api和参数
        # 检查API对象
        if not self._api:
            # 基础包不内置任何 OCR 推理后端。这里必须给出可操作的提示，
            # 并且明确说明没有可用的 CPU 回退，不能让用户以为是配置问题。
            return (
                "[Error] 未安装 OCR 后端。本体只提供界面与任务调度，"
                "不内置任何文字识别推理（包括 CPU）。"
                "请解压一个 OCR 插件归档到 Umi-OCR 本体目录后刷新插件状态。\n"
                "No OCR backend is installed. The base package ships the UI and "
                "task scheduler only, with no built-in inference (CPU included). "
                "Extract an OCR plugin archive into the Umi-OCR directory and refresh plugin status."
            )
        # 检查参数更新
        startInfo = self._dictShortKey(msnInfo["argd"])
        # 恢复int类型
        argdIntConvert(startInfo)
        msg = self._api.start(startInfo)
        if msg.startswith("[Error]"):
            logger.error(f"OCR引擎启动失败： {msg}")
            return msg  # 更新失败，结束该队列
        else:
            return ""  # 更新成功 TODO: continue

    def msnTask(self, msnInfo, msn):  # 执行msn
        if "path" in msn:
            res = self._api.runPath(msn["path"])
            res["path"] = msn["path"]  # 结果字典中补充参数
        elif "bytes" in msn:
            res = self._api.runBytes(msn["bytes"])
        elif "base64" in msn:
            res = self._api.runBase64(msn["base64"])
        else:
            res = {
                "code": 901,
                "data": f"[Error] Unknown task type.\n【异常】未知的任务类型。\n{str(msn)[:100]}",
            }
        # Snapshot the backend that executed this task, not the current QML selection.
        execution = {"pluginId": self._apiKey, "device": "设备未确认", "model": self._apiKey}
        getExecution = getattr(self._api, "get_execution_info", None)
        if callable(getExecution):
            try:
                execution.update(getExecution())
            except Exception:
                logger.warning("读取 OCR 执行信息失败。", exc_info=True)
        res["execution"] = execution
        # 任务成功时的后处理
        if res["code"] == 100:
            # 计算平均置信度
            res["score"] = averageScore(res["data"])
            # 执行 tbpu
            if msnInfo["tbpu"]:
                for tbpu in msnInfo["tbpu"]:
                    res["data"] = tbpu.run(res["data"])
                    # 如果忽略区域等处理将所有文本删除，则结束tbpu
                    if not res["data"]:
                        res["code"] = 101
                        res["data"] = ""
                        break
        return res

    # ========================= 【qml接口】 =========================

    def getStatus(self):  # 返回当前状态
        return {
            "apiKey": self._apiKey,
            "missionListsLength": self.getMissionListsLength(),
            "apiState": self._api.get_status()
            if self._api
            else {"state": "unavailable", "idleSeconds": 0, "error": ""},
        }

    def warmup(self, info):
        if not self._api:
            return "[Error] MissionOCR: API object is None."
        start_info = self._dictShortKey(info)
        argdIntConvert(start_info)
        return self._api.warmup(start_info)

    def releaseModel(self):
        if not self._api:
            return "[Error] MissionOCR: API object is None."
        if self.getMissionListsLength():
            return "[Error] OCR 任务正在运行，不能清理模型后台。"
        return self._api.release()

    @staticmethod
    def getSystemMemoryPercent():
        import psutil

        return float(psutil.virtual_memory().percent)

    def shutdown(self):
        if self._api:
            self._api.stop()

    def setApi(self, apiKey, info):  # 设置api
        # 成功返回 [Success] ，失败返回 [Error] 开头的字符串
        if self.getMissionListsLength():
            return "[Error] 当前任务尚未完成，请稍后切换。"
        if not apiKey:
            self.shutdown()
            self._api = None
            self._apiKey = ""
            return "[Success]"
        self._apiKey = apiKey
        info = self._dictShortKey(info)
        # 如果api对象已启动，则先停止
        if self._api:
            self._api.stop()
        # 获取新api对象
        res = getApiOcr(apiKey, info)
        # 失败
        if isinstance(res, str):
            self._apiKey = ""
            self._api = None
            return res
        # 成功
        else:
            self._api = res
            return "[Success]"

    # 将字典中配置项的长key转为短key
    # 如： ocr.win32_PaddleOCRv6_CUDA.device → device
    def _dictShortKey(self, d):
        newD = {}
        key1 = "ocr."
        key2 = key1 + self._apiKey + "."
        servicePrefix = "pluginServices." + self._apiKey + "."
        for k in d:
            if k.startswith(key2):
                newD[k[len(key2) :]] = d[k]
            elif k.startswith(key1):
                newD[k[len(key1) :]] = d[k]
            elif k.startswith(servicePrefix):
                # GlobalConfigs carries shared service settings in their
                # persisted namespace.  Flatten one service id so capability
                # APIs receive the same short keys as applyConfigs().
                rest = k[len(servicePrefix) :]
                separator = rest.find(".")
                if separator > 0 and separator + 1 < len(rest):
                    newD[rest[separator + 1 :]] = d[k]
            elif not k.startswith("ocr."):
                # Plugin-level shared-service values are already short keys
                # (for example ``service.host``).  Keep them when OCR is
                # configured, otherwise a capability cannot see its declared
                # serviceRefs configuration.
                newD[k] = d[k]
        return newD

    # ========================= 【qml接口】 =========================

    def getLocalOptions(self):
        if self._apiKey:
            return getLocalOptions(self._apiKey)
        else:
            return {}


# 全局 OCR任务管理器
MissionOCR = __MissionOcrClass()
