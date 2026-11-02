import argparse
import contextlib
import ctypes
import json
import math
import os
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from ctypes import wintypes


SETTINGS_FILES = (".settings", ".pre_settings", "themes.json")


def _find_visible_window(process_id):
    matches = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def visit(hwnd, _lparam):
        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value != process_id or not ctypes.windll.user32.IsWindowVisible(hwnd):
            return True
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, title, len(title))
        if title.value.startswith("Umi-OCR"):
            matches.append(hwnd)
        return True

    ctypes.windll.user32.EnumWindows(visit, 0)
    return matches[0] if matches else None


@contextlib.contextmanager
def _preserve_portable_state(data_root):
    originals = {}
    for name in SETTINGS_FILES:
        path = data_root / name
        originals[path] = path.read_bytes() if path.is_file() else None
    try:
        yield
    finally:
        for path, content in originals.items():
            path.unlink(missing_ok=True)
            if content is not None:
                path.write_bytes(content)


def _clean_portable_state(data_root):
    for name in SETTINGS_FILES:
        (data_root / name).unlink(missing_ok=True)


def _measure_once(executable, timeout):
    data_root = executable.parent / "UmiOCR-data"
    _clean_portable_state(data_root)
    started = time.perf_counter()
    process = subprocess.Popen(
        [str(executable), "--force"],
        cwd=executable.parent,
        close_fds=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        deadline = started + timeout
        while time.perf_counter() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"Umi-OCR exited before showing a window: {process.returncode}")
            hwnd = _find_visible_window(process.pid)
            if hwnd:
                ctypes.windll.dwmapi.DwmFlush()
                return (time.perf_counter() - started) * 1000.0
            time.sleep(0.005)
        raise TimeoutError(f"No Umi-OCR window after {timeout:.1f} seconds")
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(10)


def _summary(executable, warmups, measurements, timeout):
    executable = executable.resolve()
    if not executable.is_file():
        raise FileNotFoundError(executable)
    data_root = executable.parent / "UmiOCR-data"
    with _preserve_portable_state(data_root):
        for _ in range(warmups):
            _measure_once(executable, timeout)
        samples = [_measure_once(executable, timeout) for _ in range(measurements)]
    ordered = sorted(samples)
    return {
        "executable": Path(*executable.parts[-3:]).as_posix(),
        "warmups": warmups,
        "measurements": measurements,
        "samplesMs": [round(value, 3) for value in samples],
        "medianMs": round(statistics.median(samples), 3),
        "p95Ms": round(ordered[math.ceil(len(ordered) * 0.95) - 1], 3),
    }


def main():
    if os.name != "nt":
        raise RuntimeError("The startup UI benchmark requires Windows.")
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--measurements", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args()

    baseline = _summary(args.baseline, args.warmups, args.measurements, args.timeout)
    candidate = _summary(args.candidate, args.warmups, args.measurements, args.timeout)
    change = (candidate["medianMs"] / baseline["medianMs"] - 1.0) * 100.0
    result = {
        "timestampUtc": datetime.now(timezone.utc).isoformat(),
        "method": "3 warmups, 10 measurements, visible window plus DwmFlush",
        "baseline": baseline,
        "candidate": candidate,
        "medianChangePercent": round(change, 2),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
