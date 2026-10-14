# ================================================
# =============== 插件清单 解析与校验 ===============
# ================================================

"""
umi-plugin.json 是插件的唯一事实源。

设计要点：
- 【发现阶段只读 JSON，不导入插件 Python】。一个依赖损坏、平台不符或
  宿主 API 不兼容的插件仍然可以被列出、被解释、被禁用，而不会在启动时
  炸掉宿主进程。这是"安装/发现/启用/禁用/卸载后状态明确"的前提。
- 其他旧插件（只有 __init__.py 里的 PluginInfo 、没有清单）由 legacy 适配层
  合成一份等价清单，零改动继续可用。3.0 对明确已知的三个 2.x 实现有独立
  技术迁移门禁，且在 import 前生效。适配出来的清单标记 legacy=True 。
"""

import json
import os
import re

from umi_log import logger

from .host_api import (
    MANIFEST_NAME,
    SUPPORTED_SCHEMA_VERSIONS,
    matchTokenList,
    matchVersionRange,
    parseVersion,
)

# 3.0 只拒绝明确列出的 Umi-OCR 2.x 随包实现。其他插件（包括第三方
# OCR/document 插件）仍按通用清单/legacy 契约加载，不以能力类型推断来源。
KNOWN_PLUGIN_IDS_REQUIRING_3X = frozenset(
    {
        "win32_PaddleOCRv6_CPU",
        "win32_PaddleOCRv6_CUDA",
        "win32_PaddleOCRVL_1_6",
    }
)
KNOWN_PLUGIN_MIN_VERSION = "3.0.0"


# 插件状态
STATE_READY = "ready"  # 校验通过，已启用，可注册
STATE_DISABLED = "disabled"  # 用户主动禁用
STATE_INCOMPATIBLE = "incompatible"  # 宿主 API / 平台 / 架构 不匹配
STATE_CONFLICT = "conflict"  # 与另一个已启用插件互斥
STATE_INVALID = "invalid"  # 清单缺失或非法
STATE_ERROR = "error"  # 导入或注册阶段失败
STATE_UNHEALTHY = "unhealthy"  # 健康检查未通过

# vendor 目录默认追加到 sys.path 末尾，基础环境优先，避免插件污染宿主。
# 插件确需覆盖时显式声明 "priority": "prepend" 。
PRIORITY_APPEND = "append"
PRIORITY_PREPEND = "prepend"


class EntryRef:
    """入口引用 "<相对模块>:<属性>" 。相对模块为空表示插件包根。

    解析是惰性的：只有真正需要该入口时才 import ，这样重量级后端
    （CUDA、Paddle）不会拖慢启动，也不会在未使用时占用显存。
    """

    __slots__ = ("module", "attr", "raw")

    def __init__(self, module, attr, raw):
        self.module = module
        self.attr = attr
        self.raw = raw

    @classmethod
    def parse(cls, raw):
        text = str(raw or "").strip()
        if not text:
            return None, "入口引用为空。"
        if ":" not in text:
            return None, f'入口引用缺少 ":" 分隔符："{text}"，应形如 "api:Api" 。'
        module, _, attr = text.partition(":")
        module = module.strip().strip(".")
        attr = attr.strip()
        if not attr:
            return None, f'入口引用缺少属性名："{text}" 。'
        return cls(module, attr, text), ""

    def moduleName(self, pluginId):
        return f"{pluginId}.{self.module}" if self.module else pluginId

    def __repr__(self):
        return f"<EntryRef {self.raw}>"


def _translateConfig(node, tr):
    """递归翻译配置字典中的用户可见字符串。

    只翻译确定会出现在界面上的位置：title / toolTip / unit ，以及
    optionsList 里 [值, 显示文本] 的显示文本。其余值原样保留，避免把
    配置项的取值也误翻译掉。
    """
    if isinstance(node, dict):
        result = {}
        for key, value in node.items():
            if key in ("title", "toolTip", "unit") and isinstance(value, str):
                result[key] = tr(value)
            elif key == "optionsList" and isinstance(value, list):
                options = []
                for pair in value:
                    if isinstance(pair, list) and len(pair) >= 2 and isinstance(pair[1], str):
                        options.append([pair[0], tr(pair[1])] + list(pair[2:]))
                    else:
                        options.append(pair)
                result[key] = options
            else:
                result[key] = _translateConfig(value, tr)
        return result
    if isinstance(node, list):
        return [_translateConfig(item, tr) for item in node]
    return node


class Capability:
    """插件提供的一项能力。

    互斥关系由清单顶层的 conflicts 显式声明（例如 CPU 与 GPU OCR 插件
    各自 vendor 了不兼容的 paddle 构建），不在能力层面隐式推断。

    config 有两种写法：
    - 内联对象：配置直接写在清单里。发现阶段【完全不导入插件 Python】，
      这是推荐写法。
    - 入口字符串 "config:CONFIG"：配置由 Python 模块提供，适合需要按机器
      计算默认值的场景（如线程数取决于 CPU 核心数）。代价是发现阶段会
      导入插件包与该配置模块，因此配置模块必须保持轻量。
    """

    __slots__ = ("type", "entry", "config", "meta")

    def __init__(self, type_, entry, config, meta):
        self.type = type_
        self.entry = entry
        self.config = config
        self.meta = meta


class ServiceSpec:
    """插件级共享服务。

    服务和 capability 一样是惰性入口；唯一差别是它可以被多个 capability
    通过 meta.serviceRefs 引用，并且它的配置只在全局界面出现一次。
    """

    __slots__ = ("id", "entry", "config", "meta")

    def __init__(self, id_, entry, config, meta):
        self.id = id_
        self.entry = entry
        self.config = config
        self.meta = meta


class PageSpec:
    """插件提供的标签页。"""

    __slots__ = ("key", "qml", "controller", "title", "intro", "meta")

    def __init__(self, key, qml, controller, title, intro, meta):
        self.key = key
        self.qml = qml
        self.controller = controller
        self.title = title
        self.intro = intro
        self.meta = meta


class PluginManifest:
    __slots__ = (
        "id",
        "path",
        "name",
        "version",
        "hostApi",
        "platforms",
        "arches",
        "vendor",
        "license",
        "description",
        "homepage",
        "capabilities",
        "services",
        "pages",
        "conflicts",
        "vendorDirs",
        "pythonArchives",
        "resourceArchives",
        "dllDirs",
        "priority",
        "closureLock",
        "health",
        "i18nFile",
        "legacy",
    )

    def __init__(self, id_, path):
        self.id = id_
        self.path = path
        self.name = id_
        self.version = "0.0.0"
        self.hostApi = "*"
        self.platforms = []
        self.arches = []
        self.vendor = ""
        self.license = ""
        self.description = ""
        self.homepage = ""
        self.capabilities = []
        self.services = []
        self.pages = []
        self.conflicts = []
        self.vendorDirs = []
        self.pythonArchives = []
        self.resourceArchives = []
        self.dllDirs = []
        self.priority = PRIORITY_APPEND
        self.closureLock = ""
        self.health = None
        self.i18nFile = ""
        self.legacy = False

    def capabilityTypes(self):
        return [c.type for c in self.capabilities]

    def toDict(self):
        """供 QML / 诊断使用的纯数据视图。"""
        return {
            "id": self.id,
            "path": self.path,
            "name": self.name,
            "version": self.version,
            "hostApi": self.hostApi,
            "platforms": list(self.platforms),
            "arches": list(self.arches),
            "vendor": self.vendor,
            "license": self.license,
            "description": self.description,
            "homepage": self.homepage,
            "capabilities": self.capabilityTypes(),
            "services": [service.id for service in self.services],
            "pages": [p.key for p in self.pages],
            "conflicts": list(self.conflicts),
            "legacy": self.legacy,
        }


def _asList(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [v for v in value if v is not None]
    return [value]


def manifestPath(pluginDir):
    return os.path.join(pluginDir, MANIFEST_NAME)


def hasManifest(pluginDir):
    return os.path.isfile(manifestPath(pluginDir))


def checkKnownPluginMigration(pluginId, version=None, legacy=False):
    """Pure, id-scoped technical migration check; no plugin code is imported.

    Generic manifests and legacy plugins retain their existing contract.  For
    these three known ids only, a malformed version fails closed without
    throwing during discovery.  Numeric components and optional suffixes use
    the same comparison semantics as the existing Host API version parser.
    """
    if pluginId not in KNOWN_PLUGIN_IDS_REQUIRING_3X:
        return ""
    nextStep = (
        f"请安装已完成 3.x 技术迁移、带有 {MANIFEST_NAME} 且 version >= "
        f"{KNOWN_PLUGIN_MIN_VERSION} 的更新插件；不要仅修改旧实现的版本号。"
        "应用版本为 3.0，宿主 API 仍为 2.8。"
    )
    if legacy:
        return (
            f'已知插件 "{pluginId}" 没有 {MANIFEST_NAME}，属于 2.x 旧版实现；'
            f"Umi-OCR 3.0 不兼容该实现。{nextStep}"
        )
    text = str(version or "").strip()
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,2}(?:[-+][0-9A-Za-z][0-9A-Za-z.+-]*)?", text):
        return (
            f'已知插件 "{pluginId}" 的 version "{text}" 无法进行 3.x 技术迁移校验。'
            f"{nextStep}"
        )
    try:
        current = parseVersion(text)
    except (TypeError, ValueError, OverflowError):
        return f'已知插件 "{pluginId}" 的 version 无法进行 3.x 技术迁移校验。{nextStep}'
    if current < parseVersion(KNOWN_PLUGIN_MIN_VERSION):
        return (
            f'已知插件 "{pluginId}" 的 version "{text}" 属于 2.x 旧版实现；'
            f"Umi-OCR 3.0 不兼容该实现。{nextStep}"
        )
    return ""


def loadManifest(pluginId, pluginDir, translator=None):
    """读取并校验 umi-plugin.json 。成功返回 (manifest, "") ，失败返回 (None, 原因)。"""
    path = manifestPath(pluginDir)
    try:
        with open(path, "r", encoding="utf-8") as stream:
            raw = json.load(stream)
    except Exception as e:
        return None, f"读取 {MANIFEST_NAME} 失败：{e}"
    if not isinstance(raw, dict):
        return None, f"{MANIFEST_NAME} 顶层必须是对象。"

    schema = raw.get("schema_version")
    if schema not in SUPPORTED_SCHEMA_VERSIONS:
        supported = ", ".join(str(v) for v in SUPPORTED_SCHEMA_VERSIONS)
        return None, f"不支持的 schema_version：{schema}（宿主支持：{supported}）。"

    declaredId = str(raw.get("id") or "").strip()
    if not declaredId:
        return None, "清单缺少 id 。"
    if declaredId != pluginId:
        return None, f'清单 id "{declaredId}" 与目录名 "{pluginId}" 不一致。'

    manifest = PluginManifest(pluginId, pluginDir)

    def tr(text):
        text = str(text or "")
        if translator and text:
            return translator(text)
        return text

    manifest.name = tr(raw.get("name") or pluginId)
    manifest.version = str(raw.get("version") or "").strip()
    if not manifest.version:
        return None, "清单缺少 version 。"
    manifest.hostApi = str(raw.get("host_api") or "*").strip()
    manifest.platforms = [str(v) for v in _asList(raw.get("platform"))]
    manifest.arches = [str(v) for v in _asList(raw.get("arch"))]
    manifest.vendor = str(raw.get("vendor") or "")
    manifest.license = str(raw.get("license") or "")
    manifest.description = tr(raw.get("description") or "")
    manifest.homepage = str(raw.get("homepage") or "")
    manifest.conflicts = [str(v) for v in _asList(raw.get("conflicts"))]
    manifest.i18nFile = str(raw.get("i18n") or "")

    runtime = raw.get("runtime") or {}
    if not isinstance(runtime, dict):
        return None, "runtime 必须是对象。"
    manifest.pythonArchives = [str(v) for v in _asList(runtime.get("python_archives"))]
    manifest.resourceArchives = [str(v) for v in _asList(runtime.get("resource_archives"))]
    for archive in manifest.pythonArchives + manifest.resourceArchives:
        target = os.path.abspath(os.path.join(pluginDir, archive))
        if os.path.commonpath([os.path.abspath(pluginDir), target]) != os.path.abspath(pluginDir):
            return None, "归档路径必须位于插件目录内。"
        if not os.path.isfile(target):
            return None, f"插件归档不存在：{archive}"
    manifest.vendorDirs = [str(v) for v in _asList(runtime.get("vendor_dirs"))]
    manifest.dllDirs = [str(v) for v in _asList(runtime.get("dll_dirs"))]
    manifest.closureLock = str(runtime.get("closure_lock") or "")
    priority = str(runtime.get("priority") or PRIORITY_APPEND).strip().lower()
    if priority not in (PRIORITY_APPEND, PRIORITY_PREPEND):
        return None, f'runtime.priority 只能是 "{PRIORITY_APPEND}" 或 "{PRIORITY_PREPEND}" 。'
    manifest.priority = priority

    capabilities = _asList(raw.get("capabilities"))
    if not capabilities:
        return None, "清单必须至少声明一项 capabilities 。"
    for index, item in enumerate(capabilities):
        if not isinstance(item, dict):
            return None, f"capabilities[{index}] 必须是对象。"
        capType = str(item.get("type") or "").strip()
        if not capType:
            return None, f"capabilities[{index}] 缺少 type 。"
        entry, err = EntryRef.parse(item.get("entry"))
        if not entry:
            return None, f"capabilities[{index}].entry {err}"
        configValue = item.get("config")
        config = None
        if isinstance(configValue, dict):
            config = _translateConfig(configValue, tr)  # 内联配置，零导入
        elif configValue:
            config, err = EntryRef.parse(configValue)
            if not config:
                return None, f"capabilities[{index}].config {err}"
        manifest.capabilities.append(
            Capability(capType, entry, config, dict(item.get("meta") or {}))
        )

    serviceIds = set()
    for index, item in enumerate(_asList(raw.get("services"))):
        if not isinstance(item, dict):
            return None, f"services[{index}] 必须是对象。"
        serviceId = str(item.get("id") or "").strip()
        if not serviceId:
            return None, f"services[{index}] 缺少 id 。"
        if serviceId in serviceIds:
            return None, f"services 中的 id 重复：{serviceId} 。"
        entry, err = EntryRef.parse(item.get("entry"))
        if not entry:
            return None, f"services[{index}].entry {err}"
        configValue = item.get("config")
        config = None
        if isinstance(configValue, dict):
            config = _translateConfig(configValue, tr)
        elif configValue:
            config, err = EntryRef.parse(configValue)
            if not config:
                return None, f"services[{index}].config {err}"
        serviceIds.add(serviceId)
        manifest.services.append(
            ServiceSpec(serviceId, entry, config, dict(item.get("meta") or {}))
        )

    for index, capability in enumerate(manifest.capabilities):
        refs = capability.meta.get("serviceRefs") or []
        if not isinstance(refs, list) or not all(isinstance(item, str) for item in refs):
            return None, f"capabilities[{index}].meta.serviceRefs 必须是字符串列表。"
        missing = [ref for ref in refs if ref not in serviceIds]
        if missing:
            return None, (
                f"capabilities[{index}].meta.serviceRefs 引用了未声明的服务："
                f"{', '.join(missing)} 。"
            )

    for index, item in enumerate(_asList(raw.get("pages"))):
        if not isinstance(item, dict):
            return None, f"pages[{index}] 必须是对象。"
        key = str(item.get("key") or "").strip()
        if not key:
            return None, f"pages[{index}] 缺少 key 。"
        qml = str(item.get("qml") or "").strip()
        if not qml:
            return None, f"pages[{index}] 缺少 qml 。"
        qmlPath = os.path.join(pluginDir, qml)
        if not os.path.isfile(qmlPath) and not manifest.resourceArchives:
            return None, f"pages[{index}] 的 qml 文件不存在：{qmlPath}"
        controller = None
        if item.get("controller"):
            controller, err = EntryRef.parse(item.get("controller"))
            if not controller:
                return None, f"pages[{index}].controller {err}"
        manifest.pages.append(
            PageSpec(
                key,
                qmlPath,
                controller,
                tr(item.get("title") or key),
                tr(item.get("intro") or ""),
                dict(item.get("meta") or {}),
            )
        )

    if raw.get("health"):
        health, err = EntryRef.parse(raw.get("health"))
        if not health:
            return None, f"health {err}"
        manifest.health = health

    return manifest, ""


def adaptLegacyPluginInfo(pluginId, pluginDir, pluginInfo):
    """把旧版 PluginInfo 合成为等价清单。

    旧插件没有版本、平台、架构和依赖闭包信息，因此这些字段留空 = 不限制。
    api_class 是【已求值的对象】而不是入口字符串，用 meta 直接携带，
    调用方通过 resolvedEntry 拿到它，无需再次 import 。
    """
    if not isinstance(pluginInfo, dict):
        return None, "PluginInfo 必须是字典。"
    group = str(pluginInfo.get("group") or "").strip()
    if not group:
        return None, "PluginInfo 中未定义 group 。"
    if "api_class" not in pluginInfo:
        return None, "PluginInfo 中未定义 api_class 。"

    manifest = PluginManifest(pluginId, pluginDir)
    manifest.legacy = True
    manifest.name = pluginId
    manifest.version = "0.0.0"
    manifest.hostApi = "*"

    capability = Capability(
        group,
        None,
        None,
        {
            "resolvedEntry": pluginInfo["api_class"],
            "resolvedConfig": {
                "global_options": pluginInfo.get("global_options"),
                "local_options": pluginInfo.get("local_options"),
            },
        },
    )
    manifest.capabilities.append(capability)

    page = pluginInfo.get("page")
    if page:
        if not isinstance(page, dict):
            return None, "PluginInfo.page 必须是字典。"
        key = str(page.get("key") or "").strip()
        qml = str(page.get("qml") or "").strip()
        if not key or not qml:
            return None, "PluginInfo.page 缺少 key 或 qml 。"
        qmlPath = os.path.join(pluginDir, qml)
        if not os.path.isfile(qmlPath) and not manifest.resourceArchives:
            return None, f"插件页面不存在：{qmlPath}"
        manifest.pages.append(
            PageSpec(
                key,
                qmlPath,
                None,
                str(page.get("title") or key),
                str(page.get("intro") or ""),
                {"needController": bool(page.get("needController", False))},
            )
        )
    return manifest, ""


def checkCompatibility(manifest, hostApiVersion, platform, arch):
    """返回 "" 表示兼容，否则返回不兼容原因。"""
    if not matchVersionRange(hostApiVersion, manifest.hostApi):
        return (
            f"插件要求宿主 API {manifest.hostApi} ，"
            f"当前宿主为 {hostApiVersion} 。请升级 Umi-OCR 或改用匹配的插件版本。"
        )
    if not matchTokenList(platform, manifest.platforms):
        supported = ", ".join(manifest.platforms) or "-"
        return f"插件仅支持平台 {supported} ，当前平台为 {platform} 。"
    if not matchTokenList(arch, manifest.arches):
        supported = ", ".join(manifest.arches) or "-"
        return f"插件仅支持架构 {supported} ，当前架构为 {arch} 。"
    return ""


def loadTranslator(pluginDir, i18nFile):
    """按现有 plugin_i18n 流程加载插件私有翻译表。失败不阻断加载。"""
    if not i18nFile:
        return None
    try:
        from plugin_i18n import Translator

        return Translator(os.path.join(pluginDir, MANIFEST_NAME), i18nFile)
    except Exception:
        logger.error(f"加载插件翻译失败：{pluginDir} / {i18nFile}", exc_info=True)
        return None
