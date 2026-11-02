"""Select whole pure-Python packages/modules into deterministic Stored ZIPs.

Only a fresh, unoccupied, not-yet-frozen build candidate may be transformed.
This tool never patches Python/manifest files, compiles bytecode, extracts a
runtime archive, or prunes dependencies/licenses/tests. Qt/RCC resources stay
loose in this workline. The recorded input hashes are NOT external provenance.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import uuid
import zipfile

# Also works under -I and when loaded by an audit tool with spec_from_file_location.
_spec = importlib.util.spec_from_file_location("umi_runtime_archive_layout", Path(__file__).with_name("runtime_archive_layout.py"))
layout = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(layout)
LayoutError = layout.LayoutError
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_POLICIES = {
    "host": {"schema_version": 1, "kind": "host", "archives": [
        {"path": "app.zip", "source_prefix": "", "packages": ["py_src"], "modules": [], "required": True},
        {"path": "dependencies.zip", "source_prefix": "site-packages", "packages": [], "modules": ["bottle.py", "six.py"]},
    ]},
    "plugin": {"schema_version": 1, "kind": "plugin", "archives": [
        {"path": "vendor.zip", "source_prefix": "vendor", "packages": ["idna", "packaging"], "modules": ["six.py", "typing_extensions.py"]},
    ]},
}
# These require real paths/native loaders or have not been approved for relocation.
EXTERNAL_PACKAGES = layout.EXTERNAL_PACKAGES
FORBIDDEN_SUFFIXES = layout.EXTERNAL_SUFFIXES
DATA_SUFFIXES = frozenset((
    ".py", ".pyi", ".typed", ".txt", ".csv", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".xml",
    ".html", ".htm", ".md", ".rst", ".css", ".js", ".png", ".jpg", ".jpeg", ".svg", ".gif", ".ico",
    ".dat", ".h", ".hpp", ".c", ".cpp", ".pxd", ".in", ".mako", ".jinja2", ".j2", ".xsl", ".xsd", ".dtd",
))
SPECIAL_DATA_NAMES = frozenset({"LICENSE", "LICENCE", "COPYING", "NOTICE", "AUTHORS", "VERSION", "README", "Makefile", ".keep"})


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _write_new(path, data):
    with path.open("xb") as stream:
        stream.write(data)


def _replace_marker(root, value):
    temporary = root / (layout.MARKER_NAME + ".tmp-" + uuid.uuid4().hex)
    _write_new(temporary, _json_bytes(value))
    os.replace(temporary, root / layout.MARKER_NAME)


def _inside(path, parent):
    path = os.path.normcase(os.path.abspath(path))
    parent = os.path.normcase(os.path.abspath(parent))
    try:
        return os.path.commonpath([path, parent]) == parent
    except ValueError:
        return False


def running_processes(root):
    """Find executables/scripts running from the candidate, without killing any."""
    root = layout.plain_path(root)
    processes = []
    if os.name == "nt":
        command = ("$ErrorActionPreference='Stop'; "
                   "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); "
                   "@(Get-CimInstance Win32_Process | Select-Object ProcessId,ExecutablePath,CommandLine) | ConvertTo-Json -Compress")
        try:
            result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                                    cwd=PROJECT_ROOT, stdin=subprocess.DEVNULL, capture_output=True, timeout=60, check=True)
            rows = json.loads(result.stdout.decode("utf-8-sig"))
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise LayoutError("Cannot establish candidate process occupancy") from exc
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list):
            raise LayoutError("Invalid candidate process inventory")
        for row in rows:
            if row.get("ProcessId") == os.getpid():
                continue
            executable = row.get("ExecutablePath")
            candidates = [executable] if executable else []
            # Existing file arguments catch external python.exe worker.py launches;
            # directory-valued --staging/--output arguments are not running code.
            for quoted, bare in re.findall(r'"([^\"]+)"|(\S+)', row.get("CommandLine") or ""):
                value = quoted or bare
                if Path(value).is_absolute() and Path(value).suffix.lower() in {".py", ".pyw", ".exe", ".dll", ".pyd", ".zip"}:
                    candidates.append(value)
            if any(_inside(value, root) for value in candidates):
                processes.append({"pid": row["ProcessId"], "executable": executable})
    else:
        proc = Path("/proc")
        if not proc.is_dir():
            raise LayoutError("No supported process-occupancy inventory on this platform")
        for directory in proc.iterdir():
            if not directory.name.isdigit() or int(directory.name) == os.getpid():
                continue
            try:
                executable = os.readlink(directory / "exe")
                arguments = (directory / "cmdline").read_bytes().split(b"\0")
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                continue
            candidates = [executable]
            candidates.extend(os.fsdecode(value) for value in arguments if value and os.path.isabs(os.fsdecode(value))
                              and Path(os.fsdecode(value)).suffix.lower() in {".py", ".pyw", ".exe", ".so", ".zip"})
            if any(_inside(value, root) for value in candidates):
                processes.append({"pid": int(directory.name), "executable": executable})
    return processes


def _reject_frozen(root, project_root):
    # finalize_release stores its freeze record outside the product, under audit/.
    # Inspect the small header first, then parse only actual freeze records.
    audit = project_root / "build/audit"
    if not audit.is_dir():
        return
    for directory, directories, filenames in os.walk(audit, followlinks=False):
        directories[:] = [name for name in directories
                          if not Path(directory, name).is_symlink()
                          and not getattr(Path(directory, name), "is_junction", lambda: False)()]
        for name in filenames:
            if not name.endswith(".json"):
                continue
            path = Path(directory) / name
            layout.reject_link(path)
            try:
                with path.open("rb") as stream:
                    header = stream.read(16384)
            except OSError as exc:
                raise LayoutError("Cannot establish the existing freeze-record boundary") from exc
            if b"immutable-review-product-not-approval" not in header:
                continue
            record = layout.read_json(path)
            frozen = record.get("package_root") if isinstance(record, dict) else None
            if not isinstance(frozen, str):
                raise LayoutError(f"Invalid existing freeze record: {path}")
            if _inside(root, frozen) or _inside(frozen, root):
                raise LayoutError(f"Candidate belongs to an already frozen product: {path}")


def _check_candidate(root, project_root, occupancy_check):
    root, project_root = layout.plain_path(root), layout.plain_path(project_root)
    build = layout.plain_path(project_root / "build")
    if not build.is_dir() or build not in root.parents:
        raise LayoutError("Runtime aggregation is restricted to a fresh project build candidate")
    relative = root.relative_to(build)
    if any("seed" in part.casefold() or part.casefold() == "release" or "frozen" in part.casefold()
           for part in relative.parts):
        raise LayoutError("Seed/release/frozen trees cannot be aggregated")
    layout.tree_files(root)
    _reject_frozen(root, project_root)
    busy = occupancy_check(root)
    if busy:
        raise LayoutError(f"Candidate is in use; ask its owner to exit normally: {busy}")
    return root, project_root


def _policy(kind, policy):
    if kind not in DEFAULT_POLICIES:
        raise LayoutError("Only host and explicitly selected CUDA/VL plugin layouts are supported")
    value = DEFAULT_POLICIES[kind] if policy is None else policy
    if (not isinstance(value, dict) or type(value.get("schema_version")) is not int
            or value["schema_version"] != 1 or value.get("kind") != kind or not isinstance(value.get("archives"), list)):
        raise LayoutError("An explicit versioned policy for the selected component kind is required")
    output, archive_names, selections = [], set(), set()
    for record in value["archives"]:
        if not isinstance(record, dict):
            raise LayoutError("Invalid policy archive")
        name = layout.canonical_relative(record.get("path"))
        prefix = record.get("source_prefix")
        if ("/" in name or not name.endswith(".zip") or name.casefold() in archive_names or not isinstance(prefix, str)
                or prefix not in ({"", "site-packages"} if kind == "host" else {"vendor"})):
            raise LayoutError("Invalid/colliding archive name or component source prefix")
        archive_names.add(name.casefold())
        packages, modules = record.get("packages", []), record.get("modules", [])
        if not isinstance(packages, list) or not isinstance(modules, list):
            raise LayoutError("Policy packages/modules must be explicit lists")
        if not prefix and (modules or packages != ["py_src"]):
            raise LayoutError("Host entry points stay loose; only the whole py_src namespace is eligible at the data root")
        extra = record.get("data_suffixes", [])
        if not isinstance(extra, list) or any(not isinstance(item, str) or not item.startswith(".")
                                               or "/" in item or "\\" in item or item.lower() in FORBIDDEN_SUFFIXES for item in extra):
            raise LayoutError("Invalid policy data suffixes")
        normalized = {"path": name, "source_prefix": prefix, "packages": [], "modules": [],
                      "required": bool(record.get("required", False)), "data_suffixes": sorted(set(extra))}
        for category, items in (("packages", packages), ("modules", modules)):
            for item in items:
                layout.canonical_relative(item)
                if "/" in item or (category == "packages" and not item.isidentifier()) or (category == "modules" and not item.endswith(".py")):
                    raise LayoutError("Only whole top-level packages or explicitly named .py modules may be selected")
                if item.split(".")[0].casefold() in EXTERNAL_PACKAGES:
                    raise LayoutError(f"Package must remain external: {item}")
                logical = (prefix + "/" if prefix else "") + item
                if logical.casefold() in selections:
                    raise LayoutError(f"Overlapping policy selection: {logical}")
                selections.add(logical.casefold())
                normalized[category].append(item)
        output.append(normalized)
    return {"schema_version": 1, "kind": kind, "archives": sorted(output, key=lambda item: item["path"])}


def _record_owners(root, prefix, selected):
    base = root / prefix
    owners = {}
    if not base.is_dir():
        return owners
    for path in sorted(base.glob("*.dist-info/RECORD")):
        layout.reject_link(path)
        data = path.read_bytes()
        for row in csv.reader(io.StringIO(data.decode("utf-8-sig"))):
            if not row:
                continue
            member = row[0]
            logical = (prefix + "/" if prefix else "") + member
            if logical not in selected:
                continue
            layout.canonical_relative(member)
            if logical in owners or len(row) != 3:
                raise LayoutError(f"Ambiguous/malformed wheel RECORD ownership: {logical}")
            owners[logical] = {"record_owner": path.parent.name, "record_path": path.relative_to(root).as_posix(),
                               "record_sha256": layout.sha256_bytes(data), "record_member": member,
                               "record_digest": row[1], "record_bytes": row[2]}
    return owners


def _check_record(data, source):
    checksum, size = source.get("record_digest"), source.get("record_bytes")
    if size and (not size.isdigit() or int(size) != len(data)):
        raise LayoutError("Input differs from its original wheel RECORD size")
    if checksum:
        algorithm, separator, encoded = checksum.partition("=")
        if not separator or algorithm not in {"sha256", "sha384", "sha512"}:
            raise LayoutError("Unsupported original wheel RECORD hash")
        actual = base64.urlsafe_b64encode(hashlib.new(algorithm, data).digest()).rstrip(b"=").decode("ascii")
        if actual != encoded:
            raise LayoutError("Input differs from its original wheel RECORD hash")


def _collect(root, kind, policy, source_hashes):
    disk = layout.tree_files(root)
    plans, retained, payloads = [], [], {}
    for rule in policy["archives"]:
        prefix = rule["source_prefix"]
        selected, selection_records, package_directories = {}, [], set()
        for category, items in (("packages", rule["packages"]), ("modules", rule["modules"])):
            for item in items:
                logical = (prefix + "/" if prefix else "") + item
                target = root / logical
                if not target.exists():
                    if rule["required"]:
                        raise LayoutError(f"Required policy input is missing: {logical}")
                    retained.append({"logical_path": logical, "reason": "allowlisted-but-not-installed"})
                    continue
                if category == "modules":
                    if not target.is_file():
                        raise LayoutError(f"Expected an explicitly named .py file: {logical}")
                    names = [logical]
                    if target.with_suffix(".pyc").exists():
                        raise LayoutError(f"Stale loose bytecode accompanies selected source: {logical}")
                else:
                    if not target.is_dir() or (not (target / "__init__.py").is_file() and not (kind == "host" and prefix == "" and item == "py_src")):
                        raise LayoutError(f"Expected a whole regular package (or host py_src namespace): {logical}")
                    names = sorted(name for name in disk if name.startswith(logical + "/"))
                    if not any(name.endswith(".py") for name in names):
                        raise LayoutError(f"Selected package has no original Python source: {logical}")
                    if source_hashes is not None and set(names) != {name for name in source_hashes if name.startswith(logical + "/")}:
                        raise LayoutError(f"Whole package member set differs from externally supplied source hashes: {logical}")
                    for directory, children, _files in os.walk(target, followlinks=False):
                        path = Path(directory)
                        layout.reject_link(path)
                        for child in children:
                            layout.reject_link(path / child)
                        parts = path.relative_to(target).parts
                        if any(part.casefold() in {"__pycache__", "models", "model", "native", "qt_res", ".settings", "logs", "temp", "temp_doc"} for part in parts):
                            raise LayoutError(f"Selected package contains a cache/native/model/state directory: {path.relative_to(root)}")
                        package_directories.add(path.relative_to(root).as_posix())
                for name in names:
                    relative = Path(name).relative_to(logical) if category == "packages" else Path(name).name
                    parts = Path(relative).parts
                    path = disk[name]
                    suffix = path.suffix.lower()
                    if ("__pycache__" in parts or any(part.casefold() in {"models", "model", "native", "qt_res", ".settings", "logs", "temp", "temp_doc"} for part in parts)
                            or suffix in FORBIDDEN_SUFFIXES or ".so." in path.name
                            or (suffix not in DATA_SUFFIXES | set(rule["data_suffixes"]) and path.name not in SPECIAL_DATA_NAMES)):
                        raise LayoutError(f"Selected package contains native/cache/model/Qt/unknown content; leave it external: {name}")
                    if name in payloads:
                        raise LayoutError(f"Input selected more than once: {name}")
                    data = path.read_bytes()
                    checksum = layout.sha256_bytes(data)
                    if source_hashes is not None and source_hashes.get(name) != checksum:
                        raise LayoutError(f"Input differs from externally supplied source hashes: {name}")
                    payloads[name] = data
                    selected[name] = {"kind": "file", "logical_path": name, "member": name.removeprefix(prefix + "/") if prefix else name,
                                      "bytes": len(data), "sha256": checksum,
                                      "source": {"logical_path": name, "sha256": checksum, "record_owner": None, "record_path": None}}
                selection_records.append({"logical_path": logical, "kind": "package" if category == "packages" else "module"})
        owners = _record_owners(root, prefix, selected)
        for name, owner in owners.items():
            selected[name]["source"].update(owner)
            _check_record(payloads[name], owner)
        if selected:
            members = {entry["member"]: entry for entry in selected.values()}
            for entry in list(members.values()):
                for parent in Path(entry["member"]).parents:
                    if str(parent) == ".":
                        continue
                    member = parent.as_posix() + "/"
                    logical = (prefix + "/" if prefix else "") + parent.as_posix()
                    members[member] = {"kind": "directory", "logical_path": logical, "member": member, "bytes": 0,
                                       "sha256": layout.EMPTY_SHA256, "source": {"logical_path": logical, "sha256": layout.EMPTY_SHA256,
                                                                                  "record_owner": None, "record_path": None}}
            for logical in package_directories:
                member = (logical.removeprefix(prefix + "/") if prefix else logical) + "/"
                members[member] = {"kind": "directory", "logical_path": logical, "member": member, "bytes": 0,
                                   "sha256": layout.EMPTY_SHA256, "source": {"logical_path": logical, "sha256": layout.EMPTY_SHA256,
                                                                              "record_owner": None, "record_path": None}}
            plans.append({"path": rule["path"], "source_prefix": prefix,
                          "selections": sorted(selection_records, key=lambda item: item["logical_path"]),
                          "members": [members[name] for name in sorted(members)]})
        base = root / prefix
        if base.is_dir():
            selected_top = set(rule["packages"] + rule["modules"])
            for path in sorted(base.iterdir()):
                if path.name in selected_top:
                    continue
                reason = "not-allowlisted"
                if path.name.endswith(".dist-info"):
                    reason = "metadata-and-notices-retained"
                elif path.name.casefold() in EXTERNAL_PACKAGES or path.suffix.lower() in FORBIDDEN_SUFFIXES:
                    reason = "native-model-Qt-or-real-path-content-remains-external"
                retained.append({"logical_path": path.relative_to(root).as_posix(), "reason": reason})
    return plans, payloads, sorted(retained, key=lambda item: (item["logical_path"], item["reason"]))


def _write_zip(root, plan, payloads):
    path = root / plan["path"]
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_STORED, allowZip64=False) as container:
        for member in plan["members"]:
            info = zipfile.ZipInfo(member["member"], layout.TIMESTAMP)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            is_dir = member["kind"] == "directory"
            info.external_attr = ((stat.S_IFDIR | 0o755) if is_dir else (stat.S_IFREG | 0o644)) << 16
            if is_dir:
                info.external_attr |= 0x10
            container.writestr(info, b"" if is_dir else payloads[member["logical_path"]])
    plan.update({"bytes": path.stat().st_size, "sha256": layout.sha256_file(path)})
    layout.verify_archive(root, plan)


def aggregate_runtime(root, *, kind, policy=None, source_hashes=None, source_manifest=None,
                      project_root=PROJECT_ROOT, occupancy_check=None):
    """Transform only the explicitly selected original files in a fresh candidate.

    ``occupancy_check`` is injectable for isolated unit fixtures; production CLI
    always uses the real process inventory. Never use it to bypass a busy tree.
    All predictable errors are checked before deletion. Unexpected I/O failures
    restore removed source bytes from the in-memory input snapshot, not a ZIP.
    """
    occupancy_check = running_processes if occupancy_check is None else occupancy_check
    root, project_root = _check_candidate(root, project_root, occupancy_check)
    if source_manifest is not None:
        if source_hashes is not None:
            raise LayoutError("Choose source_hashes or source_manifest, not both")
        source_path = layout.plain_path(source_manifest)
        if _inside(source_path, root):
            raise LayoutError("The input layout cannot serve as its own external source evidence")
        source_hashes = layout.load_source_hashes(source_path)
    source_hashes = layout.normalize_source_hashes(source_hashes)
    policy = _policy(kind, policy)
    reserved = {layout.MANIFEST_NAME, layout.INPUTS_NAME, layout.MARKER_NAME, "archive-layout.json", *layout.RUNTIME_ARCHIVES,
                *(item["path"] for item in policy["archives"])}
    for name in reserved:
        if (root / name).exists():
            raise LayoutError(f"Candidate is not fresh; refusing an existing archive/assembly record: {name}")
    if any(path.suffix.lower() == ".zip" for path in root.iterdir()):
        raise LayoutError("Candidate already contains a root-level archive")
    # Preparation/audit receipts identify a previously consumed tree, not a fresh
    # staging input. External finalizer freeze records are checked separately.
    for path in (root, *[parent for parent in root.parents if parent != project_root / "build" and project_root / "build" in parent.parents]):
        if any((path / name).exists() for name in ("finalized-product.json", "product-freeze.json", "frozen-product.json")):
            raise LayoutError("An existing frozen/finalized product cannot be transformed")
    plans, payloads, retained = _collect(root, kind, policy, source_hashes)
    marker = {"schema_version": 1, "purpose": "fresh-runtime-archive-assembly", "state": "assembling"}
    _write_new(root / layout.MARKER_NAME, _json_bytes(marker))
    created, removed, removed_dirs = [], [], []
    try:
        files = {member["logical_path"]: {"bytes": member["bytes"], "sha256": member["sha256"], "source": member["source"]}
                 for plan in plans for member in plan["members"] if member["kind"] == "file"}
        inputs = {"schema_version": 1, "files": files,
                  "source_binding": "external-hashes-supplied" if source_hashes is not None else "self-recorded-not-external-source-proof"}
        _write_new(root / layout.INPUTS_NAME, _json_bytes(inputs))
        for plan in plans:
            created.append(root / plan["path"])
            _write_zip(root, plan, payloads)
        # Complete preflight again immediately before any original is removed.
        _check_candidate(root, project_root, occupancy_check)
        for plan in plans:
            layout.verify_archive(root, plan, source_hashes=source_hashes)
            for selection in plan["selections"]:
                if selection["kind"] == "package":
                    current = layout.tree_files(root / selection["logical_path"])
                    current = {selection["logical_path"] + "/" + name for name in current}
                    expected = {name for name in payloads if name.startswith(selection["logical_path"] + "/")}
                    if current != expected:
                        raise LayoutError("Selected package changed during assembly")
        for name, data in payloads.items():
            path = root / name
            layout.reject_link(path)
            if not path.is_file() or path.read_bytes() != data:
                raise LayoutError(f"Original input changed during assembly: {name}")
        for name in sorted(payloads):
            (root / name).unlink()
            removed.append(name)
        directories = {member["logical_path"] for plan in plans for member in plan["members"] if member["kind"] == "directory"}
        for name in sorted(directories, key=lambda item: (-item.count("/"), item)):
            path = root / name
            if path.is_dir() and not any(path.iterdir()):
                path.rmdir()
                removed_dirs.append(name)
        inputs_path = root / layout.INPUTS_NAME
        document = {"schema_version": 1, "format": layout.FORMAT, "state": "complete", "kind": kind, "archives": plans,
                    "policy": policy, "external": retained, "resources": "Qt/QML/RCC and real-path resources remain external; RCC not generated",
                    "source_proof": "Layout/input hashes do not prove upstream provenance; verify independent wheel/seed/source hashes",
                    "inputs_manifest": {"path": layout.INPUTS_NAME, "bytes": inputs_path.stat().st_size, "sha256": layout.sha256_file(inputs_path)}}
        created.append(root / layout.MANIFEST_NAME)
        _write_new(root / layout.MANIFEST_NAME, _json_bytes(document))
        _replace_marker(root, {**marker, "state": "complete"})
        layout.verify_layout(root, source_hashes=source_hashes)
        return document
    except BaseException as exc:
        recovery_errors = []
        for name in removed:
            try:
                path = root / name
                layout.plain_path(path.parent)
                path.parent.mkdir(parents=True, exist_ok=True)
                _write_new(path, payloads[name])
            except BaseException as recovery:
                recovery_errors.append(f"{name}: {recovery}")
        # Keep the input inventory and failed marker as evidence. Only outputs
        # owned by this invocation may be removed, and never from a busy tree.
        try:
            if occupancy_check(root):
                raise LayoutError("Candidate became occupied; retaining generated outputs")
            for path in reversed(created):
                layout.reject_link(path)
                if path.is_file():
                    path.unlink()
        except BaseException as recovery:
            recovery_errors.append(str(recovery))
        _replace_marker(root, {**marker, "state": "failed", "error": str(exc), "recovery_errors": recovery_errors})
        if recovery_errors:
            raise LayoutError(f"Assembly failed; retained input inventory/outputs need review: {recovery_errors}") from exc
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--kind", choices=("host", "plugin"), required=True)
    parser.add_argument("--policy", type=Path, help="Explicit versioned whole-package/module allowlist")
    parser.add_argument("--source-manifest", type=Path, help="Independent root-relative source SHA-256 mapping (or sourceHashes object)")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT,
                        help="显式的授权组件项目根；仍只允许该项目build内的全新候选")
    args = parser.parse_args(argv)
    try:
        policy = layout.read_json(layout.plain_path(args.policy)) if args.policy else None
        result = aggregate_runtime(args.root, kind=args.kind, policy=policy,
                                   source_manifest=args.source_manifest, project_root=args.project_root)
        print(json.dumps({"archives": [item["path"] for item in result["archives"]],
                          "merged_files": sum(member["kind"] == "file" for item in result["archives"] for member in item["members"]),
                          "source_provenance": "NOT_PROVEN_BY_LAYOUT", "runtime_acceptance": "NOT_RUN"}, ensure_ascii=False))
        return 0
    except (LayoutError, OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"runtime aggregation error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
