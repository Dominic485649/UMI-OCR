"""声明式模型下载：仅写当前已发现插件的 model/，不导入插件或启动模型。"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import threading
import time
import urllib.parse
import urllib.request
import uuid


MAX_RESOURCE_BYTES = 4 * 1024**3
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
RESOURCE_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}\Z")


class DownloadError(ValueError):
    pass


class DownloadCancelled(DownloadError):
    pass


def relative_name(value):
    if not isinstance(value, str) or not value:
        raise DownloadError("模型文件名不能为空。")
    parts = value.split("/")
    if any(not part or part in {".", ".."} or part.endswith((".", " "))
           or any(c in '\\:<>"|?*' or ord(c) < 32 for c in part)
           or re.fullmatch(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part, re.I)
           for part in parts):
        raise DownloadError("模型路径不是安全的相对路径。")
    return PurePosixPath(value)


def https_url(value):
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.port not in (None, 443) or parsed.fragment):
        raise DownloadError("模型必须使用无凭据的 HTTPS 直链。")
    return parsed


def validate_resources(value):
    """发现阶段只检查有限纯数据；不触网、不读取权重。"""
    if not isinstance(value, dict) or len(value) > 16:
        raise DownloadError("model_downloads 必须是至多 16 项的对象。")
    for resource_id, spec in value.items():
        if not RESOURCE_ID.fullmatch(resource_id) or not isinstance(spec, dict):
            raise DownloadError("模型资源 ID 无效。")
        kind = spec.get("kind")
        destination = relative_name(spec.get("destination"))
        if destination.parts[0].startswith(".") or kind not in {"file", "directory"}:
            raise DownloadError("模型目标或类型无效。")
        files = spec.get("files")
        if not isinstance(files, list) or not 1 <= len(files) <= 16:
            raise DownloadError("模型文件清单无效。")
        seen, total = set(), 0
        for item in files:
            if not isinstance(item, dict):
                raise DownloadError("模型文件记录无效。")
            name = relative_name(item.get("name"))
            key = str(name).casefold()
            if key in seen or any(key.startswith(other + "/") or other.startswith(key + "/") for other in seen):
                raise DownloadError("模型文件名重复或冲突。")
            seen.add(key)
            if type(item.get("bytes")) is not int or not 0 < item["bytes"] <= MAX_RESOURCE_BYTES:
                raise DownloadError("模型文件大小无效。")
            total += item["bytes"]
            if not isinstance(item.get("sha256"), str) or not SHA256.fullmatch(item["sha256"]):
                raise DownloadError("模型缺少锁定的 SHA-256。")
            https_url(item.get("url", ""))
        if total > MAX_RESOURCE_BYTES or (kind == "file" and (len(files) != 1 or str(destination) != files[0]["name"])):
            raise DownloadError("模型资源超限或单文件目标不一致。")
    return value


def plain_path(path):
    path = Path(path).absolute()
    if ".." in path.parts or str(path).startswith(("\\\\", "//")):
        raise DownloadError("模型路径不能越界或使用网络目录。")
    for item in reversed((path, *path.parents)):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise DownloadError("模型目录不能经过链接或 junction：" + str(item))
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise DownloadError("模型文件不能是硬链接：" + str(item))
        if item != path and not stat.S_ISDIR(info.st_mode):
            raise DownloadError("模型路径的父项不是目录：" + str(item))
    return path


class SecureRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        old, new = https_url(request.full_url), https_url(newurl)
        hosts = ("huggingface.co", "hf.co", "xethub.hf.co")
        official = old.hostname == "huggingface.co" or any(old.hostname.endswith("." + h) or old.hostname == h for h in hosts)
        permitted = new.hostname == old.hostname or official and any(new.hostname == h or new.hostname.endswith("." + h) for h in hosts)
        if not permitted:
            raise DownloadError("下载被重定向到未允许的域名。")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def digest_file(path, cancelled):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            if cancelled.is_set():
                raise DownloadCancelled("下载已取消。")
            digest.update(chunk)
    return digest.hexdigest()


def check_file(path, item, cancelled):
    plain_path(path)
    if not path.is_file() or path.stat().st_size != item["bytes"] or digest_file(path, cancelled) != item["sha256"]:
        raise DownloadError("模型文件大小或 SHA-256 不匹配：" + str(path))
    with path.open("rb") as stream:
        if path.suffix.lower() == ".gguf" and stream.read(4) != b"GGUF":
            raise DownloadError("下载内容不是 GGUF 模型。")
    if path.name == "inference.json":
        if path.stat().st_size > 16 * 1024**2:
            raise DownloadError("版面模型 JSON 超过大小限制。")
        with path.open("r", encoding="utf-8") as stream:
            if not isinstance(json.load(stream), dict):
                raise DownloadError("版面模型 JSON 必须是对象。")


def download_resource(plugin_root, spec, cancelled, progress, *, opener=None):
    """文件组通过全部校验后才发布；既有用户模型不会被覆盖。"""
    validate_resources({"resource": spec})
    plugin_root = plain_path(plugin_root)
    if not plugin_root.is_dir():
        raise DownloadError("当前插件安装目录不存在。")
    model_root = plain_path(plugin_root / "model")
    model_root.mkdir(exist_ok=True)
    destination = plain_path(model_root / spec["destination"])
    total = sum(item["bytes"] for item in spec["files"])

    def files_at(root):
        return [(root if spec["kind"] == "file" else root / item["name"], item) for item in spec["files"]]

    if destination.exists():
        for path, item in files_at(destination):
            check_file(path, item, cancelled)
        progress(total, total)
        return {"path": str(destination), "reused": True}
    free = shutil.disk_usage(model_root).free
    if free < total + 64 * 1024**2:
        raise DownloadError("模型目录所在磁盘空间不足（另需预留 64 MiB）。")
    pending = plain_path(model_root / (".download-" + uuid.uuid4().hex))
    pending.mkdir()
    payload = pending / "payload"
    payload.mkdir()
    opener = opener or urllib.request.build_opener(SecureRedirect())
    completed, last_notice = 0, 0.0
    try:
        for item in spec["files"]:
            if cancelled.is_set():
                raise DownloadCancelled("下载已取消。")
            output = payload / item["name"]
            output.parent.mkdir(parents=True, exist_ok=True)
            request = urllib.request.Request(item["url"], headers={"User-Agent": "Umi-OCR-model-download/1", "Accept-Encoding": "identity"})
            received = 0
            with opener.open(request, timeout=20) as response, output.open("xb") as stream:
                if response.status != 200:
                    raise DownloadError("模型服务器未返回完整文件。")
                https_url(response.geturl())
                length = response.headers.get("Content-Length")
                if length is not None and int(length) != item["bytes"]:
                    raise DownloadError("模型服务器返回的文件大小与锁定记录不一致。")
                if response.headers.get("Content-Encoding", "identity").lower() not in {"identity", ""}:
                    raise DownloadError("模型服务器返回了未允许的内容编码。")
                while True:
                    if cancelled.is_set():
                        raise DownloadCancelled("下载已取消。")
                    chunk = response.read(min(256 * 1024, item["bytes"] - received + 1))
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > item["bytes"]:
                        raise DownloadError("模型下载超过锁定大小。")
                    stream.write(chunk)
                    now = time.monotonic()
                    if now - last_notice >= 0.15:
                        progress(completed + received, total)
                        last_notice = now
                stream.flush()
                os.fsync(stream.fileno())
            check_file(output, item, cancelled)
            completed += received
        if cancelled.is_set():
            raise DownloadCancelled("下载已取消。")
        plain_path(destination)
        if destination.exists():
            raise DownloadError("目标已存在，不覆盖用户模型：" + str(destination))
        if spec["kind"] == "file":
            # 同卷硬链接的排他创建不会覆盖竞态出现的目标；移除暂存后只剩一个链接。
            original = payload / spec["files"][0]["name"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.link(original, destination)
            original.unlink()
        else:
            # Windows rename 不替换既有目录，整组模型在校验后一次可见。
            payload.rename(destination)
        progress(total, total)
        return {"path": str(destination), "reused": False}
    finally:
        # 只清理本函数创建的具名空白任务目录，绝不沿链接递归删除。
        plain_path(pending)
        if pending.exists():
            for current, dirs, files in os.walk(pending, followlinks=False):
                for name in dirs + files:
                    plain_path(Path(current) / name)
            shutil.rmtree(pending)


class DownloadManager:
    def __init__(self, lookup, notify, submit):
        self.lookup, self.notify, self.submit = lookup, notify, submit
        self._lock = threading.Lock()
        self._jobs = {}
        self._closed = False

    def info(self, plugin_id, resource_id):
        root, resources = self.lookup(plugin_id)
        validate_resources(resources)
        spec = resources.get(resource_id)
        if spec is None:
            raise DownloadError("当前插件没有声明此模型下载。")
        target = plain_path(plain_path(root) / "model" / spec["destination"])
        return root, spec, {"title": spec.get("title", resource_id), "bytes": sum(item["bytes"] for item in spec["files"]),
                            "path": str(target), "urls": [item["url"] for item in spec["files"]]}

    def start(self, request_id, plugin_id, resource_id):
        key = (plugin_id, resource_id)
        try:
            if not isinstance(request_id, str) or not RESOURCE_ID.fullmatch(request_id):
                raise DownloadError("下载请求 ID 无效。")
            root, spec, info = self.info(plugin_id, resource_id)
            with self._lock:
                if self._closed or key in self._jobs:
                    raise DownloadError("此模型正在下载，或程序正在退出。")
                cancelled = threading.Event()
                self._jobs[key] = (request_id, cancelled)
        except Exception as exc:
            self.notify(request_id, {"state": "failed", "message": str(exc)})
            return

        def run():
            try:
                self.notify(request_id, {"state": "running", **info, "received": 0, "total": info["bytes"]})
                result = download_resource(root, spec, cancelled,
                    lambda received, total: self.notify(request_id, {"state": "running", "received": received, "total": total}))
                self.notify(request_id, {"state": "completed", **result})
            except DownloadCancelled as exc:
                self.notify(request_id, {"state": "cancelled", "message": str(exc)})
            except Exception as exc:
                self.notify(request_id, {"state": "failed", "message": str(exc), "path": info["path"]})
            finally:
                with self._lock:
                    self._jobs.pop(key, None)
        try:
            self.submit(run)
        except Exception as exc:
            with self._lock:
                self._jobs.pop(key, None)
            self.notify(request_id, {"state": "failed", "message": str(exc)})

    def cancel(self, request_id):
        with self._lock:
            for current_id, cancelled in self._jobs.values():
                if request_id == current_id:
                    cancelled.set()

    def close(self):
        with self._lock:
            self._closed = True
            for _, cancelled in self._jobs.values():
                cancelled.set()
