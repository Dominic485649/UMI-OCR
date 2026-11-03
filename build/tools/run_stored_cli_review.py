"""在新审查根运行正常EXE、真实第二实例和有限回环检查，原字节保留自建状态。"""
from __future__ import annotations
import argparse
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run(args):
    installer = load("cli_review_payload", ROOT / "build/tools/reinstall_review_archives.py")
    package, work, audit = map(installer.layout.plain_path, (args.root, args.work_root, args.audit_root))
    if work.parent != ROOT / "build/tmp" or not work.is_dir() or package.parent != work:
        raise ValueError("仅使用一级具名任务根的全新归档重装程序")
    if audit.parent != ROOT / "build/audit" or not audit.is_dir():
        raise ValueError("须使用本项目既存一级审计根")
    out, result_path = audit / "normal-exe-r1", audit / "normal-exe-restore-r1.json"
    saved = work / "normal-exe-r1-generated-originals"
    if out.exists() or result_path.exists() or saved.exists() or installer.merge.running_processes(package):
        raise ValueError("工作路径已用或候选有进程，不采用旧结果")
    before = installer.binding(package)
    before_dirs = {path.relative_to(package).as_posix() for path in package.rglob("*") if path.is_dir()}
    cli = load("cli_review_actual_exe", ROOT / "tests/test_stored_native_cli.py")
    verifier = load("cli_review_generated_cache", ROOT / "build/tools/verify_generated_bytecode.py")
    cli.bench.WORK, cli.bench.TMP_ROOT, cli.bench.AUDIT_ROOT = work.name, work, audit
    cli.bench.prepare(SimpleNamespace(artifact=str(package / "Umi-OCR.exe"), identity=work.name, http=True))
    original_argv = sys.argv
    try:
        sys.argv = [str(ROOT / "tests/test_stored_native_cli.py"), "--artifact", str(package / "Umi-OCR.exe"),
            "--output", str(out), "--execute-authorized"]
        if args.expect_combined:
            sys.argv.append("--expect-combined")
        status = cli.main()
    finally:
        sys.argv = original_argv
    if status != 0 or installer.layout.read_json(out / "native-cli-result.json")["status"] != "PASS":
        raise AssertionError("实际EXE/CLI未通过，保留现场")
    if installer.merge.running_processes(package):
        raise RuntimeError("候选仍有进程使用，不恢复状态或终止进程")
    after = installer.binding(package)
    if any(after.get(name) != value for name, value in before.items()):
        raise AssertionError("运行改动原产品，停止恢复")
    known = {".startup-benchmark.json", "UmiOCR-data/.settings", "UmiOCR-data/.pre_settings", "UmiOCR-data/themes.json", "UmiOCR-data/plugins/.plugins_state"}
    added = sorted(set(after) - set(before))
    cache_records = []
    sys.path.insert(0, str(ROOT / "build/tools"))
    for name in added:
        if name in known or name.startswith((".startup-state/", "UmiOCR-data/logs/")):
            continue
        cache_records.append(verifier.verify_generated_cache(package, name, before))
    if not known.intersection(added):
        raise AssertionError("没有本次驱动生成的状态")
    saved.mkdir()
    moves = []
    for name in added:
        source, target = package / name, saved / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or installer.layout.sha256_file(source) != after[name]:
            raise AssertionError("自建状态移出目标或字节变化")
        source.rename(target)
        if installer.layout.sha256_file(target) != after[name]:
            raise AssertionError("保留的状态原字节不一致")
        moves.append({"from": str(source), "to": str(target), "sha256": after[name]})
    new_dirs = [path for path in package.rglob("*") if path.is_dir() and path.relative_to(package).as_posix() not in before_dirs]
    for path in sorted(new_dirs, key=lambda item: len(item.parts), reverse=True):
        if list(path.iterdir()):
            raise AssertionError("自建目录出现内容，不递归删除")
        path.rmdir()
    if installer.binding(package) != before:
        raise AssertionError("恢复后的实际产品不匹配")
    report = {"status": "PASS", "recordedLocal": datetime.now().astimezone().isoformat(), "root": str(package),
        "actualExe": True, "actualSecondExeCli": True, "combinedHttpRegistry": args.expect_combined, "normalExit": True,
        "nativeCliResult": str(out / "native-cli-result.json"), "nativeCliResultSha256": installer.layout.sha256_file(out / "native-cli-result.json"),
        "inputFiles": len(before), "productRestored": True, "cacheVerification": cache_records, "generatedOriginalsPreserved": moves,
        "driverSha256": installer.layout.sha256_file(__file__), "originalCliDriverSha256": installer.layout.sha256_file(ROOT / "tests/test_stored_native_cli.py"),
        "benchmarkDriverSha256": installer.layout.sha256_file(ROOT / "benchmarks/benchmark_startup_isolated.py"),
        "profile": "自有Navigation/简中/100%/lazy/回环HTTP/关闭即退出；非性能对照；125%由独立首页场景验证。",
        "limits": "未请求模型，不读取真实配置，不修改固定安装；自建状态和核验缓存移出保留，未静默删除原件。"}
    with result_path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"status": "PASS", "productFiles": len(before), "cacheFilesVerified": len(cache_records),
        "generatedFilesPreserved": len(moves)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--audit-root", type=Path, required=True)
    parser.add_argument("--expect-combined", action="store_true")
    raise SystemExit(run(parser.parse_args()))
