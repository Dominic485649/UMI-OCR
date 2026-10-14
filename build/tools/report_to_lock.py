import argparse
import json
from pathlib import Path


def make_header(comment, extra_index_url):
    lines = [
        f"# {comment}",
        "# Generated from pip's Windows CPython 3.13 resolution report; do not edit by hand.",
        "--index-url https://pypi.org/simple",
    ]
    if extra_index_url:
        lines.append(f"--extra-index-url {extra_index_url}")
    lines.extend(("--only-binary=:all:", "", ""))
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("report")
    parser.add_argument("output")
    parser.add_argument("overrides", nargs="*")
    parser.add_argument(
        "--comment",
        default="Regenerate with build/windows/Resolve-Lock.ps1.",
    )
    parser.add_argument(
        "--extra-index-url",
        default="https://www.paddlepaddle.org.cn/packages/stable/cu126/",
    )
    args = parser.parse_args()
    packages = {}
    for report_path in (args.report, *args.overrides):
        report = json.loads(Path(report_path).read_text(encoding="utf-8"))
        for item in report["install"]:
            name = item["metadata"]["name"].lower().replace("_", "-")
            package_version = item["metadata"]["version"]
            hashes = item["download_info"].get("archive_info", {}).get("hashes", {})
            sha256 = hashes.get("sha256")
            if not sha256:
                raise RuntimeError(f"Missing SHA256 for {name}=={package_version}")
            packages[name] = (package_version, sha256)
    lines = []
    for name, (package_version, sha256) in sorted(packages.items()):
        lines.append(f"{name}=={package_version} \\")
        lines.append(f"    --hash=sha256:{sha256}")
    Path(args.output).write_text(
        make_header(args.comment, args.extra_index_url) + "\n".join(lines) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
