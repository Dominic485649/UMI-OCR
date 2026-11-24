# ==========================================================
# =============== 结构化文档 插件接口管理 ===============
# ==========================================================

"""
document 能力的注册表。

document 是与 ocr 平级的【正式能力类型】，不是 OCR 的变体：

| 维度     | ocr                              | document                                  |
| -------- | -------------------------------- | ----------------------------------------- |
| 输入     | 单张图片（path/bytes/base64）    | 整份文档（图片或 PDF）+ 页范围             |
| 输出     | 文本框列表 [{box,text,score}]    | 结构化块 [{type,box,text,...}] + Markdown |
| 后端     | 进程内推理                       | 可能是外部服务，需要连接/启动/健康检查      |
| 失败模式 | 模型加载失败                     | 服务不可达、模型目录缺失、协议不匹配        |

因此 document 有独立的注册表、独立的任务管理器（MissionDocument）、
独立的 QML 管理器（DocumentManager.qml）和独立的错误路径。
把 document 后端接到 OCR 的 api 上是伪装修复，本契约明确禁止。

## document 能力实现契约

能力入口是一个可调用对象，接受合并后的配置字典 argd ，返回后端实例。
后端实例必须提供：

    start(argd)   -> ""            正常；"[Error] ..." 终止本队列
    parseDoc(msn) -> dict          见下方结果约定
    get_status()  -> {"state": "unloaded|warming|loaded|unavailable",
                      "idleSeconds": float, "error": str}
    health(argd)  -> {"ok": bool, "message": str, "details": dict}
    release()     -> str           释放模型/连接，保留实例
    stop()        -> None          进程退出前的最终清理

parseDoc 的 msn 至少包含 {"path": 文档路径}，可含 "pageRange"。
返回结果约定（与 OCR 的 code 语义保持一致）：

    {"code": 100, "data": {"blocks": [...], "markdown": str, "assets": [...]}}
    {"code": 101, "data": ""}                      文档中没有可提取内容
    {"code": 9xx, "data": "[Error] 可操作的中文提示"}  失败

block 形状：{"type": "title|text|table|formula|figure|caption",
             "page": int, "box": [[x,y]*4], "text": str, "html": str}
"""

from umi_log import logger

from ...plugins_controller.capabilities import CapabilityRegistry, defineCapabilityType

# document 能力注册表。类型名 "document" 同时是 QML 全局配置的键名。
DocumentCapability = defineCapabilityType(CapabilityRegistry("document", "结构化文档"))


def getApiDocument(apiKey, argd):
    """生成一个 document api 实例。成功返回对象，失败返回 [Error] 开头的字符串。"""
    for k in argd:
        n = argd[k]
        if isinstance(n, float):
            rounded = round(n)
            if abs(n - rounded) <= 1e-7:
                argd[k] = rounded
    if not DocumentCapability.has(apiKey):
        return f'[Error] "{apiKey}" is not a registered document capability.'
    apiClass, err = DocumentCapability.resolve(apiKey)
    if not apiClass:
        return f"[Error] {err}"
    try:
        return apiClass(argd)
    except Exception as e:
        logger.error(
            f"生成 document api 实例 {apiKey} 失败。", exc_info=True, stack_info=True
        )
        return f"[Error] Failed to generate document API instance {apiKey}: {e}"


def getLocalOptions(apiKey):
    return DocumentCapability.localOptions(apiKey)


def getApiKeys():
    return DocumentCapability.keys()


def hasAnyApi():
    return bool(DocumentCapability.keys())
