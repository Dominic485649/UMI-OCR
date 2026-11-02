"""Run the locked Qt6 translation tools only on the six supported catalogs."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

LANGUAGES = ("en_US", "ja_JP", "pt", "ru_RU", "ta", "zh_TW")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("update", "compile"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--tools", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--languages", nargs="+", choices=LANGUAGES, default=LANGUAGES)
    args = parser.parse_args()
    exe = args.tools / ("lupdate.exe" if args.command == "update" else "lrelease.exe")
    provenance = json.loads((args.audit.parent / "qt-tools.json").read_text(encoding="utf-8"))
    expected = next(item["sha256"] for item in provenance["files"] if item["name"] == exe.name)
    if digest(exe) != expected:
        raise SystemExit("Qt tool changed since wheel verification")
    version_cmd = [str(exe), "-version"]
    version_run = subprocess.run(version_cmd, capture_output=True, encoding="utf-8", errors="replace", check=True)
    version = (version_run.stdout + version_run.stderr).strip()
    if "6.11.2" not in version:
        raise SystemExit("Unexpected Qt tool version: " + version)
    results = []
    for language in args.languages:
        ts = args.root / "dev-tools/i18n/release" / (language + ".ts")
        before = digest(ts)
        if args.command == "update":
            command = [str(exe), str(args.root / "UmiOCR-data/qt_res/qml"), "-recursive", "-source-language", "zh_CN", "-target-language", language, "-ts", str(ts)]
            output = ts
        else:
            output = args.root / "UmiOCR-data/i18n" / (language + ".qm")
            command = [str(exe), "-nounfinished", str(ts), "-qm", str(output)]
        completed = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace", check=False)
        item = {"language": language, "command": command, "returncode": completed.returncode,
                "stdout": completed.stdout, "stderr": completed.stderr, "tsBeforeSha256": before,
                "tsSha256": digest(ts), "output": str(output), "outputSha256": digest(output) if output.exists() else None}
        results.append(item)
        if completed.returncode:
            args.audit.write_text(json.dumps({"version": version, "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            raise SystemExit("Qt command failed; see " + str(args.audit))
    args.audit.write_text(json.dumps({"versionCommand": version_cmd, "version": version, "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"command": args.command, "version": version, "catalogs": len(results), "returncodes": [item["returncode"] for item in results]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
