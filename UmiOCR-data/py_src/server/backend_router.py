"""按能力解析请求后端，不修改 GUI 的全局模型选择。"""
from ..utils.runtime_i18n import tr
from copy import deepcopy
from dataclasses import dataclass

from ..mission.backend_runtime import BackendRuntime, BackendBusy, flatten_options
from ..plugins_controller.capabilities import getCapabilityRegistry


@dataclass
class BackendSelection:
    manager: object
    backend_id: str
    config: dict
    private: bool = False
    local_options: dict | None = None

    def close(self):
        if self.private:
            self.manager.shutdown()


def current_manager(capability):
    if capability == "ocr":
        from ..mission.mission_ocr import MissionOCR
        return MissionOCR
    if capability == "document":
        from ..mission.mission_document import MissionDocument
        return MissionDocument
    raise ValueError(tr('未知后端能力。'))


def backend_options(capability, backend_id="current"):
    manager = current_manager(capability)
    if backend_id in (None, "", "current"):
        return deepcopy(manager.getLocalOptions())
    registry = getCapabilityRegistry(capability)
    if not isinstance(backend_id, str) or not registry or not registry.has(backend_id):
        raise ValueError(tr('UNSUPPORTED_CAPABILITY：插件未启用或不提供所需能力。'))
    return deepcopy(registry.localOptions(backend_id))


def available_backends(capability):
    registry = getCapabilityRegistry(capability)
    if not registry:
        return []
    return [{"backendId": key, "name": (registry.globalOptions(key) or {}).get("title", key),
             "capability": capability} for key in registry.keys()]


def select_backend(capability, backend_id="current", *, isolated=False):
    manager = current_manager(capability)
    if getattr(manager, "_deferAdmissions", False):
        raise BackendBusy(tr('模型设置正在应用，请稍后重试。'))
    from ..mission.backend_runtime import ManagedApi
    use_current = backend_id in (None, "", "current")
    current_api = getattr(manager, "_api", None)
    resolved = (current_api.key[1] if isinstance(current_api, ManagedApi) else manager._apiKey) if use_current else backend_id
    if not isinstance(resolved, str):
        raise ValueError(tr('backendId 必须为文本。'))
    config = (deepcopy(current_api.config) if use_current and isinstance(current_api, ManagedApi)
              else BackendRuntime.configuration(capability, resolved))
    if use_current and not isolated and not isinstance(current_api, ManagedApi):
        if current_api is None and capability == "ocr":
            # 冻结“尚未配置”的状态。请求不能在 GUI 后续选好模型后意外改用它；
            # 旧文档的纯文本页仍可正常提取，真正遇到图片时保留原未配置错误。
            from ..mission.mission_ocr import createMissionOcr
            return BackendSelection(createMissionOcr("", {}), "", {}, True, {})
        # 兼容真正仍使用非受管 API 的旧嵌入调用。
        return BackendSelection(manager, resolved, config, local_options=deepcopy(manager.getLocalOptions()))
    registry = getCapabilityRegistry(capability)
    if not registry or not registry.has(resolved):
        raise ValueError(tr('UNSUPPORTED_CAPABILITY：插件未启用或不提供所需能力。'))
    if not config:
        config = {key: item.get("default") for key, item in
                  flatten_options(registry.globalOptions(resolved) or {}).items()}
    if capability == "ocr":
        from ..mission.mission_ocr import createMissionOcr
        worker = createMissionOcr(resolved, config)
    else:
        from ..mission.mission_document import createMissionDocument
        worker = createMissionDocument(resolved, config)
    return BackendSelection(worker, resolved, config, True, deepcopy(registry.localOptions(resolved)))
