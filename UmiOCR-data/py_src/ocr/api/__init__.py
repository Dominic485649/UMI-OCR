# ===============================================
# =============== OCR 插件接口管理 ===============
# ===============================================

"""
OCR 能力的注册表。

契约 v2 起，本模块不再自己维护插件字典，而是复用
plugins_controller.capabilities.CapabilityRegistry ，与 document 等
其它能力类型共用同一套注册、解析和配置暴露逻辑。

OCR 能力实现契约：
- 能力入口是一个可调用对象，接受【一个】参数（合并后的配置字典 argd），
  返回 OCR API 实例。旧插件 PluginInfo 里的 api_class 正好是这个形状，
  因此 legacy 适配层无需做任何转换。
"""

from umi_log import logger

from ...plugins_controller.capabilities import CapabilityRegistry, defineCapabilityType

# OCR 能力注册表。能力类型名 "ocr" 同时也是 QML 全局配置的键名，不可更改。
OcrCapability = defineCapabilityType(CapabilityRegistry("ocr", "文字识别"))


def getApiOcr(apiKey, argd):
    """生成一个 OCR api 实例。成功返回对象，失败返回 [Error] 开头的字符串。"""
    # 检测argd，恢复int类型
    for k in argd:
        n = argd[k]
        if isinstance(n, float):
            rounded = round(n)
            if abs(n - rounded) <= 1e-7:
                argd[k] = rounded
    if not OcrCapability.has(apiKey):
        return f'[Error] "{apiKey}" is not a registered OCR capability.'
    apiClass, err = OcrCapability.resolve(apiKey)
    if not apiClass:
        return f"[Error] {err}"
    try:
        return apiClass(argd)  # 实例化后返回
    except Exception as e:
        logger.error(f"生成api实例{apiKey}失败。", exc_info=True, stack_info=True)
        return f"[Error] Failed to generate API instance {apiKey}: {e}"


def getLocalOptions(apiKey):
    """返回一个 API 的局部配置字典。"""
    return OcrCapability.localOptions(apiKey)


def getApiKeys():
    """已注册的 OCR 插件 key 列表。基础包未安装任何 OCR 后端时为空。"""
    return OcrCapability.keys()


def hasAnyApi():
    """是否存在可用的 OCR 后端。

    基础包不再内置任何 OCR 实现，UI 必须据此给出"未安装 OCR 后端"的
    明确提示，而不能暗示 CPU 推理可用。
    """
    return bool(OcrCapability.keys())
