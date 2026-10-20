# ==============================================
# =============== 插件能力类型 注册表 ===============
# ==============================================

"""
能力（capability）是插件与宿主之间的契约单位。

在契约 v1 里只存在隐式的 "ocr" 一种能力，且被硬编码在插件控制器里
（PLUGINS_GROUPS = ["ocr"] 与 initOcrPlugins(...) ）。v2 把它抽象成注册表：
新增一种能力类型 = 新建一个 CapabilityRegistry 并登记到 CAPABILITY_TYPES ，
插件控制器本身不需要再改。
"""

from umi_log import logger


class CapabilityRegistry:
    """一种能力类型下，所有已注册插件的表。

    entry 是【惰性解析器】而不是已导入的对象：只有真正要实例化后端时
    才会 import 插件的重量级模块。config 则在发现阶段就要拿到，因为
    全局设置界面需要它来构建配置项。
    """

    def __init__(self, typeName, title):
        self.typeName = typeName
        self.title = title
        self._entries = {}

    def reset(self):
        self._entries.clear()

    def register(self, pluginId, resolve, config=None, meta=None):
        """resolve: 无参可调用，返回该能力的实现对象（类或工厂）。"""
        if not callable(resolve):
            raise TypeError(f"能力 {self.typeName}/{pluginId} 的 resolve 必须可调用。")
        config = config or {}
        self._entries[pluginId] = {
            "resolve": resolve,
            "global_options": config.get("global_options"),
            "local_options": config.get("local_options"),
            "meta": dict(meta or {}),
        }

    def unregister(self, pluginId):
        self._entries.pop(pluginId, None)

    def keys(self):
        return list(self._entries.keys())

    def has(self, pluginId):
        return pluginId in self._entries

    def get(self, pluginId):
        return self._entries.get(pluginId)

    def resolve(self, pluginId):
        """解析出能力实现对象。失败返回 (None, 错误信息)。"""
        entry = self._entries.get(pluginId)
        if not entry:
            return None, f'"{pluginId}" 未注册 {self.typeName} 能力。'
        try:
            return entry["resolve"](), ""
        except Exception as e:
            logger.error(
                f"解析 {self.typeName} 能力 {pluginId} 失败。",
                exc_info=True,
                stack_info=True,
            )
            return None, f"加载 {pluginId} 的 {self.typeName} 实现失败：{e}"

    def localOptions(self, pluginId):
        entry = self._entries.get(pluginId)
        return (entry or {}).get("local_options") or {}

    def globalOptions(self, pluginId):
        entry = self._entries.get(pluginId)
        return (entry or {}).get("global_options") or None

    def options(self):
        """供 QML 构建配置界面的字典，与契约 v1 的形状保持一致。"""
        return {
            key: {
                "global_options": entry["global_options"],
                "local_options": entry["local_options"],
                "meta": dict(entry["meta"]),
            }
            for key, entry in self._entries.items()
        }


# 宿主内置的能力类型。新增类型只需在这里登记。
CAPABILITY_TYPES = {}


def defineCapabilityType(registry):
    CAPABILITY_TYPES[registry.typeName] = registry
    return registry


def getCapabilityRegistry(typeName):
    return CAPABILITY_TYPES.get(typeName)


def knownCapabilityTypes():
    return list(CAPABILITY_TYPES.keys())


def resetAllCapabilities():
    for registry in CAPABILITY_TYPES.values():
        registry.reset()


def loadBuiltinCapabilityTypes():
    """导入内置能力类型模块，触发它们的登记。

    这些模块都是纯 Python 且不依赖任何后端，导入代价可忽略；
    真正重量级的插件实现仍然是惰性的。
    """
    from ..ocr import api as _ocr_api  # noqa: F401
    from ..document import api as _document_api  # noqa: F401

    return CAPABILITY_TYPES
