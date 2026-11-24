"""Extract only Qt Linguist CLI tools and required DLLs from a locked wheel."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--audit", required=True, type=Path)
    args = parser.parse_args()
    lock_text = args.lock.read_text(encoding="utf-8-sig")
    match = re.search(r"(?im)^pyside6[-_]essentials==([^\s\\]+)\s*\\?\s*--hash=sha256:([0-9a-f]{64})", lock_text)
    if not match:
        raise SystemExit("PySide6 Essentials pinned version/hash not found in lock")
    version, expected = match.groups()
    digest = hashlib.sha256(args.wheel.read_bytes()).hexdigest()
    if digest != expected.lower() or version not in args.wheel.name:
        raise SystemExit("Qt tool wheel does not match the pinned version/hash")
    if args.output.exists():
        raise SystemExit("Refusing to extract into an existing directory")
    args.output.mkdir(parents=True)
    names = {"lupdate.exe", "lrelease.exe", "Qt6Core.dll", "Qt6Qml.dll", "Qt6Network.dll", "Qt6Xml.dll", "Qt6Concurrent.dll", "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "vcruntime140.dll", "vcruntime140_1.dll"}
    files = []
    with zipfile.ZipFile(args.wheel) as archive:
        for item in archive.infolist():
            parts = Path(item.filename).parts
            if len(parts) == 2 and parts[0] == "PySide6" and parts[1] in names:
                data = archive.read(item)
                destination = args.output / parts[1]
                destination.write_bytes(data)
                files.append({"name": parts[1], "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)})
    versions = {}
    for tool in ("lupdate", "lrelease"):
        path = args.output / (tool + ".exe")
        if not path.is_file():
            raise SystemExit("Locked wheel has no " + tool)
        result = subprocess.run([str(path), "-version"], capture_output=True, text=True, check=True)
        output = (result.stdout + result.stderr).strip()
        if version not in output:
            raise SystemExit("Qt tool reported unexpected version: " + output)
        versions[tool] = output
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    report = {"wheel": str(args.wheel), "wheelSha256": digest, "lock": str(args.lock), "lockSha256": hashlib.sha256(args.lock.read_bytes()).hexdigest(), "version": version, "files": files, "toolVersions": versions}
    args.audit.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"version": version, "toolVersions": versions, "extractedFiles": len(files)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
