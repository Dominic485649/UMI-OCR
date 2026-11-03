"""核验运行容器的完整成员与对应源码/原wheel RECORD，不执行或解包内容。"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_archive_layout import LayoutError, load_layout, load_source_hashes, read_json, plain_path

TEXT_SUFFIXES = {".py", ".qml", ".json", ".yaml", ".yml", ".toml", ".ini"}
LEGACY_REJECTION_LINE = re.compile(r'''^\s*["']win32_PaddleOCRVL_1_6["'],?\s*$''', re.IGNORECASE)


def source_snapshot_for(root):
    """宿主规范源码使用同一候选的对应源码清单，不拿布局自身当来源。"""
    if root.name != "UmiOCR-data":
        return {}
    path = root.parent / "source-snapshot.json"
    if not path.is_file():
        raise LayoutError("聚合宿主缺少对应源码清单")
    record = read_json(plain_path(path))
    if not isinstance(record, dict):
        raise LayoutError("对应源码清单格式无效")
    prefix = "host/UmiOCR-data/"
    return {name[len(prefix):]: checksum for name, checksum in record.items()
            if name.startswith(prefix + "py_src/")}


def public_content(name, data, terms):
    if not terms or PurePosixPath(name).suffix.lower() not in TEXT_SUFFIXES:
        return
    text = data.decode("utf-8-sig", errors="replace")
    if name in {"py_src/plugins_controller/manifest.py", "py_src/utils/ui_unlock.py"}:
        # 仅允许这两个宿主模块声明精确插件ID；不是插件实现、导入或模型路径的例外。
        text = "\n".join(line for line in text.splitlines() if not LEGACY_REJECTION_LINE.fullmatch(line))
    folded = text.casefold()
    for term in terms:
        if term.casefold() in folded:
            raise LayoutError(f"禁止的基础包容器源码内容：{name} 命中 {term}")


def audit(root, *, source_hashes=None, forbidden_names=(), forbidden_text=()):
    root = plain_path(root)
    with load_layout(root, source_hashes=source_hashes) as view:
        if view.manifest is None:
            return {"status": "NOT_INCLUDED", "root": str(root), "archives": [], "archived_paths": []}
        canonical = source_snapshot_for(root) if view.manifest.get("kind") == "host" else {}
        for archive in view.archives.values():
            for member in archive["members"]:
                basename = PurePosixPath(member["logical_path"]).name.casefold()
                for pattern in forbidden_names:
                    if fnmatch.fnmatchcase(basename, pattern.casefold()):
                        raise LayoutError(f"禁止的运行容器成员：{member['logical_path']} 命中 {pattern}")
        verified = []
        for entry in view.entries.values():
            name = entry["logical_path"]
            data = view.read_bytes(name)
            checksum = hashlib.sha256(data).hexdigest()
            if name.startswith("py_src/"):
                if canonical.get(name) != checksum:
                    raise LayoutError("app.zip执行源码与对应源码不一致：" + name)
                binding = "canonical-host-source"
            else:
                source = entry["source"]
                if not source.get("record_owner") or not source.get("record_path") or not source.get("record_digest"):
                    raise LayoutError("第三方容器成员没有原wheel RECORD来源：" + name)
                # load_layout已经核验原RECORD内容、归属、大小和原哈希。
                binding = "retained-wheel-RECORD"
            if source_hashes is not None:
                if source_hashes.get(name) != checksum:
                    raise LayoutError("容器成员与独立输入清单不一致：" + name)
                binding += "+external-input-hashes"
            public_content(name, data, forbidden_text)
            verified.append({"path": name, "sha256": checksum, "bytes": len(data), "binding": binding})
        return {"status": "PASS", "root": str(root), "kind": view.manifest["kind"],
                "archives": [{"path": record["path"], "bytes": record["bytes"], "sha256": record["sha256"]}
                             for record in view.archives.values()],
                "archived_paths": sorted(entry["path"] for entry in verified),
                "members": sorted(verified, key=lambda entry: entry["path"]),
                "externalInputHashesVerified": source_hashes is not None,
                "publicRulesApplied": bool(forbidden_names or forbidden_text),
                "scope": "规范源码/已保留wheel RECORD与完整ZIP字节关联，不是运行兼容性、原生可重现构建或发布授权。"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--source-manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--paths-only", action="store_true", help="供结构审计消费已验证逻辑路径，不输出内容")
    parser.add_argument("--forbid-name", action="append", default=[])
    parser.add_argument("--forbid-text", action="append", default=[])
    args = parser.parse_args()
    hashes = load_source_hashes(args.source_manifest) if args.source_manifest else None
    result = audit(args.root, source_hashes=hashes, forbidden_names=args.forbid_name, forbidden_text=args.forbid_text)
    if args.output:
        if not args.output.parent.is_dir():
            raise ValueError("审计输出父目录必须存在")
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    if args.paths_only:
        print(json.dumps(result["archived_paths"], ensure_ascii=False))
    else:
        print(json.dumps({key: value for key, value in result.items() if key not in {"members", "archived_paths"}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
