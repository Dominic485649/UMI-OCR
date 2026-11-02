"""逐页结果的原始路径绑定、冻结与旧任务拒绝回归，不启动推理或窗口。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def run(runtime, plugin, output):
    sys.path[:0] = [str(ROOT / "UmiOCR-data"), str(ROOT / "UmiOCR-data/py_src/imports"),
        str(runtime / "site-packages"), str(runtime / "dependencies.zip"), str(plugin.parent)]
    handles = [os.add_dll_directory(str(runtime / "site-packages/PySide6"))]
    from PySide6.QtCore import QCoreApplication
    app = QCoreApplication(["document-partial-contracts"])
    from py_src.mission.mission_document import __MissionDocumentClass as Manager
    from py_src.mission.backend_runtime import RuntimeCoordinator
    from win32_PaddleOCRVL_1_6.page import StructuredDocumentPage

    checks = []

    class Backend:
        on_partial = None
        on_progress = None
        fail = False
        def start(self, _values): return ""
        def stop(self): pass
        def parseDoc(self, _item):
            self.on_partial({"page": 2, "path": "worker-temporary.png", "result": {"code": 100}})
            if self.fail: raise ValueError("controlled-error")
            return {"code": 100, "data": {"pages": []}}

    backend = Backend()
    coordinator = RuntimeCoordinator()
    manager = object.__new__(Manager)
    manager._apiKey = "test-document"
    manager._api = coordinator.handle("document", manager._apiKey, {}, lambda *_args: backend)
    events = []
    info = {"argd": {}, "onPartial": events.append}
    assert manager.msnPreTask(info) == ""
    for name in ("D:/测试 文档/A.pdf", "D:/测试 文档/B.pdf"):
        result = manager.msnTask(info, {"path": name})
        assert result["code"] == 100 and result["path"] == name
        assert events[-1]["path"] == name, events
        assert "_documentPartialPath" not in info
    count = len(events)
    backend.on_partial({"page": 99})
    assert len(events) == count, "任务结束后的后端事件不得携带上个文档路径"
    backend.fail = True
    assert manager.msnTask(info, {"path": "failure.pdf"})["code"] == 902
    assert events[-1]["path"] == "failure.pdf" and "_documentPartialPath" not in info
    backend.on_partial({"page": 99})
    assert len(events) == count + 1
    coordinator.reset()
    checks.append("真实ManagedApi在start时接收的回调按每份文档绑定原始路径，忽略worker路径和结束后的迟到事件，异常同样解绑定")

    class Connector:
        def __init__(self): self.pending, self.delivered = [], []
        def callFunc(self, function, *args): self.pending.append((function, args))
        def callQml(self, *args): self.delivered.append(args)
        def flush(self):
            pending, self.pending = self.pending, []
            for function, args in pending: function(*args)

    class Mission:
        def __init__(self): self.jobs, self.cancelled = [], []
        def addMissionList(self, info, paths):
            self.jobs.append((info, paths))
            return info["_reserved_msnID"]
        def stopMissionList(self, mission_id): self.cancelled.append(mission_id)

    connector, mission = Connector(), Mission()
    page = StructuredDocumentPage("test-page", connector)
    with patch.object(page, "_missionDocument", return_value=mission):
        first = page.parseDocuments(["A.pdf"])
        first_info = mission.jobs[-1][0]
        assert page.parseDocuments(["B.pdf"]).startswith("[Error]")
        assert page._missionId == first
        first_info["onStart"](first_info)
        event = {"path": "A.pdf", "page": 1, "result": {"data": {"pages": [{"page": 1, "text": "snapshot"}]}}}
        first_info["onPartial"](event)
        event["result"]["data"]["pages"][0]["text"] = "changed-after-queue"
        connector.flush()
        delivered = connector.delivered[-1]
        assert delivered[1:3] == ("onMissionPartial", first)
        assert delivered[3]["result"]["data"]["pages"][0]["text"] == "snapshot"
        first_info["onGet"](first_info, {"path": "A.pdf"}, {"code": 100})
        first_info["onEnd"](first_info, "[Success]")
        assert page._missionId == ""
        before = len(connector.delivered)
        second = page.parseDocuments(["B.pdf"])
        second_info = mission.jobs[-1][0]
        assert second != first
        first_info["onEnd"](first_info, "[Error] late")
        assert page._missionId == second
        connector.flush()
        assert len(connector.delivered) == before, "主线程排队的旧结果/结束事件必须在真正交付时失效"
        second_info["onStart"](second_info)
        second_info["onPartial"]({"path": "B.pdf", "page": 1})
        connector.flush()
        assert connector.delivered[-1][1:3] == ("onMissionPartial", second)
        second_info["onPartial"]({"path": "B.pdf", "page": 2})
        before = len(connector.delivered)
        page.close()
        connector.flush()
        assert len(connector.delivered) == before and mission.cancelled == [second]
    checks.append("页面回调先深拷贝后交付，忙时拒绝第二任务，新任务/关闭会让已排队旧回调失效且不误清当前任务ID")

    immediate = StructuredDocumentPage("immediate-page", None)
    class Immediate:
        def addMissionList(self, info, _paths):
            info["onEnd"](info, "[Success]")
            return info["_reserved_msnID"]
    with patch.object(immediate, "_missionDocument", return_value=Immediate()):
        assert immediate.parseDocuments(["A.pdf"]) and not immediate._missionId
        assert not immediate.parseDocuments(["B.pdf"]).startswith("[Error]")
    checks.append("同步极快完成不会留下任务ID，仍可立即再次解析")
    assert not any(name.split(".")[0] in {"paddle", "paddleocr", "paddlex", "torch", "onnxruntime"} for name in sys.modules)
    paths = [ROOT / "UmiOCR-data/py_src/mission/mission_document.py", plugin / "page.py", Path(__file__)]
    report = {"status": "PASS", "checks": checks, "model_inference": "NOT_RUN", "source_sha256": {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}}
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    del handles, app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime", type=Path)
    parser.add_argument("--plugin", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.runtime.resolve(), args.plugin.resolve(), args.output.resolve())
    except Exception:
        import traceback
        if not args.output.exists():
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump({"status": "FAIL", "traceback": traceback.format_exc()}, stream, ensure_ascii=False, indent=2)
        raise
