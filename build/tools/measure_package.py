"""Write a reproducible package inventory for a staging root and its 7z file."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    archive = args.archive.resolve()
    if not root.is_dir() or not archive.is_file():
        raise SystemExit("root and archive must exist")

    files = []
    by_hash = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        digest = sha256(path)
        item = {"path": relative, "size": size, "sha256": digest}
        files.append(item)
        by_hash.setdefault((size, digest), []).append(relative)

    files.sort(key=lambda item: (-item["size"], item["path"]))
    duplicates = [
        {"size": size, "sha256": digest, "count": len(paths), "paths": sorted(paths)}
        for (size, digest), paths in by_hash.items()
        if len(paths) > 1
    ]
    duplicates.sort(key=lambda item: (-item["size"] * (item["count"] - 1), item["sha256"]))
    total = sum(item["size"] for item in files)
    archive_size = archive.stat().st_size
    report = {
        "label": args.label,
        "timestampUtc": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "archivePath": str(archive),
        "fileCount": len(files),
        "totalBytes": total,
        "archiveBytes": archive_size,
        "archiveSha256": sha256(archive),
        "compressionRatio": round(archive_size / total, 6) if total else 0,
        "duplicateGroups": len(duplicates),
        "duplicateWastedBytes": sum(item["size"] * (item["count"] - 1) for item in duplicates),
        "largestFiles": files[:50],
        "files": files,
        "duplicates": duplicates,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps({key: report[key] for key in report if key not in {"files", "duplicates", "largestFiles"}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
