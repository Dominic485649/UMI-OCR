"""读取已声明的只读运行容器；缺失或损坏时失败，不解包或回退旧散文件。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile


MANIFEST = "runtime-archives.json"
ALLOWED_ARCHIVES = {"host": {"app.zip", "dependencies.zip"}, "plugin": {"vendor.zip"}}


def _plain(path):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & 0x400):
        raise RuntimeError("运行容器必须是普通文件：" + path.name)
    return info


def _relative(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise RuntimeError("运行容器包含无效路径")
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value or any(part in {"", ".", ".."} for part in path.parts):
        raise RuntimeError("运行容器包含越界路径")
    return value


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeError("运行容器声明含重复字段")
        result[key] = value
    return result


def prepare_archives(root, *, kind):
    """返回应挂载的容器，调用者置于私有依赖之前；默认散文件模式不作扫描。"""
    root = Path(root).absolute()
    allowed = ALLOWED_ARCHIVES[kind]
    declaration = root / MANIFEST
    def present(path):
        try:
            path.lstat()
            return True
        except FileNotFoundError:
            return False
    marker = root / ".runtime-archive-candidate.json"
    if present(root / "archive-layout.json"):
        raise RuntimeError("存在不受支持的旧运行容器声明")
    if present(marker):
        if _plain(marker).st_size > 65536:
            raise RuntimeError("运行容器装配状态过大")
        state = json.loads(marker.read_text(encoding="utf-8"), object_pairs_hook=_object)
        if (not isinstance(state, dict) or type(state.get("schema_version")) is not int
                or state["schema_version"] != 1 or state.get("state") != "complete"
                or state.get("purpose") != "fresh-runtime-archive-assembly"):
            raise RuntimeError("运行容器装配未完成")
    if not present(declaration):
        if (present(marker) or present(root / "runtime-archive-inputs.json")
                or any(present(root / name) for name in {"app.zip", "dependencies.zip", "vendor.zip"})):
            raise RuntimeError("存在未声明的运行容器，请重新安装完整候选。")
        return []
    if _plain(declaration).st_size > 16 * 1024 * 1024:
        raise RuntimeError("运行容器声明超过大小限制")
    document = json.loads(declaration.read_text(encoding="utf-8"), object_pairs_hook=_object)
    if (not isinstance(document, dict) or type(document.get("schema_version")) is not int
            or document["schema_version"] != 1 or document.get("format") != "umi-runtime-stored-zip-v1"
            or document.get("state") != "complete" or document.get("kind") != kind):
        raise RuntimeError("运行容器声明版本、组件或完成状态无效")
    archives = document.get("archives")
    if not isinstance(archives, list) or not 0 < len(archives) <= len(allowed):
        raise RuntimeError("运行容器列表无效")
    seen, logical_seen, paths = set(), set(), []
    for record in archives:
        name = record.get("path") if isinstance(record, dict) else None
        if name not in allowed or name in seen:
            raise RuntimeError("运行容器名称无效或重复")
        seen.add(name)
        archive = root / name
        info = _plain(archive)
        if type(record.get("bytes")) is not int or info.st_size != record["bytes"]:
            raise RuntimeError("运行容器大小不匹配：" + name)
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != record.get("sha256"):
                raise RuntimeError("运行容器内容损坏：" + name)
        members = record.get("members")
        if not isinstance(members, list) or len(members) > 50000:
            raise RuntimeError("运行容器成员声明无效")
        expected = {}
        for entry in members:
            directory = entry.get("kind", "file") == "directory"
            logical = _relative(entry["logical_path"].removesuffix("/") if directory else entry["logical_path"])
            member = _relative(entry["member"].removesuffix("/") if directory else entry["member"])
            if logical.casefold() in logical_seen or member.casefold() in expected:
                raise RuntimeError("运行容器成员重复")
            prefixes = ("vendor",) if kind == "plugin" else ("py_src", "site-packages")
            if not any(logical.startswith(prefix + "/") or directory and logical == prefix for prefix in prefixes):
                raise RuntimeError("运行容器逻辑范围无效")
            if directory and (entry.get("bytes") != 0 or entry.get("sha256") != hashlib.sha256(b"").hexdigest()):
                raise RuntimeError("运行容器目录项无效")
            logical_seen.add(logical.casefold())
            expected[member.casefold()] = (member, directory)
            if not directory and (root / logical).exists():
                raise RuntimeError("运行容器与旧散文件冲突：" + logical)
        with zipfile.ZipFile(archive) as reader:
            actual = set()
            for member in reader.infolist():
                path = _relative(member.filename.removesuffix("/") if member.is_dir() else member.filename)
                if (member.compress_type != zipfile.ZIP_STORED
                        or member.flag_bits & 1 or stat.S_ISLNK(member.external_attr >> 16)
                        or path.casefold() in actual or expected.get(path.casefold()) != (path, member.is_dir())):
                    raise RuntimeError("运行容器成员或存储格式无效：" + name)
                actual.add(path.casefold())
            if actual != set(expected):
                raise RuntimeError("运行容器成员集合不匹配：" + name)
        paths.append(str(archive))
    if any((root / name).exists() for name in allowed - seen):
        raise RuntimeError("存在额外的未声明运行容器")
    return paths
