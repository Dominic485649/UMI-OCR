"""在自有隔离副本中运行正常EXE与第二个真实CLI进程，不启动模型。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
import benchmark_startup_isolated as bench


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute-authorized", action="store_true")
    parser.add_argument("--expect-combined", action="store_true", help="核对组合OCR/文档注册与明确错误，不启动模型")
    args = parser.parse_args()
    bench.require(args.execute_authorized, "实际EXE/CLI运行需要明确授权")
    executable = bench.artifact_path(args.artifact)
    output = bench.checked_path(args.output, bench.AUDIT_ROOT)
    owner = bench.load_owner(executable)
    bench.require(owner["http"], "使用专属回环HTTP启用场景")
    original = bench.own_command
    native = []
    def own_command(pid, port, arguments):
        bench.require(bench.listening_pids(port) == {pid}, "端口不属于本轮主进程")
        if arguments == ["--all_pages"] and not native:
            path = output / "native-cli-pages.txt"
            bench.require(not path.exists(), "不覆盖旧CLI输出")
            env = os.environ.copy()
            for key in ("UMI_STARTUP_TRACE", "UMI_STARTUP_RUN_ID", "UMI_STARTUP_S0_NS"):
                env.pop(key, None)
            command = [str(executable), "--all_pages", "--output", str(path)]
            begin = time.monotonic()
            completed = subprocess.run(command, cwd=executable.parent, env=env, capture_output=True, timeout=30,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
            text = path.read_text("utf-8") if path.is_file() and path.stat().st_size <= 65536 else ""
            native.append({"command": command, "exitCode": completed.returncode,
                           "elapsedSeconds": time.monotonic() - begin, "outputFile": str(path),
                           "outputSha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
                           "stdout": completed.stdout.decode("utf-8", errors="replace")[:4096],
                           "stderr": completed.stderr.decode("utf-8", errors="replace")[:4096]})
            bench.require(completed.returncode == 0 and "All opened pages:" in text and "Navigation" in text,
                          "真实第二EXE的CLI单实例转发失败")
            bench.require(bench.listening_pids(port) == {pid}, "CLI调用后主实例端口归属变化")
            if args.expect_combined:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                def owned_json(route, payload=None):
                    bench.require(bench.listening_pids(port) == {pid}, "HTTP端口不属于当前主实例")
                    body = None if payload is None else json.dumps(payload).encode("utf-8")
                    request = urllib.request.Request(f"http://127.0.0.1:{port}" + route, data=body,
                        headers={"Content-Type": "application/json"})
                    with opener.open(request, timeout=10) as response:
                        content = response.read(65537)
                        bench.require(response.status == 200 and len(content) <= 65536, "响应失败或超出有限预算")
                    return json.loads(content)
                backends = owned_json("/api/backends")
                bench.require(backends.get("code") == 100, "实际后端路由未就绪")
                for kind, component in (("ocr", "win32_PaddleOCRv6_CUDA"),
                                        ("ocr", "win32_PaddleOCRVL_1_6"),
                                        ("document", "win32_PaddleOCRVL_1_6")):
                    bench.require(any(component in item.get("backendId", "") for item in backends["data"][kind]),
                                  "实际HTTP注册表缺少组合后端：" + component + "/" + kind)
                invalid = owned_json("/api/ocr", {"backendId": "not-a-registered-backend", "base64": "dGVzdA=="})
                bench.require(invalid.get("code") == 804 and invalid.get("errorType") == "INVALID_OPTIONS",
                              "无效后端请求没有明确拒绝")
                native[-1]["httpBackends"] = backends
                native[-1]["invalidBackendResponse"] = invalid
        return original(pid, port, arguments)
    bench.own_command = own_command
    try:
        result = bench.measure(argparse.Namespace(artifact=str(executable), output=str(output),
            execute_authorized=True, warmups=0, samples=1, timeout=30, exit_timeout=40, dwell=0.5))
    finally:
        bench.own_command = original
    record = {"status": "PASS" if result["status"] == "PASS" and native else "FAIL",
              "scope": "包内正常EXE、真实第二EXE CLI单实例转发、真实回环HTTP接纳和正常退出；不是性能样本或模型验收。",
              "driverSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "nativeCli": native,
              "startupReport": str(output / "report.json"), "modelInference": "NOT_REQUESTED"}
    bench.write_new(output / "native-cli-result.json", record)
    print(json.dumps({"status": record["status"], "report": str(output / "native-cli-result.json")}, ensure_ascii=False))
    return 0 if record["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
