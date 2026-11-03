"""有界、逐字节校验的源码/发行归档分块；不覆盖现存目标，不执行分块内容。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

_spec = importlib.util.spec_from_file_location("umi_chunk_paths", Path(__file__).with_name("runtime_archive_layout.py"))
layout = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(layout)

SOURCE_INDEX = ".source-chunks.json"
ARCHIVE_INDEX = "archive-chunks.json"
SOURCE_PART_BYTES = 48 * 1024**2
ARCHIVE_PART_BYTES = 1536 * 1024**2
GIT_LIMIT = 100 * 1024**2
INDEX_LIMIT = 1024**2
BUFFER_BYTES = 1024**2
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
POLICIES = {
    "source": {"prefix": ".source-chunks", "part": 64 * 1024**2, "file": 4 * 1024**3, "total": 8 * 1024**3, "files": 16},
    "archive": {"prefix": ".archive-chunks", "part": ARCHIVE_PART_BYTES, "file": 16 * 1024**3, "total": 32 * 1024**3, "files": 8},
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _checksum(value):
    require(isinstance(value, str) and _SHA256.fullmatch(value), "分块SHA256无效")
    return value


def _integer(value, maximum):
    require(type(value) is int and 0 < value <= maximum, "分块大小或预算无效")
    return value


def part_path(purpose, name, checksum, number):
    if purpose == "archive":
        return f"{name}.{number:03d}"
    identity = hashlib.sha256((name + "\0" + checksum).encode("utf-8")).hexdigest()
    return f"{POLICIES[purpose]['prefix']}/{identity}/{number:06d}.part"


def validate_index(document, purpose):
    require(purpose in POLICIES, "未知分块用途")
    policy = POLICIES[purpose]
    require(isinstance(document, dict) and set(document) == {"schema_version", "format", "files"}, "分块索引字段不完整或包含未知字段")
    require(type(document["schema_version"]) is int and document["schema_version"] == 1
            and document["format"] == f"umi-{purpose}-chunks-v1", "分块索引格式或用途不匹配")
    files = document["files"]
    require(type(files) is list and 0 < len(files) <= policy["files"], "分块文件数量超过预算")
    names, part_names, total = set(), set(), 0
    for item in files:
        require(isinstance(item, dict) and set(item) == {"path", "bytes", "sha256", "parts"}, "分块文件声明无效")
        name = layout.canonical_relative(item["path"])
        require(name.casefold() not in names, "分块逻辑路径重复")
        names.add(name.casefold())
        if purpose == "source":
            require(name.startswith("third_party/") and name.endswith((".tar.xz", ".tar.gz", ".tar.bz2", ".zip")), "只允许第三方源码归档使用Git分块")
        else:
            require("/" not in name and name.endswith(".tar.xz"), "发行分卷必须指向一个根目录tar.xz文件")
        size = _integer(item["bytes"], policy["file"])
        checksum = _checksum(item["sha256"])
        parts = item["parts"]
        require(type(parts) is list and 0 < len(parts) <= 256, "分块数量超过预算")
        sizes = []
        for number, part in enumerate(parts, 1):
            require(isinstance(part, dict) and set(part) == {"path", "bytes", "sha256"}, "分块成员字段无效")
            path = layout.canonical_relative(part["path"])
            require(path == part_path(purpose, name, checksum, number), "分块路径、顺序或身份无效")
            require(path.casefold() not in part_names, "分块成员重复")
            part_names.add(path.casefold())
            sizes.append(_integer(part["bytes"], policy["part"]))
            _checksum(part["sha256"])
        require(sum(sizes) == size and all(value == sizes[0] for value in sizes[:-1]) and sizes[-1] <= sizes[0], "分块长度之和或非末块长度不符")
        total += size
    require(total <= policy["total"], "分块总大小超过预算")
    return document


def _object(pairs):
    result = {}
    for name, value in pairs:
        require(name not in result, "分块索引含重复JSON键")
        result[name] = value
    return result


def parse_index(content, purpose):
    require(isinstance(content, bytes) and len(content) <= INDEX_LIMIT, "分块索引超过大小预算")
    return validate_index(json.loads(content.decode("utf-8-sig"), object_pairs_hook=_object), purpose)


def read_index(path, purpose):
    path = layout.plain_path(path)
    require(path.is_file() and path.stat().st_size <= INDEX_LIMIT, "分块索引文件缺失或过大")
    return parse_index(path.read_bytes(), purpose)


def write_index(path, document, purpose):
    validate_index(document, purpose)
    path = layout.plain_path(path)
    content = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    require(len(content) <= INDEX_LIMIT, "分块索引超过大小预算")
    with path.open("xb") as stream:
        stream.write(content)


def split_file(source, root, name, purpose, part_bytes):
    require(purpose in POLICIES, "未知分块用途")
    source, root = layout.plain_path(source), layout.plain_path(root)
    name = layout.canonical_relative(name)
    if purpose == "source":
        require(name.startswith("third_party/") and name.endswith((".tar.xz", ".tar.gz", ".tar.bz2", ".zip")), "只允许第三方源码归档使用Git分块")
    else:
        require("/" not in name and name.endswith(".tar.xz"), "发行分卷必须指向一个根目录tar.xz文件")
    require(source.is_file() and root.is_dir(), "分块输入或输出根无效")
    policy = POLICIES[purpose]
    _integer(part_bytes, policy["part"])
    size = _integer(source.stat().st_size, policy["file"])
    require((size + part_bytes - 1) // part_bytes <= 256, "分块数量超过预算")
    checksum = layout.sha256_file(source)
    whole, parts, total = hashlib.sha256(), [], 0
    with source.open("rb") as stream:
        number = 0
        while total < size:
            number += 1
            relative = part_path(purpose, name, checksum, number)
            path = layout.plain_path(root / relative)
            require(not path.exists(), "不覆盖现存分块")
            path.parent.mkdir(parents=True, exist_ok=True)
            count, digest = 0, hashlib.sha256()
            expected = min(part_bytes, size - total)
            with path.open("xb") as output:
                while count < expected:
                    chunk = stream.read(min(BUFFER_BYTES, expected - count))
                    require(bool(chunk), "分块期间源文件变短")
                    output.write(chunk)
                    digest.update(chunk)
                    whole.update(chunk)
                    count += len(chunk)
            total += count
            parts.append({"path": relative, "bytes": count, "sha256": digest.hexdigest()})
        require(not stream.read(1) and os.fstat(stream.fileno()).st_size == size, "分块期间源文件大小变化")
    require(whole.hexdigest() == checksum, "分块期间源文件字节变化")
    result = {"path": name, "bytes": size, "sha256": checksum, "parts": parts}
    validate_index({"schema_version": 1, "format": f"umi-{purpose}-chunks-v1", "files": [result]}, purpose)
    return result


def _commit_new(temporary, target):
    # Windows rename天然拒绝现存目标；POSIX用同目录原子新建链接再移除自有临时名，最终只有一个普通文件。
    if os.name == "nt":
        os.rename(temporary, target)
    else:
        os.link(temporary, target, follow_symlinks=False)
        temporary.unlink()


def restore(root, document, purpose, output_root=None):
    validate_index(document, purpose)
    root = layout.plain_path(root)
    destination = layout.plain_path(output_root or root)
    require(root.is_dir() and destination.is_dir(), "恢复的输入/输出根目录必须已存在")
    for item in document["files"]:
        target = layout.plain_path(destination / item["path"])
        require(not target.exists(), "不覆盖已存在的恢复目标：" + item["path"])
        for part in item["parts"]:
            path = layout.plain_path(root / part["path"])
            require(path.is_file() and path.stat().st_size == part["bytes"], "分块缺失或长度不符")
    required = sum(item["bytes"] for item in document["files"])
    require(shutil.disk_usage(destination).free >= required + 16 * 1024**2, "恢复目标空间不足，不删除其它数据腾空间")
    results = []
    for item in document["files"]:
        target = layout.plain_path(destination / item["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".restore-", suffix=".partial", dir=target.parent)
        temporary = Path(temporary_name)
        try:
            whole, total = hashlib.sha256(), 0
            with os.fdopen(descriptor, "wb") as output:
                for part in item["parts"]:
                    digest, count = hashlib.sha256(), 0
                    with layout.plain_path(root / part["path"]).open("rb") as stream:
                        for chunk in iter(lambda: stream.read(BUFFER_BYTES), b""):
                            count += len(chunk)
                            require(count <= part["bytes"], "恢复期间分块变大")
                            output.write(chunk)
                            digest.update(chunk)
                            whole.update(chunk)
                    require(count == part["bytes"] and digest.hexdigest() == part["sha256"], "分块字节或SHA256不符")
                    total += count
                output.flush()
                os.fsync(output.fileno())
            require(total == item["bytes"] and whole.hexdigest() == item["sha256"], "完整恢复文件大小或SHA256不符")
            layout.plain_path(target)
            _commit_new(temporary, target)
            results.append({"path": str(target), "bytes": total, "sha256": whole.hexdigest()})
        finally:
            if temporary.exists():
                # 只删除本次mkstemp创建且仍是普通单链接的未完成文件，不接触既有目标或输入。
                layout.plain_path(temporary).unlink()
    return results


def encode_sources(source, destination, *, threshold=GIT_LIMIT, part_bytes=SOURCE_PART_BYTES):
    source, destination = layout.plain_path(source), layout.plain_path(destination)
    require(not destination.exists() and source.is_dir(), "源码镜像输出必须全新")
    require(not destination.is_relative_to(source) and not source.is_relative_to(destination), "源码输入输出不能嵌套")
    require(type(threshold) is int and 0 < threshold <= GIT_LIMIT, "Git文件预算无效")
    paths = layout.tree_files(source)
    require(SOURCE_INDEX not in paths and not any(name.startswith(POLICIES["source"]["prefix"] + "/") for name in paths), "canonical源码不能混入分块表示")
    oversized = [name for name, path in paths.items() if path.stat().st_size >= threshold]
    require(len(oversized) <= POLICIES["source"]["files"], "超限源码数量超过预算")
    for name in oversized:
        require(name.startswith("third_party/") and name.endswith((".tar.xz", ".tar.gz", ".tar.bz2", ".zip")), "不能将普通代码或未知大文件隐藏到分块")
    destination.mkdir(parents=False)
    records = []
    for name, path in paths.items():
        if name in oversized:
            records.append(split_file(path, destination, name, "source", part_bytes))
        else:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            checksum = layout.sha256_file(path)
            shutil.copy2(path, target)
            require(layout.sha256_file(target) == checksum, "源码复制期间字节变化")
    document = {"schema_version": 1, "format": "umi-source-chunks-v1", "files": records}
    if records:
        write_index(destination / SOURCE_INDEX, document, "source")
    return {"sourceFiles": len(paths), "chunkedFiles": len(records), "destination": str(destination), "index": document if records else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    encode = sub.add_parser("source-mirror")
    encode.add_argument("--source", type=Path, required=True)
    encode.add_argument("--output", type=Path, required=True)
    archive = sub.add_parser("split-archive")
    archive.add_argument("--source", type=Path, required=True)
    archive.add_argument("--output", type=Path, required=True)
    recover = sub.add_parser("restore")
    recover.add_argument("--root", type=Path, required=True)
    recover.add_argument("--purpose", choices=tuple(POLICIES), required=True)
    recover.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "source-mirror":
        result = encode_sources(args.source, args.output)
    elif args.command == "split-archive":
        output = layout.plain_path(args.output)
        require(not output.exists() and output.parent.is_dir(), "发行分卷输出必须全新且父目录已存在")
        output.mkdir()
        item = split_file(args.source, output, args.source.name, "archive", ARCHIVE_PART_BYTES)
        document = {"schema_version": 1, "format": "umi-archive-chunks-v1", "files": [item]}
        write_index(output / ARCHIVE_INDEX, document, "archive")
        result = document
    else:
        root = layout.plain_path(args.root)
        name = SOURCE_INDEX if args.purpose == "source" else ARCHIVE_INDEX
        result = restore(root, read_index(root / name, args.purpose), args.purpose, args.output)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
