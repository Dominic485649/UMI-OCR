"""对已停止的隔离候选细分关于信息成本，不作为EXE启动性能或冷启动结论。"""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / "benchmarks"))
    import benchmark_startup_isolated as bench
    data = bench.checked_path(args.data_root, bench.TMP_ROOT)
    bench.require((data.parent / bench.OWNER).is_file(), "仅允许已建立所有权的测量副本")
    bench.assert_idle(data.parent)
    output = bench.checked_path(args.output, bench.AUDIT_ROOT)
    bench.require(not output.exists(), "诊断记录不能覆盖")
    os.chdir(data)
    sys.path[:0] = [str(data / "py_src/imports"), str(data / "site-packages")]
    started = time.perf_counter_ns()
    about = importlib.import_module("umi_about")
    imported = time.perf_counter_ns()
    calls = []
    def record(module, name):
        original = getattr(module, name)
        def timed(*values, **kwargs):
            begin = time.perf_counter_ns()
            try:
                return original(*values, **kwargs)
            finally:
                calls.append({"call": module.__name__ + "." + name, "arguments": kwargs,
                              "milliseconds": (time.perf_counter_ns() - begin) / 1e6})
        setattr(module, name, timed)
    for module, name in ((about.platform, "platform"), (about.platform, "processor"),
                         (about.psutil, "cpu_count"), (about.psutil, "virtual_memory")):
        record(module, name)
    begin = time.perf_counter_ns()
    ok = about.init(app_path=str(data.parent / "Umi-OCR.exe"))
    duration = (time.perf_counter_ns() - begin) / 1e6
    result = {"scope": "隔离Python中的关于信息微观诊断，不是完整EXE或性能收益验收",
              "dataRoot": str(data), "python": sys.version, "success": ok,
              "sourceSha256": hashlib.sha256((data / "py_src/imports/umi_about.py").read_bytes()).hexdigest(),
              "importMs": (imported - started) / 1e6, "initMs": duration, "calls": calls}
    bench.write_new(output, result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
