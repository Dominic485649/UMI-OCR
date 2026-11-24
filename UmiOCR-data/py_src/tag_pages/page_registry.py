# ==================================================
# =============== 插件页控制器 注册表 ===============
# ==================================================

"""
插件提供的页控制器注册表。

刻意与 tag_pages_connector 分开：连接器依赖 PySide6 ，而插件发现阶段
不应该因为"登记了一个页控制器"就把 Qt 拉进来。本模块只有标准库依赖。

契约 v1 中 PageClass 是硬编码的四个内置页，插件页即使声明了
needController 也拿不到控制器（addPage 返回空串，页面创建直接失败）。
本注册表补上这条路径：插件控制器在发现阶段登记【惰性工厂】，页面首次
打开时才真正 import 插件的实现模块。

插件页控制器类的构造签名与内置页一致：__init__(self, ctrlKey, connector)
"""

from umi_log import logger
from ..utils.ui_unlock import DOCUMENT_UI_FEATURE, is_ui_feature_enabled

# key -> 无参工厂，调用后返回控制器【类】
PluginPageClass = {}
# key -> 已解析的控制器类
_Resolved = {}
_RequiredFeatures = {}


def setPluginPageFeature(key, feature):
    _RequiredFeatures[key] = feature


def isPluginPageAvailable(key):
    feature = _RequiredFeatures.get(key, DOCUMENT_UI_FEATURE if key == "StructuredDocument" else "")
    return is_ui_feature_enabled(feature)


def resetPluginPageClasses():
    PluginPageClass.clear()
    _Resolved.clear()
    _RequiredFeatures.clear()


def registerPluginPageClass(key, factory, requiredFeature=None):
    """由插件控制器调用，登记一个插件页控制器工厂。"""
    if not callable(factory):
        raise TypeError(f"插件页 {key} 的控制器工厂必须可调用。")
    PluginPageClass[key] = factory
    _Resolved.pop(key, None)
    if requiredFeature is not None:
        setPluginPageFeature(key, requiredFeature)


def unregisterPluginPageClass(key):
    PluginPageClass.pop(key, None)
    _Resolved.pop(key, None)
    _RequiredFeatures.pop(key, None)


def getPluginPageClass(key):
    """惰性解析插件页控制器类。失败返回 None 并记录日志。"""
    if not isPluginPageAvailable(key):
        return None
    if key in _Resolved:
        return _Resolved[key]
    factory = PluginPageClass.get(key)
    if not factory:
        return None
    try:
        pageClass = factory()
    except Exception:
        logger.error(f"解析插件页控制器失败：{key}", exc_info=True, stack_info=True)
        return None
    if not callable(pageClass):
        logger.error(f"插件页 {key} 的控制器不是可调用对象。")
        return None
    _Resolved[key] = pageClass
    return pageClass
