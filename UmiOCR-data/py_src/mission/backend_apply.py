"""按单次配置快照串行应用能力接口，不将资源清理误判为另一能力的任务。"""
from __future__ import annotations

from .backend_runtime import BackendBusy


def apply_backends(runtime, managers, request):
    revision = request["revision"]
    applied = {}
    try:
        with runtime.reconfiguration():
            for kind, spec in request["interfaces"].items():
                manager = managers[kind]
                message = str(manager.setApi(spec["apiKey"], spec["info"]))
                if not message.startswith("[Success]"):
                    return {"revision": revision, "state": "failed", "kind": kind,
                            "message": message, "applied": applied}
                applied[kind] = spec
    except BackendBusy as exc:
        return {"revision": revision, "state": "pending", "message": str(exc), "applied": applied}
    except Exception as exc:
        return {"revision": revision, "state": "failed", "message": str(exc), "applied": applied}
    return {"revision": revision, "state": "applied", "applied": applied}
