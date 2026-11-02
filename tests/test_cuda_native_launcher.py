"""仅验证原生入口与协议，不加载 Paddle 或执行 OCR。"""

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
FAKE_WORKER = '''import ctypes
import json
import sys
from pathlib import Path

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.GetModuleFileNameW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_ulong)
kernel32.GetModuleFileNameW.restype = ctypes.c_ulong
buffer = ctypes.create_unicode_buffer(32768)
assert kernel32.GetModuleFileNameW(sys.dllhandle, buffer, len(buffer))
for line in sys.stdin:
    request = json.loads(line)
    if request.get("op") == "stop":
        print(json.dumps({"ok": True, "status": "stopped"}), flush=True)
        break
    print(json.dumps({"ok": True, "echo": request, "acp": kernel32.GetACP(), "python_utf8_mode": bool(sys.flags.utf8_mode), "isolated": bool(sys.flags.isolated), "no_site": bool(sys.flags.no_site), "dont_write_bytecode": bool(sys.dont_write_bytecode), "stdin_encoding": sys.stdin.encoding, "stdout_encoding": sys.stdout.encoding, "python_dll": buffer.value, "executable": sys.executable, "sys_path": sys.path, "inference_imports": [name for name in ("paddle", "paddlex", "paddleocr", "cv2", "numpy") if name in sys.modules]}, ensure_ascii=False), flush=True)
'''


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def no_links(path):
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink() or ancestor.is_junction():
            raise ValueError("原生入口测试不经过链接或junction。")


def run_launcher(path, cwd, wire, arguments=()):
    return subprocess.run(
        [str(path), *arguments], input=wire, cwd=cwd,
        env=dict(os.environ, PYTHONUTF8="0", PYTHONIOENCODING="gbk", PYTHONHOME=str(cwd / "missing-home"), PYTHONPATH=str(cwd)),
        encoding="utf-8", errors="strict", text=True, capture_output=True,
        timeout=20, check=False, creationflags=subprocess.CREATE_NO_WINDOW,
    )


def assert_failure(result, text):
    assert result.returncode != 0, result
    messages = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(messages) == 1 and messages[0]["ok"] is False, result.stdout
    assert text in messages[0]["error"], messages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launcher", required=True, type=Path)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--work-parent", required=True, type=Path)
    parser.add_argument("--mt", type=Path)
    args = parser.parse_args()
    launcher = args.launcher.resolve(strict=True)
    runtime = args.runtime.resolve(strict=True)
    parent = args.work_parent.resolve(strict=True)
    if not parent.is_relative_to(ROOT / "build"):
        raise ValueError("测试证据须保存在本项目build下。")
    for path in (launcher, runtime, parent):
        no_links(path)
    for path in runtime.rglob("*"):
        no_links(path)
    before = digest(launcher)
    work = Path(tempfile.mkdtemp(prefix="native-launcher-", dir=parent))
    cwd = work / "hostile-cwd"
    cwd.mkdir()
    (cwd / "json.py").write_text('raise RuntimeError("CWD shadow imported")\n', encoding="utf-8")
    shutil.copyfile(runtime / "python3.dll", cwd / "python3.dll")
    results = []
    for case in ("ascii", "中文 安装目录"):
        data = work / case / "UmiOCR-data"
        plugin = data / "plugins/win32_PaddleOCRv6_CUDA"
        plugin.mkdir(parents=True)
        shutil.copytree(runtime, data / "runtime")
        target = plugin / launcher.name
        shutil.copyfile(launcher, target)
        (plugin / "worker.py").write_text(FAKE_WORKER, encoding="utf-8")
        wire = json.dumps({"op": "中文路径：😀𠮷"}, ensure_ascii=False) + '\n{"op":"stop"}\n'
        result = run_launcher(target, cwd, wire)
        assert result.returncode == 0, result.stderr
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        assert len(responses) == 2 and responses[1] == {"ok": True, "status": "stopped"}, result.stdout
        info = responses[0]
        assert info["echo"] == {"op": "中文路径：😀𠮷"}
        assert info["acp"] == 65001 and info["python_utf8_mode"] is True
        assert all(info[key] is True for key in ("isolated", "no_site", "dont_write_bytecode"))
        assert info["stdin_encoding"] == info["stdout_encoding"] == "utf-8"
        assert Path(info["python_dll"]).resolve() == (data / "runtime/python313.dll").resolve()
        assert Path(info["executable"]).resolve() == target.resolve()
        assert info["inference_imports"] == []
        assert str((data / "runtime/python313.zip").resolve()) in info["sys_path"], info
        assert str(cwd) not in info["sys_path"], info
        assert not any(plugin.rglob("*.pyc"))
        (plugin / "worker.py").unlink()
        assert_failure(run_launcher(target, cwd, ''), "worker.py is missing")
        assert_failure(run_launcher(target, cwd, '', ("--untrusted-argument",)), "does not accept command-line arguments")
        results.append({"case": case, "status": "PASS", "native_acp": info["acp"], "python_dll": info["python_dll"], "stdio": info["stdout_encoding"], "inference_modules_loaded": False})
    missing = work / "missing-runtime/UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA"
    missing.mkdir(parents=True)
    shutil.copyfile(launcher, missing / launcher.name)
    (missing / "worker.py").write_text(FAKE_WORKER, encoding="utf-8")
    assert_failure(run_launcher(missing / launcher.name, cwd, ''), "runtime/python3.dll is missing")
    broken_runtime = work / "missing-runtime/UmiOCR-data/runtime"
    broken_runtime.mkdir()
    (broken_runtime / "python3.dll").write_bytes(b"not a valid DLL")
    assert_failure(run_launcher(missing / launcher.name, cwd, ''), "Cannot load the host Python runtime")
    legacy = None
    if args.mt:
        mt = args.mt.resolve(strict=True)
        no_links(mt)
        target = work / "cp936-native.exe"
        shutil.copyfile(launcher, target)
        manifest = ET.parse(ROOT / "build/windows/CudaWorker/worker.manifest")
        manifest.find(".//{http://schemas.microsoft.com/SMI/2019/WindowsSettings}activeCodePage").text = "zh-CN"
        manifest_path = work / "cp936.manifest"
        manifest.write(manifest_path, encoding="utf-8", xml_declaration=True)
        subprocess.run([str(mt), "-nologo", "-manifest", str(manifest_path), f"-outputresource:{target};#1"], cwd=ROOT, check=True, capture_output=True, timeout=20)
        result = run_launcher(target, cwd, '')
        assert_failure(result, "requires an effective UTF-8 process code page")
        assert "(code 936)" in result.stdout, result.stdout
        legacy = {"status": "REJECTED_NON_UTF8_AS_EXPECTED", "native_acp": 936, "original_launcher_unmodified": True}
    assert digest(launcher) == before
    record = {"status": "PASS", "launcher_sha256": before, "tests": results, "missing_script_rejected": True, "missing_runtime_rejected": True, "invalid_runtime_rejected": True, "argument_override_rejected": True, "legacy_manifest_diagnostic": legacy, "real_cuda_or_ocr_executed": False, "fixture_directory_preserved": str(work)}
    with (work / "result.json").open("x", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(record, ensure_ascii=False))


if __name__ == "__main__":
    main()
