# =======================================
# =============== 通用工具 ===============
# =======================================

import re
import os
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QJSValue

from umi_log import logger

# 传入文件名，检测是否含非法字符。没问题返回True
def allowedFileName(fn):
    pattern = r'[\\/:*?"<>|]'
    if re.search(pattern, fn):
        return False  # 转布尔值
    else:
        return True


# 复制文本到剪贴板
def copyText(text):
    QGuiApplication.clipboard().setText(text)


# QUrl列表 转 String列表
def QUrl2String(urls):
    from ..plugins_controller.services import _to_python_value
    from PySide6.QtCore import QUrl

    urls = _to_python_value(urls)
    if not isinstance(urls, (list, tuple)):
        urls = [urls] if urls else []
    from ..plugins_controller.services import _to_python_value
    from PySide6.QtCore import QUrl

    urls = _to_python_value(urls)
    if not isinstance(urls, (list, tuple)):
        urls = [urls] if urls else []
    from ..plugins_controller.services import _to_python_value
    from PySide6.QtCore import QUrl

    urls = _to_python_value(urls)
    if not isinstance(urls, (list, tuple)):
        urls = [urls] if urls else []
    resList = []
    for url in urls:
        if isinstance(url, str):
            url = QUrl(url) if url.startswith("file:") else QUrl.fromLocalFile(url)
        if not isinstance(url, QUrl):
            continue
        if isinstance(url, str):
            url = QUrl(url) if url.startswith("file:") else QUrl.fromLocalFile(url)
        if not isinstance(url, QUrl):
            continue
        if isinstance(url, str):
            url = QUrl(url) if url.startswith("file:") else QUrl.fromLocalFile(url)
        if not isinstance(url, QUrl):
            continue
        if url.isLocalFile():
            # QUrl.toLocalFile() has already decoded the local path. Validation
            # belongs to the asynchronous importer so it can report a usable error.
            resList.append(url.toLocalFile())
    return resList


# 初始化配置项字典数值，等同于 Configs.qml 的 function initConfigDict
# 主要是为了补充type和default
def initConfigDict(dic):
    toDict = {}

    def handleConfigItem(config, key):  # 处理一个配置项
        # 类型：指定type
        if not config["type"] == "":
            if config["type"] == "file":  # 文件选择
                config["default"] = "" if not config["default"] is None else None
            elif config["type"] == "var" and config["default"] is None:  # 任意类型
                config["default"] = ""
        # 类型：省略type
        else:
            if isinstance(config["default"], bool):  # 布尔
                config["type"] = "boolean"
            elif "optionsList" in config:  # 枚举
                config["type"] = "enum"
                if len(config["optionsList"]) == 0:
                    logger.error(f"处理配置项异常：{key}枚举列表为空。")
                    return
                if config["default"] is None:
                    config["default"] = config["optionsList"][0][0]
            elif isinstance(config["default"], str):  # 文本
                config["type"] = "text"
            elif isinstance(config["default"], (int, float)):  # 数字
                config["type"] = "number"
            elif "btnsList" in config:  # 按钮组
                config["type"] = "buttons"
                return
            else:
                logger.error(f"未知类型的配置项：{key}")
                return

    def handleConfigGroup(group, prefix=""):  # 处理一个配置组
        for key in group:
            config = group[key]
            if not isinstance(config, dict):
                continue
            # 补充空白参数
            if "type" not in config:  # 类型
                config["type"] = ""
            if "default" not in config:  # 默认值
                config["default"] = None
            if "advanced" not in config:  # 是否为高级选项
                config["advanced"] = False
            # 记录完整key
            fullKey = prefix + key
            if config["type"] == "group":  # 若是配置项组，递归遍历
                handleConfigGroup(config, fullKey + ".")  # 前缀加深一层
            else:  # 若是配置项
                toDict[fullKey] = config
                handleConfigItem(config, fullKey)

    handleConfigGroup(dic)
    return toDict


# 整理 argd 参数字典，将 float 恢复 int 类型，如 12.0 → 12
def argdIntConvert(argd):
    for k, v in argd.items():
        if isinstance(v, float) and v.is_integer():
            argd[k] = int(v)
