"""在新审查包执行实际七语首页检查，并移出自建状态恢复精确产品字节。"""
from __future__ import annotations
import argparse
from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]


def adjacent(name):
    spec = importlib.util.spec_from_file_location("home_review_" + name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(args):
    guard = adjacent("package_local_review")
    package, work, output = map(guard.layout.plain_path, (args.root, args.work, args.output))
    if work.parent.parent != ROOT / "build/tmp" or not work.parent.is_dir():
        raise ValueError("使用本项目build/tmp一级任务根下的显式新工作目录")
    if package.parent != work.parent or not package.is_dir():
        raise ValueError("只接纳同一任务根的新归档重装程序")
    if output.parent.parent != ROOT / "build/audit" or not output.parent.is_dir():
        raise ValueError("结果须位于本项目一级审计根下的新目录")
    if work.exists() or output.exists() or guard.merge.running_processes(package):
        raise ValueError("工作/结果路径必须全新，候选不得有运行进程")
    before = guard.payload(package)
    before_dirs = {path.relative_to(package).as_posix() for path in package.rglob("*") if path.is_dir()}
    work.mkdir()
    folders = {name: work / name for name in ("tmp", "roaming", "local", "cache")}
    for path in folders.values():
        path.mkdir()
    environment = {**os.environ, "TEMP": str(folders["tmp"]), "TMP": str(folders["tmp"]),
        "APPDATA": str(folders["roaming"]), "LOCALAPPDATA": str(folders["local"]),
        "XDG_CACHE_HOME": str(folders["cache"]), "QT_SHADER_CACHE_PATH": str(folders["cache"]),
        "PYTHONDONTWRITEBYTECODE": "1"}
    command = [str(package / "UmiOCR-data/runtime/python.exe"), "-I", "-B", "-X", "utf8",
        str(ROOT / "tests/test_stored_native_ui.py"), "--root", str(package), "--output", str(output),
        "--profile", "navigation", "--execute-authorized", "--max-screenshots", "6", "--check-homepage"]
    started = time.monotonic()
    with (work / "command.log").open("xb") as stream:
        completed = subprocess.run(command, cwd=ROOT, env=environment, stdout=stream, stderr=subprocess.STDOUT,
            timeout=240, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    record = {"status": "FAIL", "root": str(package), "command": command, "returncode": completed.returncode,
        "recordedLocal": datetime.now().astimezone().isoformat(), "elapsedSeconds": round(time.monotonic()-started, 3),
        "before": before, "driverSha256": guard.layout.sha256_file(__file__)}
    if completed.returncode == 0:
        report = guard.layout.read_json(output / "report.json")
        if report["acceptance"]["status"] != "PASS" or not report["normal_exit"] or report["errors"]:
            raise AssertionError("实际原生验收未通过")
        if guard.merge.running_processes(package):
            raise RuntimeError("候选仍有进程使用，不恢复状态或终止进程")
        after = guard.payload(package)
        if any(after.get(name) != value for name, value in before.items()):
            raise AssertionError("运行改动了原产品，保留现场")
        additions = sorted(set(after) - set(before))
        if any(name != "UmiOCR-data/.stored-native-ui-owner.json" and not name.startswith("UmiOCR-data/logs/") for name in additions):
            raise AssertionError("出现未识别的新增文件，保留现场")
        moved = []
        for name in additions:
            source, target = package / name, work / "generated-originals" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or guard.layout.sha256_file(source) != after[name]:
                raise AssertionError("移出自建状态前内容或目标变化")
            source.rename(target)
            if guard.layout.sha256_file(target) != after[name]:
                raise AssertionError("状态原字节保留失败")
            moved.append({"from": str(source), "to": str(target), "sha256": after[name]})
        new_dirs = [path for path in package.rglob("*") if path.is_dir() and path.relative_to(package).as_posix() not in before_dirs]
        for path in sorted(new_dirs, key=lambda item: len(item.parts), reverse=True):
            if list(path.iterdir()):
                raise AssertionError("新目录不再为空，不递归清理")
            path.rmdir()
        if guard.payload(package) != before:
            raise AssertionError("恢复后的产品集合或字节不一致")
        record.update(status="PASS", productRestored=True, generatedOriginalsPreserved=moved,
            homepageLanguages=report["checks"]["navigation_repository"]["languages"],
            report=str(output / "report.json"), reportSha256=guard.layout.sha256_file(output / "report.json"),
            scenarioDriverSha256=guard.layout.sha256_file(ROOT / "tests/test_stored_native_ui.py"),
            boundary="实际归档重装组合包自己的Python/Qt及编译QML/QM；只测首页、七语和共同窗口边界，不冒称模型参数、GPU或正常EXE验收。")
    with (output.parent / (output.name + "-restore.json")).open("x", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({key: record[key] for key in ("status", "root", "returncode", "elapsedSeconds")}, ensure_ascii=False))
    return 0 if record["status"] == "PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    raise SystemExit(run(parser.parse_args()))
