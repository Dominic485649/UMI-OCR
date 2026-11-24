"""离线构建显式授权的PaddleVL新候选，保留源码/依赖输入和实际原始日志。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]


def plain(path):
    path = path.absolute()
    for item in (path, *path.parents):
        if item.is_symlink() or item.is_junction():
            raise ValueError("构建路径包含链接或junction：" + str(item))
    return path


def hashes(plugin_repo):
    roots = [plugin_repo / "win32_PaddleOCRVL_1_6", plugin_repo / "tools"]
    paths = {plugin_repo / name for name in ("Build-Plugin.ps1", "VERSION", "requirements.lock",
             "requirements-vendor.lock", "requirements-vl-extra.lock", "VL_EXTRA_THIRD_PARTY_NOTICES.md")}
    for root in roots:
        paths.update(p for p in root.rglob("*") if p.is_file() and p.suffix in {".py", ".qml", ".csv", ".json"}
                     and not {"__pycache__", "temp_doc", "vendor", "models"}.intersection(p.parts))
    paths.update(ROOT / "build/tools" / name for name in ("merge_runtime.py", "runtime_archive_layout.py",
                  "audit_runtime_archives.py", "patch_paddlex_3_7_2.py", "run_pip.py"))
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths) if path.is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin-repo", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--vendor", type=Path, required=True)
    parser.add_argument("--runtime-lock", type=Path, required=True)
    parser.add_argument("--llama-bundle", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    args = parser.parse_args()
    repo = plain(args.plugin_repo)
    stage, audit, work = map(plain, (args.stage, args.audit, args.work))
    stage.relative_to(repo / "build")
    work.relative_to(repo / "build")
    audit.relative_to(ROOT / "build/audit")
    for path in (stage, audit, work):
        if path.exists():
            raise FileExistsError("只能使用全新目录：" + str(path))
    for path in (args.vendor, args.runtime_lock, args.llama_bundle, args.python):
        if not plain(path).exists():
            raise FileNotFoundError(path)
    audit.mkdir(parents=True)
    work.mkdir(parents=True)
    temporary = work / "tmp"
    temporary.mkdir()
    output = work / "archives-not-generated"
    output.mkdir()
    env = os.environ.copy()
    env.update(TEMP=str(temporary), TMP=str(temporary), PYTHONDONTWRITEBYTECODE="1", PIP_NO_INDEX="1",
               PIP_FIND_LINKS=str(repo / "build/cache/paddlevl-locked-wheels-cp313"), PIP_DISABLE_PIP_VERSION_CHECK="1")
    command = ["pwsh", "-NoProfile", "-File", str(repo / "Build-Plugin.ps1"), "-StagingRoot", str(stage),
               "-OutputRoot", str(output), "-Python", str(args.python), "-VendorRoot", str(args.vendor),
               "-RuntimeLock", str(args.runtime_lock), "-LlamaRuntimeBundle", str(args.llama_bundle),
               "-PaddleOCRWheel", str(ROOT / "build/cache/vl-wheels/paddleocr-3.7.0-py3-none-any.whl"),
               "-PaddleXWheel", str(ROOT / "build/cache/vl-wheels/paddlex-3.7.2-py3-none-any.whl"),
               "-RuntimeLayout", "stored", "-SkipArchive", "-SkipTests", "-LocalCandidate"]
    before = hashes(repo)
    record = {"startedAt": datetime.now(timezone.utc).isoformat(), "command": command, "cwd": str(work),
              "vendorSeed": str(args.vendor), "llamaBundle": str(args.llama_bundle), "offline": True,
              "sourceHashesBefore": before, "publicReleaseAuthorized": False,
              "scope": "构建只复用锁定依赖，不下载模型；定向包内及重装验收另记。"}
    with (audit / "inputs.json").open("x", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
    started = time.monotonic()
    with (audit / "build.log").open("xb") as stream:
        result = subprocess.run(command, cwd=work, env=env, stdout=stream, stderr=subprocess.STDOUT)
    after = hashes(repo)
    changed = sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))
    report = {"exitCode": result.returncode, "elapsedSeconds": round(time.monotonic() - started, 3),
              "sourceChangedDuringBuild": changed, "sourceHashes": after,
              "logSha256": hashlib.sha256((audit / "build.log").read_bytes()).hexdigest(),
              "buildPassed": result.returncode == 0 and not changed, "stage": str(stage), "runtimeAcceptance": "NOT_RUN"}
    with (audit / "result.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != "sourceHashes"}, ensure_ascii=False))
    return 0 if report["buildPassed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
