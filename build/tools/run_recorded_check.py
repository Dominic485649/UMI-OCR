"""执行一条具名验证命令，保留真实合并输出、超时和退出码，不覆盖旧记录。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or not 0 < args.timeout <= 1800:
        parser.error("必须提供命令和有效验证期限")
    root = Path(__file__).resolve().parents[2]
    record = args.record.absolute()
    audit = (root / "build/audit").resolve(strict=True)
    parent = record.parent.resolve(strict=True)
    if not parent.is_relative_to(audit):
        raise ValueError("验证记录必须位于本项目 build/audit 内")
    for item in [record.parent, *record.parent.parents]:
        if item.is_symlink() or item.is_junction():
            raise ValueError("验证记录拒绝链接路径")
        if item == root:
            break
    log = record.with_suffix(".log")
    if record.exists() or log.exists():
        raise FileExistsError("拒绝覆盖已有验证记录")
    started = datetime.now(timezone.utc).isoformat()
    begin = time.monotonic()
    timed_out = False
    with log.open("xb") as stream:
        process = subprocess.Popen(command, cwd=root, stdin=subprocess.DEVNULL,
                                   stdout=stream, stderr=subprocess.STDOUT, shell=False)
        try:
            code = process.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.terminate()
            try:
                code = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                code = process.wait(timeout=10)
    payload = log.read_bytes()
    result = {"command": command, "cwd": str(root), "startedUtc": started,
              "finishedUtc": datetime.now(timezone.utc).isoformat(),
              "elapsedSeconds": time.monotonic() - begin, "exitCode": code,
              "timedOut": timed_out, "log": str(log),
              "logSha256": hashlib.sha256(payload).hexdigest()}
    with record.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if code or timed_out:
        print(payload[-12000:].decode("utf-8", errors="replace"))
    return 1 if timed_out else (code if 0 <= code <= 255 else 1)


if __name__ == "__main__":
    sys.exit(main())
