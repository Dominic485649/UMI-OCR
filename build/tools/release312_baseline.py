"""保存 3.1.2 改动前的源码边界，尤其保留插件已有的未提交修改。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "build/audit/release-312-20261102-r1"
PLUGIN = ROOT.parent / "Umi-OCR-Plugin"


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def main():
    if AUDIT.exists():
        raise FileExistsError("基线目录必须全新：" + str(AUDIT))
    AUDIT.mkdir(parents=True)
    records = {}
    for label, repo in (("host", ROOT), ("paddlevl", PLUGIN)):
        status = git(repo, "status", "--porcelain=v1", "-z").decode("utf-8")
        paths = git(repo, "ls-files", "--cached", "--others", "--exclude-standard", "-z").decode("utf-8").split("\0")
        entries = {}
        for relative in sorted(set(paths)):
            if not relative or relative.startswith(("build/audit/", "build/staging/", "build/cache/")):
                continue
            source = repo / relative
            if not source.is_file():
                continue
            if source.is_symlink() or source.is_junction() or not source.resolve().is_relative_to(repo.resolve()):
                raise ValueError("拒绝越界源码：" + str(source))
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            entries[relative] = {"sha256": digest, "bytes": source.stat().st_size}
            if label == "paddlevl":
                target = AUDIT / "baseline-paddlevl" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        (AUDIT / f"{label}-baseline.diff").write_bytes(git(repo, "diff", "--binary", "HEAD"))
        records[label] = {"root": str(repo), "head": git(repo, "rev-parse", "HEAD").decode().strip(),
                          "statusPorcelainZ": status, "files": entries}
    (AUDIT / "baseline.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"audit": str(AUDIT), "files": {key: len(value["files"]) for key, value in records.items()}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
