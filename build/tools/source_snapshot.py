"""Freeze the public corresponding-source inputs for one local candidate.

The default boundary is deliberately limited to this repository.  In
particular, no sibling or paid-plugin checkout is inspected unless the caller
explicitly supplies ``--include-sibling-repo``.  CPU and PaddleOCR-VL plugin
roots are therefore outside the public 3.0.0 snapshot by default.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


EXCLUDED_PARTS = {
    ".git", "__pycache__", "vendor", "models", "temp_doc", "temp",
    "cache", "staging", "artifacts", "audit", "logs", ".settings",
    ".pre_settings", ".pytest_cache", ".build-cache", "node_modules",
    "runtime", "site-packages", "downloads", "wheels", "tmp",
    ".claude", ".codex", ".agents", "claude.md", "codex.md", "agents.md", "gemini.md",
}
SOURCE_ROOTS = {"umiocr-data", "build", "tests", "docs", "licenses", "third_party", ".github", "dev-tools", "pystand_for_umiocr"}
ROOT_FILES = {"copying", "license", "source-code.md", "change_log.md", "pyproject.toml", ".gitignore", ".gitattributes", "version", "source-export.json"}
SOURCE_SUFFIXES = {".py", ".ps1", ".qml", ".js", ".json", ".md", ".c", ".cpp", ".h", ".hpp", ".cmake", ".in", ".lock", ".yaml", ".yml", ".bat", ".cmd", ".sh", ".toml", ".ini", ".ts", ".po", ".png", ".jpg", ".jpeg", ".svg", ".ico", ".qrc", ".ttf", ".otf", ".webp", ".gif", ".qm", ".txt"}
SOURCE_SUFFIXES.update({".rc", ".manifest", ".xml", ".qss", ".hlsl", ".glsl", ".vert", ".frag"})
EXCLUDED_PLUGIN_ROOTS = {
    "win32_paddleocrv6_cpu",
    "win32_paddleocrvl_1_6",
    "win32_paddleocrvl",
}


def git_output(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(f"git {' '.join(arguments)} failed in {repo}: {result.stderr.strip()}")
    return result.stdout


def version_from_about(path: Path) -> str:
    document = json.loads(path.read_text(encoding="utf-8"))
    version = document.get("version")
    if isinstance(version, dict):
        try:
            return ".".join(str(version[name]) for name in ("major", "minor", "patch"))
        except KeyError as exc:
            raise RuntimeError(f"about.json has no version component: {path}") from exc
    if isinstance(version, str) and version.strip():
        return version.strip()
    raise RuntimeError(f"about.json has no usable version: {path}")


def relative_entries(repo: Path) -> list[Path]:
    raw = git_output(repo, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    return [Path(value) for value in raw.split("\0") if value]


def is_excluded(relative: Path, *, public: bool) -> bool:
    parts = {part.casefold() for part in relative.parts}
    lowered = [part.casefold() for part in relative.parts]
    if not lowered or relative.is_absolute() or ".." in relative.parts or any(":" in part for part in relative.parts):
        return True
    if parts.intersection(EXCLUDED_PARTS):
        return True
    # This is an obsolete local-candidate inventory, not a source input or
    # a license text for the current CUDA-only products.
    if relative.as_posix().casefold() == "licenses/archive-manifest.json":
        return True
    if lowered[0] not in SOURCE_ROOTS:
        return len(lowered) != 1 or not (lowered[0] in ROOT_FILES or lowered[0].startswith(("readme", "contributing", "notice")))
    if lowered[0] == "build" and (len(lowered) < 2 or lowered[1] not in {"tools", "windows"}):
        return len(lowered) != 2 or not (lowered[1] == "qt-runtime-whitelist.json" or "lock" in lowered[1] or lowered[1].startswith(("requirements-", "constraints-")))
    if lowered[0] == "umiocr-data":
        if len(lowered) < 2 or lowered[1] not in {"main.py", "about.json", "version.py", "help 帮助.txt", "py_src", "qt_res", "i18n", "plugins"}:
            return True
    if lowered[0] not in {"licenses", "third_party", "tests"} and relative.suffix.casefold() not in SOURCE_SUFFIXES and relative.name != "CMakeLists.txt":
        return True
    if not public:
        return False
    # This is intentionally an exact plugin-root test, not a broad ``cpu`` or
    # ``vl`` substring filter: license and source evidence may legitimately
    # mention those words and must remain in the public snapshot.  Plugin
    # directories live below UmiOCR-data/plugins in the host repository.
    try:
        plugin_index = lowered.index("plugins")
    except ValueError:
        return False
    return any(part in EXCLUDED_PLUGIN_ROOTS for part in lowered[plugin_index + 1:plugin_index + 2])


def files_for_repo(repo: Path, *, public: bool) -> list[Path]:
    selected: list[Path] = []
    for relative in relative_entries(repo):
        if is_excluded(relative, public=public):
            continue
        path = repo / relative
        ensure_under(path, repo)
        if path.is_symlink():
            raise RuntimeError(f"source links are not accepted: {relative}")
        if not path.is_file():
            continue
        # Source mirrors never include arbitrary generated trees.  Keep build
        # scripts, locks, notices and tests; exclude only generated build data.
        if relative.parts and relative.parts[0].casefold() == "build":
            allowed = {"tools", "windows"}
            if len(relative.parts) > 1 and relative.parts[1].casefold() not in allowed:
                # Top-level lock files in build/ are part of corresponding
                # source; generated reports and caches are not.
                if relative.suffix.casefold() not in {".in", ".lock", ".json", ".ps1", ".py"}:
                    continue
        selected.append(relative)
    return sorted(selected, key=lambda item: item.as_posix().casefold())


def mirror_sources(repo: Path, destination: Path, *, data_only: bool = False, plugin_only: bool = False) -> None:
    files = files_for_repo(repo, public=True)
    if destination.is_symlink():
        raise RuntimeError(f"source mirror destination is a link: {destination}")
    destination = destination.expanduser().resolve()
    if not data_only and not plugin_only and destination.exists():
        raise RuntimeError(f"refusing to overwrite source mirror: {destination}")
    for relative in files:
        if plugin_only:
            if not relative.as_posix().startswith("UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/"):
                continue
            relative_target = Path(*relative.parts[3:])
        elif data_only:
            if relative.parts[0] != "UmiOCR-data" or len(relative.parts) < 2 or relative.parts[1] == "plugins":
                continue
            relative_target = Path(*relative.parts[1:])
        else:
            relative_target = relative
        target = ensure_under(destination / relative_target, destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo / relative, target)


def collect_mirror(repo: Path, mirror: Path) -> tuple[dict[str, str], dict[str, str], list[str]]:
    manifest = {}
    if not mirror.is_dir():
        raise RuntimeError(f"source mirror is missing: {mirror}")
    for path in sorted(mirror.rglob("*")):
        ensure_under(path, mirror)
        if path.is_symlink():
            raise RuntimeError(f"source mirror contains a link: {path}")
        if path.is_file():
            relative = path.relative_to(mirror)
            if is_excluded(relative, public=True):
                raise RuntimeError(f"source mirror contains a non-public member: {relative}")
            manifest[f"host/{relative.as_posix()}"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return manifest, {"host": git_output(repo, "rev-parse", "HEAD").strip()}, ["public host/CUDA source mirror and locked third-party source archives"]


def locked_sources(repo: Path, cache: Path) -> list[tuple[Path, Path]]:
    lock = json.loads((repo / "build/sources-windows-cu126.lock.json").read_text(encoding="utf-8"))
    result = []
    for asset in lock.get("thirdPartySources", []):
        name = str(asset["name"])
        if Path(name).name != name or ":" in name or "\\" in name or name in {".", ".."}:
            raise RuntimeError(f"unsafe locked source filename: {name!r}")
        source = cache / name
        if source.is_symlink() or not source.is_file():
            raise RuntimeError(f"offline locked source input is missing: {source}")
        checksum = hashlib.sha256(source.read_bytes()).hexdigest()
        if checksum != asset["sha256"] or source.stat().st_size != asset["size"]:
            raise RuntimeError(f"offline locked source input does not match its lock: {source}")
        result.append((source, Path("third_party") / name))
    return result


def ensure_under(path: Path, root: Path) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeError(f"path is outside repository boundary: {path}") from exc
    return resolved


def collect(
    *,
    repo: Path,
    scope: str,
    sibling_repos: list[Path],
) -> tuple[dict[str, str], dict[str, str], list[str]]:
    public = scope == "public"
    manifest: dict[str, str] = {}
    provenance: dict[str, str] = {}
    boundaries = ["host repository"]
    repositories: list[tuple[str, Path, bool]] = [("host", repo, public)]
    for number, sibling in enumerate(sibling_repos, start=1):
        if not sibling.is_dir():
            raise RuntimeError(f"explicit sibling repository does not exist: {sibling}")
        repositories.append((f"optional-sibling-{number}", sibling, False))
        boundaries.append(f"explicit sibling repository {sibling}")

    for label, repository, public_filter in repositories:
        provenance[label] = git_output(repository, "rev-parse", "HEAD").strip()
        for relative in files_for_repo(repository, public=public_filter):
            source = repository / relative
            archive_name = f"{label}/{relative.as_posix()}"
            if archive_name in manifest:
                raise RuntimeError(f"duplicate source member: {archive_name}")
            manifest[archive_name] = hashlib.sha256(source.read_bytes()).hexdigest()
    return manifest, provenance, boundaries


def write_snapshot(output_dir: Path, manifest: dict[str, str], provenance: dict[str, str], metadata: dict[str, object]) -> None:
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = [output_dir / "source-snapshot.zip", output_dir / "source-snapshot.json", output_dir / "source-provenance.json"]
    existing = [path for path in outputs if path.exists()]
    if existing:
        raise RuntimeError("refusing to overwrite source snapshot: " + ", ".join(map(str, existing)))

    archive_path, manifest_path, provenance_path = outputs
    temporary_archive = archive_path.with_suffix(".zip.tmp")
    if temporary_archive.exists() or temporary_archive.is_symlink():
        raise RuntimeError(f"refusing to overwrite temporary archive: {temporary_archive}")
    try:
        with zipfile.ZipFile(temporary_archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name in sorted(manifest):
                # The archive is written from the source path encoded in the
                # manifest metadata, not from an untrusted archive member name.
                label, relative = name.split("/", 1)
                source = metadata["repositories"][label] / Path(relative)  # type: ignore[index]
                archive.write(source, arcname=name)
        # Reopen for validation: Windows ZipInfo.from_file retains a native orig_filename in write mode.
        with zipfile.ZipFile(temporary_archive, "r") as archive:
            names = set(archive.namelist())
            if names != set(manifest):
                raise RuntimeError("source snapshot member list changed while writing")
            for name, expected in manifest.items():
                with archive.open(name) as stream:
                    actual = hashlib.sha256(stream.read()).hexdigest()
                if actual != expected:
                    raise RuntimeError(f"source snapshot hash mismatch: {name}")
        archive_sha256 = hashlib.sha256(temporary_archive.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        provenance_document = {
            "version": metadata["version"],
            "scope": metadata["scope"],
            "parent_revisions": provenance,
            "included_boundaries": metadata["boundaries"],
            "excluded_boundaries": [
                "CPU plugin and PaddleOCR-VL plugin roots (public scope)",
                "generated release/staging/cache/vendor/model trees",
            ] if metadata["scope"] == "public" else [],
            "local_changes_included": True,
            "files": len(manifest),
            "archive_sha256": archive_sha256,
        }
        provenance_path.write_text(json.dumps(provenance_document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary_archive, archive_path)
    except Exception:
        if temporary_archive.exists():
            temporary_archive.unlink()
        for path in (manifest_path, provenance_path):
            if path.exists():
                path.unlink()
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--about", type=Path, default=None, help="about.json; defaults to UmiOCR-data/about.json")
    parser.add_argument("--output-dir", type=Path, default=None, help="versioned output directory under build/audit")
    parser.add_argument("--scope", choices=("public", "legacy"), default="public")
    parser.add_argument("--mirror-dir", type=Path, help="copy public sources into a new directory")
    parser.add_argument("--data-dir", type=Path, help="copy current host data, excluding all plugins")
    parser.add_argument("--plugin-dir", type=Path, help="copy current public CUDA adapter sources only")
    parser.add_argument("--source-cache", type=Path, help="existing locked corresponding-source cache; never downloaded")
    parser.add_argument("--mirror-source", type=Path, help="freeze a fresh source mirror with locked third_party archives")
    parser.add_argument(
        "--include-sibling-repo", action="append", type=Path, default=[],
        help="explicit development-only source boundary; never used by public default",
    )
    args = parser.parse_args(argv)
    try:
        repo = args.repo_root.expanduser().resolve()
        about = (args.about or repo / "UmiOCR-data" / "about.json").expanduser().resolve()
        version = version_from_about(about)
        if args.mirror_dir or args.data_dir or args.plugin_dir:
            if args.scope != "public" or args.include_sibling_repo:
                raise RuntimeError("source mirrors only support the public repository boundary")
            mirror_sources(repo, args.mirror_dir or args.data_dir or args.plugin_dir, data_only=bool(args.data_dir), plugin_only=bool(args.plugin_dir))
            return 0
        if args.include_sibling_repo and args.scope != "legacy":
            raise RuntimeError("--include-sibling-repo requires explicit --scope legacy")
        siblings = [path.expanduser().resolve() for path in args.include_sibling_repo]
        output_dir = (args.output_dir or repo / "build" / "audit" / version).expanduser().resolve()
        if args.mirror_source:
            if siblings or args.scope != "public":
                raise RuntimeError("--mirror-source only supports public scope")
            manifest, provenance, boundaries = collect_mirror(repo, args.mirror_source.resolve())
        else:
            manifest, provenance, boundaries = collect(repo=repo, scope=args.scope, sibling_repos=siblings)
        repositories = {"host": args.mirror_source.resolve() if args.mirror_source else repo}
        if not args.mirror_source:
            cache = (args.source_cache or repo / "build/cache/sources").resolve()
            for source, relative in locked_sources(repo, cache):
                name = relative.as_posix()
                manifest[name] = hashlib.sha256(source.read_bytes()).hexdigest()
            repositories["third_party"] = cache
            boundaries.append("hash-locked GPL/AGPL/MPL corresponding-source archives from the existing local cache")
        repositories.update({f"optional-sibling-{i}": path for i, path in enumerate(siblings, start=1)})
        write_snapshot(output_dir, manifest, provenance, {
            "version": version,
            "scope": args.scope,
            "boundaries": boundaries,
            "repositories": repositories,
        })
        print(f"Source snapshot verified: {len(manifest)} files; version={version}; scope={args.scope}; output={output_dir}")
        return 0
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"source snapshot error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
