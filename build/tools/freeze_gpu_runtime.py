"""Build a deterministic native closure lock without circular E2E input."""

import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def generate(plugin):
    manifest = json.loads((plugin / "umi-plugin.json").read_text(encoding="utf-8"))
    files = sorted(path for path in plugin.rglob("*") if path.is_file()
                   and path.name not in {"runtime.lock.json", "gpu-e2e-evidence.json"}
                   and "__pycache__" not in path.relative_to(plugin).parts)
    native = [{"path": path.relative_to(plugin).as_posix(), "sha256": digest(path)}
              for path in files if path.suffix.lower() in {".dll", ".pyd"}]
    record = {
        "pluginId": manifest["id"], "version": manifest["version"],
        "lock": "build/requirements-gpu-plugin-windows-cu126.lock",
        "fileCount": len(files), "totalBytes": sum(path.stat().st_size for path in files),
        "nativeBinaryCount": len(native), "files": native,
        "count_excludes": ["runtime.lock.json", "gpu-e2e-evidence.json", "__pycache__"],
    }
    (plugin / "runtime.lock.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print("GPU native closure frozen:", len(native), "binaries; E2E evidence excluded from its inputs.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("plugin", type=Path)
    args = parser.parse_args()
    generate(args.plugin.resolve())
