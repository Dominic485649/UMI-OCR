"""Prepare an install overlay without overwriting the host's source/notices."""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import shutil
import stat
import sys
import zipfile

PLUGIN_ID = "win32_PaddleOCRv6_CUDA"
PRIVATE_NAMES = {
    "__pycache__", ".settings", ".pre_settings", ".plugins_state", "themes.json",
    "temp", "temp_doc", "logs", "startup_error.log", ".build",
}
SOURCE_RECORDS = (
    "COPYING", "LICENSE", "NOTICE.md", "VERSION", "SOURCE-CODE.md",
    "source-snapshot.zip", "source-snapshot.json", "source-provenance.json", "source",
)
# Assembly retains the independent GPU records here, never at the host root.
# This directory is removed from the notices copy and flattened into the existing
# overlay record location, so the delivered plugin has only one set of sources.
SOURCE_RECORDS_DIR = "source-records"
SOURCE_NAMESPACE = Path("LICENSES/plugins") / PLUGIN_ID / SOURCE_RECORDS_DIR


def private_path(relative):
    return any(part.casefold() in PRIVATE_NAMES or part.casefold().endswith(".pyc")
               for part in relative.parts)


def ignore_private(_directory, names):
    return {name for name in names if private_path(Path(name))}


def reject_link(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise RuntimeError(f"CUDA input/output path contains a link or junction: {path}")


def plain_path(path):
    # Check lexical ancestors BEFORE resolve() can hide a link/junction. Walking
    # prefixes also catches a link followed by '..' in an input path.
    path = Path(path)
    if not path.is_absolute():
        path = Path.cwd() / path
    current = Path(path.anchor)
    reject_link(current)
    for part in path.parts[1:]:
        current /= part
        reject_link(current)
    return path.resolve()


def check_tree(path):
    pending = [path]
    while pending:
        current = pending.pop()
        reject_link(current)
        if current.is_dir():
            pending.extend(current.iterdir())
        elif not current.is_file():
            raise RuntimeError(f"CUDA overlay source is not a regular file/directory: {current}")


def digest(stream):
    checksum = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        checksum.update(chunk)
    return checksum.hexdigest()


def file_digest(path):
    with path.open("rb") as stream:
        return digest(stream)


def json_object(data, description):
    document = json.loads(data.decode("utf-8-sig"))
    if not isinstance(document, dict):
        raise RuntimeError(f"CUDA {description} must be a JSON object")
    return document


def snapshot_relative(name):
    parts = name.split("/")
    if (len(parts) < 2 or parts[0] != "host" or
            any(not part or part in {".", ".."} or part.endswith((".", " ")) or
                any(char in '\\:<>"|?*' or ord(char) < 32 for char in part) for part in parts)):
        raise RuntimeError(f"Unsafe CUDA source snapshot member: {name!r}")
    return Path(*parts[1:])


def validate_records(records, plugin, *, require_version):
    for name in SOURCE_RECORDS:
        path = records / name
        if name == "source":
            if path.exists() and not path.is_dir():
                raise RuntimeError("CUDA source record 'source' must be a directory")
        elif name != "VERSION" or require_version or path.exists():
            if not path.is_file():
                raise RuntimeError(f"CUDA source records lack required file: {name}")
    live_manifest = json_object((plugin / "umi-plugin.json").read_bytes(), "plugin manifest")
    version = live_manifest.get("version")
    if live_manifest.get("id") != PLUGIN_ID or not isinstance(version, str) or not version.strip():
        raise RuntimeError("CUDA plugin manifest has the wrong identity/version")
    manifest = json_object((records / "source-snapshot.json").read_bytes(), "snapshot manifest")
    provenance = json_object((records / "source-provenance.json").read_bytes(), "source provenance")
    if (provenance.get("scope") != "public" or provenance.get("version") != version or
            provenance.get("files") != len(manifest) or not manifest):
        raise RuntimeError("CUDA source provenance scope/version/file count does not match its snapshot")
    # Validate manifest paths before ZIP readers can normalize Windows separators.
    for name in manifest:
        snapshot_relative(name)
    archive_path = records / "source-snapshot.zip"
    if file_digest(archive_path) != provenance.get("archive_sha256"):
        raise RuntimeError("CUDA source snapshot archive SHA256 does not match provenance")
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        names = [member.filename for member in members]
        if (len(names) != len(manifest) or set(names) != set(manifest) or
                len({name.casefold() for name in names}) != len(names)):
            raise RuntimeError("CUDA source snapshot member list does not match manifest")
        for member in members:
            snapshot_relative(member.filename)
            if member.is_dir() or stat.S_ISLNK(member.external_attr >> 16):
                raise RuntimeError(f"CUDA source snapshot contains a directory/link: {member.filename}")
            with archive.open(member) as stream:
                if digest(stream) != manifest[member.filename]:
                    raise RuntimeError(f"CUDA source snapshot member hash mismatch: {member.filename}")
        plugin_record = f"UmiOCR-data/plugins/{PLUGIN_ID}/umi-plugin.json"
        required = ("source-export.json", "VERSION", "UmiOCR-data/about.json", plugin_record)
        if any("host/" + name not in manifest for name in required):
            raise RuntimeError("CUDA source snapshot lacks source-export identity/version members")
        exported = json_object(archive.read("host/source-export.json"), "source export")
        # 'public' provenance alone also describes the host snapshot. Only the
        # CUDA export marker, bound to this verified ZIP, identifies GPU sources.
        revision = exported.get("parent_revision")
        if (exported.get("scope") != "public-cuda-only" or exported.get("version") != version or
                not isinstance(revision, str) or not revision.strip() or
                provenance.get("parent_revisions") != {"host": revision}):
            raise RuntimeError("CUDA source export identity/version/revision does not match provenance")
        # Build evidence can be refreshed after export. Bind stable identity files;
        # all delivered contents are checked against the snapshot manifest above.
        exported_files = exported.get("files")
        if not isinstance(exported_files, dict) or any(
                exported_files.get(name) != manifest["host/" + name] for name in required[1:]):
            raise RuntimeError("CUDA source export version/plugin records do not match the snapshot")
        source_manifest = json_object(archive.read("host/" + plugin_record), "source plugin manifest")
        about = json_object(archive.read("host/UmiOCR-data/about.json"), "source about.json")
        about_version = about.get("version")
        if isinstance(about_version, dict):
            about_version = ".".join(str(about_version.get(key)) for key in ("major", "minor", "patch"))
        version_bytes = archive.read("host/VERSION")
        if (source_manifest.get("id") != PLUGIN_ID or source_manifest.get("version") != version or
                about_version != version or version_bytes.decode("utf-8-sig").strip() != version or
                file_digest(plugin / "umi-plugin.json") != manifest["host/" + plugin_record]):
            raise RuntimeError("CUDA source snapshot version/plugin identity does not match the staged plugin")
    if (records / "VERSION").exists() and (records / "VERSION").read_text(encoding="utf-8-sig").strip() != version:
        raise RuntimeError("CUDA source record VERSION does not match the staged plugin")
    source = records / "source"
    if source.is_dir():
        mirrored = {"host/" + path.relative_to(source).as_posix(): file_digest(path)
                    for path in source.rglob("*") if path.is_file()}
        if mirrored != manifest:
            raise RuntimeError("CUDA loose source tree does not match its source snapshot")
    return version, version_bytes


def inspect_staging(staging, *, combined=False):
    staging = plain_path(staging)
    if not staging.is_dir():
        raise RuntimeError("A completed independent CUDA staging tree is required")
    plugin = plain_path(staging / "UmiOCR-data/plugins" / PLUGIN_ID)
    licenses = plain_path(staging / "LICENSES" / (Path("plugins") / PLUGIN_ID if combined else Path()))
    records = plain_path(staging / SOURCE_NAMESPACE) if combined else staging
    if combined and not records.is_dir():
        raise RuntimeError("Combined CUDA source records are missing; reassemble from an independent GPU staging tree")
    if not plugin.is_dir() or not licenses.is_dir():
        raise RuntimeError("A completed CUDA staging tree with plugin-specific licenses is required")
    entries = [(licenses, "LICENSES")] if combined else [
        (child, child.name) for child in staging.iterdir()
        if child.name != "UmiOCR-data" and not private_path(Path(child.name))]
    # No content is read and no output is created before all copied subpaths and
    # their ancestors have been checked, including Windows junctions.
    check_tree(plugin)
    for source, _ in entries:
        check_tree(source)
    version, version_bytes = validate_records(records, plugin, require_version=combined)
    record_names = [name for name in SOURCE_RECORDS if name == "VERSION" or (records / name).exists()]
    if combined:
        entries.extend((records / name, name) for name in record_names)
    elif not (records / "VERSION").exists():
        entries.append((records / "VERSION", "VERSION"))
    return {"staging": staging, "plugin": plugin, "licenses": licenses, "records": records,
            "entries": entries, "version": version, "version_bytes": version_bytes,
            "source_records": record_names}


def prepare(staging, output, *, combined=False):
    output = plain_path(output)
    if output.exists():
        raise RuntimeError("CUDA overlay output must be new")
    inputs = inspect_staging(staging, combined=combined)
    if inputs["staging"] in output.parents:
        raise RuntimeError("CUDA overlay output must not be inside its input staging tree")
    output.parent.mkdir(parents=True, exist_ok=True)
    target = output / "UmiOCR-data/plugins" / PLUGIN_ID
    target.parent.mkdir(parents=True)
    shutil.copytree(inputs["plugin"], target, ignore=ignore_private)
    notices = output / "LICENSES/plugins" / PLUGIN_ID
    notices.mkdir(parents=True)

    def ignore_notices(directory, names):
        ignored = ignore_private(directory, names)
        if combined and Path(directory) == inputs["licenses"]:
            ignored.add(SOURCE_RECORDS_DIR)
        return ignored

    for source, name in inputs["entries"]:
        destination = notices / name
        if source.is_dir():
            shutil.copytree(source, destination, ignore=ignore_notices)
        elif name == "VERSION" and not source.exists():
            # Local GPU staging may keep VERSION only in its verified snapshot.
            destination.write_bytes(inputs["version_bytes"])
        else:
            shutil.copy2(source, destination)
    print("CUDA install overlay prepared; host root source and licenses are untouched:", output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--combined", action="store_true", help="read only retained CUDA source records from a combined candidate")
    parser.add_argument("--validate-only", action="store_true", help="preflight inputs without creating or changing any output")
    args = parser.parse_args()
    if args.validate_only and args.output_dir or not args.validate_only and args.output_dir is None:
        parser.error("choose --validate-only or --output-dir")
    try:
        if args.validate_only:
            inputs = inspect_staging(args.staging_root, combined=args.combined)
            print(json.dumps({"version": inputs["version"], "source_records": inputs["source_records"],
                              "version_base64": base64.b64encode(inputs["version_bytes"]).decode("ascii")}))
        else:
            prepare(args.staging_root, args.output_dir, combined=args.combined)
        return 0
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile) as exc:
        print(f"CUDA overlay error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
