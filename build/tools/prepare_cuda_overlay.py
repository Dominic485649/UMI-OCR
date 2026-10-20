"""Prepare an install overlay without overwriting the host's source/notices."""

import argparse
from pathlib import Path
import shutil

PLUGIN_ID = "win32_PaddleOCRv6_CUDA"
PRIVATE_NAMES = {
    "__pycache__", ".settings", ".pre_settings", ".plugins_state", "themes.json",
    "temp", "temp_doc", "logs", "startup_error.log", ".build",
}
SOURCE_RECORDS = (
    "COPYING", "LICENSE", "NOTICE.md", "VERSION", "SOURCE-CODE.md",
    "source-snapshot.zip", "source-snapshot.json", "source-provenance.json", "source",
)


def private_path(relative):
    return any(part.casefold() in PRIVATE_NAMES or part.casefold().endswith(".pyc")
               for part in relative.parts)


def ignore_private(_directory, names):
    return {name for name in names if private_path(Path(name))}


def prepare(staging, output, *, combined=False):
    staging = staging.resolve()
    if output.exists() or output.is_symlink():
        raise RuntimeError("CUDA overlay output must be new")
    plugin = staging / "UmiOCR-data/plugins" / PLUGIN_ID
    licenses = staging / "LICENSES"
    if combined:
        licenses = licenses / "plugins" / PLUGIN_ID
    if not plugin.is_dir() or not licenses.is_dir():
        raise RuntimeError("A completed CUDA staging tree with plugin-specific licenses is required")
    if combined:
        # A combined candidate's root LICENSES belongs to the host. Only its
        # selected plugin notices and explicit source records enter the overlay.
        entries = [(licenses, "LICENSES")]
        entries.extend((staging / name, name) for name in SOURCE_RECORDS
                       if (staging / name).exists())
    else:
        entries = [(child, child.name) for child in staging.iterdir()
                   if child.name != "UmiOCR-data" and not private_path(Path(child.name))]
    for source in [plugin, *(path for path, _ in entries)]:
        if source.is_symlink() or source.is_dir() and any(path.is_symlink() for path in source.rglob("*")):
            raise RuntimeError(f"CUDA overlay source contains a link: {source}")
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    target = output / "UmiOCR-data/plugins" / PLUGIN_ID
    target.parent.mkdir(parents=True)
    shutil.copytree(plugin, target, ignore=ignore_private)
    notices = output / "LICENSES/plugins" / PLUGIN_ID
    notices.mkdir(parents=True)
    for source, name in entries:
        destination = notices / name
        if source.is_dir():
            shutil.copytree(source, destination, ignore=ignore_private)
        elif source.is_file():
            shutil.copy2(source, destination)
    print("CUDA install overlay prepared; host root source and licenses are untouched:", output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--combined", action="store_true", help="read the selected CUDA notices from a combined candidate")
    args = parser.parse_args()
    prepare(args.staging_root, args.output_dir, combined=args.combined)
