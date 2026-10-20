# ========================================
# =============== 批量文档页 ===============
# ========================================

import os
import threading
import time

from .batch_runtime import Attempt, BatchPage, OutputSession
from ..mission.mission_doc import MissionDOC
from ..utils import utils
from ..ocr.output import Output


class BatchDOC(BatchPage):
    document = True

    @property
    def _manager(self):
        return MissionDOC

    def msnDocs(self, docs, argd):
        return self._start_batch(docs, argd)

    def _initOutputList(self, argd, path, pageRange, pageCount, password="", attempt_id=""):
        if argd["mission.dirType"] == "source":
            output_dir = os.path.dirname(path)
        else:
            output_dir = os.path.abspath(argd["mission.dir"])
            os.makedirs(output_dir, exist_ok=True)
        timestamp = time.time()
        datetime_user = argd["mission.datetimeFormat"].replace("%unix", str(timestamp))
        datetime_user = time.strftime(datetime_user, time.localtime(timestamp))
        name = argd["mission.fileNameFormat"].replace("%date", datetime_user)
        range_text = ""
        if pageRange[1] - pageRange[0] + 1 < pageCount:
            range_text = (f"(p{pageRange[0]})" if pageRange[0] == pageRange[1]
                          else f"(p{pageRange[0]}-{pageRange[1]})")
        name = name.replace("%range", range_text)
        name = name.replace("%name", os.path.splitext(os.path.basename(path))[0])
        if not utils.allowedFileName(name):
            raise ValueError(f"输出文件名【{name}】含有不允许的字符。")
        # 所有格式共享完整 attempt UUID，包含首轮，禁止覆盖旧尝试的 TXT/CSV。
        if attempt_id:
            name += "." + attempt_id
        output_argd = {
            "outputDir": output_dir, "outputDirType": argd["mission.dirType"],
            "outputFileName": name, "startDatetime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp)),
            "ignoreBlank": argd["mission.ignoreBlank"], "originPath": path, "password": password,
            "attemptPrefix": bool(attempt_id),
        }
        factories = [(key[len("mission.filesType."):], Output[key[len("mission.filesType."):]])
                     for key, enabled in argd.items() if key.startswith("mission.filesType.") and enabled]
        return OutputSession(factories, output_argd)

    def _advance(self):
        if self._active:
            if self._active.phase == "prepared":
                self._submit_document(self._active)
            return
        if not self._pending:
            self._finish_batch()
            return
        if self._paused:
            return
        identity = self._pending.pop(0)
        row = self._records[identity]
        entry = row["_entry"]
        entry["outcome"] = "active"
        context = Attempt(self._batch_id, self._generation, entry, (row,), entry["argd"])
        self._active = context
        row["status"] = "preparing"
        self._start_worker(self._prepare_worker, context)

    def _prepare_worker(self, context):
        if context.cancelled.is_set():
            return
        metadata = context.entry["metadata"]
        error = ""
        try:
            start, end, count = metadata["range_start"], metadata["range_end"], metadata["page_count"]
            if start < 1 or end < start or end > count:
                raise ValueError("识别页码范围不合法。")
            context.session = self._initOutputList(context.argd, metadata["path"], [start, end], count,
                                                   metadata["password"], context.attempt_id)
            if context.session.errors:
                error = "[Error] " + "\n".join(context.session.errors)
        except Exception as exc:
            error = f"[Error] 无法创建输出器：{exc}"
        if context.cancelled.is_set():
            self._worker_end(context, {}, "[Warning] 任务已停止。")
        else:
            self.callFunc(self._prepared, context, error)

    def _prepared(self, context, error):
        self._assert_main()
        if not self._valid_context(context):
            context.cancelled.set()
            self._worker_end(context, {}, "[Warning] 任务已停止。")
            return
        context.phase = "prepared"
        if error:
            self._worker_end(context, {}, error)
        elif not self._paused:
            self._submit_document(context)
        self._emit()

    def _submit_document(self, context):
        if not self._valid_context(context) or self._paused:
            return
        context.phase = "active"
        row = context.rows[0]
        row["status"] = "active"
        metadata = context.entry["metadata"]
        # 配置、回调和输出器都属于本次上下文，不再读取可被下一批覆盖的全局 ID。
        doc_argd = {key: value for key, value in context.argd.items()
                    if key.startswith(("ocr.", "doc.", "tbpu."))}
        info = {
            "_reserved_msnID": context.mission_id, "argd": doc_argd,
            "onStart": lambda info: self.callFunc(self._event, context, "start", info.get("msnID", "")),
            "onReady": lambda info, page: None,
            "onGet": lambda info, page, result: self._worker_get(context, info, page, result),
            "onEnd": lambda info, message: self._worker_end(context, info, message),
        }
        self._submit(context, lambda: MissionDOC.addMission(
            info, metadata["path"], [metadata["range_start"], metadata["range_end"]],
            password=metadata["password"]))

    def _worker_get(self, context, info, page, result):
        # 该集合只保护本次输出去重；队列/页数统计仍由主线程处理。
        with context.io_lock:
            if context.cancelled.is_set() or context.end_requested or page in context.seen:
                return
            context.seen.add(page)
            result = dict(result, page=page + 1, fileName=str(page + 1), path=context.entry["metadata"]["path"])
            if context.session:
                context.session.print(result)
        self.callFunc(self._event, context, "get", info.get("msnID", ""), page + 1, result)

    def _handle_event(self, context, kind, *args):
        row = context.rows[0]
        entry = context.entry
        if kind == "start":
            self._qml("onDocStart", row["path"])
        elif kind == "get":
            page, result = args
            entry["done"] += 1
            row["donePages"] = entry["done"]
            if result.get("code") not in (100, 101):
                entry["pageError"] = True
            self._qml("onDocGet", row["path"], page, result)
        elif kind == "finalizing":
            context.phase = "finalizing"
            row["status"] = "finalizing"
        elif kind == "finished":
            message, artifacts = args
            success = (message.startswith("[Success]") and not entry.get("pageError")
                       and entry["done"] == entry["budget"])
            if message.startswith("[Success]") and not success:
                message = "[Error] 文档存在识别失败或未完成的页面。"
            entry["outcome"] = "success" if success else "failed"
            row.update(status="finished" if success else "failed", message=message,
                       attemptArtifacts=artifacts)
            if success:
                saved = [artifact for artifact in artifacts if artifact.get("saved")]
                if saved:
                    row["artifacts"] = saved
            self._active = None
            # 兼容旧单文档事件，整批完成只由 onBatchState 判定，避免导入边界误报。
            self._qml("onDocEnd", row["path"], message, False)
            self._drive()
            return
        self._emit()
