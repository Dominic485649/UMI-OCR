"""本轮 Windows 组件 fresh 构建封装：离线复用依赖、隔离临时目录、保留原始日志。"""
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


def safe_build_path(path):
    path = path.absolute()
    for item in (path, *path.parents):
        if item.is_symlink() or item.is_junction():
            raise ValueError("构建路径不能包含链接或 junction。")
    path.resolve().relative_to((ROOT / "build").resolve())
    return path


def source_hashes(component):
    data = ROOT / "UmiOCR-data"
    if component == "cuda":
        roots = [data / "plugins/win32_PaddleOCRv6_CUDA", ROOT / "build/windows/CudaWorker"]
        paths = set()
    else:
        roots = [data / name for name in ("py_src", "qt_res", "i18n")]
        paths = {data / name for name in ("main.py", "about.json", "version.py", "runtime_archive_bootstrap.py")}
    extensions = {".py", ".qml", ".qm", ".csv", ".json", ".qrc", ".js", ".cpp", ".h", ".in", ".manifest"}
    for root in roots:
        paths.update(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in extensions
                     and not {"vendor", "models", "__pycache__"}.intersection(path.parts))
    paths.update(ROOT / "build" / relative for relative in (
        "tools/source_snapshot.py", "tools/export_cuda_source.py", "windows/Audit-Package.ps1",
        "windows/Build-Release.ps1", "windows/Build-GpuPlugin.ps1", "sources-windows-cu126.lock.json",
        "windows/runtime_archives_host.json", "windows/runtime_archives_cuda.json",
        "tools/merge_runtime.py", "tools/runtime_archive_layout.py", "tools/audit_runtime_archives.py"))
    return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths) if path.is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", choices=("base", "cuda"), required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed-base", type=Path, required=True)
    parser.add_argument("--seed-cuda", type=Path)
    parser.add_argument("--runtime-layout", choices=("loose", "stored"), default="loose")
    parser.add_argument("--local-candidate", action="store_true", help="记录非最终本地候选，不授予公开发布资格")
    args = parser.parse_args()
    args.stage, args.audit, args.work, args.output = map(safe_build_path, (args.stage, args.audit, args.work, args.output))
    if args.stage.exists() or args.audit.exists() or args.work.exists():
        raise FileExistsError("必须使用全新 staging、audit 和 work，禁止覆盖历史构建。")
    if not (args.seed_base / "UmiOCR-data/runtime/python.exe").is_file():
        raise ValueError("只读基础运行时种子不存在。")
    if args.component == "cuda" and (not args.seed_cuda or not (args.seed_cuda / "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/vendor").is_dir()):
        raise ValueError("只读 CUDA 私有闭包种子不存在。")
    args.audit.mkdir(parents=True)
    args.work.mkdir(parents=True)
    temporary = args.work / "tmp"
    temporary.mkdir()
    environment = os.environ.copy()
    environment.update({"TEMP": str(temporary), "TMP": str(temporary), "PYTHONDONTWRITEBYTECODE": "1", "PIP_NO_INDEX": "1"})
    command = ["pwsh", "-NoProfile", "-File", str(ROOT / "build/windows" / ("Build-Release.ps1" if args.component == "base" else "Build-GpuPlugin.ps1")),
               "-StagingRoot", str(args.stage), "-OutputRoot", str(args.output), "-ReuseDependencies", "-Offline", "-SkipArchive",
               "-RuntimeLayout", args.runtime_layout]
    if args.local_candidate:
        command.append("-LocalCandidate")
    if args.component == "base":
        command += ["-ReuseFromStagingRoot", str(args.seed_base), "-SkipTests"]
    else:
        command += ["-BaseStagingRoot", str(args.seed_base), "-ReuseVendorFromStagingRoot", str(args.seed_cuda), "-SkipModels", "-ReuseModels"]
    before = source_hashes(args.component)
    record = {"component": args.component, "startedAt": datetime.now(timezone.utc).isoformat(),
              "command": command, "cwd": str(args.work), "temporaryRoot": str(temporary),
              "seedBase": str(args.seed_base), "seedCuda": str(args.seed_cuda) if args.seed_cuda else None,
              "reusedInputs": "仅依赖/模型输入；不复用历史 PASS，不下载/量化权重。",
              "runtimeLayout": args.runtime_layout, "localCandidate": args.local_candidate,
              "archiveCreated": False, "publicReleaseAuthorized": False,
              "tests": "构建入口不例行重跑全仓库；定向证据另存，真实候选验收尚待执行。",
              "sourceHashesBefore": before}
    (args.audit / "inputs.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    started = time.monotonic()
    with (args.audit / "build.log").open("xb") as log:
        result = subprocess.run(command, cwd=args.work, env=environment, stdout=log, stderr=subprocess.STDOUT)
    after = source_hashes(args.component)
    changed = sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path))
    report = {"component": args.component, "exitCode": result.returncode, "stage": str(args.stage),
              "elapsedSeconds": round(time.monotonic() - started, 3), "sourceHashes": after,
              "sourceChangedDuringBuild": changed, "logSha256": hashlib.sha256((args.audit / "build.log").read_bytes()).hexdigest(),
              "buildPassed": result.returncode == 0 and not changed, "runtimeAcceptance": "NOT_RUN"}
    (args.audit / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "sourceHashes"}, ensure_ascii=False, indent=2))
    if result.returncode or changed:
        print((args.audit / "build.log").read_bytes()[-6000:].decode("utf-8", errors="replace"))
    return 0 if report["buildPassed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
