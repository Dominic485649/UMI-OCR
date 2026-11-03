"""插件私有容器入口，独立于宿主；同步实现见宿主 runtime_archive_bootstrap.py。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile


def prepare_archives(root):
    """只接受声明且完整的 vendor.zip，不解包、不回退旧散文件。"""
    root = Path(root).absolute()
    declaration, archive = root / "runtime-archives.json", root / "vendor.zip"
    def plain(path):
        details = path.lstat()
        if not stat.S_ISREG(details.st_mode) or getattr(details, "st_file_attributes", 0) & 0x400:
            raise RuntimeError("插件运行容器必须是普通文件")
        return details

    def relative(value):
        if not isinstance(value, str) or not value or "\\" in value or ":" in value:
            raise RuntimeError("插件运行容器路径无效")
        path = PurePosixPath(value)
        if path.is_absolute() or str(path) != value or any(part in {".", ".."} for part in path.parts):
            raise RuntimeError("插件运行容器路径越界")
        return value

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise RuntimeError("插件运行容器声明含重复字段")
            result[key] = value
        return result

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
        if plain(marker).st_size > 65536:
            raise RuntimeError("插件运行容器装配状态过大")
        state = json.loads(marker.read_text(encoding="utf-8"), object_pairs_hook=unique)
        if (not isinstance(state, dict) or type(state.get("schema_version")) is not int
                or state["schema_version"] != 1 or state.get("state") != "complete"
                or state.get("purpose") != "fresh-runtime-archive-assembly"):
            raise RuntimeError("插件运行容器装配未完成")
    if not present(declaration):
        if (present(marker) or present(root / "runtime-archive-inputs.json")
                or any(present(root / name) for name in ("app.zip", "dependencies.zip", "vendor.zip"))):
            raise RuntimeError("存在未声明的插件运行容器，请重新安装完整插件。")
        return []
    if plain(declaration).st_size > 16 * 1024 * 1024:
        raise RuntimeError("插件运行容器声明过大")
    document = json.loads(declaration.read_text(encoding="utf-8"), object_pairs_hook=unique)
    if (not isinstance(document, dict) or type(document.get("schema_version")) is not int
            or document["schema_version"] != 1 or document.get("format") != "umi-runtime-stored-zip-v1"
            or document.get("state") != "complete" or document.get("kind") != "plugin"):
        raise RuntimeError("插件运行容器声明版本、组件或完成状态无效")
    records = document.get("archives")
    if (not isinstance(records, list) or len(records) != 1
            or not isinstance(records[0], dict) or records[0].get("path") != "vendor.zip"):
        raise RuntimeError("插件运行容器声明无效")
    record = records[0]
    if type(record.get("bytes")) is not int or plain(archive).st_size != record["bytes"]:
        raise RuntimeError("插件运行容器大小不匹配")
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != record.get("sha256"):
            raise RuntimeError("插件运行容器内容损坏")
    members = record.get("members")
    if not isinstance(members, list) or len(members) > 50000:
        raise RuntimeError("插件运行容器成员声明无效")
    expected, logical_names = {}, set()
    for entry in members:
        directory = entry.get("kind", "file") == "directory"
        logical = relative(entry["logical_path"].removesuffix("/") if directory else entry["logical_path"])
        member = relative(entry["member"].removesuffix("/") if directory else entry["member"])
        if (not (logical.startswith("vendor/") or directory and logical == "vendor")
                or logical.casefold() in logical_names or member.casefold() in expected):
            raise RuntimeError("插件运行容器成员范围无效或重复")
        if directory and (entry.get("bytes") != 0 or entry.get("sha256") != hashlib.sha256(b"").hexdigest()):
            raise RuntimeError("插件运行容器目录项无效")
        if not directory and (root / logical).exists():
            raise RuntimeError("插件运行容器与旧散文件冲突：" + logical)
        logical_names.add(logical.casefold())
        expected[member.casefold()] = (member, directory)
    with zipfile.ZipFile(archive) as reader:
        actual = set()
        for member in reader.infolist():
            path = relative(member.filename.removesuffix("/") if member.is_dir() else member.filename)
            if (member.compress_type != zipfile.ZIP_STORED or member.flag_bits & 1
                    or stat.S_ISLNK(member.external_attr >> 16) or path.casefold() in actual
                    or expected.get(path.casefold()) != (path, member.is_dir())):
                raise RuntimeError("插件运行容器成员或存储格式无效")
            actual.add(path.casefold())
        if actual != set(expected):
            raise RuntimeError("插件运行容器成员集合不匹配")
    return [str(archive)]
