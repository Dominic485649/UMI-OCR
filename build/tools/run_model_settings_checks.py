"""运行本轮具名定向检查，日志与临时目录不落入用户主目录。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


def run(python, repository, data_root, output, work, checks):
    output.mkdir(parents=True, exist_ok=False)
    work.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update({"TEMP": str(work), "TMP": str(work), "PYTHONDONTWRITEBYTECODE": "1"})
    def source_hashes():
        roots = [repository / "UmiOCR-data/py_src", repository / "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA"]
        paths = {path for root in roots for path in root.rglob("*.py") if "__pycache__" not in path.parts}
        paths.update(repository / relative for relative in ("UmiOCR-data/i18n/runtime.csv", "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/i18n.csv"))
        return {str(path.relative_to(repository)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in paths if path.is_file()}
    before = source_hashes()
    records = []
    for name, arguments in checks:
        command = [str(python), "-I", "-B", "-X", "utf8", str(repository / "tests" / name), *arguments]
        started = time.monotonic()
        result = subprocess.run(command, cwd=work, env=environment, capture_output=True, timeout=180)
        path = output / (Path(name).stem + ".log")
        path.write_bytes(result.stdout + result.stderr)
        records.append({"test": name, "testSha256": hashlib.sha256((repository / "tests" / name).read_bytes()).hexdigest(),
                        "command": command, "exitCode": result.returncode,
                        "elapsedSeconds": round(time.monotonic() - started, 3),
                        "log": str(path), "logSha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        print(f"{name}: exit={result.returncode}", flush=True)
    after = source_hashes()
    changed = [key for key in sorted(set(before) | set(after)) if before.get(key) != after.get(key)]
    report = {"dataRoot": str(data_root), "sourceRoot": str(repository / "UmiOCR-data"), "checks": records,
              "sourceHashes": after, "sourceChangedDuringRun": changed}
    (output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return not changed and all(item["exitCode"] == 0 for item in records)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument("--test", action="append", default=[])
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[2]
    source = repository / "UmiOCR-data"
    checks = [("test_backend_runtime.py", []), ("test_managed_mission.py", []), ("test_model_settings_build_inputs.py", []), ("test_manifest_translation_boundary.py", []), ("test_backend_router.py", []), ("test_request_validation.py", []), ("test_request_budgets.py", []), ("test_cuda_image_tiles.py", []), ("test_cuda_worker_client.py", [str(source)]),
              ("test_mission_runtime.py", [str(args.data_root), "--source-root", str(source)]),
              ("test_http_api.py", ["--data-root", str(args.data_root), "--source-root", str(source)]),
              ("test_structured_http.py", ["--data-root", str(args.data_root)])]
    if args.test:
        unknown = set(args.test) - {name for name, _ in checks}
        if unknown:
            parser.error("未知的定向检查：" + ", ".join(sorted(unknown)))
        checks = [(name, arguments) for name, arguments in checks if name in args.test]
    raise SystemExit(0 if run(args.data_root / "runtime/python.exe", repository, args.data_root,
                            args.output, args.work, checks) else 1)
