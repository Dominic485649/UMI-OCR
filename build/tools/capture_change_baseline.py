"""为联合改动保存未提交工作基线，不修改输入仓库。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True).stdout


def capture(root: Path, destination: Path) -> dict:
    root = root.resolve(strict=True)
    if destination.exists():
        raise FileExistsError(f"基线目录已存在，拒绝覆盖：{destination}")
    destination.mkdir(parents=True)
    status = git(root, "status", "--porcelain=v1", "-z")
    (destination / "status.bin").write_bytes(status)
    (destination / "unstaged.patch").write_bytes(git(root, "diff", "--binary"))
    (destination / "staged.patch").write_bytes(git(root, "diff", "--cached", "--binary"))
    changed = set(git(root, "diff", "--name-only", "-z").decode("utf-8").split("\0"))
    changed.update(git(root, "diff", "--cached", "--name-only", "-z").decode("utf-8").split("\0"))
    changed.update(git(root, "ls-files", "--others", "--exclude-standard", "-z").decode("utf-8").split("\0"))
    records = []
    for relative in sorted(changed - {""}):
        source = root / relative
        if not source.exists():
            records.append({"path": relative, "state": "missing"})
            continue
        if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(root):
            raise ValueError(f"拒绝复制非普通文件或越界路径：{source}")
        for parent in source.parents:
            if parent == root:
                break
            if parent.is_symlink() or parent.is_junction():
                raise ValueError(f"拒绝通过链接记录基线：{parent}")
        if source.stat().st_size > 20 * 1024 * 1024:
            raise ValueError(f"未审查的大文件不纳入源码基线：{source}")
        target = destination / "files" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        with source.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        records.append({"path": relative, "size": source.stat().st_size, "sha256": checksum})
    manifest = {"repository": str(root), "head": git(root, "rev-parse", "HEAD").decode().strip(),
                "files": records, "note": "只读输入基线；不代表本轮修改或验收通过。"}
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"repository": str(root), "files": len(records), "destination": str(destination)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repository", action="append", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"输出已存在：{args.output}")
    args.output.parent.resolve(strict=True)
    args.output.mkdir()
    print(json.dumps([capture(root, args.output / root.name) for root in args.repository], ensure_ascii=False))
