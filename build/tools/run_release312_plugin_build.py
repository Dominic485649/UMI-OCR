"""在已授权插件项目的新目录构建 VL，离线复用已核验输入，不清理种子。"""
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
PLUGIN = ROOT.parent / "Umi-OCR-Plugin"


def main():
    parser = argparse.ArgumentParser()
    for name in ("stage", "work", "audit", "output"): parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    for name in ("stage", "work", "audit", "output"):
        path = getattr(args, name).absolute()
        path.relative_to(PLUGIN / "build")
        if any(node.is_symlink() or node.is_junction() for node in (path, *path.parents)): raise ValueError("拒绝链接构建路径")
        if path.exists(): raise FileExistsError(path)
        setattr(args, name, path)
    for path in (args.work, args.audit, args.output): path.mkdir(parents=True)
    temporary = args.work / "tmp"; temporary.mkdir()
    vendor = PLUGIN / "build/staging/model-settings-20261026-020955-vl-3.1.0-candidate-r5/UmiOCR-data/plugins/win32_PaddleOCRVL_1_6/vendor"
    bundle = PLUGIN / "build/staging/ui-local-update-20261101-vl-r1/UmiOCR-data/plugins/win32_PaddleOCRVL_1_6/resources/llama.cpp"
    seed = ROOT / "build/staging/release-312-20261102-runtime-seed-r1/UmiOCR-data"
    python = seed / "runtime/python.exe"
    if not (vendor / "paddle/__init__.py").is_file() or not (bundle / "runtime-manifest.json").is_file(): raise ValueError("锁定构建输入缺失")
    command = ["pwsh", "-NoProfile", "-File", str(PLUGIN / "Build-Plugin.ps1"), "-StagingRoot", str(args.stage),
        "-OutputRoot", str(args.output), "-Python", str(python), "-VendorRoot", str(vendor),
        "-RuntimeLock", str(PLUGIN / "requirements.lock"), "-LlamaRuntimeBundle", str(bundle),
        "-PaddleOCRWheel", str(ROOT / "build/cache/vl-wheels/paddleocr-3.7.0-py3-none-any.whl"),
        "-PaddleXWheel", str(ROOT / "build/cache/vl-wheels/paddlex-3.7.2-py3-none-any.whl"),
        "-RuntimeLayout", "stored", "-SkipTests", "-SkipArchive", "-DistributionRecord", str(args.audit / "distribution.json")]
    environment = {**os.environ, "TEMP": str(temporary), "TMP": str(temporary), "PYTHONDONTWRITEBYTECODE": "1",
        "PIP_NO_INDEX": "1", "PIP_FIND_LINKS": " ".join(path.as_uri() for path in (
            PLUGIN / "build/cache/paddlevl-locked-wheels-cp313",
            PLUGIN / "build/cache/release312-html-deps-r1/beautifulsoup4-4.15.0",
            PLUGIN / "build/cache/release312-html-deps-r1/soupsieve-3.0.4"))}
    def hashes():
        selected = [PLUGIN / name for name in ("Build-Plugin.ps1", "VERSION", "requirements.lock",
            "requirements-vendor.lock", "requirements-vl-extra.lock", "VL_EXTRA_THIRD_PARTY_NOTICES.md",
            "tools/runtime_archives_vl.json", "tests/test_vl_table_closure.py")]
        selected += [path for path in (PLUGIN / "win32_PaddleOCRVL_1_6").iterdir() if path.is_file() and path.suffix in {".py", ".qml", ".json", ".csv"}]
        return {str(path.relative_to(PLUGIN)): hashlib.sha256(path.read_bytes()).hexdigest() for path in selected}
    before = hashes()
    record = {"startedAt": datetime.now(timezone.utc).isoformat(), "command": command, "cwd": str(args.work),
        "inputs": {"vendor": str(vendor), "llamaBundle": str(bundle), "python": str(python),
            "offlineWheelSearch": environment["PIP_FIND_LINKS"]},
        "sourceHashesBefore": before, "modelDownloaded": False, "publicReleaseAuthorized": False,
        "boundary": "仅新建插件项目 build 产物；不删除种子，不清理插件项目已有目录；定向测试另存。"}
    (args.audit / "inputs.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    started = time.monotonic()
    log = args.audit / "build.log"
    with log.open("xb") as stream: result = subprocess.run(command, cwd=args.work, env=environment, stdout=stream, stderr=subprocess.STDOUT)
    after = hashes()
    report = {"exitCode": result.returncode, "stage": str(args.stage), "seconds": time.monotonic() - started,
        "sourceHashesAfter": after, "sourceUnchanged": before == after, "logSha256": hashlib.sha256(log.read_bytes()).hexdigest(),
        "archiveCreated": False, "runtimeAcceptance": "NOT_RUN"}
    (args.audit / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "sourceHashesAfter"}, ensure_ascii=False))
    if result.returncode: print(log.read_bytes()[-7000:].decode("utf-8", errors="replace"))
    return 0 if result.returncode == 0 and before == after else 1


if __name__ == "__main__": raise SystemExit(main())
