"""按依赖闭包把统一的锁文件拆成 基础包锁 与 GPU 插件锁。

刻意【从现有已验证的锁过滤派生】，而不是重新做依赖解析：
重新解析会联网、会引入版本漂移，而现有锁的版本与哈希已经通过完整回归。
过滤保留原样的 pin 与 --hash ，两份新锁对 pip 仍然是 --require-hashes 可用的。

分组依据是 measure_closure.py 产出的闭包报告：
- 基础包锁 = shared + baseOnly
- GPU 插件锁 = shared + gpuOnly + orphan
  （插件自包含：即使 numpy/pillow 与基础包重复也照带，卸载=删目录，
    基础包换 numpy 大版本不会打断插件。）

用法：
    python build/tools/split_lock.py \
        build/requirements-windows-cu126.lock \
        benchmarks/results/closure-2.6.0-sitepackages.json \
        --base-out build/requirements-base-windows.lock \
        --gpu-out  build/requirements-gpu-plugin-windows-cu126.lock
"""

import argparse
import json
import re
import sys
from pathlib import Path

# GPU 插件锁需要 paddle 官方源；基础包锁不再需要，去掉可以让基础包构建
# 完全不接触 paddlepaddle.org.cn 。
PADDLE_INDEX = "paddlepaddle.org.cn"
GPU_RUNTIME_EXCLUSIONS = {"aistudio-sdk"}

_ENTRY = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*==")


def canon(name):
    return re.sub(r"[-_.]+", "-", str(name)).strip().lower()


def parseLock(text):
    """返回 (前导指令行, [(规范名, 原文块)])"""
    preamble, entries = [], []
    current = None
    for line in text.splitlines():
        match = _ENTRY.match(line)
        if match:
            if current:
                entries.append(current)
            current = [canon(match.group(1)), [line]]
        elif current is not None:
            # 续行（--hash=... 或反斜杠续行）都属于当前条目
            if line.strip().startswith(("--hash", "\\")) or line.startswith((" ", "\t")):
                current[1].append(line)
            elif not line.strip():
                current[1].append(line)
            else:
                entries.append(current)
                current = None
                preamble.append(line)
        else:
            preamble.append(line)
    if current:
        entries.append(current)
    return preamble, [(name, "\n".join(block).rstrip()) for name, block in entries]


def writeLock(path, preamble, entries, names, title, dropPaddleIndex):
    selected = [(name, block) for name, block in entries if name in names]
    lines = [f"# {title}", "# 由 build/tools/split_lock.py 从统一锁过滤派生，请勿手工编辑。"]
    for line in preamble:
        stripped = line.strip()
        if not stripped or stripped.startswith("# Regenerate") or stripped.startswith("# Generated"):
            continue
        if dropPaddleIndex and PADDLE_INDEX in stripped:
            continue
        lines.append(stripped)
    lines.append("")
    for _, block in sorted(selected, key=lambda item: item[0]):
        lines.append(block)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return selected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("lock", type=Path)
    parser.add_argument("closure", type=Path)
    parser.add_argument("--base-out", type=Path, required=True)
    parser.add_argument("--gpu-out", type=Path, required=True)
    args = parser.parse_args()

    preamble, entries = parseLock(args.lock.read_text("utf-8"))
    report = json.loads(args.closure.read_text("utf-8"))

    def group(label):
        return {canon(item["name"]) for item in report["groups"][label]}

    shared, baseOnly = group("shared"), group("baseOnly")
    gpuOnly, orphan = group("gpuOnly"), group("orphan")

    baseNames = shared | baseOnly
    gpuNames = (shared | gpuOnly | orphan) - GPU_RUNTIME_EXCLUSIONS

    baseSelected = writeLock(
        args.base_out, preamble, entries, baseNames,
        "Umi-OCR 基础包依赖锁（无 CUDA / 无 Paddle / 无 OCR 推理）",
        dropPaddleIndex=True,
    )
    gpuSelected = writeLock(
        args.gpu_out, preamble, entries, gpuNames,
        "Umi-OCR GPU OCR 插件依赖锁（自包含，含 CUDA 与 Paddle）",
        dropPaddleIndex=False,
    )

    lockNames = {name for name, _ in entries}
    unplaced = sorted(lockNames - baseNames - gpuNames - GPU_RUNTIME_EXCLUSIONS)
    missing = sorted((baseNames | gpuNames) - lockNames)

    print(f"统一锁条目      : {len(entries)}")
    print(f"基础包锁        : {len(baseSelected):>3} 条  -> {args.base_out}")
    print(f"GPU 插件锁      : {len(gpuSelected):>3} 条  -> {args.gpu_out}")
    print(f"两份共有（重复携带）: {len(baseNames & gpuNames)} 条  {sorted(baseNames & gpuNames)}")
    print(f"GPU 运行时裁剪     : {sorted(GPU_RUNTIME_EXCLUSIONS)}")
    if unplaced:
        print(f"\n[FAIL] 锁中有条目未被任何闭包覆盖，不能盲目丢弃：{unplaced}")
        return 1
    if missing:
        print(f"\n[WARN] 闭包中有名字不在锁里（通常是构建期工具）：{missing}")
    print("\n每条锁条目都已归属，无遗漏。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
