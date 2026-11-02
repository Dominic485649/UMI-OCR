"""结构化文档异步 HTTP 接口，任务资源只在自己的工作目录内发布。"""
from __future__ import annotations
from ..utils.runtime_i18n import tr

from copy import deepcopy
import io
import json
import mimetypes
from pathlib import Path
import re
import shutil
import threading
import time
from uuid import uuid4
import zipfile

from bottle import request, HTTPResponse

from ..mission.backend_runtime import flatten_options
from .backend_router import backend_options, select_backend, available_backends
from .request_validation import validate_options, validate_page_range, validate_visual_budget
from .request_budgets import ByteBudget

JOB_ROOT = Path("temp_doc") / "structured-http" / uuid4().hex
MAX_JOBS = 64
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
MAX_JOB_BYTES = 128 * 1024 * 1024
MAX_RESERVED_JOB_BYTES = MAX_UPLOAD_BYTES + MAX_JOB_BYTES + 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_ASSET_BYTES = 16 * 1024 * 1024
RETENTION_SECONDS = 3 * 3600
SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
TERMINAL = {"succeeded", "partial", "failed", "cancelled"}
JOBS = {}
LOCK = threading.RLock()
BUDGET = ByteBudget(MAX_TOTAL_BYTES)


def _safe_path(path, root=None):
    path = Path(path).absolute()
    for parent in (path, *path.parents):
        if parent.exists() and (parent.is_symlink() or parent.is_junction()):
            raise ValueError(tr('任务路径不能包含链接或 junction。'))
    resolved = path.resolve()
    if root is not None and not resolved.is_relative_to(Path(root).resolve()):
        raise ValueError(tr('资源路径不属于当前任务。'))
    return resolved


def _error(message, code=804):
    return {"code": code, "data": str(message)}


def _payload():
    value = request.json
    if not isinstance(value, dict):
        raise ValueError(tr('请求必须为 JSON 对象。'))
    return value


class DocumentJob:
    def __init__(self, identifier, root, source, selected, options, page_range, timeout):
        self.identifier, self.root, self.source = identifier, root, source
        self.selected, self.options = selected, options
        self.page_range, self.timeout = page_range, timeout
        self.state, self.stage = "queued", tr('等待模型执行')
        self.result = None
        self.pages = {}
        self.assets = {}
        self._asset_paths = {}
        self.warnings = []
        self.created_at = self.updated_at = time.time()
        self.bytes = source.stat().st_size
        self.reserved_bytes = MAX_RESERVED_JOB_BYTES
        self.cancel_requested = False
        self.readers = 0
        self.lock = threading.RLock()

    def start(self):
        info = {"_reserved_msnID": self.identifier,
                "argd": {"document." + key: value for key, value in self.options.items()},
                "onStart": self._on_start, "onGet": self._on_get, "onEnd": self._on_end,
                "onProgress": self._on_progress, "onPartial": self._on_partial}
        item = {"path": str(self.source), "taskTimeoutSeconds": self.timeout,
                "assetOutputRoot": str(self.root / "assets")}
        if self.page_range:
            item["pageRange"] = self.page_range
        try:
            result = self.selected.manager.addMissionList(info, [item])
        except Exception as exc:
            result = f"[Error] {exc}"
        if result.startswith("[Error]"):
            self._on_end(info, result)
        return result

    def _on_start(self, *_):
        with self.lock:
            self.state, self.stage = "running", tr('准备输入')
            self.updated_at = time.time()

    def _on_progress(self, stage):
        with self.lock:
            self.stage = str(stage)
            self.updated_at = time.time()

    def _asset(self, raw_path):
        path = _safe_path(raw_path, self.root / "assets")
        if not path.is_file():
            raise ValueError(tr('结果资源不是普通文件。'))
        size = path.stat().st_size
        if size > MAX_ASSET_BYTES:
            raise ValueError(tr('单个结果资源超过大小限制。'))
        key = str(path)
        if key in self._asset_paths:
            return self._asset_paths[key]
        if len(self.assets) >= 512 or self.bytes + size > MAX_JOB_BYTES:
            raise ValueError(tr('任务结果资源超过预算。'))
        identifier = uuid4().hex
        self.assets[identifier] = path
        self._asset_paths[key] = identifier
        self.bytes += size
        return identifier

    def _sanitize(self, raw):
        value = deepcopy(raw)
        replacements = {}
        def collect(node):
            if isinstance(node, dict):
                path = node.get("path")
                if isinstance(path, str):
                    try:
                        asset_id = self._asset(path)
                        url = f"/api/document/assets/{self.identifier}/{asset_id}"
                        replacements[path] = url
                        replacements[Path(path).as_uri()] = url
                        node["assetId"], node["url"] = asset_id, url
                    except (ValueError, OSError) as exc:
                        # 源文档和其他任务路径不是可下载资源，不从任意路径复制。
                        if node.get("uri") or str(node.get("id", "")).startswith("asset-"):
                            self.warnings.append(str(exc))
                    node.pop("path", None)
                for child in list(node.values()):
                    collect(child)
            elif isinstance(node, list):
                for child in node:
                    collect(child)
        collect(value)
        sensitive_keys = {"path", "input_path", "logPath", "command", "source", "uri", "outputPath"}
        def clean(node):
            if isinstance(node, dict):
                return {key: clean(child) for key, child in node.items() if key not in sensitive_keys}
            if isinstance(node, list):
                return [clean(child) for child in node]
            if isinstance(node, str):
                for old, new in replacements.items():
                    node = node.replace(old, new)
                return re.sub(r"file://[^\s\"'<>\)]+", "", node)
            return node
        return clean(value)

    def _on_partial(self, event):
        if not isinstance(event, dict) or type(event.get("page")) is not int:
            return
        with self.lock:
            page = event["page"]
            self.pages[page] = self._sanitize(event.get("result", {}))
            self.warnings.extend(str(item) for item in event.get("warnings", []))
            if event.get("failed"):
                self.warnings.append(tr('第 {page} 页未完整处理。', page=page))
            self.updated_at = time.time()

    def _on_get(self, _info, _task, result):
        with self.lock:
            self.result = self._sanitize(result)
            self.warnings.extend(str(item) for item in result.get("warnings", []))
            self.updated_at = time.time()

    def _on_end(self, _info, message):
        with self.lock:
            if self.cancel_requested or str(message).startswith("[Warning]"):
                self.state = "cancelled"
            elif self.result is None:
                self.state = "partial" if self.pages else "failed"
                self.result = {"code": 902, "data": str(message)}
            else:
                code = self.result.get("code")
                metadata = self.result.get("metadata") or {}
                partial = bool(self.result.get("partial") or self.warnings or
                               metadata.get("partialBlocks") or metadata.get("failedPages"))
                if code in (100, 101):
                    self.state = "partial" if partial else "succeeded"
                else:
                    self.state = "partial" if self.pages else "failed"
            self._settle_budget()
            if self.warnings and self.state == "succeeded":
                self.state = "partial"
            self.updated_at = time.time()
        self.selected.close()

    def _settle_budget(self):
        # 执行时预留输入及输出上限，结束后按实际自有文件占用结算。
        try:
            actual = 0
            for path in self.root.rglob("*"):
                _safe_path(path, self.root)
                if path.is_file():
                    actual += path.stat().st_size
            if actual > self.reserved_bytes:
                self.warnings.append(tr('任务文件超过已预留空间预算。'))
                return
            BUDGET.release(self.reserved_bytes - actual)
            self.reserved_bytes = actual
            self.bytes = actual
        except (ValueError, OSError) as exc:
            self.warnings.append(str(exc))

    def snapshot(self, include_result=True):
        with self.lock:
            result = {"code": 100, "jobId": self.identifier, "backendId": self.selected.backend_id,
                      "state": self.state, "stage": self.stage,
                      "warnings": list(dict.fromkeys(self.warnings)),
                      "completedPages": len(self.pages), "createdAt": self.created_at,
                      "updatedAt": self.updated_at}
            if include_result:
                result["result"] = deepcopy(self.result)
                result["partialPages"] = deepcopy(list(self.pages.values()))
            return result

    def cancel(self):
        with self.lock:
            if self.state in TERMINAL:
                return
            self.cancel_requested = True
        self.selected.manager.stopMissionList(self.identifier)

    def export(self, kind):
        with self.lock:
            if self.state not in TERMINAL:
                raise ValueError(tr('任务尚未结束，请先读取部分结果或等待完成。'))
            pages = [deepcopy(value) for _, value in sorted(self.pages.items())]
            result = deepcopy(self.result or {})
            if self.state != "succeeded":
                result["partial"] = True
                result["partialPages"] = pages
                result["warnings"] = list(dict.fromkeys([*result.get("warnings", []), *self.warnings]))
            text = str(result.get("text") or "\n\n".join(str(page.get("text") or "") for page in pages))
            markdown = str(result.get("markdown") or "\n\n".join(str(page.get("markdown") or page.get("text") or "") for page in pages) or text)
            if kind == "txt":
                return text.encode("utf-8"), "text/plain; charset=utf-8", "document.txt"
            if kind == "md":
                return markdown.encode("utf-8"), "text/markdown; charset=utf-8", "document.md"
            if kind == "json":
                return json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"), "application/json", "document.json"
            if kind != "zip":
                raise ValueError(tr('format 必须为 txt、md、json 或 zip。'))
            stream = io.BytesIO()
            def relative_assets(node):
                if isinstance(node, dict):
                    return {key: relative_assets(value) for key, value in node.items()}
                if isinstance(node, list):
                    return [relative_assets(value) for value in node]
                if isinstance(node, str):
                    for asset_id, path in self.assets.items():
                        node = node.replace(f"/api/document/assets/{self.identifier}/{asset_id}",
                                            f"assets/{asset_id}{path.suffix.lower()}")
                return node
            markdown = relative_assets(markdown)
            result = relative_assets(result)
            with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("document.md", markdown)
                archive.writestr("document.txt", text)
                archive.writestr("document.json", json.dumps(result, ensure_ascii=False, indent=2))
                for asset_id, path in self.assets.items():
                    source = _safe_path(path, self.root / "assets")
                    archive.write(source, f"assets/{asset_id}{source.suffix.lower()}")
            data = stream.getvalue()
            if len(data) > MAX_JOB_BYTES:
                raise ValueError(tr('导出文件超过任务预算。'))
            return data, "application/zip", "document.zip"


def _lookup(identifier):
    if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{32}", identifier):
        raise ValueError(tr('jobId 无效。'))
    with LOCK:
        job = JOBS.get(identifier)
    if job is None:
        raise ValueError(tr('任务不存在或已过期。'))
    return job


def _cleanup():
    now = time.time()
    with LOCK:
        for identifier, job in tuple(JOBS.items()):
            with job.lock:
                if (job.state not in TERMINAL or job.readers or
                        now - job.updated_at < RETENTION_SECONDS):
                    continue
                root = _safe_path(job.root, JOB_ROOT)
                if root.name != identifier or not (root / ".http-document-job").is_file():
                    continue
                try:
                    shutil.rmtree(root)
                except OSError:
                    continue
                JOBS.pop(identifier, None)
                BUDGET.release(job.reserved_bytes)


def init(app):
    @app.route("/api/document/get_options")
    @app.route("/api/document/options")
    def options():
        try:
            backend = request.query.get("backendId", "current")
            return {"code": 100, "backends": available_backends("document"),
                    "options": flatten_options(backend_options("document", backend))}
        except ValueError as exc:
            return _error(exc)

    @app.route("/api/document/upload", method="POST")
    def upload():
        selected = None
        root = None
        reservation = 0
        try:
            _cleanup()
            item = request.files.get("file")
            if item is None:
                raise ValueError(tr('缺少上传文件 file。'))
            suffix = Path(str(item.raw_filename or "")).suffix.lower()
            if suffix not in SUFFIXES:
                raise ValueError(tr('不支持该文档格式。'))
            data = json.loads(request.forms.get("json") or "{}")
            if not isinstance(data, dict) or set(data) - {"backendId", "options", "pageRange", "taskTimeoutSeconds"}:
                raise ValueError(tr('上传参数必须是受支持的 JSON 对象。'))
            backend = data.get("backendId", "current")
            selected = select_backend("document", backend, isolated=True)
            schema = selected.local_options if selected.local_options is not None else backend_options("document", selected.backend_id)
            definitions = flatten_options(schema)
            parameters = validate_options(data.get("options", {}), definitions)
            pages = validate_page_range(data.get("pageRange"))
            timeout = data.get("taskTimeoutSeconds", 1800)
            if type(timeout) is not int or not 1 <= timeout <= 1800:
                raise ValueError(tr('taskTimeoutSeconds 必须为 1 到 1800 的整数。'))
            validate_visual_budget(selected.backend_id, selected.config, parameters.get("maxOutputTokens", 4096))
            with LOCK:
                if len(JOBS) >= MAX_JOBS:
                    raise ValueError(tr('HTTP 文档任务或临时空间预算已满。'))
                BUDGET.take(MAX_RESERVED_JOB_BYTES)
                reservation = MAX_RESERVED_JOB_BYTES
                identifier = uuid4().hex
                root = _safe_path(JOB_ROOT / identifier, JOB_ROOT)
                root.mkdir(parents=True, exist_ok=False)
                (root / ".http-document-job").write_text(identifier, encoding="ascii")
                (root / "assets").mkdir()
                source = root / ("input" + suffix)
                size = 0
                with source.open("xb") as stream:
                    while True:
                        chunk = item.file.read(1024 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > MAX_UPLOAD_BYTES:
                            raise ValueError(tr('上传文件超过大小预算。'))
                        stream.write(chunk)
                if not size:
                    raise ValueError(tr('上传文件为空。'))
                job = DocumentJob(identifier, root, source, selected, parameters, pages, timeout)
                JOBS[identifier] = job
                reservation = 0  # 预算所有权已交给 job，结束或回收时结算。
            result = job.start()
            if result.startswith("[Error]"):
                return _error(result, 902)
            selected = None
            return {"code": 100, "data": identifier, "jobId": identifier}
        except Exception as exc:
            if selected:
                selected.close()
            cleaned = root is None
            if root is not None:
                with LOCK:
                    owned = root.name not in JOBS
                if owned:
                    try:
                        shutil.rmtree(_safe_path(root, JOB_ROOT))
                        cleaned = True
                    except (OSError, ValueError):
                        cleaned = False
            if reservation and cleaned:
                BUDGET.release(reservation)
            return _error(exc)

    @app.route("/api/document/result", method="POST")
    def result():
        try:
            data = _payload()
            _cleanup()
            return _lookup(data.get("jobId", data.get("id"))).snapshot(data.get("includeResult", True) is not False)
        except ValueError as exc:
            return _error(exc)

    @app.route("/api/document/cancel", method="POST")
    def cancel():
        try:
            data = _payload()
            job = _lookup(data.get("jobId", data.get("id")))
            job.cancel()
            return job.snapshot(False)
        except ValueError as exc:
            return _error(exc)

    @app.route("/api/document/download", method="POST")
    def download():
        try:
            data = _payload()
            job = _lookup(data.get("jobId", data.get("id")))
            payload, content_type, name = job.export(data.get("format", "zip"))
            return HTTPResponse(payload, headers={"Content-Type": content_type,
                                "Content-Disposition": f'attachment; filename="{name}"'})
        except ValueError as exc:
            return _error(exc)

    @app.route("/api/document/assets/<job_id>/<asset_id>")
    def asset(job_id, asset_id):
        try:
            job = _lookup(job_id)
            with job.lock:
                path = job.assets.get(asset_id)
                if path is None:
                    raise ValueError(tr('资源不存在。'))
                source = _safe_path(path, job.root / "assets")
                if source.stat().st_size > MAX_ASSET_BYTES:
                    raise ValueError(tr('资源超过大小预算。'))
                payload = source.read_bytes()
                job.updated_at = time.time()
            content_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
            if content_type not in {"image/png", "image/jpeg", "image/webp", "image/bmp", "image/gif"}:
                content_type = "application/octet-stream"
            return HTTPResponse(payload, headers={"Content-Type": content_type, "X-Content-Type-Options": "nosniff"})
        except (ValueError, OSError) as exc:
            return HTTPResponse(str(exc), status=404)
