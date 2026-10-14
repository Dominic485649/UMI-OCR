# =======================================
# =============== 加载插件 ===============
# =======================================

"""
插件控制器（契约 v2）。

与 v1 的关键差异：
1. 发现阶段【只读 umi-plugin.json】，不导入插件 Python 。因此依赖损坏、
   平台不符或宿主 API 不兼容的插件仍然可以被列出并解释原因，而不会
   在启动时炸掉宿主。
2. 能力类型来自注册表而不是硬编码的 PLUGINS_GROUPS ，ocr 与 document
   走各自独立的注册、配置、任务和错误路径。
3. 能力实现是【惰性解析】的，重量级后端（CUDA / Paddle / 外部服务）
   在真正被使用前不会被导入。
4. 插件可以携带私有 vendor 目录与 DLL 目录，由宿主统一挂载，用户不必
   手动 pip install 。vendor 默认追加到 sys.path 末尾，基础环境优先。
5. 一般旧版 PluginInfo 插件由 legacy 适配层零改动继续可用；明确已知的
   三个 2.x 实现先经过 3.0 技术迁移校验，不会先导入再拒绝。
"""

import glob
import importlib
import json
import os
import site
import sys

from umi_log import logger

from .capabilities import (
    getCapabilityRegistry,
    knownCapabilityTypes,
    loadBuiltinCapabilityTypes,
    resetAllCapabilities,
)
from .host_api import (
    HOST_API_VERSION,
    hostArch,
    hostEnvironment,
    hostPlatform,
)
from .manifest import (
    PRIORITY_PREPEND,
    STATE_CONFLICT,
    STATE_DISABLED,
    STATE_ERROR,
    STATE_INCOMPATIBLE,
    STATE_INVALID,
    STATE_READY,
    STATE_UNHEALTHY,
    adaptLegacyPluginInfo,
    checkCompatibility,
    checkKnownPluginMigration,
    hasManifest,
    loadManifest,
    loadTranslator,
)
from .services import PluginServices

# 插件 总目录
PLUGINS_PATH = "plugins"
# 插件启用/禁用状态。属于可移植用户状态，发布包中不得存在。
PLUGINS_STATE_FILE = ".plugins_state"

_DllDirectoryHandles = []


def _appendDllSearchPath(path, prepend=False):
    """让使用传统 LoadLibrary 的后端也能找到插件私有 DLL。"""
    path = os.path.abspath(path)
    entries = os.environ.get("PATH", "").split(os.pathsep) if os.environ.get("PATH") else []
    known = {entry.casefold() for entry in entries if entry}
    if path.casefold() in known:
        return
    if prepend:
        entries.insert(0, path)
    else:
        entries.append(path)
    os.environ["PATH"] = os.pathsep.join(entries)


class PluginRecord:
    """一个插件目录的完整状态。无论加载成功与否都会有一条记录。"""

    __slots__ = ("id", "path", "manifest", "state", "message", "health")

    def __init__(self, id_, path):
        self.id = id_
        self.path = path
        self.manifest = None
        self.state = STATE_INVALID
        self.message = ""
        self.health = None

    def toDict(self):
        info = {
            "id": self.id,
            "path": self.path,
            "state": self.state,
            "message": self.message,
            "health": self.health,
        }
        if self.manifest:
            info.update(self.manifest.toDict())
        else:
            info.setdefault("name", self.id)
            info.setdefault("version", "")
            info.setdefault("capabilities", [])
            info.setdefault("legacy", False)
        return info


class _PluginsControllerClass:
    def __init__(self):
        self.records = {}
        self.pageInfos = []
        self._enabledState = {}
        self._initialized = False
        self._resourceArchives = set()

    # ========================= 【对外接口】 =========================

    def init(self):
        """扫描、校验并注册全部插件。返回供 QML 使用的汇总信息。"""
        loadBuiltinCapabilityTypes()
        resetAllCapabilities()
        PluginServices.reset()
        if self._resourceArchives:
            from PySide6.QtCore import QResource
            for path in self._resourceArchives: QResource.unregisterResource(path)
            self._resourceArchives.clear()
        import importlib
        for name in list(sys.modules):
            if any(name == key or name.startswith(key + ".") for key in self.records):
                del sys.modules[name]
        importlib.invalidate_caches()
        self.records = {}
        self.pageInfos = []

        if not os.path.exists(PLUGINS_PATH):
            try:
                os.makedirs(PLUGINS_PATH)
            except OSError as e:
                logger.error(f"插件目录创建失败: {PLUGINS_PATH} {e}")
            return self._summary()

        self._enabledState = self._readEnabledState()
        # 用绝对路径，避免后续任何 chdir 让插件包解析到错误位置。
        site.addsitedir(os.path.abspath(PLUGINS_PATH))  # 使 import <插件id> 可用

        for name in sorted(os.listdir(PLUGINS_PATH)):
            pluginDir = os.path.join(PLUGINS_PATH, name)
            if not os.path.isdir(pluginDir):
                continue
            if not hasManifest(pluginDir) and not os.path.isfile(
                os.path.join(pluginDir, "__init__.py")
            ):
                continue  # 既不是 v2 插件也不是旧版插件，忽略
            self.records[name] = self._discover(name, pluginDir)

        self._resolveConflicts()

        for record in self.records.values():
            if record.state == STATE_READY:
                self._activate(record)

        self._initialized = True
        return self._summary()

    def getPlugins(self):
        """全部插件的状态列表，供插件管理界面使用。"""
        return [r.toDict() for r in self.records.values()]

    def setEnabled(self, pluginId, enabled):
        """启用/禁用一个插件。返回给用户看的提示文本。

        宿主在当前任务完成后刷新能力并结束独立工作进程。
        """
        record = self.records.get(pluginId)
        if not record:
            return f'[Error] 插件不存在："{pluginId}"'
        self._enabledState[pluginId] = bool(enabled)
        if not self._writeEnabledState():
            return "[Error] 写入插件启用状态失败，请检查目录读写权限。"
        return "[Success] 已保存，将在当前任务结束后自动刷新插件。"

    def isEnabled(self, pluginId):
        return self._enabledState.get(pluginId, True)

    def runHealthCheck(self, pluginId):
        """按需执行插件自带的健康检查。

        健康检查【必须】在插件真正可用时才返回 ok=True 。UI 依赖它来
        决定是否显示"可用"，不得凭"已发现"就宣称可用。
        """
        record = self.records.get(pluginId)
        if not record:
            return {"ok": False, "message": f'插件不存在："{pluginId}"', "details": {}}
        if record.state not in (STATE_READY, STATE_UNHEALTHY):
            return {
                "ok": False,
                "message": record.message or f"插件当前状态为 {record.state} 。",
                "details": {"state": record.state},
            }
        manifest = record.manifest
        if not manifest or not manifest.health:
            result = {
                "ok": True,
                "message": "该插件未提供健康检查，已按加载成功处理。",
                "details": {"declared": False},
            }
            record.health = result
            return result
        try:
            checker = self._resolveEntry(manifest, manifest.health)
            result = checker()
        except Exception as e:
            logger.error(f"插件 {pluginId} 健康检查异常。", exc_info=True, stack_info=True)
            result = {"ok": False, "message": f"健康检查异常：{e}", "details": {}}
        if not isinstance(result, dict):
            result = {"ok": False, "message": "健康检查返回了不符合契约的结果。", "details": {}}
        result = {
            "ok": bool(result.get("ok")),
            "message": str(result.get("message") or ""),
            "details": result.get("details") or {},
        }
        record.health = result
        record.state = STATE_READY if result["ok"] else STATE_UNHEALTHY
        if not result["ok"]:
            record.message = result["message"]
        return result

    def hostInfo(self):
        return hostEnvironment()

    # ========================= 【发现】 =========================

    def _discover(self, name, pluginDir):
        record = PluginRecord(name, os.path.abspath(pluginDir))

        if not self.isEnabled(name):
            record.state = STATE_DISABLED
            record.message = "已被用户禁用。"
            # 仍然读取清单，好让界面显示名称与版本
            if hasManifest(pluginDir):
                manifest, _ = loadManifest(name, pluginDir)
                record.manifest = manifest
            return record

        if hasManifest(pluginDir):
            translator = None
            probe, err = loadManifest(name, pluginDir)
            if probe:
                reason = checkKnownPluginMigration(name, probe.version)
                if reason:
                    record.manifest = probe
                    record.state = STATE_INCOMPATIBLE
                    record.message = reason
                    return record
            if probe and probe.i18nFile:
                translator = loadTranslator(pluginDir, probe.i18nFile)
                probe, err = loadManifest(name, pluginDir, translator)
            if not probe:
                record.state = STATE_INVALID
                record.message = err
                logger.error(f"插件 {name} 清单非法：{err}")
                return record
            record.manifest = probe
        else:
            # 已知无清单的 2.x 实现必须在导入 PluginInfo / 挂载运行时前拒绝。
            # 不按能力类型、第三方身份或来源屏蔽一般 legacy 插件。
            reason = checkKnownPluginMigration(name, legacy=True)
            if reason:
                record.state = STATE_INCOMPATIBLE
                record.message = reason
                return record
            manifest, err = self._loadLegacy(name, pluginDir)
            if not manifest:
                record.state = STATE_INVALID
                record.message = err
                logger.error(f"加载旧版插件 {name} 失败：{err}")
                return record
            record.manifest = manifest

        reason = checkCompatibility(
            record.manifest, HOST_API_VERSION, hostPlatform(), hostArch()
        )
        if reason:
            record.state = STATE_INCOMPATIBLE
            record.message = reason
            return record

        unknown = [
            t for t in record.manifest.capabilityTypes() if not getCapabilityRegistry(t)
        ]
        if unknown:
            known = ", ".join(knownCapabilityTypes()) or "-"
            record.state = STATE_INCOMPATIBLE
            record.message = (
                f'插件声明了本宿主未知的能力类型：{", ".join(unknown)} 。'
                f"当前宿主支持：{known} 。"
            )
            return record

        record.state = STATE_READY
        return record

    def _loadLegacy(self, name, pluginDir):
        """旧版插件没有清单，必须导入才能读到 PluginInfo 。"""
        self._mountRuntime(None, pluginDir)
        try:
            module = importlib.import_module(name)
        except Exception as e:
            return None, f"动态导入包失败：{e}"
        if not hasattr(module, "PluginInfo"):
            return None, "__init__.py 中未定义 PluginInfo 。"
        return adaptLegacyPluginInfo(name, pluginDir, module.PluginInfo)

    def _resolveConflicts(self):
        """按 id 字典序，先到者保留，后到者标记冲突。结果可复现。"""
        ready = [r for r in self.records.values() if r.state == STATE_READY]
        kept = []
        for record in sorted(ready, key=lambda r: r.id):
            blocker = None
            for other in kept:
                if other.id in record.manifest.conflicts or (
                    record.id in other.manifest.conflicts
                ):
                    blocker = other
                    break
            if blocker:
                record.state = STATE_CONFLICT
                record.message = (
                    f'与已启用的插件 "{blocker.id}" 互斥，两者不能同时启用。'
                    f'请在插件管理中禁用其中一个。'
                )
            else:
                kept.append(record)

    # ========================= 【激活】 =========================

    def _activate(self, record):
        manifest = record.manifest
        try:
            self._mountRuntime(manifest, manifest.path)
            for service in manifest.services:
                self._registerService(record, service)
            for capability in manifest.capabilities:
                self._registerCapability(record, capability)
            for page in manifest.pages:
                self._registerPage(record, page)
        except Exception as e:
            record.state = STATE_ERROR
            record.message = f"注册插件失败：{e}"
            logger.error(f"注册插件 {record.id} 失败。", exc_info=True, stack_info=True)
            self._rollback(record)

    def _mountRuntime(self, manifest, pluginDir):
        """挂载插件私有运行时：vendor 包目录与原生 DLL 目录。

        vendor 默认【追加】到 sys.path 末尾，基础环境优先，避免插件覆盖
        宿主自己的依赖；插件确需覆盖时在清单里声明 priority=prepend 。
        """
        if not manifest:
            return
        for relative in manifest.pythonArchives:
            path = os.path.abspath(os.path.join(pluginDir, relative))
            if not os.path.isfile(path): raise FileNotFoundError(path)
            if path not in sys.path: sys.path.append(path)
        if manifest.resourceArchives:
            from PySide6.QtCore import QResource
            for relative in manifest.resourceArchives:
                path = os.path.abspath(os.path.join(pluginDir, relative))
                if not QResource.registerResource(path): raise RuntimeError(f"Invalid RCC: {path}")
                self._resourceArchives.add(path)
        for relative in manifest.vendorDirs:
            path = os.path.abspath(os.path.join(pluginDir, relative))
            if not os.path.isdir(path):
                raise FileNotFoundError(f"插件 vendor 目录不存在：{path}")
            if path in sys.path:
                continue
            if manifest.priority == PRIORITY_PREPEND:
                sys.path.insert(0, path)
            else:
                sys.path.append(path)
        if os.name != "nt" or not hasattr(os, "add_dll_directory"):
            return
        for pattern in manifest.dllDirs:
            full = os.path.abspath(os.path.join(pluginDir, pattern))
            matches = sorted(glob.glob(full)) if glob.has_magic(pattern) else [full]
            if not matches:
                raise FileNotFoundError(f"插件 DLL 目录不存在：{full}")
            for path in matches:
                if os.path.isdir(path):
                    _appendDllSearchPath(path, manifest.priority == PRIORITY_PREPEND)
                    _DllDirectoryHandles.append(os.add_dll_directory(path))

    def _registerCapability(self, record, capability):
        registry = getCapabilityRegistry(capability.type)
        manifest = record.manifest

        if "resolvedEntry" in capability.meta:  # legacy
            resolved = capability.meta["resolvedEntry"]
            config = capability.meta.get("resolvedConfig") or {}

            def resolve(_resolved=resolved):
                return _resolved

        else:
            config = self._loadCapabilityConfig(manifest, capability)

            def resolve(_manifest=manifest, _entry=capability.entry):
                return self._resolveEntry(_manifest, _entry)

        registry.register(
            record.id,
            resolve,
            config,
            {
                "legacy": manifest.legacy,
                "version": manifest.version,
                **capability.meta,
            },
        )

    def _registerService(self, record, service):
        manifest = record.manifest
        config = self._loadServiceConfig(manifest, service)

        def resolve(_manifest=manifest, _entry=service.entry):
            value = self._resolveEntry(_manifest, _entry)
            return value() if callable(value) else value

        PluginServices.register(
            record.id,
            service.id,
            resolve,
            config,
            {"pluginName": manifest.name, **service.meta},
        )

    def _loadCapabilityConfig(self, manifest, capability):
        """配置在发现阶段就必须拿到（全局设置界面要用它构建配置项）。

        内联配置直接取用，插件的 Python 一行都不会被导入。
        入口式配置则必须导入插件包与配置模块，因此该模块必须轻量：
        只描述配置，不导入后端。重量级实现始终留在 entry 里惰性加载。
        """
        if not capability.config:
            return {}
        if isinstance(capability.config, dict):
            value = capability.config
        else:
            value = self._resolveEntry(manifest, capability.config)
            if callable(value):
                value = value()
        if not isinstance(value, dict):
            raise TypeError(
                f"{capability.config.raw} 必须是字典或返回字典的可调用对象。"
            )
        if "global_options" in value or "local_options" in value:
            return value
        return {"global_options": None, "local_options": value}

    def _loadServiceConfig(self, manifest, service):
        if not service.config:
            return {}
        if isinstance(service.config, dict):
            value = service.config
        else:
            value = self._resolveEntry(manifest, service.config)
            if callable(value):
                value = value()
        if not isinstance(value, dict):
            raise TypeError(f"{service.config.raw} 必须是字典或返回字典的可调用对象。")
        return value

    def _resolveEntry(self, manifest, entry):
        module = importlib.import_module(entry.moduleName(manifest.id))
        if not hasattr(module, entry.attr):
            raise AttributeError(
                f"{entry.moduleName(manifest.id)} 中不存在 {entry.attr} 。"
            )
        return getattr(module, entry.attr)

    def _registerPage(self, record, page):
        info = {
            "key": page.key,
            "url": ("qrc:/plugins/" + record.id + "/" + os.path.relpath(page.qml, record.path).replace("\\", "/")
                    if record.manifest.resourceArchives else _fileUri(page.qml)),
            "title": page.title,
            "intro": page.intro,
            "pluginKey": record.id,
            "needController": bool(page.controller)
            or bool(page.meta.get("needController")),
        }
        if page.controller:
            from ..tag_pages.page_registry import registerPluginPageClass

            manifest = record.manifest

            def factory(_manifest=manifest, _entry=page.controller):
                return self._resolveEntry(_manifest, _entry)

            registerPluginPageClass(page.key, factory)
        elif info["needController"]:
            # 旧版插件声明了 needController 但没有可注册的控制器入口。
            # v1 在这里会静默失败（addPage 返回空串，页面创建不出来），
            # v2 明确降级为无控制器页并留下日志。
            logger.warning(
                f"插件 {record.id} 的页面 {page.key} 声明了 needController ，"
                f"但未提供 controller 入口，已按无控制器页加载。"
            )
            info["needController"] = False
        self.pageInfos.append(info)

    def _rollback(self, record):
        for capability in record.manifest.capabilities:
            registry = getCapabilityRegistry(capability.type)
            if registry:
                registry.unregister(record.id)
        self.pageInfos = [p for p in self.pageInfos if p.get("pluginKey") != record.id]
        PluginServices.unregisterPlugin(record.id)

    # ========================= 【状态持久化】 =========================

    def _stateFilePath(self):
        return os.path.join(PLUGINS_PATH, PLUGINS_STATE_FILE)

    def _readEnabledState(self):
        path = self._stateFilePath()
        if not os.path.isfile(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as stream:
                data = json.load(stream)
            if isinstance(data, dict):
                return {str(k): bool(v) for k, v in data.items()}
        except Exception:
            logger.error(f"读取插件启用状态失败：{path}", exc_info=True)
        return {}

    def _writeEnabledState(self):
        try:
            with open(self._stateFilePath(), "w", encoding="utf-8") as stream:
                json.dump(self._enabledState, stream, ensure_ascii=False, indent=2)
            return True
        except Exception:
            logger.error("写入插件启用状态失败。", exc_info=True)
            return False

    # ========================= 【汇总】 =========================

    def _summary(self):
        options = {}
        for typeName in knownCapabilityTypes():
            registry = getCapabilityRegistry(typeName)
            options[typeName] = registry.options()
        errors = {
            r.id: r.message
            for r in self.records.values()
            if r.state in (STATE_INVALID, STATE_ERROR, STATE_CONFLICT)
        }
        return {
            "options": options,
            "services": PluginServices.options(),
            "errors": errors,
            "pages": self.pageInfos,
            "plugins": self.getPlugins(),
            "host": hostEnvironment(),
            "pluginsPath": os.path.abspath(PLUGINS_PATH),
            "capabilityTypes": knownCapabilityTypes(),
        }


def _fileUri(path):
    from pathlib import Path

    return Path(path).resolve().as_uri()


PluginsController = _PluginsControllerClass()
