"""Prepare an install overlay without overwriting the host's source/notices."""

import argparse
from pathlib import Path
import shutil

PLUGIN_ID = "win32_PaddleOCRv6_CUDA"


def prepare(staging, output):
    staging = staging.resolve()
    if output.exists() or output.is_symlink():
        raise RuntimeError("CUDA overlay output must be new")
    plugin = staging / "UmiOCR-data/plugins" / PLUGIN_ID
    if not plugin.is_dir() or not (staging / "LICENSES").is_dir():
        raise RuntimeError("A completed standalone CUDA staging tree is required")
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    target = output / "UmiOCR-data/plugins" / PLUGIN_ID
    target.parent.mkdir(parents=True)
    shutil.copytree(plugin, target)
    notices = output / "LICENSES/plugins" / PLUGIN_ID
    notices.mkdir(parents=True)
    for child in staging.iterdir():
        if child.name in {"UmiOCR-data", ".build"}:
            continue
        destination = notices / child.name
        if child.is_dir():
            shutil.copytree(child, destination)
        elif child.is_file():
            shutil.copy2(child, destination)
    print("CUDA install overlay prepared; host root source and licenses are untouched:", output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.staging_root, args.output_dir)
