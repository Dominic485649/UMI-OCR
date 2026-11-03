"""Fail closed if a public tree/archive contains assistant or private state.

This is a packaging check, not a local cleanup operation. Nothing is removed.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import zipfile


PRIVATE_SEGMENTS = {
    ".claude", ".codex", ".agents", "claude.md", "codex.md", "agents.md", "gemini.md",
    ".git", ".settings", ".pre_settings", ".plugins_state", "startup_error.log",
}
ARCHIVE_SUFFIXES = (".zip", ".whl", ".tar", ".tar.xz", ".tar.gz", ".tgz", ".tar.bz2")
FORBIDDEN_PLUGINS = {"win32_paddleocrv6_cpu", "win32_paddleocrvl_1_6"}

# 官方锁定源码中原本公开的协作说明不是本机助手状态。只接受该归档的
# 精确路径、整包SHA256和五个成员；不得按文件名或第三方目录整体豁免。
QT_SOURCE_NAME = "qtwebengine-everywhere-src-6.11.2.tar.xz"
QT_SOURCE_SHA256 = "6101c1aa00ff933d1b65ee5d167f76e8d71b9ac5b378b0111277723ebda7c163"
QT_UPSTREAM_ASSISTANT_FILES = frozenset(
    "qtwebengine-everywhere-src-6.11.2/src/3rdparty/chromium/" + name for name in (
        "agents/extensions/landmines/GEMINI.md",
        "third_party/crossbench/GEMINI.md",
        "third_party/harfbuzz-ng/src/AGENTS.md",
        "third_party/harfbuzz-ng/src/CLAUDE.md",
        "v8/GEMINI.md",
    )
)


def forbidden(name):
    parts = PurePosixPath(name.replace("\\", "/")).parts
    return any(part.casefold() in PRIVATE_SEGMENTS for part in parts)


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def inspect_archive(path):
    if path.name.lower().endswith((".zip", ".whl")):
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
    else:
        with tarfile.open(path, "r:*") as archive:
            names = [member.name for member in archive]
    return [name for name in names if forbidden(name)]


def verify(root, scan_archives=True):
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"Missing public tree: {root}")
    violations = []
    archives = []
    files = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if forbidden(relative):
            violations.append(relative)
        if path.is_symlink():
            violations.append(relative + " (symlink must be reviewed explicitly)")
        if not path.is_file():
            continue
        files.append(relative)
        if scan_archives and path.name.lower().endswith(ARCHIVE_SUFFIXES):
            bad_members = inspect_archive(path)
            checksum = digest(path)
            upstream = []
            if (relative in {"third_party/" + QT_SOURCE_NAME, "source/third_party/" + QT_SOURCE_NAME}
                    and checksum == QT_SOURCE_SHA256):
                upstream = sorted(set(bad_members) & QT_UPSTREAM_ASSISTANT_FILES)
                bad_members = [name for name in bad_members if name not in QT_UPSTREAM_ASSISTANT_FILES]
            record = {"file": relative, "SHA256": checksum, "private_members": bad_members}
            if upstream:
                record["preserved_upstream_assistant_files"] = upstream
            archives.append(record)
            violations.extend(relative + "!" + member for member in bad_members)
    plugins_root = root / "UmiOCR-data/plugins"
    if plugins_root.is_dir():
        for path in plugins_root.iterdir():
            if path.is_dir() and path.name.casefold() in FORBIDDEN_PLUGINS:
                violations.append(path.relative_to(root).as_posix() + " (non-public plugin)")
    return {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "status": "BLOCK" if violations else "PASS",
        "checked_files": len(files),
        "checked_archives": archives,
        "excluded_policy": sorted(PRIVATE_SEGMENTS),
        "violations": sorted(set(violations)),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--no-archives", action="store_true")
    args = parser.parse_args()
    report = verify(args.root, scan_archives=not args.no_archives)
    if args.output:
        output = args.output.resolve()
        if not output.parent.is_dir():
            raise ValueError("Report parent must already exist")
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "checked_files": report["checked_files"],
                      "violations": report["violations"]}, ensure_ascii=False))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
