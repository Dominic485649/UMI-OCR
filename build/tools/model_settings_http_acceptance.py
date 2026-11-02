"""Real-package, real-socket model-settings acceptance (GPU opt-in only).

Real execution is pinned to UmiOCR-data/runtime/python.exe (CPython 3.13.16),
with -I -B -X utf8, and all product/dependency modules must come from the candidate.
Without --execute-gpu this prints a plan and imports no product/Qt/model code. --work and --audit must be NEW, disjoint paths
under this project's build directory. No existing service is stopped/adopted.
The real execution uses transparent observations/scheduling gates, never fake
model responses; every result under acceptance comes through urllib + TCP.
"""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import ctypes
from dataclasses import dataclass, field
import hashlib
import io
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import traceback
from urllib import error, parse, request
from uuid import uuid4
import zipfile
import zlib

PROJECT = Path(__file__).resolve().parents[2]
SCENARIOS = ["package-provenance", "backend-discovery", "invalid-options-and-capability",
             "cuda-vl-current-ocr", "instance-reuse", "cross-backend-serialization",
             "legacy-doc-cbz-upload-result-download-cancel", "structured-document-exports",
             "queued-target-cancellation", "real-partial-active-cancellation-and-export",
             "real-deadline-failure-not-success", "resource-boundaries", "owned-process-cleanup"]
MAX_RESPONSE = 32 * 1024 * 1024


class AcceptanceError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise AcceptanceError(message)


def safe_path(path):
    path = Path(path).absolute()
    for parent in (path, *path.parents):
        if parent.exists():
            require(not parent.is_symlink() and not getattr(parent, "is_junction", lambda: False)(),
                    f"Links/junctions are forbidden: {parent}")
    return path.resolve()


def inside(path, root):
    return safe_path(path).is_relative_to(safe_path(root))


def validate_paths(root, work, audit):
    root, work, audit = map(safe_path, (root, work, audit))
    require(root.is_dir(), "Candidate root does not exist")
    build = PROJECT / "build"
    for path in (work, audit):
        require(path.is_relative_to(build.resolve()) and path != build.resolve(),
                "Work and audit must be below this project's build directory")
        require(not path.exists(), f"Refusing to overwrite an existing path: {path}")
        require(not path.is_relative_to(root) and not root.is_relative_to(path),
                "Candidate and test output paths must not overlap")
    require(not work.is_relative_to(audit) and not audit.is_relative_to(work),
            "Work and audit must be disjoint")
    return root, work, audit


def candidate_python(root):
    root = safe_path(root)
    data_root = root if root.name == "UmiOCR-data" else root / "UmiOCR-data"
    executable = safe_path(data_root / "runtime" / "python.exe")
    require(executable.is_file() and executable.is_relative_to(root),
            "Candidate must supply UmiOCR-data/runtime/python.exe; no system interpreter fallback")
    return executable


def trusted_document_fixture(path):
    """复用已固定的非敏感无文本层PDF，只读真实文件及其原始预期，不生成新PDF。"""
    if path is None:
        return None
    manifest = safe_path(path)
    require(manifest.is_file() and manifest.stat().st_size <= 2 * 1024 * 1024, "Invalid document fixture manifest")
    document = json.loads(manifest.read_text(encoding="utf-8"))["document"]
    source = safe_path(document["path"])
    require(source.parent == manifest.parent and source.suffix.lower() == ".pdf" and source.is_file(),
            "Document fixture must be the manifest's adjacent PDF")
    require(0 < source.stat().st_size <= 64 * 1024 * 1024 and sha256_file(source) == document.get("sha256"),
            "Document fixture bytes differ from their pinned SHA256")
    require(document.get("pageRange") == [2, 2] and document.get("expectedPages") == [2]
            and document.get("size") == [1100, 1500], "Unexpected selected-page fixture")
    truth = document.get("truth")
    require(isinstance(truth, list) and len(truth) == 22 and all(isinstance(row, dict)
            and isinstance(row.get("token"), str) and row["token"].startswith("PAGE2") for row in truth),
            "Document fixture lacks the original selected-page identifiers")
    tokens = [row["token"] for row in truth]
    require(len(set(tokens)) == len(tokens), "Repeated document fixture identifiers")
    return {"path": str(source), "sha256": document["sha256"], "manifest": str(manifest),
            "manifestSha256": sha256_file(manifest), "pageRange": [2, 2], "expectedPages": [2],
            "size": [1100, 1500], "tokens": tokens}


def pdf_http_metrics(result, fixture):
    """只核对真实HTTP返回的原页号、固定标识和公开页界，不声称通用OCR准确率。"""
    import math
    require(isinstance(result, dict) and result.get("code") == 100, "PDF result is not successful")
    data = result.get("data") or {}
    pages, blocks = data.get("pages") or [], data.get("blocks") or []
    require([page.get("page") for page in pages] == fixture["expectedPages"], "HTTP PDF lost original selected page")
    text = re.sub(r"\s+", "", "\n".join(str(block.get("content", "")) for block in blocks))
    hits = [token for token in fixture["tokens"] if token in text]
    require(len(hits) == len(fixture["tokens"]), "HTTP PDF omitted selected-page identifiers")
    require(bool(blocks), "HTTP PDF has no recognized blocks")
    for block in blocks:
        points = block.get("polygon") or block.get("bbox") or []
        if len(points) == 4 and all(isinstance(value, (int, float)) for value in points):
            x1, y1, x2, y2 = points
            points = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
        require(len(points) >= 3 and all(isinstance(point, (list, tuple)) and len(point) == 2
                and all(isinstance(value, (int, float)) and math.isfinite(value) for value in point)
                and 0 <= point[0] <= fixture["size"][0] and 0 <= point[1] <= fixture["size"][1] for point in points),
                "HTTP PDF exposes coordinates outside the actual page")
    return {"expectedIdentifiers": len(fixture["tokens"]), "identifierHits": len(hits),
            "pages": fixture["expectedPages"], "coordinatesBounded": True,
            "scope": "real uploaded PDF, original selected page, known identifiers and mapped page bounds"}


def production_worker_command(args, executable, root, work, audit, token):
    command = [str(executable), "-I", "-B", "-X", "utf8", str(Path(__file__).resolve()),
               "--root", str(root), "--work", str(work), "--audit", str(audit),
               "--model-inputs", str(safe_path(args.model_inputs)), "--execute-gpu",
               "--deadline-seconds", str(args.deadline_seconds), "--worker-token", token]
    if getattr(args, "document_fixture", None) is not None:
        command += ["--document-fixture", str(safe_path(args.document_fixture))]
    return command


def isolated_worker_environment(work, inherited=None):
    """All explicit/fallback caches belong to this NEW work; never clear user caches."""
    work = safe_path(work)
    profile, cache = work / "isolated-profile", work / "cache"
    paths = {
        "TEMP": work / "temporary", "TMP": work / "temporary", "TMPDIR": work / "temporary",
        "CUDA_CACHE_PATH": cache / "cuda",
        "HF_HOME": cache / "huggingface", "HF_HUB_CACHE": cache / "huggingface/hub",
        "HUGGINGFACE_HUB_CACHE": cache / "huggingface/hub",
        "HF_DATASETS_CACHE": cache / "huggingface/datasets", "TRANSFORMERS_CACHE": cache / "huggingface/transformers",
        "PADDLE_HOME": cache / "paddle", "PADDLE_PDX_CACHE_HOME": cache / "paddlex", "PADDLEX_HOME": cache / "paddlex",
        "XDG_CACHE_HOME": cache, "QML_DISK_CACHE_PATH": cache / "qml",
        "QT_OPENGL_SHADER_CACHE_DIR": cache / "qt-opengl",
        "HOME": profile, "USERPROFILE": profile,
        "APPDATA": profile / "AppData/Roaming", "LOCALAPPDATA": profile / "AppData/Local",
    }
    overrides = {key: str(path) for key, path in paths.items()}
    overrides.update({"HF_HUB_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                      "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True", "QML_DISABLE_DISK_CACHE": "1"})
    if os.name == "nt":
        overrides["HOMEDRIVE"], overrides["HOMEPATH"] = profile.drive, str(profile)[len(profile.drive):]
    environment = dict(os.environ if inherited is None else inherited)
    environment.update(overrides)
    # Do not allow inherited proxy settings to redirect localhost model calls.
    for key in tuple(environment):
        if key.lower() in {"http_proxy", "https_proxy", "all_proxy"}:
            environment.pop(key)
    environment["NO_PROXY"] = "127.0.0.1,localhost"
    return environment, overrides, paths


def prepare_worker_environment(work):
    environment, overrides, paths = isolated_worker_environment(work)
    for path in set(paths.values()):
        require(inside(path, work), "Worker cache escaped this round's work")
        safe_path(path).mkdir(parents=True, exist_ok=True)
    return environment, overrides


def verify_worker_environment(work):
    _environment, expected, _paths = isolated_worker_environment(work)
    require(all(os.environ.get(key) == value for key, value in expected.items()),
            "Worker did not inherit its isolated temporary/cache environment")
    import tempfile
    require(inside(tempfile.gettempdir(), work), "Python temporary directory escaped this round's work")
    return {"overrides": expected, "pythonTemporaryDirectory": tempfile.gettempdir(),
            "existingUserCachesDeleted": False,
            "cacheCleanupClaim": "none; this tool never clears external system/user caches"}


def write_json_new(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def trusted_model_inputs(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    hashes = value.get("sha256")
    require(isinstance(hashes, dict) and hashes, "model-inputs must contain sha256 mappings")
    verified = {}
    for name, expected in hashes.items():
        source = safe_path(name)
        require(source.is_file() and re.fullmatch(r"[a-fA-F0-9]{64}", str(expected)),
                "Invalid trusted model input")
        actual = sha256_file(source)
        require(actual.lower() == expected.lower(), f"Model hash mismatch: {source.name}")
        verified[source] = actual
    gguf = [p for p in verified if p.suffix.lower() == ".gguf" and "mmproj" not in p.name.lower()]
    projector = [p for p in verified if p.suffix.lower() == ".gguf" and "mmproj" in p.name.lower()]
    layouts = [p for p in verified if p.name == "inference.pdiparams"]
    require(len(gguf) == len(projector) == len(layouts) == 1, "Ambiguous GGUF/projector/layout inputs")
    require(layouts[0].with_suffix(".json") in verified, "Layout JSON is not hash-verified")
    return {"model": str(gguf[0]), "projector": str(projector[0]),
            "layout": str(layouts[0].parent), "verified": {str(p): h for p, h in verified.items()}}


# Deliberately plain bitmap glyphs: no fonts, screenshots, personal files or PDF.
GLYPHS = {
    "0": "01110/10001/10011/10101/11001/10001/01110", "1": "00100/01100/00100/00100/00100/00100/01110",
    "2": "01110/10001/00001/00010/00100/01000/11111", "3": "11110/00001/00001/01110/00001/00001/11110",
    "4": "00010/00110/01010/10010/11111/00010/00010", "5": "11111/10000/10000/11110/00001/00001/11110",
    "6": "01110/10000/10000/11110/10001/10001/01110", "7": "11111/00001/00010/00100/01000/01000/01000",
    "8": "01110/10001/10001/01110/10001/10001/01110", "9": "01110/10001/10001/01111/00001/00001/01110",
    "R": "11110/10001/10001/11110/10100/10010/10001", "O": "01110/10001/10001/10001/10001/10001/01110",
    "W": "10001/10001/10001/10101/10101/10101/01010", " ": "00000/00000/00000/00000/00000/00000/00000",
}


def countable_png(rows=3, scale=6):
    require(1 <= rows <= 60 and 2 <= scale <= 8, "Fixture dimensions out of bounds")
    width, height = 720, 40 + rows * (7 * scale + 24)
    pixels = bytearray(b"\xff" * width * height * 3)
    for index in range(rows):
        text = f"ROW {index + 1:02d} 12345"
        for column, char in enumerate(text):
            for y, line in enumerate(GLYPHS[char].split("/")):
                for x, bit in enumerate(line):
                    if bit == "1":
                        for dy in range(scale):
                            for dx in range(scale):
                                at = ((24 + index * (7 * scale + 24) + y * scale + dy) * width
                                      + 24 + column * 6 * scale + x * scale + dx) * 3
                                pixels[at:at + 3] = b"\x00\x00\x00"
    raw = b"".join(b"\x00" + pixels[y * width * 3:(y + 1) * width * 3] for y in range(height))
    def chunk(kind, content):
        return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", zlib.crc32(kind + content) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def png_cbz(png, pages=2):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_STORED) as archive:
        for index in range(pages):
            archive.writestr(f"page-{index + 1:03d}.png", png)
    return stream.getvalue()


def multipart(fields, filename, content, content_type):
    require(not any(char in filename for char in '\r\n"\\/'), "Unsafe fixture filename")
    boundary = "UmiAcceptance" + uuid4().hex
    parts = []
    for name, value in fields.items():
        require(re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", name), "Unsafe form field")
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n').encode("utf-8"))
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                  f'Content-Type: {content_type}\r\n\r\n').encode("utf-8") + content + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def text_from(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(text_from(item) for item in value)
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"]
        if isinstance(value.get("markdown"), str):
            return value["markdown"]
        return "\n".join(text_from(value[key]) for key in ("data", "pages", "blocks", "partialPages", "result") if key in value)
    return ""


def require_countable(value, expected=3):
    text = re.sub(r"\s+", "", text_from(value))
    count = text.count("12345")
    require(count >= expected, f"Countable fixture text missing: expected >= {expected}, got {count}")
    return {"expectedRows": expected, "recognizedTokens": count}


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AcceptanceError("Unexpected HTTP redirect: " + newurl)


class HttpClient:
    def __init__(self, port, deadline, audit=None, invariant=None):
        self.base = f"http://127.0.0.1:{int(port)}"
        self.deadline, self.audit, self.invariant = deadline, audit, invariant
        self.opener = request.build_opener(request.ProxyHandler({}), NoRedirect())
        self.lock, self.sequence = threading.Lock(), 0

    def local_url(self, url):
        parsed = parse.urlsplit(url if "://" in url else self.base + url)
        base = parse.urlsplit(self.base)
        require(parsed.scheme == "http" and parsed.hostname == "127.0.0.1" and parsed.port == base.port
                and not parsed.username and not parsed.password and not parsed.fragment,
                "Only this driver's loopback listener may be requested")
        return parse.urlunsplit((parsed.scheme, parsed.netloc, parse.quote(parsed.path, safe="/%"), parsed.query, ""))

    def call(self, path, *, data=None, body=None, content_type=None, method=None):
        remaining = self.deadline - time.monotonic()
        require(remaining > 0, "Acceptance deadline exceeded")
        if data is not None:
            body, content_type = json.dumps(data, ensure_ascii=True).encode("ascii"), "application/json"
        headers = {"Content-Type": content_type} if content_type else {}
        req = request.Request(self.local_url(path), data=body, headers=headers, method=method or ("POST" if body is not None else "GET"))
        start = time.monotonic()
        try:
            with self.opener.open(req, timeout=min(300, remaining)) as response:
                status, payload, response_headers = response.status, response.read(MAX_RESPONSE + 1), dict(response.headers)
        except error.HTTPError as exc:
            status, payload, response_headers = exc.code, exc.read(MAX_RESPONSE + 1), dict(exc.headers)
        require(len(payload) <= MAX_RESPONSE, "HTTP response exceeds acceptance budget")
        if self.invariant:
            self.invariant()
        with self.lock:
            self.sequence += 1
            if self.audit:
                name = f"response-{self.sequence:04d}.bin"
                with (self.audit / name).open("xb") as stream:
                    stream.write(payload)
                record = {"sequence": self.sequence, "method": req.method, "path": parse.urlsplit(req.full_url).path,
                          "status": status, "elapsed": time.monotonic() - start, "bodyFile": name,
                          "sha256": hashlib.sha256(payload).hexdigest(), "responseHeaders": response_headers}
                with (self.audit / "http.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        return status, payload, response_headers

    def json(self, path, **kwargs):
        status, payload, _ = self.call(path, **kwargs)
        require(status == 200, f"HTTP {status} from {path}: {payload[:200]!r}")
        try:
            result = json.loads(payload)
        except (UnicodeError, ValueError) as exc:
            raise AcceptanceError(f"Non-JSON result from {path}") from exc
        require(isinstance(result, dict), "Expected a JSON object")
        return result

    def upload(self, endpoint, content, parameters, *, legacy=False, filename="计数页.png"):
        fields = {"json": json.dumps(parameters, ensure_ascii=True)}
        if legacy:
            fields["backendId"] = fields.pop("backendId", "current")
            fields["json"] = json.dumps(parameters.get("options", {}), ensure_ascii=True)
            fields["backendId"] = parameters.get("backendId", "current")
        media_type = {".cbz": "application/vnd.comicbook+zip", ".pdf": "application/pdf"}.get(Path(filename).suffix.lower(), "image/png")
        body, content_type = multipart(fields, filename, content, media_type)
        return self.json(endpoint, body=body, content_type=content_type)


def wait_for(predicate, deadline, label):
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.025)
    raise AcceptanceError("Deadline waiting for " + label)


def module_provenance(root, plugin_ids=()):
    result = {}
    for name, module in tuple(sys.modules.items()):
        if not (name == "py_src" or name.startswith("py_src.") or name in {"umi_log", "call_func", "PySide6", "bottle", "fitz", "pymupdf", "PIL", "cv2", "numpy", "psutil"}
                or any(name == plugin or name.startswith(plugin + ".") for plugin in plugin_ids)):
            continue
        origin = getattr(module, "__file__", None)
        locations = [origin] if origin else list(getattr(module, "__path__", []))
        require(locations, "No package provenance for " + name)
        for location in locations:
            require(inside(location, root), f"Product module escaped candidate package: {name}: {location}")
        result[name] = locations
    require("py_src.server.web_server" in result and "py_src.mission.backend_runtime" in result,
            "Product server/runtime were not imported from candidate")
    return result


@dataclass
class Gate:
    owner: str
    entered: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)


class Observations:
    """Transparent calls into the real coordinator/APIs; no fake inference."""
    def __init__(self, runtime, managed_type, deadline):
        self.runtime, self.managed_type, self.deadline = runtime, managed_type, deadline
        self.lock, self.local = threading.RLock(), threading.local()
        self.events, self.instances, self.references = [], [], []
        self.active, self.peak, self.gate = 0, 0, None
        self.original_operation, self.original_instance = runtime.operation, runtime._instance
        self.original_cancel = managed_type.cancel

    def install(self):
        observations = self
        @contextmanager
        def operation(owner, *args, **kwargs):
            with observations.original_operation(owner, *args, **kwargs):
                depth = getattr(observations.local, "depth", 0)
                tracked = not depth and kwargs.get("activate", True)
                observations.local.depth = depth + 1
                gate = None
                if tracked:
                    with observations.lock:
                        observations.active += 1
                        observations.peak = max(observations.peak, observations.active)
                        observations.events.append({"event": "permit-enter", "owner": owner, "time": time.monotonic()})
                        if observations.gate and observations.gate.owner == owner:
                            gate, observations.gate = observations.gate, None
                try:
                    if gate:
                        gate.entered.set()
                        require(gate.release.wait(max(0, observations.deadline - time.monotonic())), "Scheduling gate deadline")
                    yield
                finally:
                    observations.local.depth = depth
                    if tracked:
                        with observations.lock:
                            observations.events.append({"event": "permit-exit", "owner": owner, "time": time.monotonic()})
                            observations.active -= 1

        def instance(handle):
            entry = observations.original_instance(handle)
            with observations.lock:
                if not any(value is entry.instance for value in observations.references):
                    observations.references.append(entry.instance)
                number = next(index for index, value in enumerate(observations.references) if value is entry.instance)
                observations.instances.append({"key": list(handle.key), "instance": number,
                                               "implementation": type(entry.instance).__module__, "time": time.monotonic()})
            return entry

        def cancel(handle, token=None):
            with observations.lock:
                observations.events.append({"event": "cancel-enter", "key": list(handle.key), "time": time.monotonic(),
                    "matchesActive": handle._active_thread is not None and (token is None or handle._active_token is token)})
            try:
                return observations.original_cancel(handle, token)
            finally:
                with observations.lock:
                    observations.events.append({"event": "cancel-exit", "key": list(handle.key), "time": time.monotonic()})

        self.runtime.operation, self.runtime._instance = operation, instance
        self.managed_type.cancel = cancel

    def arm(self, owner):
        with self.lock:
            require(self.gate is None, "An observation gate is already armed")
            self.gate = Gate(owner)
            return self.gate

    def restore(self):
        if self.gate:
            self.gate.release.set()
        self.runtime.operation, self.runtime._instance = self.original_operation, self.original_instance
        self.managed_type.cancel = self.original_cancel

    def instance_ids(self, key, since=0):
        with self.lock:
            return {value["instance"] for value in self.instances[since:] if value["key"] == list(key)}


def trusted_overrides(cuda, vl, canonical_keys, models, model_port):
    """Bind only the reviewed manifest's canonical fields, on the trusted side."""
    service = f"pluginServices.{vl}.paddlevl."
    bindings = {
        service + "service.mainModel": models["model"],
        service + "service.mmprojModel": models["projector"],
        service + "service.port": model_port,
        service + "resources.contextLength": 8192,
        service + "resources.slots": 1,
        service + "resources.maxOutputTokens": 4096,
        f"document.{vl}.pipeline.layoutModelDir": models["layout"],
    }
    missing = set(bindings) - set(canonical_keys)
    require(not missing, "Candidate manifest lacks trusted fields: " + ", ".join(sorted(missing)))
    for key in (f"ocr.{cuda}.device", f"document.{vl}.pipeline.cudaDevice"):
        if key in canonical_keys:
            bindings[key] = "gpu:0"
    return bindings


def configure_backends(runtime, registries, services, models, root):
    ocr_ids, doc_ids = set(registries["ocr"].keys()), set(registries["document"].keys())
    cuda = [key for key in ocr_ids - doc_ids if "cuda" in key.lower()]
    vl = [key for key in ocr_ids & doc_ids if "vl" in key.lower()]
    require(len(cuda) == len(vl) == 1, "Candidate must contain exactly one CUDA OCR and VL OCR+document backend")
    cuda, vl = cuda[0], vl[0]
    with socket.socket() as port_socket:
        port_socket.bind(("127.0.0.1", 0))
        model_port = port_socket.getsockname()[1]
    from py_src.mission.backend_runtime import flatten_options
    values = {}
    for capability, registry in registries.items():
        for backend in registry.keys():
            for key, definition in flatten_options(registry.globalOptions(backend) or {}).items():
                values[f"{capability}.{backend}.{key}"] = definition.get("default")
    for backend, declared in services.options().items():
        for service in declared:
            for key, definition in flatten_options(service["config"]).items():
                values[f"pluginServices.{backend}.{service['id']}.{key}"] = definition.get("default")
    bindings = trusted_overrides(cuda, vl, values, models, model_port)
    values.update(bindings)
    require(runtime.publish(values).startswith("[Success]"), "Cannot publish trusted canonical snapshot")
    configured = {(capability, backend): runtime.configuration(capability, backend)
                  for capability, registry in registries.items() for backend in registry.keys()}
    for capability in ("ocr", "document"):
        config = configured[(capability, vl)]
        require(config["resources.contextLength"] == 8192 and config["resources.slots"] == 1,
                "Published service is not 8K single-slot")
        require(config["service.mainModel"] == models["model"] and config["service.mmprojModel"] == models["projector"],
                "Service snapshot did not bind the trusted models")
    return cuda, vl, model_port, configured, bindings


def assert_gpu_result(value):
    execution = value.get("execution") or (value.get("metadata") or {}).get("execution") or {}
    description = json.dumps(execution, ensure_ascii=False).lower()
    require("cuda" in description or "gpu" in description, "Response does not prove actual GPU execution")
    require(not ("cpu" in description and "cuda" not in description and "gpu" not in description), "CPU fallback is not acceptance")


def own_listener(port, root_pid):
    import psutil
    current = psutil.Process(root_pid)
    owned = {root_pid, *(process.pid for process in current.children(recursive=True))}
    matches = [connection.pid for connection in psutil.net_connections(kind="tcp")
               if connection.status == psutil.CONN_LISTEN and connection.laddr.port == port]
    require(matches and all(pid in owned for pid in matches), "Model listener is not owned by this acceptance process tree")
    return matches


def execute_scenarios(client, runtime, observers, cuda, vl, structured, doc_server, work, deadline):
    report = {}
    png, dense = countable_png(), countable_png(rows=48, scale=4)
    cbz = png_cbz(png)
    for name, content in (("计数页.png", png), ("密集计数页.png", dense), ("两页计数.cbz", cbz)):
        with (work / name).open("xb") as stream:
            stream.write(content)
    report["fixtures"] = {"pngRows": 3, "cbzPages": 2, "denseRows": 48,
                           "sensitive": False, "newPdfCreated": False}
    backends = client.json("/api/backends")
    require(backends.get("code") == 100, "Backend discovery failed")
    require(any(item["backendId"] == cuda for item in backends["data"]["ocr"]), "CUDA missing from HTTP registry")
    require(any(item["backendId"] == vl for item in backends["data"]["document"]), "VL missing from HTTP registry")
    report["backends"] = backends
    encoded = base64.b64encode(png).decode("ascii")

    def ocr(backend, *, content=encoded, options=None):
        result = client.json("/api/ocr", data={"backendId": backend, "base64": content,
                                               "options": options or {}, "taskTimeoutSeconds": 300})
        require(result.get("code") == 100 and not result.get("partial"), f"OCR failed for {backend}: {str(result)[:600]}")
        require_countable(result)
        assert_gpu_result(result)
        return result

    invalid = [client.json("/api/ocr", data={"base64": encoded, "backendId": cuda,
                 "options": {"service.modelPath": "untrusted-client-model"}}),
               client.json("/api/ocr", data={"base64": encoded, "backendId": cuda, "options": []}),
               client.json("/api/ocr", data={"base64": encoded, "backendId": "not-a-registered-backend"}),
               client.upload("/api/document/upload", png, {"backendId": cuda}),
               client.upload("/api/document/upload", png, {"backendId": vl, "options": {"assetOutputRoot": "client-root"}}),
               client.upload("/api/document/upload", png, {"backendId": vl, "pageRange": [1, 501]})]
    require(all(value.get("code") != 100 for value in invalid), "An invalid option/capability was accepted")
    report["invalidRequestsRejected"] = len(invalid)
    report["cudaOcr"] = require_countable(ocr(cuda))
    report["currentOcr"] = require_countable(ocr("current"))

    with ThreadPoolExecutor(max_workers=4) as executor:
        gate = observers.arm(vl)
        index = len(observers.instances)
        first = executor.submit(ocr, vl)
        require(gate.entered.wait(min(30, deadline - time.monotonic())), "VL did not enter scheduling gate")
        second = executor.submit(ocr, vl)
        try:
            wait_for(lambda: runtime.status()["pendingTasks"] >= 2, min(deadline, time.monotonic() + 15), "second VL admission")
        finally:
            gate.release.set()
        first.result(timeout=max(1, deadline - time.monotonic()))
        second.result(timeout=max(1, deadline - time.monotonic()))
        require(len(observers.instance_ids(("ocr", vl), index)) == 1, "Overlapping same-backend requests did not reuse the real API")
        report["sameBackendRealInstanceReuse"] = True

        gate = observers.arm(cuda)
        first = executor.submit(ocr, cuda)
        require(gate.entered.wait(min(30, deadline - time.monotonic())), "CUDA did not enter gate")
        second = executor.submit(ocr, vl)
        try:
            wait_for(lambda: runtime.status()["waitingRequests"] >= 1, min(deadline, time.monotonic() + 15), "cross-backend queue")
            require(not second.done(), "Second backend bypassed the occupied global slot")
        finally:
            gate.release.set()
        first.result(timeout=max(1, deadline - time.monotonic()))
        second.result(timeout=max(1, deadline - time.monotonic()))

        legacy = client.upload("/api/doc/upload", cbz, {"backendId": cuda, "options": {"doc.extractionMode": "fullPage"}},
                               legacy=True, filename="两页计数.cbz")
        require(legacy.get("code") == 100, f"Legacy CBZ upload failed: {legacy}")
        legacy_id = legacy["data"]
        def legacy_status():
            value = client.json("/api/doc/result", data={"id": legacy_id, "is_data": True, "is_unread": False})
            return value if value.get("is_done") else None
        legacy_result = wait_for(legacy_status, deadline, "legacy document completion")
        require(legacy_result.get("state") == "success" and legacy_result.get("processed_count") == 2, "Legacy document did not succeed for two pages")
        require_countable(legacy_result, expected=6)
        download = client.json("/api/doc/download", data={"id": legacy_id, "file_types": ["txt"], "ignore_blank": False})
        require(download.get("code") == 100, f"Legacy export failed: {download}")
        status, content, _ = client.call(download["data"])
        require(status == 200 and b"12345" in re.sub(rb"\s+", b"", content), "Legacy download is not recognized content")
        report["legacyDocument"] = {"pages": 2, "downloadBytes": len(content)}

        def structured_upload(content=png, **parameters):
            value = client.upload("/api/document/upload", content, {"backendId": vl, **parameters})
            require(value.get("code") == 100, f"Structured upload failed: {value}")
            return value["jobId"]

        def job_status(identifier):
            value = client.json("/api/document/result", data={"jobId": identifier})
            require(value.get("code") == 100, "Structured status failed")
            return value

        def finished(identifier):
            value = job_status(identifier)
            return value if value.get("state") in structured.TERMINAL else None

        identifier = structured_upload()
        full = wait_for(lambda: finished(identifier), deadline, "structured document completion")
        require(full["state"] == "succeeded", f"Structured document not fully successful: {str(full)[:600]}")
        require_countable(full)
        exports = {}
        for kind in ("txt", "md", "json", "zip"):
            status, payload, headers = client.call("/api/document/download", data={"jobId": identifier, "format": kind})
            require(status == 200 and "attachment" in headers.get("Content-Disposition", ""), f"Structured {kind} export failed")
            if kind == "zip":
                with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                    require({"document.txt", "document.md", "document.json"} <= set(archive.namelist()), "ZIP export lacks required members")
                    require(all(not name.startswith(("/", "\\")) and ".." not in Path(name).parts for name in archive.namelist()), "Unsafe ZIP member")
                    require(b"file://" not in archive.read("document.json"), "ZIP exposes local resource URI")
            else:
                require(b"file://" not in payload and b"12345" in re.sub(rb"\s+", b"", payload), "Export omitted text or exposed local URI")
            exports[kind] = len(payload)
        report["structuredExports"] = exports
        pdf_fixture = getattr(client, "document_fixture", None)
        if pdf_fixture is not None:
            with Path(pdf_fixture["path"]).open("rb") as source:
                pdf_bytes = source.read(64 * 1024 * 1024 + 1)
            require(hashlib.sha256(pdf_bytes).hexdigest() == pdf_fixture["sha256"], "Pinned PDF changed before HTTP upload")
            uploaded = client.upload("/api/document/upload", pdf_bytes,
                {"backendId": vl, "pageRange": pdf_fixture["pageRange"], "taskTimeoutSeconds": 300},
                filename="无文本层_选页.pdf")
            require(uploaded.get("code") == 100, "Real PDF HTTP upload failed: " + str(uploaded)[:600])
            pdf_id = uploaded["jobId"]
            pdf_result = wait_for(lambda: finished(pdf_id), deadline, "real selected-page PDF through HTTP")
            require(pdf_result["state"] == "succeeded", "Real HTTP PDF did not succeed: " + str(pdf_result)[:600])
            metrics = pdf_http_metrics(pdf_result.get("result"), pdf_fixture)
            status, payload, _ = client.call("/api/document/download", data={"jobId": pdf_id, "format": "txt"})
            normalized = re.sub(r"\s+", "", payload.decode("utf-8"))
            require(status == 200 and all(token in normalized for token in pdf_fixture["tokens"]),
                    "HTTP PDF export lost selected-page identifiers")
            require(sha256_file(pdf_fixture["path"]) == pdf_fixture["sha256"], "Pinned PDF was modified during acceptance")
            report["structuredPdf"] = {"status": "PASS", "fixture": pdf_fixture, "jobId": pdf_id,
                                       "metrics": metrics, "textDownloadBytes": len(payload)}
        else:
            report["structuredPdf"] = {"status": "NOT_RUN", "reason": "No --document-fixture supplied"}
        report["ownedModelListenerPids"] = own_listener(client.model_port, os.getpid())
        for path in (f"/api/document/assets/{identifier}/not-owned", "/api/document/assets/" + "0" * 32 + "/not-owned",
                     f"/api/document/assets/{identifier}/%2e%2e", "/api/doc/download/%2e%2e/private"):
            status, _, _ = client.call(path)
            require(status in (400, 403, 404), "Unauthorized resource request was not denied: " + path)
        report["unauthorizedResourcesRejected"] = 4

        # Cancel a queued structured task while a real CUDA request owns the
        # permit. The survivor goes through real VL after CUDA is released.
        gate = observers.arm(cuda)
        active = executor.submit(ocr, cuda)
        require(gate.entered.wait(min(30, deadline - time.monotonic())), "CUDA cancellation gate not entered")
        target = structured_upload()
        survivor = structured_upload()
        cancel_index = len(observers.events)
        try:
            client.json("/api/document/cancel", data={"jobId": target})
            cancelled = wait_for(lambda: finished(target), min(deadline, time.monotonic() + 30), "queued target cancellation")
            require(cancelled["state"] == "cancelled", "Queued cancellation did not end target")
            require(job_status(survivor)["state"] not in structured.TERMINAL, "Cancellation changed the survivor")
            require(not any(event["event"] == "cancel-enter" and event.get("matchesActive") for event in observers.events[cancel_index:]),
                    "Queued cancellation reached an active real backend")
        finally:
            gate.release.set()
        active.result(timeout=max(1, deadline - time.monotonic()))
        survived = wait_for(lambda: finished(survivor), deadline, "uncancelled survivor")
        require(survived["state"] == "succeeded", "Cancelling target damaged survivor")
        report["queuedCancelIsolation"] = True

        # Old /api/doc has clear-as-cancel, not a separate cancel endpoint.
        gate = observers.arm(cuda)
        active = executor.submit(ocr, cuda)
        require(gate.entered.wait(min(30, deadline - time.monotonic())), "Legacy cancellation gate not entered")
        legacy_cancel = client.upload("/api/doc/upload", cbz, {"backendId": cuda, "options": {"doc.extractionMode": "fullPage"}},
                                     legacy=True, filename="取消两页.cbz")
        require(legacy_cancel.get("code") == 100, "Legacy cancellation upload failed")
        try:
            client.json("/api/doc/clear/" + legacy_cancel["data"])
        finally:
            gate.release.set()
        active.result(timeout=max(1, deadline - time.monotonic()))
        legacy_cancelled = wait_for(lambda: (value if value.get("is_done") else None)
            if (value := client.json("/api/doc/result", data={"id": legacy_cancel["data"]})) else None,
            deadline, "legacy cancellation completion")
        require(legacy_cancelled.get("state") == "failure", "Legacy cancelled task reported success")
        report["legacyCancellation"] = "failure (legacy contract)"

        # A real valid page must be emitted by the actual VL backend. Only its
        # callback scheduling is held, allowing real HTTP active cancellation.
        partial_entered, partial_release = threading.Event(), threading.Event()
        original_partial = structured.DocumentJob._on_partial
        partial_target = {}
        def partial(job, event):
            original_partial(job, event)
            if (not partial_target and not event.get("failed") and "12345" in re.sub(r"\s+", "", text_from(event.get("result")))):
                partial_target["job"] = job.identifier
                partial_entered.set()
                require(partial_release.wait(max(0, deadline - time.monotonic())), "Real partial scheduling deadline")
        structured.DocumentJob._on_partial = partial
        try:
            partial_id = structured_upload()
            require(partial_entered.wait(max(0, deadline - time.monotonic())), "Real backend emitted no valid countable partial page")
            require(partial_target["job"] == partial_id, "Partial observer attached to another job")
            queued_cuda = executor.submit(ocr, cuda)
            cancellation = executor.submit(client.json, "/api/document/cancel", data={"jobId": partial_id})
            wait_for(lambda: structured.JOBS[partial_id].cancel_requested, min(deadline, time.monotonic() + 15), "active HTTP cancellation flag")
            partial_release.set()
            cancellation.result(timeout=max(1, deadline - time.monotonic()))
            cancelled = wait_for(lambda: finished(partial_id), deadline, "active cancellation finish")
            require(cancelled["state"] == "cancelled" and cancelled["completedPages"] >= 1,
                    "Active cancellation lost valid partial page or masked cancellation")
            for kind in ("txt", "md", "json", "zip"):
                status, payload, _ = client.call("/api/document/download", data={"jobId": partial_id, "format": kind})
                require(status == 200, "Partial export failed: " + kind)
                if kind == "json":
                    exported = json.loads(payload)
                    require(exported.get("partial") is True and exported.get("partialPages"), "Partial JSON hides incompleteness")
                elif kind in ("txt", "md"):
                    require(b"12345" in re.sub(rb"\s+", b"", payload), "Valid partial page not exported")
            queued_cuda.result(timeout=max(1, deadline - time.monotonic()))
            report["realPartialCancellation"] = {"state": cancelled["state"], "completedPages": cancelled["completedPages"],
                                                  "schedulingGate": "after genuine valid onPartial; real HTTP cancel and real backend cancel"}
        finally:
            partial_release.set()
            structured.DocumentJob._on_partial = original_partial

        timeout_id = structured_upload(dense, taskTimeoutSeconds=1)
        timed_out = wait_for(lambda: finished(timeout_id), deadline, "one-second real document deadline")
        require(timed_out["state"] in {"failed", "partial"},
                "Real timeout/failure coverage not reached; do not count a fast successful run as failure validation")
        final_code = (timed_out.get("result") or {}).get("code")
        failure_description = json.dumps(timed_out, ensure_ascii=False).lower()
        require(final_code not in (None, 100, 101) or any(marker in failure_description for marker in ("timeout", "timed out", "超时")),
                "No actual deadline failure observed; partial alone is not failure evidence")
        require(timed_out["state"] != "succeeded", "Partial content masked a real deadline failure")
        report["deadlineFailure"] = {"state": timed_out["state"], "resultCode": final_code,
                                      "completedPages": timed_out["completedPages"]}
    require(observers.peak == 1 and observers.active == 0, "Global heavy execution slot was not serialized")
    report["peakHeavyExecutions"] = observers.peak
    return report


def worker(args):
    audit, work, root = map(safe_path, (args.audit, args.work, args.root))
    guard = json.loads((audit / "guard.json").read_text(encoding="utf-8"))
    require(args.execute_gpu and args.worker_token == guard["token"], "Worker has no explicit GPU authorization")
    wait_for(lambda: (audit / "supervisor-ready").is_file(), time.monotonic() + 20, "process containment")
    deadline = time.monotonic() + args.deadline_seconds - 30
    data_root = root if root.name == "UmiOCR-data" else root / "UmiOCR-data"
    require(data_root.is_dir(), "Candidate lacks UmiOCR-data")
    require(safe_path(sys.executable) == candidate_python(root), "Worker is not using the candidate's packaged Python")
    require(sys.implementation.name == "cpython" and tuple(sys.version_info[:3]) == (3, 13, 16),
            "This acceptance round requires candidate CPython 3.13.16")
    require(sys.flags.isolated and sys.flags.dont_write_bytecode and sys.flags.utf8_mode,
            "Worker must run with -I -B -X utf8")
    environment_evidence = verify_worker_environment(work)
    models = trusted_model_inputs(args.model_inputs)
    require(not any(name == "py_src" or name.startswith("py_src.") for name in sys.modules),
            "Product modules were already imported before candidate loading")
    # -I deliberately excludes the script directory from sys.path. Load only
    # this trusted loader by its absolute path, without adding source imports.
    loader_path = Path(__file__).resolve().with_name("staging_smoke.py")
    spec = importlib.util.spec_from_file_location("acceptance_staging_smoke", loader_path)
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    handles = loader.configure_runtime(data_root)
    runtime_work = work / "中文路径_HTTP联合验收"
    runtime_work.mkdir(exist_ok=False)
    os.chdir(runtime_work)
    from PySide6.QtCore import QCoreApplication, QThreadPool
    application = QCoreApplication.instance() or QCoreApplication([])
    from py_src.plugins_controller import plugins_controller
    plugins_controller.PLUGINS_PATH = str(data_root / "plugins")
    plugins = plugins_controller.PluginsController.init()
    from py_src.plugins_controller.capabilities import CAPABILITY_TYPES
    from py_src.plugins_controller.services import PluginServices
    from py_src.mission.backend_runtime import BackendRuntime, ManagedApi
    cuda, vl, model_port, configurations, bindings = configure_backends(
        BackendRuntime, {key: CAPABILITY_TYPES[key] for key in ("ocr", "document")}, PluginServices, models, root)
    from py_src.mission.mission_ocr import MissionOCR
    from py_src.mission.mission_document import MissionDocument
    require(MissionOCR.setApi(cuda, configurations[("ocr", cuda)]).startswith("[Success]"), "Cannot select CUDA globally")
    require(MissionDocument.setApi(vl, configurations[("document", vl)]).startswith("[Success]"), "Cannot select VL document globally")
    from py_src.server import web_server, structured_document_server, doc_server
    from wsgiref.simple_server import make_server
    provenance = module_provenance(root, (cuda, vl))
    write_json_new(audit / "package-before.json", {"root": str(root), "python": sys.executable,
        "pythonVersion": sys.version, "pythonFlags": {"isolated": sys.flags.isolated,
        "dontWriteBytecode": sys.flags.dont_write_bytecode, "utf8Mode": sys.flags.utf8_mode},
        "modules": provenance, "pluginSummary": plugins, "trustedModels": models,
        "trustedBindings": bindings, "modelPort": model_port,
        "configurations": {"/".join(key): value for key, value in configurations.items()},
        "driverSha256": sha256_file(__file__), "modelInputsSha256": sha256_file(args.model_inputs),
        "environment": environment_evidence, "modelsReadOnly": True, "downloadsAuthorized": False,
        "precisionChangesAuthorized": False})
    baseline = [(manager._apiKey, manager._api, json.dumps(manager._api.config, sort_keys=True, default=str))
                for manager in (MissionOCR, MissionDocument)]
    def invariant():
        for manager, (key, api, config) in zip((MissionOCR, MissionDocument), baseline):
            require(manager._apiKey == key and manager._api is api and
                    json.dumps(manager._api.config, sort_keys=True, default=str) == config,
                    "HTTP changed a GUI/global backend selection or configuration")
    server = make_server("127.0.0.1", 0, web_server.UmiWeb,
                         server_class=web_server._WSGIRefServer.CustomWSGIServer)
    server_thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.1), daemon=True)
    server_thread.start()
    observers = Observations(BackendRuntime, ManagedApi, deadline)
    observers.install()
    result = {"accepted": False, "realSocket": True, "realPackage": True, "gpuExecutionAuthorized": True,
              "baseUrl": f"http://127.0.0.1:{server.server_port}", "limitations": [],
              "observerMode": "transparent real API calls plus finite trusted-side scheduling gates; no fake model responses",
              "runtimeWork": str(runtime_work)}
    client = HttpClient(server.server_port, deadline, audit, invariant)
    client.model_port = model_port
    client.document_fixture = trusted_document_fixture(getattr(args, "document_fixture", None))
    outcome, completed = {}, threading.Event()
    def run():
        try:
            outcome["scenarios"] = execute_scenarios(client, BackendRuntime, observers, cuda, vl,
                                                     structured_document_server, doc_server, runtime_work, deadline)
            after = trusted_model_inputs(args.model_inputs)
            require(after["verified"] == models["verified"], "Trusted model inputs changed during acceptance")
            outcome["modelInputHashesUnchanged"] = True
        except BaseException:
            outcome["error"] = traceback.format_exc()
        finally:
            completed.set()
    orchestration = threading.Thread(target=run, name="real-http-acceptance", daemon=True)
    orchestration.start()
    try:
        while not completed.wait(0.01):
            application.processEvents()
            require(time.monotonic() < deadline, "Worker orchestration deadline")
        result.update(outcome)
        invariant()
        result["modulesAfterInference"] = module_provenance(root, (cuda, vl))
        result["accepted"] = "error" not in result
    except BaseException:
        result["error"] = traceback.format_exc()
    finally:
        # Only jobs registered in THIS fresh process and test-owned listener.
        for job in tuple(structured_document_server.JOBS.values()):
            if job.state not in structured_document_server.TERMINAL:
                job.cancel()
        for unit in tuple(doc_server._DocUnitManager.doc_units.values()):
            if not unit.is_done:
                unit.clear()
        end = min(deadline + 10, time.monotonic() + 20)
        while BackendRuntime.busy() and time.monotonic() < end:
            application.processEvents()
            time.sleep(0.02)
        cleanup_error = None
        try:
            require(not BackendRuntime.busy(), "Backend did not drain; supervisor must close only the owned process job")
            MissionOCR.shutdown()
            MissionDocument.shutdown()
            BackendRuntime.reset()
            PluginServices.shutdownAll()
        except BaseException:
            cleanup_error = traceback.format_exc()
        observers.restore()
        server.shutdown()
        server.close_all_request()
        server.server_close()
        server_thread.join(3)
        QThreadPool.globalInstance().waitForDone(3000)
        result["cleanupError"] = cleanup_error
        if cleanup_error:
            result["accepted"] = False
        result["observations"] = {"events": observers.events, "instances": observers.instances,
                                   "peakHeavyExecutions": observers.peak}
        result["globalSelectionsUnchanged"] = [(key, config) for key, _api, config in baseline]
        write_json_new(audit / "result.json", result)
        # Preserve DLL handles through all real backend/thread cleanup.
        _ = handles
    return 0 if result["accepted"] else 1


class OwnedProcessJob:
    """Windows kernel ownership boundary; never kill a PID found by name/port."""
    def __init__(self, process):
        self.process, self.handle = process, None
        if os.name == "nt":
            from ctypes import wintypes
            class BASIC(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]
            class IO(ctypes.Structure):
                _fields_ = [(name, ctypes.c_ulonglong) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]
            class EXTENDED(ctypes.Structure):
                _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                            ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateJobObjectW.argtypes, kernel.CreateJobObjectW.restype = [ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE
            kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
            kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            self.kernel = kernel
            self.handle = kernel.CreateJobObjectW(None, None)
            require(self.handle, "Cannot create owned Windows process job")
            information = EXTENDED()
            information.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
            require(kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(information), ctypes.sizeof(information)), "Cannot constrain owned process job")
            require(kernel.AssignProcessToJobObject(self.handle, int(process._handle)), "Cannot assign acceptance worker to owned job")

    def terminate(self):
        if os.name == "nt" and self.handle:
            self.kernel.TerminateJobObject(self.handle, 124)
        elif self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGKILL)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "work", "audit", "model-inputs"):
        result.add_argument("--" + name, required=True, type=Path)
    result.add_argument("--document-fixture", type=Path, help="Optional pinned synthetic PDF fixtures.json; never generates a new PDF")
    result.add_argument("--execute-gpu", action="store_true", help="Explicitly authorize real CUDA/VL execution; default is plan-only")
    result.add_argument("--deadline-seconds", type=int, default=1800)
    result.add_argument("--worker-token", help=argparse.SUPPRESS)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    require(120 <= args.deadline_seconds <= 3600, "deadline-seconds must be 120..3600")
    if not args.execute_gpu:
        print(json.dumps({"planOnly": True, "gpuExecuted": False, "productImported": False,
                          "scenarios": SCENARIOS, "requires": "candidate root and explicit --execute-gpu authorization"}, ensure_ascii=False, indent=2))
        return 0
    if args.worker_token:
        return worker(args)
    root, work, audit = validate_paths(args.root, args.work, args.audit)
    executable = candidate_python(root)
    token = uuid4().hex
    work.mkdir(parents=True, exist_ok=False)
    audit.mkdir(parents=True, exist_ok=False)
    environment, environment_overrides = prepare_worker_environment(work)
    write_json_new(audit / "environment-overrides.json", environment_overrides)
    write_json_new(audit / "guard.json", {"token": token, "root": str(root), "work": str(work),
                   "deadlineSeconds": args.deadline_seconds, "startedAt": time.time(), "supervisorPid": os.getpid()})
    command = production_worker_command(args, executable, root, work, audit, token)
    owned, child, timed_out = None, None, False
    try:
        with (audit / "worker.stdout.log").open("xb") as stdout, (audit / "worker.stderr.log").open("xb") as stderr:
            child = subprocess.Popen(command, cwd=work, stdout=stdout, stderr=stderr, env=environment,
                                     start_new_session=os.name != "nt")
            owned = OwnedProcessJob(child)
            with (audit / "supervisor-ready").open("x", encoding="ascii") as stream:
                stream.write(token)
            try:
                code = child.wait(timeout=args.deadline_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                owned.terminate()
                child.wait(timeout=15)
                code = 124
        write_json_new(audit / "supervisor.json", {"exitCode": code, "timedOut": timed_out,
                       "workerPid": child.pid, "finishedAt": time.time(),
                       "terminationScope": "only the kernel-owned acceptance process job/group",
                       "retained": [str(work), str(audit)], "deleted": []})
        print(json.dumps({"exitCode": code, "audit": str(audit), "work": str(work), "gpuExecuted": True}))
        return code
    finally:
        if owned:
            if child.poll() is None:
                owned.terminate()
                child.wait(timeout=15)
            owned.close()
        elif child and child.poll() is None:
            # Containment failed BEFORE the worker's start gate was released.
            child.terminate()
            child.wait(timeout=15)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AcceptanceError as exc:
        print("ACCEPTANCE BLOCKED: " + str(exc), file=sys.stderr)
        raise SystemExit(2)
