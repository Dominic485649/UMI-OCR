"""本轮受影响入口的定向验证，隔离 cwd／临时目录并保留原始日志。"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--plugin", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--only", choices=("vl-plugin", "document-partial", "file-import"), action="append")
    args = parser.parse_args()
    runtime, plugin, work, audit = map(Path.absolute, (args.runtime, args.plugin, args.work, args.audit))
    for path in (work, audit):
        path.relative_to(ROOT / "build")
        if path.exists(): raise FileExistsError(path)
        path.mkdir(parents=True)
    python = runtime / "runtime/python.exe"
    source = ROOT / "UmiOCR-data"
    bootstrap = "import sys,os,runpy; from pathlib import Path; runtime=Path(sys.argv[1]); source=Path(sys.argv[2]); script=sys.argv[3]; sys.path[:0]=[str(source),str(source/'py_src/imports'),str(runtime/'site-packages'),str(runtime/'dependencies.zip')]; dll=os.add_dll_directory(str(runtime/'site-packages/PySide6')); import plugin_i18n; plugin_i18n.setLangCode('zh_CN'); sys.argv=[script,*sys.argv[4:]]; runpy.run_path(script,run_name='__main__')"
    tests = [
        ("vl-plugin", [str(python), "-I", "-B", "-c", bootstrap, str(runtime), str(source), str(plugin.parent / "tests/test_plugin.py"), str(plugin)]),
        ("document-partial", [str(python), "-I", "-B", str(ROOT / "tests/test_document_partial_delivery.py"), str(runtime), "--plugin", str(plugin), "--output", str(audit / "document-partial.json")]),
        ("file-import", [str(python), "-I", "-B", str(ROOT / "tests/test_file_import.py"), str(runtime), "--source-root", str(source)]),
    ]
    records = []
    for name, command in tests:
        if args.only and name not in args.only: continue
        directory = work / name
        directory.mkdir()
        temporary = directory / "tmp"
        temporary.mkdir()
        environment = {**os.environ, "TEMP": str(temporary), "TMP": str(temporary), "PYTHONDONTWRITEBYTECODE": "1"}
        log = audit / (name + ".log")
        started = time.monotonic()
        with log.open("xb") as stream:
            process = subprocess.run(command, cwd=directory, env=environment, stdout=stream, stderr=subprocess.STDOUT)
        records.append({"name": name, "command": command, "cwd": str(directory), "returncode": process.returncode,
                        "elapsedSeconds": round(time.monotonic() - started, 3), "log": str(log), "logSha256": hashlib.sha256(log.read_bytes()).hexdigest()})
        print(name + ": " + ("PASS" if process.returncode == 0 else "FAIL"), flush=True)
        if process.returncode: print(log.read_text("utf-8", errors="replace")[-6000:], flush=True)
    (audit / "result.json").write_text(json.dumps({"status": "PASS" if all(record["returncode"] == 0 for record in records) else "FAIL", "runtime": str(runtime), "source": str(source), "records": records,
        "boundary": "仅受影响插件、文档 partial 与导入路径；未运行桌面捕获/HDR/混屏或全仓库回归。"}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all(record["returncode"] == 0 for record in records) else 1


if __name__ == "__main__": raise SystemExit(main())
