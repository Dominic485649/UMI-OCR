"""为本地非最终审查候选生成标准tar.xz并绑定全部输入字节；不发布或授权发布。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[2]


def adjacent(name):
    spec = importlib.util.spec_from_file_location("local_review_" + name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


layout = adjacent("runtime_archive_layout")
packaging = adjacent("package_tar_xz")
merge = adjacent("merge_runtime")


def payload(root):
    return {name: layout.sha256_file(path) for name, path in layout.tree_files(root).items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--component", choices=("base", "cuda", "vl"), required=True)
    args = parser.parse_args()
    root, output, audit = (layout.plain_path(path) for path in (args.root, args.output, args.audit))
    for path in (root, output, audit):
        path.relative_to(ROOT / "build")
    if output.exists() or audit.exists():
        raise FileExistsError("归档与证据必须使用新路径")
    if merge.running_processes(root):
        raise RuntimeError("候选目录有运行进程，拒绝打包；请正常退出")
    if not root.is_dir() or not output.parent.is_dir() or not audit.parent.is_dir():
        raise ValueError("输入与输出父目录须已建立并核对")
    started = time.monotonic()
    before = payload(root)
    input_verified = time.monotonic()
    result = packaging.create_archive(root, output, streaming=True)
    archive_verified = time.monotonic()
    after = payload(root)
    finished = time.monotonic()
    stable = before == after
    record = {"purpose": "local-nonfinal-review-artifact", "component": args.component,
              "publicReleaseAuthorized": False, "formalRelease": False, "status": "PASS" if stable else "FAIL",
              "inputRoot": str(root), "payload": before, "sourceUnchangedDuringPackaging": stable,
              "elapsedSeconds": round(finished - started, 3),
              "inputVerificationSeconds": round(input_verified - started, 3),
              "archiveCreationAndVerificationSeconds": round(archive_verified - input_verified, 3),
              "postPackagingVerificationSeconds": round(finished - archive_verified, 3), "archive": result,
              "packagerSha256": layout.sha256_file(Path(packaging.__file__)),
              "driverSha256": layout.sha256_file(Path(__file__)),
              "limits": "只证明本地归档完整性与输入稳定；不替代包内/重装验收、许可公开发布门禁或当次用户审查。"}
    with audit.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"status": record["status"], "component": args.component, "files": len(before),
                      "archive": result, "elapsedSeconds": record["elapsedSeconds"], "audit": str(audit)}, ensure_ascii=False))
    return 0 if stable else 1


if __name__ == "__main__":
    raise SystemExit(main())
