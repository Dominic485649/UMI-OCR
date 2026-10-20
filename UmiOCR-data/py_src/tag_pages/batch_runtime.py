# 批量页面共用的主线程队列与输出会话。公共任务管理器不承担动态追加。

import copy
import os
import threading
import time
from dataclasses import dataclass, field
from uuid import uuid4
from weakref import WeakSet

from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool
from umi_log import logger
from .page import Page
from ..utils.thread_pool import Runnable


# 输出保存/准备/解锁不占用 Mission 的全局池，避免 DOC 等待 OCR 时饥饿。
BatchIOPool = QThreadPool()
BatchIOPool.setMaxThreadCount(2)
_BatchPages = WeakSet()
_LiveOutputSessions = set()
_SessionLock = threading.Lock()


def _drain_batch_callbacks():
    application = QCoreApplication.instance()
    if application is not None and application.thread().isCurrentThread():
        # 只派送 queued 调用，不重入用户输入、定时器或新的网络请求。
        QCoreApplication.sendPostedEvents(None, QEvent.Type.MetaCall)


def waitForBatchIO(timeout=5000):
    """等待私有任务、活跃输出会话和主线程终态；超时单位为毫秒。"""
    deadline = None if timeout < 0 else time.monotonic() + timeout / 1000
    while True:
        _drain_batch_callbacks()
        remaining_ms = 25 if deadline is None else max(0, min(25, int((deadline - time.monotonic()) * 1000)))
        pool_done = BatchIOPool.waitForDone(remaining_ms)
        _drain_batch_callbacks()
        with _SessionLock:
            sessions = tuple(_LiveOutputSessions)
        if pool_done and not sessions:
            # 派送终态可能刚产生新的收尾任务，必须复核，不能只看先前空池。
            _drain_batch_callbacks()
            if BatchIOPool.waitForDone(0):
                with _SessionLock:
                    if not _LiveOutputSessions:
                        return True
        remaining = None if deadline is None else max(0, deadline - time.monotonic())
        if remaining == 0:
            return False
        if pool_done and sessions:
            # 短时条件等待为 MetaCall 留出派送点，不阻塞 DOC 所依赖的全局池。
            sessions[0].done.wait(0.025 if remaining is None else min(0.025, remaining))


def shutdownBatchIO(timeout=30000):
    """Qt 主线程退出入口：先取消页面，再等待独立 I/O 与输出会话释放。"""
    for page in tuple(_BatchPages):
        page.close()
    return waitForBatchIO(timeout)


def path_identity(path):
    """路径既是稳定标识的来源，也是界面操作的唯一寻址依据。"""
    path = os.path.abspath(os.path.normpath(os.fspath(path)))
    return os.path.normcase(path), path.replace("\\", "/")


def artifact_snapshot(artifacts, check_exists=True):
    result = []
    for artifact in artifacts:
        item = dict(artifact)
        if check_exists:
            item["exists"] = bool(item.get("path") and os.path.isfile(item["path"]))
        else:
            # 进度推送只使用保存时的凭据，不在主线程遍历磁盘。
            item["exists"] = bool(item.get("exists", item.get("saved", False)))
        item["openable"] = bool(item.get("saved") and item["exists"])
        result.append(item)
    return result


class OutputSession:
    """只由工作线程使用；每个实例只收尾一次，不引用页面当前输出器。"""

    def __init__(self, factories, argd):
        self.outputs = []
        self.error_count = 0
        self._error_counts = {}
        self._overflow_errors = 0
        self._finished = False
        self._finish_requested = False
        self._artifacts = []
        self._lock = threading.RLock()
        self._claim_lock = threading.Lock()
        self.done = threading.Event()
        with _SessionLock:
            _LiveOutputSessions.add(self)
        try:
            for key, factory in factories:
                output = factory(argd)
                self.outputs.append((key, output))
        except Exception as exc:
            self._record_error("初始化输出器", exc)

    @property
    def errors(self):
        result = [f"{message}（{count} 次）" for message, count in self._error_counts.items()]
        if self._overflow_errors:
            result.append(f"另有 {self._overflow_errors} 次输出异常，省略重复详情。")
        return result

    def _record_error(self, prefix, error):
        self.error_count += 1
        message = f"{prefix}失败：{str(error)[:512]}"
        if message in self._error_counts:
            self._error_counts[message] += 1
            return False
        if len(self._error_counts) < 8:
            self._error_counts[message] = 1
            return True
        self._overflow_errors += 1
        return self._overflow_errors == 1

    def request_finish(self):
        with self._claim_lock:
            if self._finish_requested:
                return False
            self._finish_requested = True
            return True

    def print(self, result):
        with self._lock:
            if self._finished:
                return
            for key, output in self.outputs:
                try:
                    output.print(result)
                except Exception as exc:
                    if self._record_error(f"{key} 输出", exc):
                        logger.error("批量结果输出失败。", exc_info=True)

    def finish(self, cancelled=False):
        with self._lock:
            if self._finished:
                return copy.deepcopy(self._artifacts), self.errors
            self._finished = True
            try:
                for key, output in self.outputs:
                    error = ""
                    try:
                        output.onEnd()
                    except Exception as exc:
                        error = str(exc)[:512]
                        if self._record_error(f"{key} 保存", exc):
                            logger.error("批量输出收尾失败。", exc_info=True)
                    get_artifacts = getattr(output, "getArtifacts", None)
                    try:
                        artifacts = get_artifacts() if callable(get_artifacts) else []
                    except Exception as exc:
                        artifacts = []
                        error = str(exc)[:512]
                        self._record_error(f"{key} 读取产物记录", exc)
                    # 没有显式保存凭据时只报告失败/未生成，绝不以 exists 推定成功。
                    if not artifacts and getattr(output, "outputPath", ""):
                        artifacts = [{"path": output.outputPath, "status": "failed", "saved": False,
                                      "error": error or "本次没有生成可确认的产物。"}]
                    for artifact in artifacts:
                        item = dict(artifact)
                        item["format"] = key
                        # 存在性只在保存工作线程记录一次；打开菜单时再按需复核。
                        item["exists"] = bool(item.get("path") and os.path.isfile(item["path"]))
                        if cancelled and item.get("status") != "recovery":
                            item.update(status="cancelled", saved=False, error="任务已停止，产物可能不完整。")
                        elif error or self.error_count:
                            if item.get("status") != "recovery":
                                item.update(status="failed", saved=False, error=error or "本次输出不完整。")
                        self._artifacts.append(item)
                return copy.deepcopy(self._artifacts), self.errors
            finally:
                self.done.set()
                with _SessionLock:
                    _LiveOutputSessions.discard(self)


@dataclass(eq=False)
class Attempt:
    batch_id: str
    generation: int
    entry: dict
    rows: tuple
    argd: dict
    mission_id: str = field(default_factory=lambda: str(uuid4()))
    session: object = None
    phase: str = "preparing"
    submitting: bool = False
    buffered: list = field(default_factory=list)
    cancelled: threading.Event = field(default_factory=threading.Event)
    finish_lock: threading.Lock = field(default_factory=threading.Lock)
    io_lock: threading.RLock = field(default_factory=threading.RLock)
    end_requested: bool = False
    seen: set = field(default_factory=set)
    rows_by_path: dict = field(init=False, repr=False)

    def __post_init__(self):
        self.rows_by_path = {row["path"]: row for row in self.rows}

    @property
    def attempt_id(self):
        return self.entry["attemptId"]

    def claim_end(self):
        with self.finish_lock:
            if self.end_requested:
                return False
            self.end_requested = True
            return True


class BatchPage(Page):
    """所有记录、队列、票据和统计只在创建本页面的 Qt 主线程修改。"""

    document = False

    def __init__(self, *args):
        super().__init__(*args)
        self._main_thread = threading.get_ident()
        self._generation = 0
        self._stop_epoch = 0
        self._mutation = 0
        self._records = {}
        self._order = []
        self._pending = []
        self._tickets = {}
        self._tombstones = {}
        self._entries = []
        self._active = None
        self._batch_id = ""
        self._batch_argd = {}
        self._running = False
        self._paused = False
        self._completed = False
        self._closed = False
        self._initial_imports = False
        self._terminal_state = "idle"
        self._started_at = None
        self._ended_at = None
        self._import_errors = []
        self._summary = ""
        self._driving = False
        self._drive_again = False
        _BatchPages.add(self)

    def _assert_main(self):
        if threading.get_ident() != self._main_thread:
            raise RuntimeError("批量页面状态只能在 Qt 主线程修改。")

    def _start_worker(self, function, *args):
        worker = Runnable(function, *args)
        BatchIOPool.start(worker)
        return worker

    def _qml(self, name, *args):
        self._assert_main()
        if not self._closed:
            self.callQml(name, *args)

    def _lookup(self, key):
        if isinstance(key, dict):
            key = key.get("id") or key.get("path", "")
        if not key:
            return None
        return self._records.get(path_identity(key)[0])

    def _budget(self, row):
        if not self.document:
            return 1
        return max(0, row["range_end"] - row["range_start"] + 1)

    def _entry_is_current(self, entry):
        return entry is not None and entry.get("batchId") == self._batch_id

    def _metadata(self, source, previous=None):
        row = dict(previous or {})
        if isinstance(source, str):
            source = {"path": source}
        identity, path = path_identity(source["path"])
        row.update(id=identity, path=path)
        if self.document:
            count = max(0, int(source.get("page_count", row.get("page_count", 0)) or 0))
            row["page_count"] = count
            row["range_start"] = int(source.get("range_start", row.get("range_start", 1)) or 1)
            row["range_end"] = int(source.get("range_end", row.get("range_end", count)) or count)
            # 兼容文档任务原有的负页码约定，快照始终显示规范化范围。
            if row["range_start"] < 0:
                row["range_start"] += count + 1
            if row["range_end"] < 0:
                row["range_end"] += count + 1
            row["is_encrypted"] = bool(source.get("is_encrypted", row.get("is_encrypted", False)))
            row["is_authenticate"] = bool(source.get("is_authenticate", row.get("is_authenticate", not row["is_encrypted"])))
            row["password"] = str(source.get("password", row.get("password", "")) or "")
        else:
            row.update(page_count=1, range_start=1, range_end=1, is_encrypted=False,
                       is_authenticate=True, password="")
        overrides = copy.deepcopy(row.get("argd", {}))
        overrides.update(copy.deepcopy(source.get("argd") or {}))
        overrides.update({key: copy.deepcopy(value) for key, value in source.items()
                          if key.startswith(("ocr.", "doc.", "tbpu."))})
        row["argd"] = overrides
        row.setdefault("status", "ready")
        row.setdefault("attemptId", "")
        row.setdefault("missionId", "")
        row.setdefault("donePages", 0)
        row.setdefault("message", "")
        row.setdefault("artifacts", [])
        row.setdefault("attemptArtifacts", [])
        row.setdefault("_entry", None)
        row.setdefault("_unlockToken", "")
        if source.get("error"):
            row["message"] = str(source["error"])
        return row

    def _enroll(self, row, argd=None, frozen=False):
        entry = {"id": row["id"], "batchId": self._batch_id, "attemptId": uuid4().hex, "budget": self._budget(row),
                 "done": 0, "outcome": "pending", "included": True, "frozen": frozen,
                 "metadata": copy.deepcopy({key: row[key] for key in
                                            ("path", "page_count", "range_start", "range_end", "password")}),
                 "argd": copy.deepcopy(argd if argd is not None else self._batch_argd)}
        entry["argd"].update(copy.deepcopy(row["argd"]))
        self._entries.append(entry)
        row.update(_entry=entry, attemptId=entry["attemptId"], missionId="", donePages=0,
                   attemptArtifacts=[], _attemptArtifactsShared=(), message="")
        if row["is_encrypted"] and not row["is_authenticate"]:
            row["status"] = "unlocking" if row["_unlockToken"] else "locked"
            entry["outcome"] = "locked"
        else:
            row["status"] = "pending"
            self._pending.append(row["id"])
        return entry

    def beginImport(self, requestId=""):
        self._assert_main()
        if self._closed:
            return {"ok": False, "error": "页面已关闭。", "ticketId": ""}
        ticket_id = uuid4().hex
        ticket = {"ticketId": ticket_id, "requestId": str(requestId), "generation": self._generation,
                  "batchId": self._batch_id if self._running else "", "mutation": self._mutation}
        self._tickets[ticket_id] = ticket
        self._emit()
        return dict(ticket, ok=True)

    def _merge_rows(self, rows, ticket=None):
        enroll = self._running and (ticket is None or ticket["batchId"] == self._batch_id)
        added = []
        for source in rows or []:
            try:
                if isinstance(source, str):
                    source = {"path": source}
                identity, _ = path_identity(source["path"])
                if ticket and self._tombstones.get(identity, -1) > ticket["mutation"]:
                    continue
                previous = self._records.get(identity)
                if previous:
                    # 旧扫描不能覆盖新批次的参数，同路径追加不会重新派发。
                    if ticket and not enroll and self._running:
                        continue
                    if previous["status"] in ("preparing", "active", "finalizing"):
                        continue
                    if self._running and self._entry_is_current(previous.get("_entry")):
                        continue
                row = self._metadata(source, previous)
                if previous is None:
                    self._order.append(identity)
                    self._records[identity] = row
                    added.append(identity)
                else:
                    self._records[identity] = row
                if enroll and (previous is None or not self._entry_is_current(row.get("_entry"))):
                    self._enroll(row)
            except (KeyError, TypeError, ValueError, OSError) as exc:
                if ticket is None or (self._running and ticket["batchId"] == self._batch_id):
                    self._import_errors.append(f"忽略无效导入项：{exc}")
        return added

    def finishImport(self, ticketId, rows=None, terminal=None):
        self._assert_main()
        ticket = self._tickets.pop(str(ticketId), None)
        if ticket is None or ticket["generation"] != self._generation or self._closed:
            return self._result(False, "导入票据已失效。")
        terminal = terminal or {}
        if terminal.get("status") != "cancelled":
            self._merge_rows(rows, ticket)
        if ticket["batchId"] == self._batch_id and self._running:
            if terminal.get("status") in ("error", "cancelled") or terminal.get("error"):
                self._import_errors.append(str(terminal.get("error") or "本次导入未完成。"))
            known = set(self._import_errors)
            for issue in terminal.get("issues") or []:
                if isinstance(issue, dict):
                    detail = issue.get("error") or issue.get("message") or issue.get("reason") or issue.get("kind") or "导入项未完成。"
                    detail = f"{issue['path']}：{detail}" if issue.get("path") else str(detail)
                else:
                    detail = str(issue)
                if detail and detail not in known:
                    self._import_errors.append(detail)
                    known.add(detail)
        self._drive()
        return self._result()

    def syncRows(self, rows, ticketId=""):
        self._assert_main()
        ticket = self._tickets.get(str(ticketId)) if ticketId else None
        if self._closed or (ticketId and (not ticket or ticket["generation"] != self._generation)):
            return self._result(False, "导入票据已失效。")
        self._merge_rows(rows, ticket)
        self._drive()
        return self._result()

    def syncMetadata(self, path, metadata):
        self._assert_main()
        row = self._lookup(path)
        if not row:
            return self._result(False, "文件记录不存在。")
        if row["status"] in ("preparing", "active", "finalizing", "unlocking"):
            return self._result(False, "当前文件已提交或正在验证，不能修改。")
        entry = row.get("_entry")
        if self._running and self._entry_is_current(entry) and entry.get("frozen"):
            return self._result(False, "重新识别已确认，不能修改本次执行参数。")
        updated = self._metadata(dict(metadata, path=row["path"]), row)
        row.update(updated)
        if self._running and self._entry_is_current(entry) and entry["outcome"] in ("pending", "locked"):
            entry["budget"] = self._budget(row)
            entry["metadata"] = copy.deepcopy({key: row[key] for key in entry["metadata"]})
            entry["argd"].update(copy.deepcopy(row["argd"]))
            if row["is_encrypted"] and not row["is_authenticate"]:
                row["status"] = entry["outcome"] = "locked"
                if row["id"] in self._pending:
                    self._pending.remove(row["id"])
            else:
                row["status"] = entry["outcome"] = "pending"
                if row["id"] not in self._pending:
                    self._pending.append(row["id"])
        self._drive()
        return self._result()

    def _start_batch(self, rows, argd):
        self._assert_main()
        if self._closed:
            return "[Error] 页面已关闭。"
        if self._running:
            return "[Error] 已有批次进行中，请使用追加导入。"
        self._merge_rows(rows)
        selected = set()
        for source in rows or []:
            path = source if isinstance(source, str) else source.get("path", "")
            if path:
                identity = path_identity(path)[0]
                if identity in self._records:
                    selected.add(identity)
        waiting = [ticket for ticket in self._tickets.values() if not ticket["batchId"]]
        if not selected and not waiting:
            return "[Error] 没有可识别的文件。"
        self._batch_id = uuid4().hex
        self._batch_argd = copy.deepcopy(argd)
        self._entries = []
        self._pending = []
        self._active = None
        self._running = True
        self._paused = self._completed = False
        self._terminal_state = "running"
        self._started_at = time.monotonic()
        self._ended_at = None
        self._summary = ""
        self._import_errors = []
        for ticket in waiting:
            ticket["batchId"] = self._batch_id
        self._initial_imports = bool(waiting)
        # 使用后端显示顺序，不相信表格传来的可变下标或过期排序。
        for identity in self._order:
            if identity in selected:
                self._enroll(self._records[identity])
        self._drive()
        return self._batch_id

    def _batch_tickets(self):
        return sum(ticket["batchId"] == self._batch_id for ticket in self._tickets.values())

    def _locked_rows(self):
        return [row for row in self._records.values() if self._entry_is_current(row.get("_entry"))
                and row["status"] in ("locked", "unlocking") and self._running]

    def _drive(self):
        self._assert_main()
        if self._driving:
            self._drive_again = True
            return
        self._driving = True
        try:
            while True:
                self._drive_again = False
                if not self._running or self._closed:
                    self._emit()
                    break
                if self._initial_imports and not self._batch_tickets():
                    self._initial_imports = False
                if not self._initial_imports:
                    # 暂停只禁止提交新任务，已经结束的段仍须保存和结算。
                    self._advance()
                self._emit()
                if not self._drive_again:
                    break
        finally:
            self._driving = False

    def _advance(self):
        raise NotImplementedError

    def _valid_context(self, context):
        return (not self._closed and self._running and self._active is context
                and context.batch_id == self._batch_id and context.generation == self._generation
                and not context.cancelled.is_set())

    def _event(self, context, kind, mission_id, *args):
        self._assert_main()
        if not self._valid_context(context):
            if kind == "finished":
                self._archive_cancelled(context, *args)
            return
        if context.submitting:
            context.buffered.append((kind, mission_id, args))
            return
        if mission_id and mission_id != context.mission_id:
            return
        self._handle_event(context, kind, *args)

    def _archive_cancelled(self, context, message, artifacts):
        # 停止后的保存记录可归档，但绝不能调度，也不能写进下一批的同路径行。
        context.entry["artifacts"] = copy.deepcopy(artifacts)
        if (self._closed or self._running or context.batch_id != self._batch_id
                or context.generation != self._generation or not context.cancelled.is_set()):
            return
        rows = tuple(row for row in context.rows
                     if self._records.get(row["id"]) is row and row["status"] == "stopped")
        self._store_attempt_artifacts(rows, artifacts)
        self._emit()

    def _store_attempt_artifacts(self, rows, artifacts):
        for row in rows:
            row["attemptArtifacts"] = artifacts

    def _handle_event(self, context, kind, *args):
        raise NotImplementedError

    def _submit(self, context, submit):
        # 上下文和 reserved ID 在公共调度器启动线程之前已经可见。
        context.submitting = True
        try:
            mission_id = submit()
        except Exception as exc:
            mission_id = f"[Error] 提交任务失败：{exc}"
        context.submitting = False
        if isinstance(mission_id, str) and not mission_id.startswith("["):
            context.mission_id = mission_id
            for row in context.rows:
                row["missionId"] = mission_id
            if self._valid_context(context):
                if self._paused:
                    self._manager.pauseMissionList(mission_id)
                for kind, event_id, args in context.buffered:
                    self._event(context, kind, event_id, *args)
            else:
                self._manager.stopMissionList(mission_id)
        else:
            self._worker_end(context, {"msnID": context.mission_id}, str(mission_id))
        context.buffered.clear()

    def _worker_end(self, context, info, message):
        if not context.claim_end():
            return
        if context.session and not context.session.request_finish():
            return
        mission_id = info.get("msnID", context.mission_id) if info else context.mission_id
        self.callFunc(self._event, context, "finalizing", mission_id)
        # 不论 Mission 回调来自哪个线程，保存都交给独立有界 I/O 池。
        self._start_worker(self._finish_worker, context, mission_id, message)

    def _finish_worker(self, context, mission_id, message):
        try:
            with context.io_lock:
                artifacts, errors = context.session.finish(context.cancelled.is_set()) if context.session else ([], [])
        except Exception as exc:
            artifacts, errors = [], [f"输出收尾异常：{exc}"]
        # 用户也可能在 onEnd 已开始写盘后停止，最终凭据仍必须标为取消。
        if context.cancelled.is_set():
            artifacts = [dict(item, status="cancelled", saved=False, error="任务已停止，产物可能不完整。")
                         if item.get("status") != "recovery" else item for item in artifacts]
        if errors:
            message = "[Error] " + "\n".join(errors) + "\n" + message
        self.callFunc(self._event, context, "finished", mission_id, message, artifacts)

    def _finish_batch(self):
        if self._active or self._pending or self._batch_tickets() or self._locked_rows():
            return
        self._running = False
        self._paused = False
        self._completed = True
        self._terminal_state = "finished"
        self._ended_at = time.monotonic()
        counts = self._counts()
        if counts["failedDocs"] or self._import_errors:
            self._summary = f"[Error] 批次结束：{counts['successDocs']} 成功，{counts['failedDocs']} 失败。"
        elif counts["skippedDocs"] or counts["stoppedDocs"]:
            self._summary = f"[Warning] 批次结束：{counts['successDocs']} 成功，{counts['skippedDocs']} 跳过。"
        elif counts["successDocs"]:
            self._summary = "[Success] 批量识别完成。"
        else:
            self._summary = "[Warning] 没有执行可完成的任务。"
        self._on_batch_finished()

    def _on_batch_finished(self):
        pass

    def msnPause(self):
        self._assert_main()
        if self._running:
            self._paused = True
            if self._active and self._active.phase == "active":
                self._manager.pauseMissionList(self._active.mission_id)
        self._emit()
        return self._result()

    def msnResume(self):
        self._assert_main()
        if self._running:
            self._paused = False
            if self._active and self._active.phase == "active":
                self._manager.resumeMissionList(self._active.mission_id)
        self._drive()
        return self._result()

    def msnStop(self):
        self._assert_main()
        self._stop_epoch += 1
        self._paused = False
        affected = {id(row) for row in self._stopping_rows()}
        for row in self._records.values():
            if row["_unlockToken"]:
                row["_unlockToken"] = ""
                if not self._running:
                    row["status"] = "ready"
        if self._running:
            self._running = False
            self._completed = False
            self._terminal_state = "stopped"
            self._ended_at = time.monotonic()
            self._summary = "[Warning] 用户停止了批次。"
            context, self._active = self._active, None
            self._pending = []
            for row in self._records.values():
                entry = row.get("_entry")
                if self._entry_is_current(entry) and (entry["outcome"] in ("pending", "locked", "active") or id(row) in affected):
                    entry["outcome"] = "stopped"
                    row["status"] = "stopped"
                    row["message"] = self._summary
            if context:
                context.cancelled.set()
                if context.phase == "active":
                    self._manager.stopMissionList(context.mission_id)
                elif context.phase in ("prepared", "preparing") and context.session is not None:
                    BatchPage._worker_end(self, context, {}, self._summary)
                # preparing 的线程回来后负责自己的输出器，finalizing 仍自然收尾。
            self._on_stopped()
        self._emit()
        return self._result()

    def _stopping_rows(self):
        return self._active.rows if self._active else ()

    def _on_stopped(self):
        pass

    def movePending(self, path, beforePath=""):
        self._assert_main()
        row = self._lookup(path)
        before = self._lookup(beforePath) if beforePath else None
        candidates = self._pending if self._running else self._order
        if not row or row["id"] not in candidates or row["status"] in ("preparing", "active", "finalizing", "unlocking"):
            return self._result(False, "只能移动尚未提交的文件。")
        if beforePath and (not before or before["id"] not in candidates):
            return self._result(False, "目标已经不是等待任务。")
        if before is row:
            return self._result()
        candidates.remove(row["id"])
        position = candidates.index(before["id"]) if before else len(candidates)
        candidates.insert(position, row["id"])
        if self._running:
            iterator = iter(self._pending)
            pending_set = set(self._pending)
            self._order = [next(iterator) if identity in pending_set else identity for identity in self._order]
        self._emit()
        return self._result()

    def removeRows(self, paths):
        self._assert_main()
        if isinstance(paths, str):
            paths = [paths]
        errors = []
        for path in paths or []:
            row = self._lookup(path)
            if not row:
                continue
            if row["status"] in ("preparing", "active", "finalizing"):
                errors.append("当前文件正在处理或保存，不能移出。")
                continue
            entry = row.get("_entry")
            if self._running and self._entry_is_current(entry) and entry["outcome"] in ("pending", "locked"):
                entry.update(outcome="skipped", included=False)
            identity = row["id"]
            self._mutation += 1
            self._tombstones[identity] = self._mutation
            self._records.pop(identity)
            self._order.remove(identity)
            if identity in self._pending:
                self._pending.remove(identity)
        self._drive()
        return self._result(not errors, "\n".join(errors))

    def reOCR(self, path, argd=None, metadata=None):
        self._assert_main()
        row = self._lookup(path)
        if not row or row["status"] in ("pending", "preparing", "active", "finalizing", "unlocking", "locked"):
            return self._result(False, "该文件已在队列中或尚未解锁。")
        if metadata:
            row.update(self._metadata(dict(metadata, path=row["path"]), row))
        settings = copy.deepcopy(argd or self._batch_argd)
        if not settings:
            return self._result(False, "请先确认识别设置。")
        # 显式确认的新设置优先于该行上一轮保存的配置。
        row["argd"].update(copy.deepcopy(settings))
        if not self._running:
            result = self._start_batch([row["path"]], settings)
            current = self._lookup(row["path"])
            if not result.startswith("[Error]") and current and current.get("_entry"):
                current["_entry"]["frozen"] = True
            return self._result(not result.startswith("[Error]"), result if result.startswith("[Error]") else "")
        self._enroll(row, settings, frozen=True)
        self._drive()
        return self._result()

    def unlockDocument(self, path, password):
        self._assert_main()
        row = self._lookup(path)
        if not row or not row["is_encrypted"] or row["status"] in ("preparing", "active", "finalizing", "pending", "unlocking"):
            return self._result(False, "该文件当前不能验证密码。")
        token = uuid4().hex
        row.update(_unlockToken=token, status="unlocking", message="正在验证密码。")
        self._start_worker(self._unlock_worker, row["id"], row["path"], str(password), token,
                           self._generation, self._stop_epoch)
        self._emit()
        return dict(self._result(), unlockToken=token)

    def cancelUnlock(self, path, unlockToken, generation=-1):
        self._assert_main()
        row = self._lookup(path)
        matches = (not self._closed and row is not None and bool(unlockToken)
                   and row["_unlockToken"] == unlockToken
                   and (generation == -1 or generation == self._generation))
        if not matches:
            return dict(self._result(), cancelled=False)
        row.update(_unlockToken="", status="locked", message="已取消密码验证，文件仍待解锁。")
        self._emit()
        return dict(self._result(), cancelled=True)

    def _unlock_worker(self, identity, path, password, token, generation, epoch):
        try:
            from ..utils.doc_probe import probe_document
            result = probe_document(path, password=password)
        except Exception as exc:
            result = {"path": path, "error": str(exc), "is_authenticate": False}
        self.callFunc(self._unlocked, identity, password, token, generation, epoch, result)

    def _unlocked(self, identity, password, token, generation, epoch, result):
        self._assert_main()
        row = self._records.get(identity)
        if (self._closed or generation != self._generation or epoch != self._stop_epoch
                or not row or row["_unlockToken"] != token):
            return
        row["_unlockToken"] = ""
        accepted = bool(not result.get("error") and result.get("is_authenticate"))
        row["status"] = "locked" if self._running else "ready"
        if accepted:
            fields = dict(result, password=password)
            fields.pop("path", None)
            if row["range_end"] <= 0:
                fields["range_end"] = result.get("page_count", 0)
            self.syncMetadata(row["path"], fields)
        else:
            row["message"] = str(result.get("error") or "密码不正确，文件仍在等待解锁。")
            self._drive()
        self._qml("onUnlockResult", row["path"], dict(result, ok=accepted, unlockToken=token, generation=generation))

    def getOriginal(self, path):
        self._assert_main()
        row = self._lookup(path)
        value = row["path"] if row else ""
        exists = bool(value and os.path.isfile(value))
        return {"path": value, "exists": exists, "openable": exists,
                "error": "" if exists else "原始文件不存在。"}

    def getArtifacts(self, path):
        self._assert_main()
        row = self._lookup(path)
        return artifact_snapshot(self._artifact_values(row)) if row else []

    def _artifact_values(self, row, latest=True):
        name = "artifacts" if latest else "attemptArtifacts"
        shared = "_artifactsShared" if latest else "_attemptArtifactsShared"
        return (*row.get(shared, ()), *row[name])

    def openArtifact(self, path, format="", artifactPath=""):
        artifacts = self.getArtifacts(path)
        selected = [item for item in artifacts if item["openable"]
                    and (not format or item["format"] == format)
                    and (not artifactPath or item["path"] == artifactPath)]
        return {"ok": len(selected) == 1, "path": selected[0]["path"] if len(selected) == 1 else "",
                "artifacts": artifacts, "error": "" if len(selected) == 1 else "请选择已保存且仍存在的产物。"}

    def clearRows(self):
        self._assert_main()
        self.msnStop()
        self._generation += 1
        self._records.clear()
        self._order.clear()
        self._tickets.clear()
        self._entries.clear()
        self._tombstones.clear()
        self._batch_id = ""
        self._terminal_state = "idle"
        self._completed = False
        self._started_at = self._ended_at = None
        self._summary = ""
        self._emit()
        return self._result()

    def closeBatch(self):
        self._assert_main()
        self.msnStop()
        self._closed = True
        self._generation += 1
        self._tickets.clear()
        self._terminal_state = "closed"
        _BatchPages.discard(self)
        return self._result()

    def close(self):
        return self.closeBatch()

    def _counts(self):
        included = [entry for entry in self._entries if entry["included"]]
        return {"totalDocs": len(included),
                "doneDocs": sum(entry["outcome"] in ("success", "failed", "stopped") for entry in included),
                "successDocs": sum(entry["outcome"] == "success" for entry in included),
                "failedDocs": sum(entry["outcome"] == "failed" for entry in included),
                "skippedDocs": sum(entry["outcome"] == "skipped" for entry in self._entries),
                "stoppedDocs": sum(entry["outcome"] == "stopped" for entry in included),
                "totalPages": sum(max(entry["budget"], entry["done"]) for entry in included),
                "donePages": sum(entry["done"] for entry in included)}

    def getBatchState(self):
        self._assert_main()
        counts = self._counts()
        state = self._terminal_state
        if self._running:
            if self._paused:
                state = "paused"
            elif self._active:
                state = self._active.phase
            elif self._batch_tickets():
                state = "waiting_import"
            elif self._locked_rows():
                state = "waiting_unlock"
            else:
                state = "running"
        rows = []
        for identity in self._order:
            row = self._records[identity]
            item = {key: copy.deepcopy(value) for key, value in row.items()
                    if not key.startswith("_") and key not in ("artifacts", "attemptArtifacts")}
            protected = row["status"] in ("preparing", "active", "finalizing")
            item.update(canRemove=not protected,
                        canMove=(row["status"] == "pending" if self._running else not protected and row["status"] != "unlocking"),
                        canReocr=row["status"] in ("ready", "finished", "failed", "stopped"),
                        canUnlock=row["is_encrypted"] and not row["is_authenticate"] and not protected and row["status"] != "unlocking",
                        artifacts=artifact_snapshot(self._artifact_values(row), check_exists=False),
                        attemptArtifacts=artifact_snapshot(self._artifact_values(row, latest=False), check_exists=False))
            rows.append(item)
        end = self._ended_at or time.monotonic()
        return dict(counts, ok=True, error="", batchId=self._batch_id, generation=self._generation,
                    state=state, running=self._running, paused=self._paused, completed=self._completed,
                    canPostTaskActions=bool(self._completed and counts["successDocs"] and not counts["failedDocs"]
                                            and not counts["skippedDocs"] and not counts["stoppedDocs"] and not self._import_errors),
                    activeId=self._active.rows[0]["id"] if self._active else "",
                    pending=list(self._pending), importCount=self._batch_tickets() if self._running else len(self._tickets),
                    lockedCount=len(self._locked_rows()), rows=rows, summary=self._summary,
                    elapsed=max(0, end - self._started_at) if self._started_at else 0,
                    importErrors=list(self._import_errors))

    def _emit(self):
        if not self._closed:
            self._qml("onBatchState", self.getBatchState())

    def _result(self, ok=True, error=""):
        return dict(self.getBatchState(), ok=ok, error=error)
