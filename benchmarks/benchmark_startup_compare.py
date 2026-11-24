"""交错比较两个自有正常EXE副本；不改配置、不清缓存、不强制结束进程。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import benchmark_startup_isolated as bench


def statistics_for(pairs):
    baseline = [row["baselineMs"] for row in pairs]
    candidate = [row["candidateMs"] for row in pairs]
    differences = [left - right for left, right in zip(baseline, candidate)]
    randomizer = random.Random(20261029)
    resampled = sorted(statistics.median(randomizer.choices(differences, k=len(differences))) for _ in range(3000))
    interval = [resampled[74], resampled[2924]]
    decision = "INCONCLUSIVE" if interval[0] <= 0 <= interval[1] else ("OBSERVED_IMPROVEMENT" if interval[0] > 0 else "OBSERVED_REGRESSION")
    def summary(values):
        return {"medianMs": statistics.median(values), "minMs": min(values), "maxMs": max(values),
                "stdevMs": statistics.stdev(values) if len(values) > 1 else 0}
    return {"baseline": summary(baseline), "candidate": summary(candidate), "pairedBaselineMinusCandidateMs": differences,
            "medianPairedDifferenceMs": statistics.median(differences), "pairedMedianBootstrap95PercentMs": interval,
            "assessment": decision,
            "limits": "此置信区间只描述本机同场景有限交错样本，不能消除系统性环境差异或外推到其他机器。"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=8)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--execute-authorized", action="store_true")
    args = parser.parse_args()
    bench.require(args.execute_authorized, "真实EXE比较必须明确授权")
    bench.require(4 <= args.pairs <= 20 and 1 <= args.warmups <= 5, "采样数量超出有限范围")
    paths = {"baseline": bench.artifact_path(args.baseline), "candidate": bench.artifact_path(args.candidate)}
    bench.require(paths["baseline"].parent != paths["candidate"].parent, "比较需要不同的自有副本")
    owners = {key: bench.load_owner(path) for key, path in paths.items()}
    bench.require(owners["baseline"]["profile"] == owners["candidate"]["profile"] and owners["baseline"]["http"] == owners["candidate"]["http"], "启动场景不一致")
    for path in paths.values():
        bench.assert_idle(path.parent)
    output = bench.checked_path(args.output, bench.AUDIT_ROOT)
    bench.require(not output.exists(), "使用全新比较证据目录")
    output.mkdir()
    arm_outputs = {key: output / (output.name + ("-a" if key == "baseline" else "-b")) for key in paths}
    for directory in arm_outputs.values():
        directory.mkdir()
    bench.write_new(output / "inputs.json", {"arguments": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
        "owners": owners, "driverSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "sampleDriverSha256": hashlib.sha256(Path(bench.__file__).read_bytes()).hexdigest(), "python": sys.version,
        "conditions": "持久独立配置/Qt缓存，不清系统缓存；只比较同样散文件布局的启动逻辑，不是ZIP启动A/B。"})
    report = {"status": "FAIL", "samples": [], "pairs": [], "firstRunIsNotColdBoot": True,
              "modelInference": "NOT_REQUESTED", "forcedTermination": False}
    counters = {key: 0 for key in paths}
    def sample(key, *, warmup):
        index = counters[key]
        result = bench.sample(paths[key], owners[key], arm_outputs[key], index, 30, 0.5, 40)
        result.update(arm=key, warmup=warmup)
        counters[key] += 1
        bench.write_new(arm_outputs[key] / f"sample-{index}.json", result)
        report["samples"].append(result)
        bench.require(result["status"] == "PASS", "比较中样本失败，保留现场且停止后续启动：" + json.dumps(result, ensure_ascii=False))
        return result
    try:
        for _ in range(args.warmups):
            for key in ("baseline", "candidate"):
                sample(key, warmup=True)
        for index in range(args.pairs):
            order = ("baseline", "candidate") if index % 2 == 0 else ("candidate", "baseline")
            values = {key: sample(key, warmup=False) for key in order}
            report["pairs"].append({"index": index, "order": list(order),
                "baselineMs": values["baseline"]["interactiveMs"], "candidateMs": values["candidate"]["interactiveMs"],
                "baselineRunId": values["baseline"]["runId"], "candidateRunId": values["candidate"]["runId"]})
        report.update(status="PASS", statistics=statistics_for(report["pairs"]))
    except Exception as exc:
        report["error"] = str(exc)
    bench.write_new(output / "report.json", report)
    print(json.dumps({"status": report["status"], "pairs": len(report["pairs"]), "statistics": report.get("statistics"), "report": str(output / "report.json")}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
