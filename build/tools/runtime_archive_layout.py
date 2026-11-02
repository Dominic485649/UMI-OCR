"""Read and verify a runtime Stored-ZIP layout without importing or extracting it.

The layout records a transformation, not the provenance of its input. Supply
``source_hashes`` from an independently locked wheel/seed/source inventory when
that provenance is required. No code from the inspected tree is executed.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import unicodedata
import zipfile

MANIFEST_NAME = "runtime-archives.json"
INPUTS_NAME = "runtime-archive-inputs.json"
MARKER_NAME = ".runtime-archive-candidate.json"
FORMAT = "umi-runtime-stored-zip-v1"
TIMESTAMP = (1980, 1, 1, 0, 0, 0)
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
RUNTIME_ARCHIVES = frozenset({"app.zip", "dependencies.zip", "vendor.zip"})
EXTERNAL_SUFFIXES = frozenset({
    ".dll", ".pyd", ".so", ".dylib", ".exe", ".com", ".lib", ".a", ".o", ".obj", ".pyc", ".pyo",
    ".gguf", ".safetensors", ".onnx", ".pdparams", ".pdiparams", ".pdmodel", ".engine", ".trt", ".pt", ".pth",
    ".bin", ".pickle", ".pkl", ".joblib", ".qml", ".qm", ".rcc", ".qrc", ".ttf", ".otf", ".woff", ".woff2",
})
EXTERNAL_PACKAGES = frozenset(name.casefold() for name in (
    "PySide6", "shiboken6", "cv2", "numpy", "PIL", "pymupdf", "fitz", "paddle", "paddlex", "nvidia",
    "onnxruntime", "scipy", "sklearn", "skimage", "pandas", "certifi", "imagecodecs", "psutil", "zxingcpp",
    "Crypto", "shapely", "lxml", "pydantic_core", "yaml", "runtime", "native", "models", "model", "qt_res", "i18n",
))
EXTERNAL_PARTS = frozenset({"__pycache__", "models", "model", "native", "qt_res", ".settings", "logs", "temp", "temp_doc"})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_RESERVED = re.compile(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?\Z", re.I)


class LayoutError(RuntimeError):
    """An unsafe, incomplete, inconsistent or unbound layout."""


def canonical_relative(value):
    """Require a canonical, portable, root-relative POSIX path."""
    if not isinstance(value, str) or not value or unicodedata.normalize("NFC", value) != value:
        raise LayoutError(f"Noncanonical relative path: {value!r}")
    parts = value.split("/")
    if any(not part or part in {".", ".."} or part.endswith((".", " "))
           or _RESERVED.fullmatch(part)
           or any(char in '\\:<>"|?*' or ord(char) < 32 or ord(char) == 127 for char in part)
           for part in parts):
        raise LayoutError(f"Unsafe relative path: {value!r}")
    return value


def reject_link(path):
    try:
        info = Path(path).lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise LayoutError(f"Link/junction/reparse point is not allowed: {path}")
    if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
        raise LayoutError(f"Hard-linked input is not allowed: {path}")
    if not stat.S_ISREG(info.st_mode) and not stat.S_ISDIR(info.st_mode):
        raise LayoutError(f"Nonregular input is not allowed: {path}")


def plain_path(path):
    path = Path(path)
    if str(path).startswith(("\\\\", "//")) or (path.drive and not path.is_absolute()):
        raise LayoutError("Network/device/drive-relative paths are not supported")
    if ".." in path.parts:
        raise LayoutError("Parent traversal is not allowed in filesystem roots")
    if not path.is_absolute():
        path = Path.cwd() / path
    current = Path(path.anchor)
    reject_link(current)
    for part in path.parts[1:]:
        current /= part
        reject_link(current)
    return path.resolve()


def tree_files(root):
    """Inventory plain files, rejecting collisions/links before reading bytes."""
    root = plain_path(root)
    if not root.is_dir():
        raise LayoutError(f"Missing layout root: {root}")
    result, folded = {}, {}
    pending = [root]
    while pending:
        directory = pending.pop()
        reject_link(directory)
        for path in sorted(directory.iterdir(), key=lambda item: item.name):
            name = canonical_relative(path.relative_to(root).as_posix())
            key = name.casefold()
            if key in folded:
                raise LayoutError(f"Case-colliding paths: {folded[key]} and {name}")
            folded[key] = name
            reject_link(path)
            if path.is_dir():
                pending.append(path)
            else:
                result[name] = path
    return result


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise LayoutError(f"Duplicate JSON key: {key}")
        value[key] = item
    return value


def read_json(path):
    try:
        return json.loads(Path(path).read_text("utf-8-sig"), object_pairs_hook=_json_object)
    except (OSError, ValueError) as exc:
        raise LayoutError(f"Cannot read JSON: {path}: {exc}") from exc


def normalize_source_hashes(source_hashes):
    if source_hashes is None:
        return None
    if not isinstance(source_hashes, dict):
        raise LayoutError("source_hashes must be an independently supplied path/hash mapping")
    result, folded = {}, set()
    for name, checksum in source_hashes.items():
        canonical_relative(name)
        if not isinstance(checksum, str) or not _SHA256.fullmatch(checksum):
            raise LayoutError(f"Invalid source SHA-256: {name}")
        if name.casefold() in folded:
            raise LayoutError(f"Case-colliding source hashes: {name}")
        result[name] = checksum
        folded.add(name.casefold())
    return result


def load_source_hashes(path):
    value = read_json(plain_path(path))
    if isinstance(value, dict) and "sourceHashes" in value:
        value = value["sourceHashes"]
    return normalize_source_hashes(value)


def _checksum(record, label):
    if not isinstance(record, dict) or type(record.get("bytes")) is not int or record["bytes"] < 0:
        raise LayoutError(f"Invalid byte count for {label}")
    if not isinstance(record.get("sha256"), str) or not _SHA256.fullmatch(record["sha256"]):
        raise LayoutError(f"Invalid SHA-256 for {label}")


def _register_name(names, value, label):
    key = value.casefold()
    if key in names:
        raise LayoutError(f"Duplicate/colliding {label}: {value}")
    names[key] = value


def _archive_member_path(raw, kind, prefix):
    parts = raw.split("/")
    if (prefix == "" and parts[0] != "py_src") or parts[0].casefold() in EXTERNAL_PACKAGES:
        raise LayoutError(f"Native/real-path/entry-point namespace must remain external: {raw}")
    if any(part.casefold() in EXTERNAL_PARTS or part.casefold().endswith((".dist-info", ".egg-info")) for part in parts):
        raise LayoutError(f"Cache/model/native/state/metadata must remain external: {raw}")
    if kind == "file" and (Path(raw).suffix.lower() in EXTERNAL_SUFFIXES or ".so." in parts[-1].lower()):
        raise LayoutError(f"Native/model/Qt/bytecode resource must remain external: {raw}")


def _source_record(source, logical, checksum, kind):
    if not isinstance(source, dict) or source.get("logical_path") != logical or source.get("sha256") != checksum:
        raise LayoutError(f"Missing original-file binding: {logical}")
    if source.get("record_path") is None:
        if any(source.get(name) is not None for name in ("record_owner", "record_sha256", "record_member", "record_digest", "record_bytes")):
            raise LayoutError("Incomplete original wheel RECORD binding")
        return
    if kind != "file":
        raise LayoutError("A directory cannot claim wheel file ownership")
    canonical_relative(source["record_path"])
    canonical_relative(source.get("record_member"))
    if (not isinstance(source.get("record_owner"), str) or not isinstance(source.get("record_sha256"), str)
            or not _SHA256.fullmatch(source["record_sha256"])
            or not isinstance(source.get("record_digest"), str) or not isinstance(source.get("record_bytes"), str)):
        raise LayoutError("Invalid original wheel RECORD fields")


def verify_archive(root, archive, *, source_hashes=None):
    """Verify one complete declared container; does not inspect loose shadows."""
    root = plain_path(root)
    source_hashes = normalize_source_hashes(source_hashes)
    _checksum(archive, "container")
    name = canonical_relative(archive.get("path"))
    if "/" in name or not name.endswith(".zip"):
        raise LayoutError("Runtime containers must be root-level .zip files")
    path = plain_path(root / name)
    if not path.is_file() or path.stat().st_size != archive["bytes"] or sha256_file(path) != archive["sha256"]:
        raise LayoutError(f"Missing/changed runtime container: {name}")
    prefix = archive.get("source_prefix")
    if not isinstance(prefix, str) or prefix not in {"", "site-packages", "vendor"}:
        raise LayoutError("Unsupported runtime source namespace")
    members = archive.get("members")
    if not isinstance(members, list) or not members:
        raise LayoutError(f"Missing member inventory: {name}")
    expected, logical_names, member_names = {}, {}, {}
    for entry in members:
        _checksum(entry, "member")
        logical = canonical_relative(entry.get("logical_path"))
        member = entry.get("member")
        kind = entry.get("kind")
        if kind not in {"file", "directory"} or not isinstance(member, str):
            raise LayoutError("Every member needs an explicit file/directory kind")
        raw = member[:-1] if kind == "directory" and member.endswith("/") else member
        canonical_relative(raw)
        if (kind == "directory") != member.endswith("/"):
            raise LayoutError(f"Incorrect member kind: {member}")
        if logical != (prefix + "/" if prefix else "") + raw:
            raise LayoutError(f"Member/logical namespace mismatch: {member}")
        _archive_member_path(raw, kind, prefix)
        _register_name(logical_names, logical, "logical path")
        _register_name(member_names, raw, "ZIP member")
        source = entry.get("source")
        _source_record(source, logical, entry["sha256"], kind)
        if kind == "directory":
            if entry["bytes"] != 0 or entry["sha256"] != EMPTY_SHA256:
                raise LayoutError("Directory members must be empty")
        elif source_hashes is not None and source_hashes.get(logical) != entry["sha256"]:
            raise LayoutError(f"Member differs from externally supplied source hashes: {logical}")
        expected[member] = entry
    if [entry["member"] for entry in members] != sorted(expected):
        raise LayoutError("Manifest member order is not deterministic")
    for member, entry in expected.items():
        for parent in Path(member.rstrip("/")).parents:
            if str(parent) != "." and parent.as_posix() + "/" not in expected:
                raise LayoutError(f"Missing declared ZIP directory: {member}")
    try:
        with zipfile.ZipFile(path) as container:
            infos = container.infolist()
            actual_names = [item.filename for item in infos]
            if actual_names != sorted(expected) or container.comment:
                raise LayoutError(f"ZIP member set/order/comment differs from declaration: {name}")
            folded = {}
            for info in infos:
                raw = info.filename.rstrip("/")
                canonical_relative(raw)
                _register_name(folded, raw, "physical ZIP member")
                entry = expected[info.filename]
                mode = stat.S_IFMT(info.external_attr >> 16)
                wanted = stat.S_IFDIR if entry["kind"] == "directory" else stat.S_IFREG
                if mode not in {0, wanted} or info.is_dir() != (entry["kind"] == "directory"):
                    raise LayoutError(f"Link/nonregular/mistyped ZIP member: {info.filename}")
                if (info.compress_type != zipfile.ZIP_STORED or info.compress_size != info.file_size
                        or info.flag_bits & 1 or info.date_time != TIMESTAMP or info.extra or info.comment):
                    raise LayoutError(f"Non-Stored/noncanonical ZIP member: {info.filename}")
                if info.file_size != entry["bytes"]:
                    raise LayoutError(f"ZIP member size mismatch: {info.filename}")
                checksum = hashlib.sha256()
                record_digest = entry["source"].get("record_digest")
                record_hasher = None
                if record_digest:
                    algorithm, separator, encoded = record_digest.partition("=")
                    if not separator or algorithm not in {"sha256", "sha384", "sha512"}:
                        raise LayoutError("Unsupported wheel RECORD digest")
                    record_hasher = hashlib.new(algorithm)
                with container.open(info) as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        checksum.update(chunk)
                        if record_hasher is not None:
                            record_hasher.update(chunk)
                if checksum.hexdigest() != entry["sha256"]:
                    raise LayoutError(f"ZIP member hash mismatch: {info.filename}")
                if record_hasher is not None and base64.urlsafe_b64encode(record_hasher.digest()).rstrip(b"=").decode("ascii") != encoded:
                    raise LayoutError(f"ZIP member differs from wheel RECORD: {info.filename}")
    except (OSError, ValueError, zipfile.BadZipFile, NotImplementedError, RuntimeError) as exc:
        if isinstance(exc, LayoutError):
            raise
        raise LayoutError(f"Invalid runtime ZIP: {name}: {exc}") from exc
    return expected


class RuntimeArchiveLayout:
    """An audited logical view. Missing/corrupt archives never fall back to disk."""

    def __init__(self, root, *, source_hashes=None, manifest_name=MANIFEST_NAME):
        self._containers = {}
        try:
            self._initialize(root, source_hashes=source_hashes, manifest_name=manifest_name)
        except BaseException:
            self.close()
            raise

    def _initialize(self, root, *, source_hashes=None, manifest_name=MANIFEST_NAME):
        self.root = plain_path(root)
        self.source_hashes = normalize_source_hashes(source_hashes)
        self.disk_files = tree_files(self.root)
        canonical_relative(manifest_name)
        self.manifest_name = manifest_name
        self.entries = {}
        self.archives = {}
        self.manifest = None
        self._containers = {}
        self._archive_stats = {}
        reserved = {manifest_name, INPUTS_NAME, MARKER_NAME, *RUNTIME_ARCHIVES}
        for actual in self.disk_files:
            if actual.casefold() in {name.casefold() for name in reserved} and actual not in reserved:
                raise LayoutError(f"Noncanonical case in a reserved runtime path: {actual}")
        root_archives = {name for name in self.disk_files if "/" not in name and name.lower().endswith(".zip")}
        if manifest_name not in self.disk_files:
            if root_archives:
                raise LayoutError("A runtime ZIP exists without its required layout manifest")
            if MARKER_NAME in self.disk_files or INPUTS_NAME in self.disk_files:
                raise LayoutError("Incomplete runtime-archive assembly")
            return
        document = read_json(self.disk_files[manifest_name])
        if (not isinstance(document, dict) or type(document.get("schema_version")) is not int or document["schema_version"] != 1
                or document.get("format") != FORMAT or document.get("state") != "complete" or document.get("kind") not in ("host", "plugin")):
            raise LayoutError("Unsupported/incomplete runtime layout")
        if MARKER_NAME in self.disk_files:
            marker = read_json(self.disk_files[MARKER_NAME])
            if (not isinstance(marker, dict) or marker.get("purpose") != "fresh-runtime-archive-assembly" or marker.get("state") != "complete"):
                raise LayoutError("Unfinished/failed runtime-archive assembly marker")
        archives = document.get("archives")
        if not isinstance(archives, list):
            raise LayoutError("Invalid archive inventory")
        names, selection_names = {}, {}
        for archive in archives:
            if not isinstance(archive, dict):
                raise LayoutError("Invalid archive record")
            if archive.get("source_prefix") not in (("", "site-packages") if document["kind"] == "host" else ("vendor",)):
                raise LayoutError("An archive crosses its host/plugin namespace boundary")
            name = canonical_relative(archive.get("path"))
            _register_name(names, name, "archive path")
            path = self.root / name
            try:
                path_signature = self._signature(path.stat())
                container = zipfile.ZipFile(path)
            except (OSError, zipfile.BadZipFile) as exc:
                raise LayoutError(f"Missing/invalid runtime container: {name}") from exc
            self._containers[name] = container
            signature = self._signature(os.fstat(container.fp.fileno()))
            entries = verify_archive(self.root, archive, source_hashes=self.source_hashes)
            # Windows path.stat and CRT fstat can expose different file IDs/
            # timestamp precision. Compare each source with itself, never them
            # with one another.
            if path_signature != self._signature(path.stat()) or signature != self._signature(os.fstat(container.fp.fileno())):
                raise LayoutError("Runtime container changed during verification")
            self._archive_stats[name] = {"path": path_signature, "handle": signature}
            self.archives[name] = archive
            for entry in entries.values():
                if entry["kind"] == "directory":
                    continue
                logical = entry["logical_path"]
                _register_name(self.entries, logical, "logical file")
                self.entries[logical.casefold()] = {**entry, "archive": name}
            selections = archive.get("selections")
            if not isinstance(selections, list) or not selections:
                raise LayoutError("Missing whole-package/single-module selection inventory")
            selected, packages = set(), set()
            for selection in selections:
                if not isinstance(selection, dict) or selection.get("kind") not in ("package", "module"):
                    raise LayoutError("Invalid archive selection")
                logical = canonical_relative(selection.get("logical_path"))
                _register_name(selection_names, logical, "whole-package/module selection")
                prefix = archive["source_prefix"]
                if prefix and not logical.startswith(prefix + "/"):
                    raise LayoutError("Selection crosses its declared source namespace")
                raw = logical.removeprefix(prefix + "/") if prefix else logical
                if "/" in raw or (not prefix and (raw != "py_src" or selection["kind"] != "package")):
                    raise LayoutError("Only whole top-level packages or named modules are allowed")
                if selection["kind"] == "module":
                    if not raw.endswith(".py"):
                        raise LayoutError("A module selection must name original .py source")
                    selected.add(logical)
                else:
                    if not raw.isidentifier():
                        raise LayoutError("A package selection must name a whole Python package")
                    package_files = {entry["logical_path"] for entry in entries.values()
                                     if entry["kind"] == "file" and entry["logical_path"].startswith(logical + "/")}
                    if not package_files or not any(item.endswith(".py") for item in package_files):
                        raise LayoutError(f"Empty/non-Python package selection: {logical}")
                    if prefix and logical + "/__init__.py" not in package_files:
                        raise LayoutError("Only the host py_src root may be a namespace package")
                    if self.source_hashes is not None and package_files != {item for item in self.source_hashes if item.startswith(logical + "/")}:
                        raise LayoutError("Whole package differs from the external source member set")
                    selected.update(package_files)
                    packages.add(logical)
                for base in {logical, raw, "site-packages/" + raw, "vendor/" + raw}:
                    for loose in self.disk_files:
                        if loose.casefold() == base.casefold() or (selection["kind"] == "package" and loose.casefold().startswith(base.casefold() + "/")):
                            raise LayoutError(f"Loose file shadows archived selection: {loose}")
                    if selection["kind"] == "module" and base.endswith(".py"):
                        stale = base[:-3] + ".pyc"
                        if stale.casefold() in {item.casefold() for item in self.disk_files}:
                            raise LayoutError(f"Loose bytecode shadows archived module: {stale}")
            if selected != {entry["logical_path"] for entry in entries.values() if entry["kind"] == "file"}:
                raise LayoutError("Selection inventory does not match archive contents")
            for entry in entries.values():
                if entry["kind"] != "directory":
                    continue
                logical = entry["logical_path"]
                if (not any(logical == package or logical.startswith(package + "/") for package in packages)
                        and not any(name.startswith(logical + "/") for name in selected)):
                    raise LayoutError("Directory member is outside its selected package/source closure")
        if [item["path"] for item in archives] != sorted(self.archives):
            raise LayoutError("Archive inventory order is not deterministic")
        if root_archives != set(self.archives):
            raise LayoutError("Undeclared/missing runtime container")
        inputs = document.get("inputs_manifest")
        _checksum(inputs, "input inventory")
        inputs_name = canonical_relative(inputs.get("path"))
        if inputs_name != INPUTS_NAME or inputs_name not in self.disk_files:
            raise LayoutError("Missing original input inventory")
        path = self.disk_files[inputs_name]
        if path.stat().st_size != inputs["bytes"] or sha256_file(path) != inputs["sha256"]:
            raise LayoutError("Changed original input inventory")
        inventory = read_json(path)
        records = {}
        for entry in self.entries.values():
            source = entry["source"]
            record_path = source.get("record_path")
            if record_path is None:
                if source.get("record_owner") is not None:
                    raise LayoutError("An owner without its original wheel RECORD is invalid")
                continue
            canonical_relative(record_path)
            record_file = self.disk_files.get(record_path)
            if record_file is None or not record_path.endswith(".dist-info/RECORD") or source.get("record_owner") != Path(record_path).parent.name:
                raise LayoutError("Missing/mismatched original wheel RECORD owner")
            if record_path not in records:
                raw = record_file.read_bytes()
                row_index = {}
                for row in csv.reader(io.StringIO(raw.decode("utf-8-sig"))):
                    if row:
                        row_index.setdefault(row[0], []).append(row)
                records[record_path] = (sha256_bytes(raw), row_index)
            checksum, rows = records[record_path]
            matching = rows.get(source.get("record_member"), [])
            prefix = self.archives[entry["archive"]]["source_prefix"]
            if (checksum != source.get("record_sha256") or len(matching) != 1 or len(matching[0]) != 3
                    or matching[0][1:] != [source.get("record_digest"), source.get("record_bytes")]
                    or entry["logical_path"] != (prefix + "/" if prefix else "") + matching[0][0]
                    or (matching[0][2] and (not matching[0][2].isdigit() or int(matching[0][2]) != entry["bytes"]))):
                raise LayoutError("Original wheel RECORD mapping differs from archived source")
        expected_sources = {item["logical_path"]: {"bytes": item["bytes"], "sha256": item["sha256"], "source": item["source"]}
                            for item in self.entries.values()}
        if not isinstance(inventory, dict) or type(inventory.get("schema_version")) is not int or inventory["schema_version"] != 1 or inventory.get("files") != expected_sources:
            raise LayoutError("Original input inventory differs from archived sources")
        self.manifest = document

    @staticmethod
    def _signature(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def close(self):
        for container in self._containers.values():
            container.close()
        self._containers.clear()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def __del__(self):
        for container in getattr(self, "_containers", {}).values():
            container.close()

    def files(self, prefix=""):
        return tuple(self.iter_files(prefix))

    def iter_files(self, prefix=""):
        if prefix:
            canonical_relative(prefix.rstrip("/"))
            prefix = prefix.rstrip("/") + "/"
        hidden = {self.manifest_name, INPUTS_NAME, MARKER_NAME, *self.archives}
        names = (set(self.disk_files) - hidden) | {item["logical_path"] for item in self.entries.values()}
        return iter(sorted(name for name in names if not prefix or name.startswith(prefix)))

    def read_bytes(self, logical_path):
        logical_path = canonical_relative(logical_path)
        entry = self.entries.get(logical_path.casefold())
        if entry is not None:
            if entry["logical_path"] != logical_path:
                raise LayoutError("Noncanonical case in logical lookup")
            name = entry["archive"]
            path = plain_path(self.root / name)
            container = self._containers.get(name)
            if container is None:
                raise LayoutError("The audited layout has been closed")
            if not path.is_file() or self._signature(path.stat()) != self._archive_stats[name]["path"] or self._signature(os.fstat(container.fp.fileno())) != self._archive_stats[name]["handle"]:
                raise LayoutError("Runtime container changed after verification")
            try:
                data = container.read(entry["member"])
            except (OSError, KeyError, RuntimeError, zipfile.BadZipFile) as exc:
                raise LayoutError("Cannot read declared runtime member") from exc
            if len(data) != entry["bytes"] or sha256_bytes(data) != entry["sha256"]:
                raise LayoutError("Runtime member changed after verification")
            return data
        path = plain_path(self.root / logical_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        data = path.read_bytes()
        if self.source_hashes is not None and logical_path in self.source_hashes and sha256_bytes(data) != self.source_hashes[logical_path]:
            raise LayoutError("Loose source differs from external source hashes")
        return data

    def summary(self):
        return {"mode": "archived" if self.manifest is not None else "loose", "archives": list(self.archives.values()),
                "file_count": sum(1 for _ in self.iter_files()), "archived_files": len(self.entries),
                "source_binding": "external-hashes-verified" if self.source_hashes is not None else "not-proven-by-layout"}


def load_layout(root, *, source_hashes=None, manifest_name=MANIFEST_NAME):
    return RuntimeArchiveLayout(root, source_hashes=source_hashes, manifest_name=manifest_name)


def verify_layout(root, *, source_hashes=None, manifest_name=MANIFEST_NAME):
    with load_layout(root, source_hashes=source_hashes, manifest_name=manifest_name) as view:
        return view.summary()


def iter_logical_files(root, *, prefix="", source_hashes=None, manifest_name=MANIFEST_NAME):
    with load_layout(root, source_hashes=source_hashes, manifest_name=manifest_name) as view:
        return iter(view.files(prefix))


def read_logical_bytes(root, logical_path, *, source_hashes=None, manifest_name=MANIFEST_NAME):
    with load_layout(root, source_hashes=source_hashes, manifest_name=manifest_name) as view:
        return view.read_bytes(logical_path)
