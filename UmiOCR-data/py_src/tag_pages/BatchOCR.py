# ========================================
# =============== 批量OCR页 ===============
# ========================================

import copy
import os
import time
from uuid import uuid4

from .batch_runtime import Attempt, BatchPage, OutputSession
from ..mission.mission_ocr import MissionOCR
from ..utils.utils import allowedFileName
from ..ocr.output import Output


class BatchOCR(BatchPage):
    def __init__(self, *args):
        super().__init__(*args)
        self.argd = None
        self.msnID = ""
        self.outputList = []
        self._ocr_session = None
        self._session_rows = []
        self._preview_id = ""
        self._preview_token = ""

    @property
    def _manager(self):
        return MissionOCR

    def msnPaths(self, paths, argd):
        settings = dict(argd, **{"ocr.taskType": "batch"})
        result = self._start_batch(paths, settings)
        if not result.startswith("[Error]"):
            self.msnID = result
        return result

    def _preprocessArgd(self, argd, path0, attempt_id=""):
        settings = copy.deepcopy(argd)
        if settings["mission.dirType"] == "source":
            settings["mission.dir"] = os.path.dirname(path0)
        else:
            settings["mission.dir"] = os.path.abspath(settings["mission.dir"])
            os.makedirs(settings["mission.dir"], exist_ok=True)
        timestamp = time.time()
        settings["startTimestamp"] = timestamp
        settings["startDatetime"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
        datetime_user = settings["mission.datetimeFormat"].replace("%unix", str(timestamp))
        datetime_user = time.strftime(datetime_user, time.localtime(timestamp))
        name = settings["mission.fileNameFormat"].replace("%date", datetime_user)
        name = name.replace("%name", os.path.basename(os.path.dirname(path0)))
        if not allowedFileName(name):
            raise ValueError(f"输出文件名【{name}】含有不允许的字符。")
        settings["mission.fileName"] = name + ("." + attempt_id if attempt_id else "")
        return settings

    def _initOutputList(self, argd):
        output_argd = {
            "outputDir": argd["mission.dir"], "outputDirType": argd["mission.dirType"],
            "outputFileName": argd["mission.fileName"], "startDatetime": argd["startDatetime"],
            "ignoreBlank": argd["mission.ignoreBlank"], "attemptPrefix": True,
        }
        factories = [(key[len("mission.filesType."):], Output[key[len("mission.filesType."):]])
                     for key, enabled in argd.items() if key.startswith("mission.filesType.") and enabled]
        return OutputSession(factories, output_argd)

    def _take_pending(self):
        # 只续接队首的同质连续段，既不丢失逐项确认参数，也不改变等待顺序。
        first = self._records[self._pending[0]]["_entry"]["argd"]
        settings = {key: value for key, value in first.items() if key.startswith(("ocr.", "tbpu."))}
        end = 1
        while end < len(self._pending):
            argd = self._records[self._pending[end]]["_entry"]["argd"]
            candidate = {key: value for key, value in argd.items() if key.startswith(("ocr.", "tbpu."))}
            if candidate != settings:
                break
            end += 1
        identities, self._pending = self._pending[:end], self._pending[end:]
        rows = tuple(self._records[identity] for identity in identities)
        for row in rows:
            row["_entry"]["outcome"] = "active"
        return rows

    def _advance(self):
        if self._active:
            if self._active.phase == "prepared":
                self._submit_segment(self._active)
            return
        if self._pending:
            if self._paused:
                return
            rows = self._take_pending()
            context = Attempt(self._batch_id, self._generation, rows[0]["_entry"], rows,
                              copy.deepcopy(rows[0]["_entry"]["argd"]))
            self._active = context
            if self._ocr_session is None:
                self._ocr_session = context
                self._session_rows = list(rows)
                for row in rows:
                    row["status"] = "preparing"
                self._start_worker(self._prepare_worker, context)
            else:
                context.session = self._ocr_session.session
                self._session_rows.extend(rows)
                context.phase = "prepared"
                self._submit_segment(context)
            return
        if self._ocr_session:
            if not self._batch_tickets():
                # 分段任务结束不等于输出结束；开始保存后到达的文件留在下一会话。
                owner = self._ocr_session
                context = Attempt(self._batch_id, self._generation, owner.entry,
                                  tuple(self._session_rows), owner.argd, session=owner.session,
                                  phase="finalizing")
                self._active = context
                self._ocr_session = None
                self._session_rows = []
                for row in context.rows:
                    row["status"] = "finalizing"
                BatchPage._worker_end(self, context, {}, "[Success] 输出会话完成。")
            return
        self._finish_batch()

    def _prepare_worker(self, context):
        if context.cancelled.is_set():
            return
        error = ""
        try:
            settings = self._preprocessArgd(context.argd, context.rows[0]["path"], context.attempt_id)
            context.session = self._initOutputList(settings)
            context.argd = settings
            if context.session.errors:
                error = "[Error] " + "\n".join(context.session.errors)
        except Exception as exc:
            error = f"[Error] 无法创建输出器：{exc}"
        if context.cancelled.is_set():
            BatchPage._worker_end(self, context, {}, "[Warning] 任务已停止。")
        else:
            self.callFunc(self._prepared, context, error)

    def _prepared(self, context, error):
        self._assert_main()
        if not self._valid_context(context):
            context.cancelled.set()
            BatchPage._worker_end(self, context, {}, "[Warning] 任务已停止。")
            return
        self.argd = context.argd
        self.outputList = [output for _key, output in context.session.outputs] if context.session else []
        context.phase = "prepared"
        if error:
            self._ocr_session = None
            self._session_rows = []
            BatchPage._worker_end(self, context, {}, error)
        elif not self._paused:
            self._submit_segment(context)
        self._emit()

    def _submit_segment(self, context):
        if not self._valid_context(context) or self._paused:
            return
        context.phase = "active"
        for row in context.rows:
            row["status"] = "active"
        info = {
            "_reserved_msnID": context.mission_id, "argd": copy.deepcopy(context.argd),
            "onStart": lambda info: None,
            "onReady": lambda info, item: self.callFunc(self._event, context, "ready", info.get("msnID", ""), item["path"]),
            "onGet": lambda info, item, result: self._worker_get(context, info, item, result),
            "onEnd": lambda info, message: self._worker_end(context, info, message),
        }
        self._submit(context, lambda: MissionOCR.addMissionList(info, [{"path": row["path"]} for row in context.rows]))

    def _worker_get(self, context, info, item, result):
        path = item["path"]
        with context.io_lock:
            if context.cancelled.is_set() or context.end_requested or path in context.seen:
                return
            context.seen.add(path)
            result = dict(result, fileName=os.path.basename(path), dir=os.path.dirname(path), path=path)
            if context.session:
                context.session.print(result)
        self.callFunc(self._event, context, "get", info.get("msnID", ""), path, result)

    def _worker_end(self, context, info, message):
        # OCR 的 onEnd 只关闭本段 Mission，不能在每次追加续接时重复关闭输出器。
        if not context.claim_end():
            return
        self.callFunc(self._event, context, "segment_end", info.get("msnID", context.mission_id), message)

    def _handle_event(self, context, kind, *args):
        if kind == "ready":
            self._qml("onOcrReady", args[0])
        elif kind == "get":
            path, result = args
            row = context.rows_by_path.get(path)
            if row:
                entry = row["_entry"]
                entry["done"] = 1
                success = result.get("code") in (100, 101)
                entry["outcome"] = "success" if success else "failed"
                row.update(donePages=1, status="finished" if success else "failed")
                self._qml("onOcrGet", path, result)
        elif kind == "segment_end":
            message = args[0]
            for row in context.rows:
                entry = row["_entry"]
                if entry["done"] == 0 or not message.startswith("[Success]"):
                    entry["outcome"] = "failed"
                    row.update(status="failed", message=message)
            self._active = None
            self._drive()
            return
        elif kind == "finalizing":
            context.phase = "finalizing"
            for row in context.rows:
                row["status"] = "finalizing"
        elif kind == "finished":
            message, artifacts = args
            for row in context.rows:
                entry = row["_entry"]
                if not message.startswith("[Success]") or entry["done"] == 0:
                    entry["outcome"] = "failed"
                success = entry["outcome"] == "success"
                row.update(status="finished" if success else "failed", message=message)
            self._store_session_artifacts(context.rows, artifacts, update_success=True)
            self._active = None
            self.outputList = []
            self._drive()
            return
        self._emit()

    def _store_attempt_artifacts(self, rows, artifacts):
        self._store_session_artifacts(rows, artifacts)

    def _store_session_artifacts(self, rows, artifacts, update_success=False):
        # 聚合文件的凭据每会话只留一份，个体文件按输入身份分桶，禁止 N×N 复制。
        from .batch_runtime import path_identity
        shared = tuple(item for item in artifacts if not item.get("sourcePath"))
        saved_shared = tuple(item for item in shared if item.get("saved"))
        by_source = {}
        for item in artifacts:
            if item.get("sourcePath"):
                identity = path_identity(item["sourcePath"])[0]
                by_source.setdefault(identity, []).append(item)
        for row in rows:
            individual = tuple(by_source.get(row["id"], ()))
            row["attemptArtifacts"] = individual
            row["_attemptArtifactsShared"] = shared
            if update_success and row["_entry"]["outcome"] == "success":
                saved = tuple(item for item in individual if item.get("saved"))
                if saved or saved_shared:
                    row["artifacts"] = saved
                    row["_artifactsShared"] = saved_shared

    def _stopping_rows(self):
        return tuple(self._session_rows) + super()._stopping_rows()

    def _on_stopped(self):
        owner, self._ocr_session = self._ocr_session, None
        rows, self._session_rows = tuple(self._session_rows), []
        self.outputList = []
        self.argd = None
        self.msnID = ""
        if owner and owner.session:
            cleanup = Attempt(owner.batch_id, owner.generation, owner.entry, rows,
                              owner.argd, session=owner.session, phase="finalizing")
            cleanup.cancelled.set()
            BatchPage._worker_end(self, cleanup, {}, "[Warning] 用户停止了批次。")

    def _on_batch_finished(self):
        self._qml("onOcrEnd", self._summary, self._batch_id)

    def msnPreview(self, path, argd):
        self._assert_main()
        token = self._preview_token = uuid4().hex
        generation = self._generation
        settings = dict(argd, **{"ocr.taskType": "batch"})
        info = {"argd": settings, "onGet": lambda info, item, result:
                self.callFunc(self._preview_result, token, generation, item["path"], result)}
        self._preview_id = MissionOCR.addMissionList(info, [{"path": path}])
        return self._preview_id

    def _preview_result(self, token, generation, path, result):
        if not self._closed and token == self._preview_token and generation == self._generation:
            self._qml("onPreview", path, result)

    def close(self):
        self._preview_token = ""
        if self._preview_id:
            MissionOCR.stopMissionList(self._preview_id)
        return super().close()
