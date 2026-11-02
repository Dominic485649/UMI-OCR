"""Model-free Windows runtime probe with isolated child PATH and DLL debug events."""
from __future__ import annotations
import argparse
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import msvcrt
import os
import re
from pathlib import Path
import subprocess
import time


class ExceptionRecord(C.Structure):
    pass
ExceptionRecord._fields_ = [("code", W.DWORD), ("flags", W.DWORD), ("record", C.c_void_p),
                           ("address", C.c_void_p), ("count", W.DWORD), ("information", C.c_size_t * 15)]
class ExceptionInfo(C.Structure):
    _fields_ = [("record", ExceptionRecord), ("firstChance", W.DWORD)]
class CreateInfo(C.Structure):
    _fields_ = [("file", W.HANDLE), ("process", W.HANDLE), ("thread", W.HANDLE),
                ("base", C.c_void_p), ("debugOffset", W.DWORD), ("debugSize", W.DWORD),
                ("tls", C.c_void_p), ("start", C.c_void_p), ("imageName", C.c_void_p), ("unicode", W.WORD)]
class LoadInfo(C.Structure):
    _fields_ = [("file", W.HANDLE), ("base", C.c_void_p), ("debugOffset", W.DWORD),
                ("debugSize", W.DWORD), ("name", C.c_void_p), ("unicode", W.WORD)]
class ExitInfo(C.Structure):
    _fields_ = [("code", W.DWORD)]
class EventUnion(C.Union):
    _fields_ = [("exception", ExceptionInfo), ("create", CreateInfo), ("load", LoadInfo), ("exit", ExitInfo)]
class DebugEvent(C.Structure):
    _fields_ = [("code", W.DWORD), ("pid", W.DWORD), ("tid", W.DWORD), ("data", EventUnion)]
class StartupInfo(C.Structure):
    _fields_ = [("cb", W.DWORD), ("reserved", W.LPWSTR), ("desktop", W.LPWSTR), ("title", W.LPWSTR),
                ("x", W.DWORD), ("y", W.DWORD), ("width", W.DWORD), ("height", W.DWORD),
                ("charsX", W.DWORD), ("charsY", W.DWORD), ("fill", W.DWORD), ("flags", W.DWORD),
                ("show", W.WORD), ("reservedSize", W.WORD), ("reserved2", C.POINTER(C.c_byte)),
                ("stdin", W.HANDLE), ("stdout", W.HANDLE), ("stderr", W.HANDLE)]
class ProcessInfo(C.Structure):
    _fields_ = [("process", W.HANDLE), ("thread", W.HANDLE), ("pid", W.DWORD), ("tid", W.DWORD)]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_architectures(output: bytes) -> set[str]:
    return set(re.findall(r"sm_([0-9]+a?)(?:\.|\b)", output.decode("utf-8", errors="replace")))


def trace_modules(executable: Path, environment: dict, output: Path) -> dict:
    kernel = C.WinDLL("kernel32", use_last_error=True)
    kernel.CreateProcessW.argtypes = [W.LPCWSTR, W.LPWSTR, C.c_void_p, C.c_void_p, W.BOOL, W.DWORD,
                                     C.c_void_p, W.LPCWSTR, C.POINTER(StartupInfo), C.POINTER(ProcessInfo)]
    kernel.CreateProcessW.restype = W.BOOL
    kernel.WaitForDebugEvent.argtypes = [C.POINTER(DebugEvent), W.DWORD]
    kernel.WaitForDebugEvent.restype = W.BOOL
    kernel.ContinueDebugEvent.argtypes = [W.DWORD, W.DWORD, W.DWORD]
    kernel.ContinueDebugEvent.restype = W.BOOL
    kernel.GetFinalPathNameByHandleW.argtypes = [W.HANDLE, W.LPWSTR, W.DWORD, W.DWORD]
    kernel.GetFinalPathNameByHandleW.restype = W.DWORD
    kernel.CloseHandle.argtypes = [W.HANDLE]
    kernel.CloseHandle.restype = W.BOOL
    kernel.DebugActiveProcessStop.argtypes = [W.DWORD]
    kernel.DebugSetProcessKillOnExit.argtypes = [W.BOOL]
    command = C.create_unicode_buffer(subprocess.list2cmdline([str(executable), "--list-devices"]))
    block = C.create_unicode_buffer("\0".join(f"{k}={v}" for k, v in sorted(environment.items())) + "\0\0")
    startup, process = StartupInfo(), ProcessInfo()
    startup.cb, startup.flags = C.sizeof(StartupInfo), 0x100
    modules = []
    started = False
    exited = False
    with output.open("wb") as log, open(os.devnull, "rb") as stdin:
        out_handle = msvcrt.get_osfhandle(log.fileno())
        in_handle = msvcrt.get_osfhandle(stdin.fileno())
        os.set_handle_inheritable(out_handle, True)
        os.set_handle_inheritable(in_handle, True)
        startup.stdin, startup.stdout, startup.stderr = in_handle, out_handle, out_handle
        if not kernel.CreateProcessW(str(executable), command, None, None, True, 0x2 | 0x400 | 0x08000000,
                                     block, str(executable.parent), C.byref(startup), C.byref(process)):
            raise C.WinError(C.get_last_error())
        started = True
        kernel.DebugSetProcessKillOnExit(False)
        deadline = time.monotonic() + 45
        try:
            while time.monotonic() < deadline:
                event = DebugEvent()
                if not kernel.WaitForDebugEvent(C.byref(event), 10000):
                    raise C.WinError(C.get_last_error())
                disposition = 0x00010002
                if event.code in (3, 6):
                    handle = event.data.create.file if event.code == 3 else event.data.load.file
                    if handle:
                        buffer = C.create_unicode_buffer(32768)
                        count = kernel.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
                        if not 0 < count < len(buffer):
                            raise C.WinError(C.get_last_error())
                        path = buffer.value
                        if path.startswith("\\\\?\\"):
                            path = path[4:]
                        modules.append({"event": "process-image" if event.code == 3 else "dll-load", "path": path})
                        kernel.CloseHandle(handle)
                elif event.code == 1:
                    code = event.data.exception.record.code
                    if code not in (0x80000003, 0x80000004):
                        disposition = 0x80010001
                elif event.code == 5:
                    exit_code = event.data.exit.code
                    exited = True
                if not kernel.ContinueDebugEvent(event.pid, event.tid, disposition):
                    raise C.WinError(C.get_last_error())
                if exited:
                    return {"exitCode": exit_code, "modules": modules, "method": "Windows DEBUG_ONLY_THIS_PROCESS LOAD_DLL_DEBUG_EVENT file handles"}
            raise TimeoutError("Read-only module trace exceeded 45 seconds; no process was terminated")
        finally:
            if started and not exited:
                kernel.DebugActiveProcessStop(process.pid)
            kernel.CloseHandle(process.thread)
            kernel.CloseHandle(process.process)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--audit", required=True, type=Path)
    parser.add_argument("--cuobjdump", type=Path, help="Optional local CUDA tool for binary architecture verification")
    args = parser.parse_args()
    root, audit = args.runtime.absolute(), args.audit.absolute()
    if audit.exists():
        raise ValueError("Use a new probe audit directory")
    audit.mkdir(parents=True, exist_ok=False)
    (audit / "temp").mkdir()
    windows = Path(os.environ["SystemRoot"])
    environment = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "ProgramData", "ProgramFiles", "ProgramFiles(x86)") if key in os.environ}
    environment.update(PATH=f"{root};{windows / 'System32'};{windows}", TEMP=str(audit / "temp"), TMP=str(audit / "temp"))
    manifest = json.loads((root / "runtime-manifest.json").read_text(encoding="utf-8-sig"))
    binaries = {Path(p["path"]).name.lower(): p for p in manifest["files"] if p["path"].lower().endswith((".dll", ".exe"))}
    results = {"environment": environment, "runtimeManifestSha256": hashlib.sha256((root / "runtime-manifest.json").read_bytes()).hexdigest(), "commands": []}
    executable = root / "llama-server.exe"
    try:
        for flag in ("--version", "--help", "--list-devices"):
            command = [str(executable), flag]
            run = subprocess.run(command, cwd=root, env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=45)
            filename = flag[2:] + ".log"
            (audit / filename).write_bytes(run.stdout)
            results["commands"].append({"argv": command, "exitCode": run.returncode, "output": filename})
            if run.returncode:
                raise RuntimeError(f"Read-only probe failed: {flag} ({run.returncode})")
            text = run.stdout.decode("utf-8", errors="replace")
            if flag == "--version" and manifest["identity"]["commit"][:7] not in text:
                raise RuntimeError("Runtime --version does not report the reviewed source commit")
            if flag == "--list-devices" and ("CUDA0" not in text or "NVIDIA" not in text):
                raise RuntimeError("Runtime device discovery did not report a local NVIDIA CUDA device")
        if args.cuobjdump:
            results["binaryArchitectures"] = {}
            expected = set(manifest["identity"]["architectures"])
            for flag in ("--list-elf", "--list-ptx"):
                run = subprocess.run([str(args.cuobjdump), flag, str(root / "ggml-cuda.dll")], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=45)
                (audit / (flag[2:] + ".log")).write_bytes(run.stdout)
                found = parse_architectures(run.stdout)
                results["binaryArchitectures"][flag] = {"architectures": sorted(found), "exitCode": run.returncode}
                if run.returncode or found != expected:
                    raise RuntimeError(f"CUDA binary architecture verification failed: {flag}, expected={sorted(expected)}, found={sorted(found)}")
        trace = trace_modules(executable, environment, audit / "module-trace-command.log")
        results["moduleTrace"] = trace
        errors = []
        for module in trace["modules"]:
            path = Path(module["path"])
            name = path.name.lower()
            app_dependency = re.match(r"(?:msvcp140|vcruntime140|vcomp140|concrt140|cudart|cublas|ggml|llama|mtmd)", name)
            if (name in binaries or app_dependency) and path.parent != root:
                errors.append(f"Bundled/application dependency loaded outside runtime: {path}")
            elif path.parent == root:
                if name not in binaries or file_sha256(path) != binaries[name]["sha256"]:
                    errors.append(f"Unmanifested/changed runtime module: {path}")
            elif windows not in path.parents:
                errors.append(f"Module outside runtime/Windows driver/OS root: {path}")
        loaded = {Path(m["path"]).name.lower() for m in trace["modules"] if Path(m["path"]).parent == root}
        missing = binaries.keys() - loaded
        if missing:
            errors.append(f"Packaged binaries not exercised by device discovery: {sorted(missing)}")
        if trace["exitCode"]:
            errors.append(f"Module trace child failed: {trace['exitCode']}")
        results["errors"] = errors
        results["passed"] = not errors
        if errors:
            raise RuntimeError("; ".join(errors))
    except Exception as error:
        results["passed"] = False
        results["failure"] = str(error)
        raise
    finally:
        (audit / "probe-result.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": True, "audit": str(audit), "loadedModules": len(results["moduleTrace"]["modules"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
