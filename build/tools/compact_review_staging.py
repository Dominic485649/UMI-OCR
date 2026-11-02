"""仅压缩本轮明确列出的打包暂存目录，保留全部文件并验证内容哈希不变。"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def adjacent(name):
    spec = importlib.util.spec_from_file_location("review_compact_" + name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


layout = adjacent("runtime_archive_layout")
merge = adjacent("merge_runtime")
measurement = adjacent("measure_runtime_layout")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("packaging", "completed-candidates", "post-run-reserve"), default="packaging")
    args = parser.parse_args()
    name = {"packaging": "compact-review-staging-20261029-r1",
            "completed-candidates": "compact-completed-candidates-20261029-r1",
            "post-run-reserve": "compact-post-run-reserve-20261029-r1"}[args.profile]
    audit = ROOT / "build/audit/startup-small-files-20261028-r1" / name
    if audit.exists():
        raise FileExistsError("不覆盖已有压缩记录")
    if args.profile == "packaging":
        roots = [ROOT / "build/artifacts/startup-small-files-20261029-r1" / name for name in ("cuda-overlay", "vl-overlay")]
    elif args.profile == "post-run-reserve":
        # 仅已结束的本轮基线与已授权插件项目的新候选，不删除或清扫插件项目。
        roots = [ROOT / "build/staging" / ("startup-small-files-20261028-base-baseline-r" + str(index))
                 for index in (1, 2, 3, 4)]
        roots += [ROOT.parent / "Umi-OCR-Plugin/build/staging/startup-small-files-20261029-vl-r2",
                  ROOT / "build/staging/startup-small-files-20261029-base-stored-r2",
                  ROOT / "build/tmp/startup-small-files-20261028-r1/stored-base-native-ui-20261029-r2"]
    else:
        # 已完成本轮运行的具名副本；不含活动的r2 UI、副仓库、历史种子或最终重装根。
        roots = [ROOT / "build/staging" / name for name in (
            "startup-small-files-20261029-base-opt-loose-r1",
            "startup-small-files-20261029-base-stored-r1",
            "startup-small-files-20261029-cuda-r1")]
        roots += [ROOT / "build/tmp/startup-small-files-20261028-r1" / name for name in (
            "compare-20261029-r1-a", "compare-20261029-r1-b",
            "stored-base-ui-20261029-r1", "stored-base-native-ui-20261029-r1")]
    for root in roots:
        layout.plain_path(root)
        if not root.is_dir() or merge.running_processes(root):
            raise RuntimeError("暂存目录缺失或有运行进程：" + str(root))
        layout.tree_files(root)
    audit.mkdir()
    rows = []
    for root in roots:
        before = {name: layout.sha256_file(path) for name, path in layout.tree_files(root).items()}
        allocated_before = measurement.measure(root)["total"]
        command = ["compact.exe", "/C", "/S:" + str(root), "/Q"]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=600)
        raw = result.stdout + result.stderr
        (audit / (root.name + ".log")).write_bytes(raw)
        after = {name: layout.sha256_file(path) for name, path in layout.tree_files(root).items()}
        allocated_after = measurement.measure(root)["total"]
        record = {"root": str(root), "command": command, "exitCode": result.returncode,
                  "files": before, "bytesUnchanged": before == after,
                  "before": allocated_before, "after": allocated_after,
                  "logSha256": hashlib.sha256(raw).hexdigest()}
        rows.append(record)
        if result.returncode or before != after:
            with (audit / "result.json").open("x", encoding="utf-8") as stream:
                json.dump({"status": "FAIL", "rows": rows}, stream, ensure_ascii=False, indent=2)
            raise RuntimeError("压缩失败或内容变化，停止，不绕过错误")
    record = {"status": "PASS", "profile": args.profile,
              "scope": "本轮具名自有副本的可逆NTFS存储属性压缩；不是ZIP聚合收益或模型内容修改。completed-candidates发生在运行和统计之后，不改写历史未压缩条件；最终归档重装根不在此列表。",
              "filesDeleted": False, "globalSystemSettingsChanged": False, "rows": rows}
    with (audit / "result.json").open("x", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
    print(json.dumps({"status": "PASS", "rows": [{k: v for k, v in row.items() if k != "files"} for row in rows]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
