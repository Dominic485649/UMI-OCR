"""复用同一PAX tar及载荷门禁，仅为尚未开始的本地组件归档选择较快XZ参数。"""
from __future__ import annotations

import argparse
import importlib.util
import json
import lzma
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("local_review_original_guards", Path(__file__).with_name("package_local_review.py"))
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def create_fast_archive(root, output):
    """标准tar.xz，不压缩或改写内部Stored成员，不产生中间tar。"""
    root, output = review.layout.plain_path(root), review.layout.plain_path(output)
    if not root.is_dir() or output == root or root in output.parents:
        raise ValueError("输入必须为目录，归档输出不得位于输入内部")
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    with output.open("xb") as destination:
        with lzma.LZMAFile(destination, mode="w", format=lzma.FORMAT_XZ, preset=1) as stream:
            count = review.packaging._write_tar(root, None, stream=stream)
    result = review.packaging.verify_archive(output)
    result.update(root=str(root), member_count=count, compressor="python-stdlib-streamed-standard-lzma2",
                  compression_preset=1, temporary_tar_created=False)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--component", choices=("vl",), required=True)
    args = parser.parse_args()
    root, output, audit = (review.layout.plain_path(path) for path in (args.root, args.output, args.audit))
    for path in (root, output, audit):
        path.relative_to(ROOT / "build")
    if output.exists() or audit.exists():
        raise FileExistsError("不覆盖既有归档或审计")
    if review.merge.running_processes(root):
        raise RuntimeError("暂存仍有进程使用，拒绝打包，不结束任何进程")
    if not root.is_dir() or not output.parent.is_dir() or not audit.parent.is_dir():
        raise ValueError("输入与输出父目录须已建立并核对")
    started = time.monotonic()
    before = review.payload(root)
    input_verified = time.monotonic()
    result = create_fast_archive(root, output)
    archive_verified = time.monotonic()
    after = review.payload(root)
    finished = time.monotonic()
    stable = before == after
    record = {"purpose": "local-nonfinal-review-artifact", "component": args.component,
              "publicReleaseAuthorized": False, "formalRelease": False, "status": "PASS" if stable else "FAIL",
              "inputRoot": str(root), "payload": before, "sourceUnchangedDuringPackaging": stable,
              "elapsedSeconds": round(finished-started, 3),
              "inputVerificationSeconds": round(input_verified-started, 3),
              "archiveCreationAndVerificationSeconds": round(archive_verified-input_verified, 3),
              "postPackagingVerificationSeconds": round(finished-archive_verified, 3), "archive": result,
              "packagerSha256": review.layout.sha256_file(Path(review.packaging.__file__)),
              "reusedGuardDriverSha256": review.layout.sha256_file(Path(review.__file__)),
              "driverSha256": review.layout.sha256_file(Path(__file__)),
              "limits": "只改变外层XZ编码参数，不改变模型、原始载荷、内部ZIP_STORED或公开发行门禁；不提供压缩提速对照结论。"}
    with audit.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"status":record["status"],"component":args.component,"archive":result,"elapsedSeconds":record["elapsedSeconds"]}, ensure_ascii=False))
    return 0 if stable else 1


if __name__ == "__main__":
    raise SystemExit(main())
