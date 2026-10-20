"""使用主线程信箱和可控任务/保存屏障验证批量页面，不加载模型。"""

import argparse
import copy
import importlib
import os
import queue
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build" / "tools"))
from staging_smoke import configure_runtime

DOC = OCR = Runtime = None


class Mailbox:
    def __init__(self):
        self.owner = threading.get_ident()
        self.mail = queue.Queue()
        self.events = []
        self.workers = []
        self.errors = []
        self.releases = []

    def callQml(self, key, name, *args):
        assert threading.get_ident() == self.owner, "工作线程直接调用了界面。"
        self.events.append((name, copy.deepcopy(args)))

    def callFunc(self, function, *args):
        if threading.get_ident() == self.owner:
            return function(*args)
        self.mail.put((function, args))

    def spawn(self, function, *args):
        def run():
            try:
                function(*args)
            except BaseException as exc:
                self.errors.append(exc)
                self.mail.put((lambda: None, ()))
        worker = threading.Thread(target=run, daemon=True)
        self.workers.append(worker)
        worker.start()
        return worker

    def until(self, predicate, message="等待受控事件超时。", timeout=5):
        deadline = time.monotonic() + timeout
        while not predicate():
            if self.errors:
                raise AssertionError(f"工作线程异常：{self.errors}") from self.errors[0]
            remaining = deadline - time.monotonic()
            assert remaining > 0, message
            try:
                function, args = self.mail.get(timeout=remaining)
            except queue.Empty:
                raise AssertionError(message) from None
            function(*args)
        self.drain()

    def drain(self):
        while True:
            try:
                function, args = self.mail.get_nowait()
            except queue.Empty:
                break
            function(*args)
        assert not self.errors, self.errors

    def finish(self):
        for release in self.releases:
            release.set()
        deadline = time.monotonic() + 5
        while True:
            self.drain()
            for worker in list(self.workers):
                worker.join(max(0, deadline - time.monotonic()))
                assert not worker.is_alive(), "测试工作线程没有退出。"
            self.drain()
            if all(not worker.is_alive() for worker in self.workers) and self.mail.empty():
                break
            assert time.monotonic() < deadline, "收尾产生的新线程没有退出。"


class FakeMission:
    def __init__(self, mailbox, document):
        self.mailbox = mailbox
        self.document = document
        self.jobs = []
        self.paused = []
        self.resumed = []
        self.stopped = []
        self.early = False

    def _admit(self, info, items):
        assert threading.get_ident() == self.mailbox.owner, "任务派发不在主线程。"
        mission_id = f"受控任务-{len(self.jobs)}"
        info["msnID"] = mission_id
        job = {"info": info, "items": items, "id": mission_id}
        self.jobs.append(job)
        if self.early:
            # 专门覆盖回调早于 addMission 返回的同步边界。
            self.emit_all(job)
        return mission_id

    def addMission(self, info, path, page_range, password=""):
        info["path"] = path
        return self._admit(info, list(range(page_range[0] - 1, page_range[1])))

    def addMissionList(self, info, items):
        return self._admit(info, items)

    def stopMissionList(self, mission_id):
        self.stopped.append(mission_id)

    def pauseMissionList(self, mission_id):
        self.paused.append(mission_id)

    def resumeMissionList(self, mission_id):
        self.resumed.append(mission_id)

    def emit_all(self, job, code=100, message="[Success] 受控任务完成。", duplicate=False):
        info = job["info"]
        info["onStart"](info)
        for item in job["items"]:
            info["onReady"](info, item)
            result = {"code": code, "data": [{"text": "受控文字", "end": "\n"}]
                      if code == 100 else "受控异常", "time": 0.1, "score": 0.99}
            info["onGet"](info, item, result)
            if duplicate:
                info["onGet"](info, item, result)
        info["onEnd"](info, message)
        if duplicate:
            info["onEnd"](info, message)

    def complete(self, index, **kwargs):
        return self.mailbox.spawn(lambda: self.emit_all(self.jobs[index], **kwargs))

    def paths(self):
        if self.document:
            return [Path(job["info"]["path"]).name for job in self.jobs]
        return [[Path(item["path"]).name for item in job["items"]] for job in self.jobs]


class FakeOutputFactory:
    def __init__(self, mailbox):
        self.mailbox = mailbox
        self.instances = []
        self.gates = {}
        self.fail = set()

    def block(self, index):
        entered, release = threading.Event(), threading.Event()
        self.gates[index] = (entered, release)
        self.mailbox.releases.append(release)
        return entered, release

    def __call__(self, argd):
        index = len(self.instances)
        output = FakeOutput(self, index, argd)
        self.instances.append(output)
        return output


class FakeOutput:
    def __init__(self, factory, index, argd):
        self.factory = factory
        self.index = index
        self.outputPath = str(Path(argd["outputDir"]) / (argd["outputFileName"] + ".fake"))
        Path(self.outputPath).write_text("本次初始化\n", encoding="utf-8")
        self.end_count = 0
        self.print_count = 0
        self.end_threads = []
        self.saved = False

    def print(self, result):
        assert not self.end_count, "保存后继续写入了已关闭的输出器。"
        self.print_count += 1
        with open(self.outputPath, "a", encoding="utf-8") as stream:
            stream.write(f"{result['path']}\n")

    def onEnd(self):
        self.end_count += 1
        self.end_threads.append(threading.get_ident())
        gate = self.factory.gates.get(self.index)
        if gate:
            entered, release = gate
            entered.set()
            # 唤醒主线程信箱，主线程不在 Event.wait 中阻塞自己的回调。
            self.factory.mailbox.mail.put((lambda: None, ()))
            assert release.wait(5), "保存屏障未释放。"
        if self.index in self.factory.fail:
            raise OSError("受控保存失败，预期路径虽存在但不能当作成功。")
        with open(self.outputPath, "a", encoding="utf-8") as stream:
            stream.write("本次保存成功\n")
        self.saved = True

    def getArtifacts(self):
        return [{"path": self.outputPath, "status": "saved", "saved": True, "error": ""}] if self.saved else []


class World:
    def __init__(self, root, document, real_outputs=False):
        self.root = root
        self.mailbox = Mailbox()
        self.manager = FakeMission(self.mailbox, document)
        self.factory = FakeOutputFactory(self.mailbox)
        self.module = DOC if document else OCR
        self.real_outputs = real_outputs
        self.page = None
        self.argd = {"mission.dirType": "specify", "mission.dir": str(root),
                     "mission.datetimeFormat": "%Y%m%d-%H%M", "mission.fileNameFormat": "%name%range",
                     "mission.ignoreBlank": False, "mission.filesType.txt": True,
                     "doc.extractionMode": "textOnly"}

    def doc(self, name, pages=1, locked=False):
        path = self.root / name
        path.write_text("受控源文件，不读取为真实文档。", encoding="utf-8")
        return {"path": str(path), "page_count": pages, "range_start": 1, "range_end": pages,
                "is_encrypted": locked, "is_authenticate": not locked, "password": ""}

    def image(self, name):
        path = self.root / name
        path.write_bytes(b"controlled-image")
        return str(path)

    def until_jobs(self, number):
        self.mailbox.until(lambda: len(self.manager.jobs) >= number, f"没有派发第{number}份任务。")

    def complete(self, index, **kwargs):
        return self.manager.complete(index, **kwargs)

    def done(self):
        self.mailbox.until(lambda: self.page.getBatchState()["completed"], "批次没有完成。")

    def row(self, path):
        identity = Runtime.path_identity(path if isinstance(path, str) else path["path"])[0]
        return next(item for item in self.page.getBatchState()["rows"] if item["id"] == identity)


@contextmanager
def world(document=True, real_outputs=False):
    with tempfile.TemporaryDirectory(prefix="umi-batch-regression-") as directory:
        item = World(Path(directory), document, real_outputs)
        manager_name = "MissionDOC" if document else "MissionOCR"
        with patch.object(item.module, manager_name, item.manager):
            output_patch = patch.object(item.module, "Output", {"txt": item.factory}) if not real_outputs else patch.dict({}, {})
            with output_patch:
                item.page = item.module.BatchDOC("批量文档测试", item.mailbox) if document else item.module.BatchOCR("批量图片测试", item.mailbox)
                item.page._start_worker = item.mailbox.spawn
                try:
                    yield item
                finally:
                    item.page.close()
                    item.mailbox.finish()


def test_doc_append_while_last_save_is_blocked():
    with world() as w:
        a, b = w.doc("A.pdf", 2), w.doc("B.pdf", 3)
        entered, release = w.factory.block(0)
        w.page.msnDocs([a], w.argd)
        w.until_jobs(1)
        w.complete(0, duplicate=True)
        w.mailbox.until(entered.is_set)
        assert w.row(a)["status"] == "finalizing"
        ticket = w.page.beginImport("扫描-B")
        w.page.finishImport(ticket["ticketId"], [b], {"status": "complete"})
        state = w.page.getBatchState()
        assert state["totalPages"] == 5 and state["donePages"] == 2 and not state["completed"]
        assert not w.page.removeRows([a["path"]])["ok"]
        assert not w.page.reOCR(a["path"], w.argd)["ok"]
        assert len(w.manager.jobs) == 1
        release.set()
        w.until_jobs(2)
        w.complete(1)
        w.done()
        state = w.page.getBatchState()
        assert state["successDocs"] == 2 and state["donePages"] == state["totalPages"] == 5
        assert state["canPostTaskActions"]
        assert all(output.end_count == 1 for output in w.factory.instances)
        assert all(w.mailbox.owner not in output.end_threads for output in w.factory.instances)
        assert w.manager.paths() == ["A.pdf", "B.pdf"]
        assert all(not args[2] for name, args in w.mailbox.events if name == "onDocEnd")


def test_doc_pause_reorder_remove_changes_actual_dispatch():
    with world() as w:
        a, b, c, d = [w.doc(f"{name}.pdf") for name in "ABCD"]
        w.page.msnDocs([a, b, c, d], w.argd)
        w.until_jobs(1)
        w.page.msnPause()
        w.complete(0)
        w.mailbox.until(lambda: w.page._active is None)
        assert w.page.getBatchState()["paused"] and len(w.manager.jobs) == 1
        assert w.page.movePending(c["path"], b["path"])["ok"]
        w.page.removeRows([d["path"]])
        w.page.syncRows([a, b, c])
        state = w.page.getBatchState()
        assert state["totalDocs"] == state["totalPages"] == 3
        assert state["donePages"] == 1 and state["skippedDocs"] == 1
        w.page.msnResume()
        w.until_jobs(2)
        w.complete(1)
        w.until_jobs(3)
        w.complete(2)
        w.done()
        assert w.manager.paths() == ["A.pdf", "C.pdf", "B.pdf"]
        before = w.page.getBatchState()
        w.page.removeRows([a["path"]])
        after = w.page.getBatchState()
        assert after["donePages"] == before["donePages"] == 3
        assert after["totalDocs"] == before["totalDocs"] == 3
        assert after["summary"].startswith("[Warning]") and not after["canPostTaskActions"]
        assert all(Path(item["path"]).is_file() for item in (a, d))


def test_doc_delete_pending_tombstone_blocks_old_scan_and_success_actions():
    with world() as w:
        a, b = w.doc("A.pdf"), w.doc("B.pdf", 4)
        w.page.msnDocs([a, b], w.argd)
        w.until_jobs(1)
        ticket = w.page.beginImport()
        w.page.msnPause()
        w.page.removeRows([b["path"]])
        w.complete(0)
        w.mailbox.until(lambda: w.page._active is None)
        w.page.msnResume()
        assert w.page.getBatchState()["state"] == "waiting_import"
        assert not w.page.getBatchState()["completed"]
        w.page.finishImport(ticket["ticketId"], [b], {"status": "complete"})
        w.done()
        state = w.page.getBatchState()
        assert len(state["rows"]) == 1 and len(w.manager.jobs) == 1
        assert state["totalPages"] == state["donePages"] == 1
        assert state["skippedDocs"] == 1 and not state["canPostTaskActions"]


def test_doc_stop_new_batch_ignores_old_save_callbacks_and_import():
    with world() as w:
        a, b, c = w.doc("A.pdf"), w.doc("B.pdf"), w.doc("C.pdf")
        entered, release = w.factory.block(0)
        old_id = w.page.msnDocs([a], w.argd)
        w.until_jobs(1)
        ticket = w.page.beginImport()
        w.complete(0)
        w.mailbox.until(entered.is_set)
        w.page.msnStop()
        new_id = w.page.msnDocs([b], w.argd)
        assert new_id != old_id
        w.until_jobs(2)
        w.page.finishImport(ticket["ticketId"], [c], {"status": "complete"})
        assert w.row(c)["status"] == "ready"
        old_job = w.manager.jobs[0]
        w.mailbox.spawn(w.manager.emit_all, old_job)
        release.set()
        w.complete(1)
        w.done()
        state = w.page.getBatchState()
        assert state["batchId"] == new_id and state["totalDocs"] == state["successDocs"] == 1
        assert w.manager.paths() == ["A.pdf", "B.pdf"]
        assert w.factory.instances[0].end_count == 1
        assert len([event for event in w.mailbox.events if event[0] == "onDocGet"]) == 2


def test_doc_callbacks_before_submission_returns_and_duplicate_end():
    with world() as w:
        a = w.doc("立即回调.pdf", 2)
        w.manager.early = True
        w.page.msnDocs([a], w.argd)
        w.done()
        assert w.page.getBatchState()["donePages"] == 2
        assert w.row(a)["missionId"] == w.manager.jobs[0]["id"]
        assert w.factory.instances[0].end_count == 1
        w.manager.jobs[0]["info"]["onEnd"](w.manager.jobs[0]["info"], "[Success] 重复结束。")
        w.mailbox.drain()
        assert w.factory.instances[0].end_count == 1


def test_initial_import_holds_start_and_close_invalidates_ticket():
    with world() as w:
        a, b = w.doc("A.pdf"), w.doc("B.pdf")
        ticket = w.page.beginImport()
        batch_id = w.page.msnDocs([a], w.argd)
        assert batch_id and not w.manager.jobs
        assert w.page.getBatchState()["state"] == "waiting_import"
        w.page.finishImport(ticket["ticketId"], [a, b], {"status": "complete"})
        w.until_jobs(1)
        w.complete(0)
        w.until_jobs(2)
        w.complete(1)
        w.done()
        assert w.page.getBatchState()["totalDocs"] == 2
        late = w.page.beginImport()
        w.page.clearRows()
        result = w.page.finishImport(late["ticketId"], [a], {"status": "complete"})
        assert not result["ok"] and result["rows"] == []
        late = w.page.beginImport()
        w.page.closeBatch()
        assert not w.page.finishImport(late["ticketId"], [b])["ok"]


def test_encrypted_doc_waits_without_blocking_normal_docs_and_unlocks_async():
    probe_module = importlib.import_module("py_src.utils.doc_probe")
    with world() as w:
        locked, normal, extra = w.doc("加密.pdf", 2, True), w.doc("普通.pdf"), w.doc("新增.pdf")
        w.page.msnDocs([locked, normal], w.argd)
        w.until_jobs(1)
        w.complete(0)
        w.mailbox.until(lambda: w.page.getBatchState()["state"] == "waiting_unlock")
        assert w.page.getBatchState()["lockedCount"] == 1 and not w.page.getBatchState()["completed"]
        def probe(path, password="", timeout=30):
            assert threading.get_ident() != w.mailbox.owner
            return {"path": path, "page_count": 2, "is_encrypted": True, "is_authenticate": password == "正确密码"}
        with patch.object(probe_module, "probe_document", probe):
            w.page.unlockDocument(locked["path"], "错误密码")
            w.mailbox.until(lambda: w.row(locked)["status"] == "locked")
            assert not w.page.getBatchState()["completed"]
            w.page.syncRows([extra])
            w.until_jobs(2)
            w.complete(1)
            w.mailbox.until(lambda: w.page.getBatchState()["state"] == "waiting_unlock")
            w.page.unlockDocument(locked["path"], "正确密码")
            w.until_jobs(3)
            assert w.manager.jobs[2]["info"]["path"].endswith("加密.pdf")
            w.complete(2)
            w.done()
        state = w.page.getBatchState()
        assert state["successDocs"] == 3 and state["totalPages"] == state["donePages"] == 4


def test_removed_unlock_result_cannot_reinsert_record():
    probe_module = importlib.import_module("py_src.utils.doc_probe")
    with world() as w:
        locked = w.doc("加密.pdf", 2, True)
        entered, release = threading.Event(), threading.Event()
        w.mailbox.releases.append(release)
        def probe(path, password="", timeout=30):
            entered.set()
            w.mailbox.mail.put((lambda: None, ()))
            assert release.wait(5)
            return {"path": path, "page_count": 2, "is_encrypted": True, "is_authenticate": True}
        with patch.object(probe_module, "probe_document", probe):
            w.page.msnDocs([locked], w.argd)
            w.page.unlockDocument(locked["path"], "密码")
            w.mailbox.until(entered.is_set)
            w.page.removeRows([locked["path"]])
            w.done()
            release.set()
            w.mailbox.finish()
        assert w.page.getBatchState()["rows"] == [] and not w.manager.jobs
        assert not w.page.getBatchState()["canPostTaskActions"]


def test_reocr_only_one_doc_unique_all_outputs_and_failure_keeps_previous():
    with world(real_outputs=True) as w:
        a, b = w.doc("A.pdf"), w.doc("B.pdf")
        for key in ("txtPlain", "txtIndividual", "csv", "jsonl", "md"):
            w.argd["mission.filesType." + key] = True
        w.page.msnDocs([a, b], w.argd)
        w.until_jobs(1)
        w.complete(0)
        w.until_jobs(2)
        w.complete(1)
        w.done()
        old_artifacts = w.page.getArtifacts(a["path"])
        assert len(old_artifacts) == 6 and all(item["saved"] and item["openable"] for item in old_artifacts)
        old_bytes = {item["path"]: Path(item["path"]).read_bytes() for item in old_artifacts}
        result = w.page.reOCR(a["path"], w.argd)
        assert result["ok"] and not w.page.reOCR(a["path"], w.argd)["ok"]
        w.until_jobs(3)
        w.complete(2, code=102)
        w.done()
        assert {item["path"] for item in w.page.getArtifacts(a["path"])} == set(old_bytes)
        assert all(Path(path).read_bytes() == value for path, value in old_bytes.items())
        assert not w.page.getBatchState()["canPostTaskActions"]
        w.page.reOCR(a["path"], w.argd)
        w.until_jobs(4)
        w.complete(3)
        w.done()
        fresh = w.page.getArtifacts(a["path"])
        assert all(item["path"] not in old_bytes for item in fresh)
        assert all(Path(path).read_bytes() == value for path, value in old_bytes.items())
        assert w.manager.paths() == ["A.pdf", "B.pdf", "A.pdf", "A.pdf"]
        choice = w.page.openArtifact(a["path"])
        assert not choice["ok"] and len(choice["artifacts"]) == 6
        selected = w.page.openArtifact(a["path"], "csv")
        assert selected["ok"] and selected["path"].endswith(".csv")
        assert w.page.getOriginal(a["path"])["exists"]


def test_existing_file_is_not_proof_of_this_attempt_save():
    with world() as w:
        a = w.doc("A.pdf")
        w.factory.fail.add(0)
        w.page.msnDocs([a], w.argd)
        w.until_jobs(1)
        w.complete(0)
        w.done()
        row = w.row(a)
        assert row["status"] == "failed" and not row["artifacts"]
        assert row["attemptArtifacts"][0]["exists"] and not row["attemptArtifacts"][0]["saved"]
        assert not row["attemptArtifacts"][0]["openable"]


def test_pdf_recovery_artifact_is_not_normal_save_success():
    output_module = importlib.import_module("py_src.ocr.output.output_pdf_layered")
    with tempfile.TemporaryDirectory(prefix="umi-artifact-regression-") as directory:
        destination = str(Path(directory) / "受控.layered.pdf")
        class FakePDF:
            is_closed = False
            def save(self, path, **options):
                if path == destination:
                    raise OSError("受控正常路径保存失败。")
                Path(path).write_bytes(b"recovery-only")
            def close(self):
                self.is_closed = True
        output = output_module.OutputPdfLayered.__new__(output_module.OutputPdfLayered)
        output.outputPath = destination
        pdf = FakePDF()
        with patch.object(output_module.os, "replace", side_effect=PermissionError("受控文件占用。")):
            try:
                output.save(pdf, destination)
                raise AssertionError("应该报告正常路径保存失败。")
            except RuntimeError:
                pass
        artifacts = output.getArtifacts()
        recovery = next(item for item in artifacts if item["status"] == "recovery")
        assert recovery["path"].endswith(".temp") and not recovery["saved"]
        assert Path(recovery["path"]).is_file() and pdf.is_closed
        assert all(not item["saved"] for item in artifacts)


def test_ocr_segments_share_output_and_append_during_save_uses_new_session():
    with world(document=False) as w:
        a, b, c, d = [w.image(f"{name}.png") for name in "ABCD"]
        entered, release = w.factory.block(0)
        batch_id = w.page.msnPaths([a], w.argd)
        w.until_jobs(1)
        w.page.syncRows([b, b])
        w.complete(0, duplicate=True)
        w.until_jobs(2)
        assert len(w.factory.instances) == 1 and w.factory.instances[0].end_count == 0
        w.complete(1)
        w.mailbox.until(entered.is_set)
        assert w.page.getBatchState()["state"] == "finalizing"
        w.page.syncRows([c, d])
        assert len(w.manager.jobs) == 2 and not w.page.getBatchState()["completed"]
        release.set()
        w.until_jobs(3)
        assert len(w.factory.instances) == 2
        w.complete(2, duplicate=True)
        w.done()
        assert w.manager.paths() == [["A.png"], ["B.png"], ["C.png", "D.png"]]
        assert all(output.end_count == 1 for output in w.factory.instances)
        assert [output.print_count for output in w.factory.instances] == [2, 2]
        ends = [args for name, args in w.mailbox.events if name == "onOcrEnd"]
        assert len(ends) == 1 and ends[0][1] == batch_id
        assert w.page.getBatchState()["successDocs"] == w.page.getBatchState()["totalDocs"] == 4


def test_ocr_import_ticket_and_pause_hold_segment_and_output_finish():
    with world(document=False) as w:
        a, b = w.image("A.png"), w.image("B.png")
        w.page.msnPaths([a], w.argd)
        w.until_jobs(1)
        ticket = w.page.beginImport()
        w.page.msnPause()
        w.complete(0)
        w.mailbox.until(lambda: w.page._active is None)
        assert w.factory.instances[0].end_count == 0
        w.page.finishImport(ticket["ticketId"], [b], {"status": "complete"})
        assert len(w.manager.jobs) == 1
        w.page.msnResume()
        w.until_jobs(2)
        w.complete(1)
        w.done()
        assert len(w.factory.instances) == 1 and w.factory.instances[0].end_count == 1
        assert w.manager.paths() == [["A.png"], ["B.png"]]


def test_ocr_stop_then_new_batch_does_not_reuse_old_output():
    with world(document=False) as w:
        a, b, c = w.image("A.png"), w.image("B.png"), w.image("C.png")
        entered, release = w.factory.block(0)
        w.page.msnPaths([a], w.argd)
        w.until_jobs(1)
        ticket = w.page.beginImport()
        w.page.msnStop()
        w.mailbox.until(entered.is_set)
        new_id = w.page.msnPaths([b], w.argd)
        w.until_jobs(2)
        w.page.finishImport(ticket["ticketId"], [c], {"status": "complete"})
        w.complete(0)
        release.set()
        w.complete(1)
        w.done()
        state = w.page.getBatchState()
        assert state["batchId"] == new_id and state["successDocs"] == state["totalDocs"] == 1
        assert w.row(c)["status"] == "ready"
        assert [output.end_count for output in w.factory.instances] == [1, 1]
        assert w.factory.instances[0].print_count == 0 and w.factory.instances[1].print_count == 1


def test_ocr_stop_during_save_removes_protection_and_archives_cancelled_artifact():
    with world(document=False) as w:
        a = w.image("A.png")
        entered, release = w.factory.block(0)
        w.page.msnPaths([a], w.argd)
        w.until_jobs(1)
        w.complete(0)
        w.mailbox.until(entered.is_set)
        w.page.msnStop()
        row = w.row(a)
        assert row["status"] == "stopped" and row["canRemove"] and row["canReocr"]
        release.set()
        w.mailbox.until(lambda: bool(w.row(a)["attemptArtifacts"]))
        assert all(item["status"] == "cancelled" and not item["saved"] for item in w.row(a)["attemptArtifacts"])
        assert not w.page.getBatchState()["completed"]
        assert w.page.getBatchState()["stoppedDocs"] == 1
        assert w.factory.instances[0].end_count == 1


def test_doc_stop_preparing_and_restart_same_path_isolates_output_context():
    with world() as w:
        a = w.doc("A.pdf")
        entered, release = threading.Event(), threading.Event()
        w.mailbox.releases.append(release)
        original = w.page._initOutputList
        calls = []
        def prepare(*args, **kwargs):
            calls.append(args)
            if len(calls) == 1:
                entered.set()
                w.mailbox.mail.put((lambda: None, ()))
                assert release.wait(5)
            return original(*args, **kwargs)
        with patch.object(w.page, "_initOutputList", prepare):
            old_id = w.page.msnDocs([a], w.argd)
            w.mailbox.until(entered.is_set)
            w.page.msnStop()
            new_id = w.page.msnDocs([a], w.argd)
            assert old_id != new_id
            w.until_jobs(1)
            w.complete(0)
            w.done()
            fresh = w.page.getArtifacts(a["path"])
            release.set()
            w.mailbox.finish()
            assert w.page.getBatchState()["batchId"] == new_id
            assert w.page.getArtifacts(a["path"]) == fresh
            assert len(w.factory.instances) == 2
            assert len({output.outputPath for output in w.factory.instances}) == 2
            assert all(output.end_count == 1 for output in w.factory.instances)
            assert len(w.manager.jobs) == 1


def test_remove_all_initial_pending_does_not_claim_success():
    with world() as w:
        a, b = w.doc("A.pdf"), w.doc("B.pdf", 3)
        ticket = w.page.beginImport()
        w.page.msnDocs([a, b], w.argd)
        w.page.removeRows([a["path"], b["path"]])
        state = w.page.getBatchState()
        assert state["totalDocs"] == state["totalPages"] == 0 and state["skippedDocs"] == 2
        assert state["running"] and not state["completed"]
        w.page.finishImport(ticket["ticketId"], [], {"status": "empty"})
        w.done()
        state = w.page.getBatchState()
        assert not state["canPostTaskActions"] and state["summary"].startswith("[Warning]")
        assert not w.manager.jobs and not w.factory.instances


def test_reocr_freezes_new_confirmed_settings_and_explicit_none():
    with world() as w:
        a = w.doc("A.pdf")
        a["argd"] = dict(w.argd, **{"doc.extractionMode": "textOnly", "tbpu.ignoreArea": [[1, 2, 3, 4]]})
        w.page.msnDocs([a], w.argd)
        w.until_jobs(1)
        w.complete(0)
        w.done()
        ticket = w.page.beginImport()
        settings = dict(w.argd, **{"doc.extractionMode": "mixed", "tbpu.ignoreArea": None})
        assert w.page.reOCR(a["path"], settings)["ok"]
        assert not w.page.syncMetadata(a["path"], {"range_end": 1})["ok"]
        w.page.finishImport(ticket["ticketId"], [], {"status": "empty"})
        w.until_jobs(2)
        submitted = w.manager.jobs[1]["info"]["argd"]
        assert submitted["doc.extractionMode"] == "mixed" and submitted["tbpu.ignoreArea"] is None
        w.complete(1)
        w.done()


def test_real_document_mission_text_only_and_both_pdf_artifacts():
    import fitz
    with tempfile.TemporaryDirectory(prefix="umi-real-doc-regression-") as directory:
        root = Path(directory)
        mailbox = Mailbox()
        page = DOC.BatchDOC("真实文档小型回归", mailbox)
        page._start_worker = mailbox.spawn
        source = root / "真实源文档.pdf"
        with fitz.open() as document:
            for text in ("Controlled document page one", "Controlled document page two"):
                document.new_page().insert_text((60, 80), text)
            document.save(source)
        metadata = {"path": str(source), "page_count": 2, "range_start": 1, "range_end": 2,
                    "password": "", "is_encrypted": False, "is_authenticate": True}
        settings = {"mission.dirType": "specify", "mission.dir": str(root),
                    "mission.datetimeFormat": "%Y%m%d-%H%M", "mission.fileNameFormat": "%name%range",
                    "mission.ignoreBlank": False, "mission.filesType.txt": True,
                    "mission.filesType.csv": True, "mission.filesType.pdfLayered": True,
                    "mission.filesType.pdfOneLayer": True, "doc.extractionMode": "textOnly"}
        try:
            page.msnDocs([metadata], settings)
            mailbox.until(lambda: page.getBatchState()["completed"], timeout=15)
            state = page.getBatchState()
            assert state["successDocs"] == 1 and state["donePages"] == state["totalPages"] == 2
            old_artifacts = page.getArtifacts(str(source))
            assert len(old_artifacts) == 4 and all(item["openable"] for item in old_artifacts)
            old_bytes = {item["path"]: Path(item["path"]).read_bytes() for item in old_artifacts}
            for item in old_artifacts:
                if item["format"] in ("pdfLayered", "pdfOneLayer"):
                    with fitz.open(item["path"]) as document:
                        assert document.page_count == 2
            page.reOCR(str(source), settings, {"range_start": 2, "range_end": 2})
            mailbox.until(lambda: page.getBatchState()["completed"], timeout=15)
            assert page.getBatchState()["successDocs"] == 1
            for item in page.getArtifacts(str(source)):
                assert item["path"] not in old_bytes
                if item["format"] in ("pdfLayered", "pdfOneLayer"):
                    with fitz.open(item["path"]) as document:
                        assert document.page_count == 1
            assert all(Path(path).read_bytes() == content for path, content in old_bytes.items())
        finally:
            page.close()
            mailbox.finish()


def test_review_individual_output_identity_source_and_specified():
    for directory_type in ("source", "specify"):
        with world(document=False, real_outputs=True) as w:
            first_dir, second_dir = w.root / "目录甲", w.root / "目录乙"
            first_dir.mkdir()
            second_dir.mkdir()
            first, second = first_dir / "scan.png", second_dir / "scan.png"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            w.argd.update({"mission.dirType": directory_type, "mission.filesType.txt": False,
                           "mission.filesType.txtIndividual": True})
            w.page.msnPaths([str(first), str(second)], w.argd)
            w.until_jobs(1)
            w.complete(0)
            w.done()
            files = list(w.root.rglob("*.txt"))
            assert len(files) == 2, f"同名输入发生覆盖：{directory_type} 只生成 {len(files)} 份。"
            if directory_type == "source":
                assert {path.parent for path in files} == {first_dir, second_dir}, "未按每个输入的原目录保存。"
            else:
                assert all(path.parent == w.root for path in files)
            first_artifacts = w.page.getArtifacts(str(first))
            second_artifacts = w.page.getArtifacts(str(second))
            assert len(first_artifacts) == len(second_artifacts) == 1
            assert first_artifacts[0]["path"] != second_artifacts[0]["path"]
            old_bytes = {path: path.read_bytes() for path in files}
            w.page.reOCR(str(first), w.argd)
            w.until_jobs(2)
            w.complete(1)
            w.done()
            assert all(path.read_bytes() == content for path, content in old_bytes.items())
            assert w.page.getArtifacts(str(first))[0]["path"] not in {str(path) for path in files}


def test_review_reocr_heterogeneous_settings_are_dispatched_separately():
    with world(document=False) as w:
        first, second, current = [w.image(f"{name}.png") for name in ("first", "second", "current")]
        w.page.msnPaths([first, second], w.argd)
        w.until_jobs(1)
        w.complete(0)
        w.done()
        w.page.msnPaths([current], w.argd)
        w.until_jobs(2)
        w.page.msnPause()
        first_settings = dict(w.argd, **{"ocr.language": "第一语言", "tbpu.ignoreArea": None})
        second_settings = dict(w.argd, **{"ocr.language": "第二语言", "tbpu.ignoreArea": [[[0, 0], [10, 0], [10, 10], [0, 10]]]})
        assert w.page.reOCR(first, first_settings)["ok"]
        assert w.page.reOCR(second, second_settings)["ok"]
        w.complete(1)
        w.mailbox.until(lambda: w.page._active is None)
        w.page.msnResume()
        w.until_jobs(3)
        assert w.manager.paths()[2] == ["first.png"], "不同确认参数被合并到首项的 Mission。"
        assert w.manager.jobs[2]["info"]["argd"]["ocr.language"] == "第一语言"
        w.complete(2)
        w.until_jobs(4)
        assert w.manager.paths()[3] == ["second.png"]
        submitted = w.manager.jobs[3]["info"]["argd"]
        assert submitted["ocr.language"] == "第二语言" and submitted["tbpu.ignoreArea"] == second_settings["tbpu.ignoreArea"]
        w.complete(3)
        w.done()


def test_review_individual_receipts_are_linear_and_row_scoped():
    with world(document=False) as w:
        count = 96
        paths = [w.image(f"image-{index:03}.png") for index in range(count)]
        class ReceiptOutput:
            def __init__(self, argd):
                self.root = Path(argd["outputDir"])
                self.prefix = argd["outputFileName"]
                self.receipts = []
            def print(self, result):
                destination = self.root / f"{self.prefix}.{Path(result['path']).name}.txt"
                destination.write_text("受控产物", encoding="utf-8")
                self.receipts.append({"path": str(destination), "sourcePath": result["path"],
                                      "status": "saved", "saved": True, "error": ""})
            def onEnd(self):
                pass
            def getArtifacts(self):
                return list(self.receipts)
        w.argd.update({"mission.filesType.txt": False, "mission.filesType.txtIndividual": True})
        with patch.object(OCR, "Output", {"txtIndividual": ReceiptOutput}):
            w.page.msnPaths(paths, w.argd)
            w.until_jobs(1)
            w.complete(0)
            w.done()
        state = w.page.getBatchState()
        references = sum(len(row["artifacts"]) + len(row["attemptArtifacts"]) for row in state["rows"])
        assert references == count * 2, f"个体凭据随行数平方复制：{references}，应为 {count * 2}。"
        for path in (paths[0], paths[count // 2], paths[-1]):
            artifacts = w.page.getArtifacts(path)
            assert len(artifacts) == 1 and artifacts[0]["sourcePath"] == Runtime.path_identity(path)[1]
        assert len({id(row["artifacts"][0]) for row in w.page._records.values()}) == count


def test_review_state_snapshot_does_not_probe_every_artifact():
    with world(document=False) as w:
        paths = [w.image(f"image-{index:03}.png") for index in range(80)]
        w.page.msnPaths(paths, w.argd)
        w.until_jobs(1)
        w.complete(0)
        w.done()
        original_isfile = Runtime.os.path.isfile
        with patch.object(Runtime.os.path, "isfile", wraps=original_isfile) as stat:
            for _ in range(6):
                w.page.getBatchState()
            assert stat.call_count == 0, f"状态快照触发了 {stat.call_count} 次主线程磁盘检查。"
            artifacts = w.page.getArtifacts(paths[0])
            assert stat.call_count == len(artifacts), "只在按需读取菜单产物时检查存在性。"
            Path(artifacts[0]["path"]).unlink()
            assert not w.page.getArtifacts(paths[0])[0]["openable"]


def test_review_start_selection_dedup_is_linear():
    with world(document=False) as w:
        count = 256
        paths = [str(w.root / f"image-{index:04}.png") for index in range(count)]
        class ComparedIdentity(str):
            comparisons = 0
            __hash__ = str.__hash__
            def __eq__(self, other):
                type(self).comparisons += 1
                return str.__eq__(self, other)
        original_identity = Runtime.path_identity
        def identity(path):
            key, display = original_identity(path)
            return ComparedIdentity(key), display
        w.page.beginImport()
        with patch.object(Runtime, "path_identity", identity):
            w.page.msnPaths(paths, w.argd)
        assert ComparedIdentity.comparisons < count * 20, f"开始去重发生线性表扫描：{ComparedIdentity.comparisons} 次比较。"


def test_review_result_row_lookup_is_linear():
    with world(document=False) as w:
        count = 160
        paths = [w.image(f"image-{index:04}.png") for index in range(count)]
        class ComparedPath(str):
            comparisons = 0
            __hash__ = str.__hash__
            def __eq__(self, other):
                type(self).comparisons += 1
                return str.__eq__(self, other)
        original_identity = Runtime.path_identity
        def identity(path):
            key, display = original_identity(path)
            return key, ComparedPath(display)
        with patch.object(Runtime, "path_identity", identity):
            w.page.msnPaths(paths, w.argd)
            w.until_jobs(1)
            ComparedPath.comparisons = 0
            w.complete(0)
            w.done()
        assert ComparedPath.comparisons < count * 20, f"逐结果查行发生全段扫描：{ComparedPath.comparisons} 次比较。"


def test_review_repeated_output_errors_are_bounded():
    for distinct in (False, True):
        class FailingOutput:
            def __init__(self, argd):
                self.calls = 0
            def print(self, result):
                self.calls += 1
                raise OSError("受控写入失败" + (str(self.calls) if distinct else ""))
            def onEnd(self):
                pass
            def getArtifacts(self):
                return []
        count = 512
        with patch.object(Runtime.logger, "error") as log:
            session = Runtime.OutputSession([("txt", FailingOutput)], {})
            for _ in range(count):
                session.print({})
            assert len(session.errors) <= 9, f"输出异常逐页累积了 {len(session.errors)} 条。"
            assert session.error_count == count
            _, errors = session.finish()
            assert len("\n".join(errors)) < 6000 and log.call_count <= 9


def test_review_production_io_dispatcher_is_bounded_and_waitable_after_close():
    with world(document=False) as w:
        entered = [threading.Event() for _ in range(8)]
        release = threading.Event()
        w.mailbox.releases.append(release)
        lock = threading.Lock()
        active = peak = 0
        handles = []
        w.page._start_worker = Runtime.BatchPage._start_worker.__get__(w.page)
        def blocked(index):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            entered[index].set()
            w.mailbox.mail.put((lambda: None, ()))
            try:
                assert release.wait(5), "后台 I/O 屏障未释放。"
            finally:
                with lock:
                    active -= 1
        try:
            for index in range(8):
                handle = w.page._start_worker(blocked, index)
                handles.append(handle)
                if isinstance(handle, threading.Thread):
                    assert entered[index].wait(5)
            w.mailbox.until(lambda: sum(event.is_set() for event in entered) >= 2)
            assert peak <= 2, f"生产 I/O 派发创建了 {peak} 个同时阻塞的线程。"
            w.page.closeBatch()
            from py_src.utils.thread_pool import GlobalThreadPool
            assert GlobalThreadPool.waitForDone(0), "私有 I/O 不应占用全局任务池。"
            assert not Runtime.waitForBatchIO(0), "关闭页面后仍须能观察并等待后台收尾。"
        finally:
            release.set()
            for handle in handles:
                if isinstance(handle, threading.Thread):
                    handle.join(5)
            wait = getattr(Runtime, "waitForBatchIO", None)
            if wait:
                assert wait(5000), "后台 I/O 没有完整退出。"
        assert active == 0 and all(event.is_set() for event in entered)


def test_review_import_issues_block_success_actions_without_dropping_valid_files():
    with world() as w:
        valid = w.doc("有效.pdf")
        missing = str(w.root / "缺失.pdf")
        ticket = w.page.beginImport()
        w.page.msnDocs([valid], w.argd)
        w.page.finishImport(ticket["ticketId"], [], {"status": "complete", "error": "",
                           "issues": [{"kind": "error", "path": missing, "error": "受控文件缺失"}]})
        w.until_jobs(1)
        w.complete(0)
        w.done()
        state = w.page.getBatchState()
        assert state["successDocs"] == 1
        assert state["importErrors"] and missing in "\n".join(state["importErrors"]), "扫描 issues 被静默忽略。"
        assert not state["canPostTaskActions"] and not state["summary"].startswith("[Success]")


def test_review_paused_doc_still_settles_after_last_pending_removed():
    with world() as w:
        first, pending = w.doc("第一份.pdf"), w.doc("等待.pdf")
        entered, release = w.factory.block(0)
        w.page.msnDocs([first, pending], w.argd)
        w.until_jobs(1)
        w.complete(0)
        w.mailbox.until(entered.is_set)
        w.page.msnPause()
        w.page.removeRows([pending["path"]])
        release.set()
        w.mailbox.until(lambda: w.page._active is None)
        state = w.page.getBatchState()
        assert state["completed"] and not state["running"], "暂停不应阻止无剩余任务的批次结算。"
        assert not state["canPostTaskActions"] and len(w.manager.jobs) == 1


def test_review_paused_ocr_still_finalizes_after_empty_import():
    with world(document=False) as w:
        image = w.image("图片.png")
        w.page.msnPaths([image], w.argd)
        w.until_jobs(1)
        ticket = w.page.beginImport()
        w.complete(0)
        w.mailbox.until(lambda: w.page._active is None)
        w.page.msnPause()
        w.page.finishImport(ticket["ticketId"], [], {"status": "empty"})
        assert w.page._active is not None or w.page.getBatchState()["completed"], "暂停阻止了最终输出保存。"
        w.done()
        assert w.factory.instances[0].end_count == 1


def test_review_cancel_unlock_ignores_late_success_and_old_dialog_token():
    probe_module = importlib.import_module("py_src.utils.doc_probe")
    with world() as w:
        locked = w.doc("加密.pdf", locked=True)
        gates = [(threading.Event(), threading.Event()) for _ in range(2)]
        for _, release in gates:
            w.mailbox.releases.append(release)
        calls = []
        def probe(path, password="", timeout=30):
            index = len(calls)
            calls.append(password)
            entered, release = gates[index]
            entered.set()
            w.mailbox.mail.put((lambda: None, ()))
            assert release.wait(5)
            return {"path": path, "page_count": 1, "is_encrypted": True, "is_authenticate": True}
        w.page.msnDocs([locked], w.argd)
        with patch.object(probe_module, "probe_document", probe):
            first = w.page.unlockDocument(locked["path"], "第一次密码")
            w.mailbox.until(gates[0][0].is_set)
            cancel = getattr(w.page, "cancelUnlock", None)
            if cancel:
                result = cancel(locked["path"], first["unlockToken"], first["generation"])
                assert result["cancelled"]
                assert not cancel(locked["path"], first["unlockToken"], first["generation"])["cancelled"]
            gates[0][1].set()
            first_worker = w.mailbox.workers[-1]
            first_worker.join(5)
            assert not first_worker.is_alive()
            w.mailbox.drain()
            assert w.row(locked)["status"] == "locked" and not w.manager.jobs, "取消后的晚验证成功自动派发了文档。"
            second = w.page.unlockDocument(locked["path"], "第二次密码")
            w.mailbox.until(gates[1][0].is_set)
            assert second["unlockToken"] != first["unlockToken"]
            assert not cancel(locked["path"], first["unlockToken"], first["generation"])["cancelled"]
            assert w.row(locked)["status"] == "unlocking"
            assert not cancel(locked["path"], second["unlockToken"], second["generation"] + 1)["cancelled"]
            assert w.row(locked)["status"] == "unlocking"
            gates[1][1].set()
            w.until_jobs(1)
            w.complete(0)
            w.done()


def test_review_production_start_stop_reuses_bounded_pool_and_cleans_stale_prepares():
    with world(document=False) as w:
        image = w.image("同一路径.png")
        gates = [w.factory.block(index) for index in range(2)]
        w.page._start_worker = Runtime.BatchPage._start_worker.__get__(w.page)
        try:
            for index in range(2):
                w.page.msnPaths([image], w.argd)
                w.until_jobs(index + 1)
                w.page.msnStop()
                w.mailbox.until(gates[index][0].is_set)
            for _ in range(6):
                w.page.msnPaths([image], w.argd)
                w.page.msnStop()
            w.page.closeBatch()
            assert Runtime.BatchIOPool.maxThreadCount() == 2
            assert Runtime.BatchIOPool.activeThreadCount() <= 2
            assert len(w.factory.instances) == 2, "已取消的排队准备不应构造更多输出器。"
            assert not Runtime.waitForBatchIO(0)
            from py_src.utils.thread_pool import GlobalThreadPool
            assert GlobalThreadPool.waitForDone(0)
        finally:
            for _, release in gates:
                release.set()
            assert Runtime.waitForBatchIO(5000)
            w.mailbox.drain()
        assert all(output.end_count == 1 for output in w.factory.instances)
        assert not any(thread.name == "UmiBatchOutput" for thread in threading.enumerate())


def test_review_close_cleans_prepared_output_without_draining_main_callbacks():
    for document in (True, False):
        with world(document=document) as w:
            source = w.doc("文档.pdf") if document else w.image("图片.png")
            w.page._start_worker = Runtime.BatchPage._start_worker.__get__(w.page)
            if document:
                w.page.msnDocs([source], w.argd)
            else:
                w.page.msnPaths([source], w.argd)
            # 故意不处理主线程 _prepared，覆盖 aboutToQuit 后没有事件循环的窗口。
            assert Runtime.BatchIOPool.waitForDone(5000)
            assert len(w.factory.instances) == 1 and not w.manager.jobs
            w.page.closeBatch()
            assert Runtime.waitForBatchIO(5000), "准备回调未派送时关闭，输出会话被遗留。"
            assert w.factory.instances[0].end_count == 1
            w.mailbox.drain()
            assert not w.manager.jobs


def test_review_exit_wait_tracks_doc_waiting_for_mission_end():
    with world() as w:
        source = w.doc("文档.pdf")
        w.page._start_worker = Runtime.BatchPage._start_worker.__get__(w.page)
        w.page.msnDocs([source], w.argd)
        w.until_jobs(1)
        w.page.closeBatch()
        assert Runtime.BatchIOPool.waitForDone(5000)
        assert not Runtime.waitForBatchIO(0), "不能只等空池而漏掉尚待 Mission 结束的输出会话。"
        w.complete(0)
        assert Runtime.waitForBatchIO(5000), "停止后的 Mission 回调未能独立完成资源收尾。"
        assert w.factory.instances[0].end_count == 1
        w.mailbox.drain()


def test_review_old_import_issues_and_invalid_rows_do_not_pollute_new_batch():
    with world() as w:
        first, second = w.doc("旧.pdf"), w.doc("新.pdf")
        w.page.msnDocs([first], w.argd)
        w.until_jobs(1)
        ticket = w.page.beginImport()
        w.page.msnStop()
        new_id = w.page.msnDocs([second], w.argd)
        w.until_jobs(2)
        w.page.finishImport(ticket["ticketId"], [{"invalid": True}], {"status": "complete", "issues": [
            {"kind": "error", "path": "旧扫描缺失文件", "error": "旧扫描异常"}]})
        assert w.page.getBatchState()["importErrors"] == []
        w.complete(0)
        w.complete(1)
        w.done()
        state = w.page.getBatchState()
        assert state["batchId"] == new_id and state["canPostTaskActions"]


def test_review_shutdown_entry_closes_pages_and_waits_for_real_io_pool():
    with world(document=False) as w:
        image = w.image("退出等待.png")
        entered, release = w.factory.block(0)
        w.page._start_worker = Runtime.BatchPage._start_worker.__get__(w.page)
        w.page.msnPaths([image], w.argd)
        w.until_jobs(1)
        closed = threading.Event()
        original_close = w.page.close
        def observed_close():
            result = original_close()
            closed.set()
            return result
        w.page.close = observed_close
        def release_after_close():
            assert entered.wait(5), "退出入口没有触发输出收尾。"
            assert closed.wait(5), "退出入口没有关闭页面。"
            release.set()
        releaser = w.mailbox.spawn(release_after_close)
        try:
            assert Runtime.shutdownBatchIO(5000), "实际退出入口未等待页面输出收尾。"
            assert w.page.getBatchState()["state"] == "closed"
            assert w.factory.instances[0].end_count == 1
            assert Runtime.waitForBatchIO(0)
        finally:
            release.set()
            releaser.join(5)
            assert not releaser.is_alive()
            assert Runtime.waitForBatchIO(5000)
        w.mailbox.drain()


def test_review_shutdown_drains_qt_queued_terminal_callbacks():
    from PySide6.QtCore import QCoreApplication, QEvent
    from py_src.utils.call_func import CallFunc
    with world() as w:
        source = w.doc("关闭回调.pdf")
        seen = []
        w.page._start_worker = Runtime.BatchPage._start_worker.__get__(w.page)
        w.mailbox.callFunc = lambda function, *args: CallFunc.now(function, *args)
        try:
            w.page.msnDocs([source], w.argd)
            assert Runtime.BatchIOPool.waitForDone(5000)
            w.page._start_worker(lambda: w.page.callFunc(lambda: seen.append(threading.get_ident())))
            assert Runtime.BatchIOPool.waitForDone(5000)
            assert not seen, "本用例必须保留一个真实 Qt queued 回调到退出阶段。"
            assert Runtime.shutdownBatchIO(5000)
            assert seen == [w.mailbox.owner], "退出等待没有排空主线程 queued 回调。"
            assert w.factory.instances[0].end_count == 1
        finally:
            w.page.close()
            assert Runtime.waitForBatchIO(5000)
            QCoreApplication.sendPostedEvents(None, QEvent.Type.MetaCall)


def test_backend_rejects_worker_thread_mutation():
    with world() as w:
        errors = []
        def illegal():
            try:
                w.page.beginImport()
            except RuntimeError as exc:
                errors.append(str(exc))
        worker = w.mailbox.spawn(illegal)
        worker.join(5)
        assert errors and w.page.getBatchState()["importCount"] == 0


def main():
    global DOC, OCR, Runtime
    parser = argparse.ArgumentParser()
    parser.add_argument("data_root", type=Path, help="待验证包或借用依赖的便携运行时数据目录")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--source-root", type=Path, help="显式注入当前 UmiOCR-data 源码")
    mode.add_argument("--packaged", action="store_true", help="只验证指定数据目录内的实际业务代码，允许 app.zip")
    parser.add_argument("--case", action="append", help="仅运行指定用例，可重复指定以定位受控回归")
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    handles = configure_runtime(data_root)
    expected_root = data_root
    if args.source_root:
        expected_root = args.source_root.resolve()
        sys.path[:0] = [str(expected_root), str(expected_root / "py_src" / "imports")]
    from PySide6.QtCore import QCoreApplication
    app = QCoreApplication.instance() or QCoreApplication([])
    DOC = importlib.import_module("py_src.tag_pages.BatchDOC")
    OCR = importlib.import_module("py_src.tag_pages.BatchOCR")
    Runtime = importlib.import_module("py_src.tag_pages.batch_runtime")
    business_modules = (DOC, OCR, Runtime) + tuple(importlib.import_module(name) for name in (
        "py_src.mission.mission_doc", "py_src.mission.mission_ocr", "py_src.ocr.output.output",
        "py_src.utils.doc_probe"))
    for module in business_modules:
        # zipimport 的 __file__ 含 app.zip 虚拟路径，仍必须位于指定根目录之下。
        assert Path(module.__file__).resolve().is_relative_to(expected_root), module.__file__
    tests = [value for key, value in globals().items() if key.startswith("test_") and callable(value)]
    if args.case:
        requested = set(args.case)
        available = {test.__name__ for test in tests}
        if requested - available:
            parser.error("未知用例：" + ", ".join(sorted(requested - available)))
        tests = [test for test in tests if test.__name__ in requested]
    for test in tests:
        test()
    from py_src.utils.thread_pool import GlobalThreadPool
    assert GlobalThreadPool.waitForDone(5000), "Qt 任务线程没有退出。"
    assert Runtime.waitForBatchIO(5000), "私有 I/O 池或输出会话没有收尾。"
    app.processEvents()
    del handles
    origin = "包内业务模块来源已断言" if args.packaged else "当前源码覆盖入口已断言"
    print(f"批量生命周期回归通过（{len(tests)} 项；{origin}）。")


if __name__ == "__main__":
    main()
