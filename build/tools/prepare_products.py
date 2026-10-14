"""Prepare independently selected 3.0.0 local products without rebuilding.

The public default creates only the base application and the CUDA plugin. CPU
and PaddleOCR-VL are not read from a sibling checkout and are never selected
implicitly.  Historical/development products remain available through an
explicit ``--optional-plugin ID=PATH`` argument.

Every output directory must be new.  This helper never deletes or overwrites a
candidate, a release archive, or a source staging tree.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import re
import zipfile
from typing import Iterable


class PreparationError(RuntimeError):
    """Raised for an invalid product selection or source tree."""


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def payload(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): digest(path)
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold())
        if path.is_file()
    }


def version_from_about(path: Path) -> str:
    document = json.loads(path.read_text(encoding="utf-8"))
    value = document.get("version")
    if isinstance(value, dict):
        try:
            return ".".join(str(value[key]) for key in ("major", "minor", "patch"))
        except KeyError as exc:
            raise PreparationError(f"about.json lacks a version component: {path}") from exc
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise PreparationError(f"about.json lacks a usable version: {path}")


def version_label(about: Path) -> str:
    document = json.loads(about.read_text(encoding="utf-8"))
    value = document.get("version")
    if isinstance(value, dict):
        base = version_from_about(about)
        prerelease = str(value.get("prerelease") or "").strip()
        number = value.get("prereleaseNumber", 0)
        return f"{base}-{prerelease}.{number}" if prerelease else base
    return version_from_about(about)


def ensure_new(path: Path, *, description: str) -> Path:
    path = path.expanduser()
    if path.is_symlink():
        raise PreparationError(f"refusing to write through a link: {path}")
    path = path.resolve()
    if path.exists():
        raise PreparationError(f"refusing to overwrite existing {description}: {path}")
    return path


def ensure_under_build(path: Path, build_root: Path, *, description: str) -> Path:
    path = path.expanduser().resolve()
    try:
        path.relative_to(build_root.resolve())
    except ValueError as exc:
        raise PreparationError(f"{description} must remain under build/: {path}") from exc
    return path


def copy_tree(source: Path, target: Path) -> None:
    if source.is_symlink():
        raise PreparationError(f"source links are not accepted: {source}")
    for path in source.rglob("*"):
        if path.is_symlink():
            raise PreparationError(f"source tree contains a link: {path}")
    source = source.expanduser().resolve()
    if not source.is_dir():
        raise PreparationError(f"source directory does not exist: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, symlinks=True, copy_function=shutil.copy2)


def copy_file(source: Path, target: Path) -> None:
    source = source.expanduser().resolve()
    if not source.is_file():
        raise PreparationError(f"source file does not exist: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def copy_common_files(complete: Path, target: Path, names: Iterable[str]) -> None:
    for name in names:
        source = complete / name
        if source.is_file():
            copy_file(source, target / name)


def safe_component(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value) or value.endswith((".", " ")):
        raise PreparationError(f"unsafe output path component: {value!r}")
    return value


def parse_optional_plugin(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise PreparationError(f"--optional-plugin must be ID=PATH: {value}")
    plugin_id, raw_path = value.split("=", 1)
    plugin_id = plugin_id.strip()
    if not plugin_id or not raw_path.strip():
        raise PreparationError(f"--optional-plugin must be ID=PATH: {value}")
    return safe_component(plugin_id), Path(raw_path).expanduser().resolve()


def check_snapshot_version(complete: Path, version: str) -> None:
    provenance = complete / "source-provenance.json"
    if not provenance.is_file():
        raise PreparationError(f"complete candidate lacks source provenance: {provenance}")
    document = json.loads(provenance.read_text(encoding="utf-8"))
    if document.get("scope") != "public":
        raise PreparationError("public products require a public source snapshot, not a legacy/sibling snapshot")
    recorded = str(document.get("version", ""))
    if recorded != version:
        raise PreparationError(f"source provenance version {recorded!r} != about.json version {version!r}")
    for name in ("source-snapshot.zip", "source-snapshot.json", "source-provenance.json"):
        if not (complete / name).is_file():
            raise PreparationError(f"complete candidate lacks {name}")

    manifest = json.loads((complete / "source-snapshot.json").read_text(encoding="utf-8"))
    archive = complete / "source-snapshot.zip"
    if digest(archive) != document.get("archive_sha256"):
        raise PreparationError("source snapshot archive SHA256 does not match provenance")
    with zipfile.ZipFile(archive) as snapshot:
        if len(snapshot.namelist()) != len(manifest) or set(snapshot.namelist()) != set(manifest):
            raise PreparationError("source snapshot member list does not match manifest")
        for name, expected in manifest.items():
            parts = name.replace("\\", "/").split("/")
            if name.startswith(("/", "\\")) or ".." in parts or any(":" in part for part in parts):
                raise PreparationError(f"unsafe source snapshot member: {name}")
            if hashlib.sha256(snapshot.read(name)).hexdigest() != expected:
                raise PreparationError(f"source snapshot member hash mismatch: {name}")


def prepare_base(complete: Path, target: Path) -> None:
    # Build-Release's complete staging root already contains no inference
    # backend in its base product. An assembly can include selected plugins.
    def ignore(directory: str, names: list[str]) -> set[str]:
        relative = Path(directory).relative_to(complete)
        omitted = {name for name in names if name.casefold() in {
            "__pycache__", ".settings", ".pre_settings", ".plugins_state",
            "temp", "temp_doc", "logs", "startup_error.log", ".build",
        }}
        if relative.as_posix() == "UmiOCR-data/plugins":
            return set(names)
        if relative.as_posix() == "LICENSES":
            omitted.update({"plugins"}.intersection(names))
        if not relative.parts:
            omitted.update({"assembly.json", "prepared-products.json"}.intersection(names))
        return omitted
    for path in complete.rglob("*"):
        if path.is_symlink():
            raise PreparationError(f"candidate contains a link: {path}")
    shutil.copytree(complete, target, ignore=ignore)


def prepare_plugin(
    complete: Path,
    target: Path,
    plugin_id: str,
    plugin_source: Path,
    version: str,
) -> None:
    if not plugin_source.is_dir():
        raise PreparationError(f"selected plugin source does not exist: {plugin_source}")
    plugin_target = target / "UmiOCR-data" / "plugins" / plugin_id
    copy_tree(plugin_source, plugin_target)
    license_source = complete / "LICENSES" / "plugins" / plugin_id
    if license_source.is_dir():
        copy_tree(license_source, target / "LICENSES")
    else:
        # A separately built plugin can carry its own licenses.  This is the
        # only fallback and is still explicit; no sibling checkout is guessed.
        local_licenses = plugin_source.parent.parent.parent / "LICENSES"
        if local_licenses.is_dir():
            copy_tree(local_licenses, target / "LICENSES")
        else:
            raise PreparationError(f"selected plugin has no license tree: {plugin_id}")
    copy_common_files(
        complete,
        target,
        (
            "COPYING", "LICENSE", "VERSION", "SOURCE-CODE.md",
            "source-snapshot.zip", "source-snapshot.json", "source-provenance.json",
        ),
    )
    manifest = plugin_target / "umi-plugin.json"
    if manifest.is_file():
        document = json.loads(manifest.read_text(encoding="utf-8"))
        plugin_version = str(document.get("version", ""))
        if plugin_version and plugin_version != version:
            raise PreparationError(f"plugin {plugin_id} version {plugin_version!r} != {version!r}")


def product_name(version: str, label: str, product: str, plugin_id: str | None = None) -> str:
    suffix = f"-{label}" if label else ""
    if product == "base":
        return f"Umi-OCR_v{version}{suffix}_Windows_x64"
    if product == "cuda":
        return f"Umi-OCR-Plugin_GPU-OCR_v{version}{suffix}_Windows_x64_CUDA12.6"
    safe_id = plugin_id or product
    return f"Umi-OCR-Plugin_{safe_id}_v{version}{suffix}_Windows_x64"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--about", type=Path, default=None)
    parser.add_argument("--complete-root", type=Path, default=None)
    parser.add_argument("--products-root", type=Path, default=None)
    parser.add_argument("--label", default="local-candidate")
    parser.add_argument(
        "--product", action="append", choices=("base", "cuda"),
        help="public products to create; repeat --product (default: base and cuda)",
    )
    parser.add_argument(
        "--optional-plugin", action="append", default=[], metavar="ID=PATH",
        help="explicit development-only plugin product source; never inferred from a sibling repo",
    )
    args = parser.parse_args(argv)
    try:
        repo = args.repo_root.expanduser().resolve()
        build_root = (repo / "build").resolve()
        about = (args.about or repo / "UmiOCR-data" / "about.json").expanduser().resolve()
        version = safe_component(version_from_about(about))
        label = str(args.label).strip()
        if label:
            safe_component(label)
        complete = (args.complete_root or build_root / "artifacts" / f"{version}-final" / "complete").expanduser().resolve()
        products_root = (args.products_root or build_root / "artifacts" / f"{version}-products" / "validated").expanduser().resolve()
        ensure_under_build(products_root, build_root, description="products root")
        if not complete.is_dir():
            raise PreparationError(f"complete candidate does not exist: {complete}")
        check_snapshot_version(complete, version)

        selected: list[str] = []
        for item in (args.product or ["base,cuda"]):
            selected.extend(part.strip().lower() for part in item.split(",") if part.strip())
        selected = list(dict.fromkeys(selected))
        optional = [parse_optional_plugin(value) for value in args.optional_plugin]
        if not selected and not optional:
            raise PreparationError("no product selected")
        report = products_root / "prepared-products.json"
        ensure_new(report, description="prepared-products report")
        for product in selected:
            ensure_new(products_root / product_name(version, label, product), description=f"{product} product")
        for plugin_id, _ in optional:
            ensure_new(products_root / product_name(version, label, "optional", plugin_id), description="optional product")
        products_root.mkdir(parents=True, exist_ok=True)
        result: dict[str, object] = {
            "version": version,
            "scope": "public" if not optional else "public-plus-explicit-development",
            "complete": str(complete),
            "products": {},
            "verification": "copy integrity only; current-source E2E has not been run by this helper",
            "public_release_allowed": False,
        }

        for product in selected:
            target = ensure_new(products_root / product_name(version, label, product), description=f"{product} product")
            if product == "base":
                prepare_base(complete, target)
                expected_source = complete
            else:
                plugin_id = "win32_PaddleOCRv6_CUDA"
                source = complete / "UmiOCR-data" / "plugins" / plugin_id
                prepare_plugin(complete, target, plugin_id, source, version)
                expected_source = source
            expected = payload(expected_source)
            if product == "base":
                expected = {name: value for name, value in expected.items()
                            if not name.startswith(("UmiOCR-data/plugins/", "LICENSES/plugins/"))}
            actual_root = target if product == "base" else target / "UmiOCR-data" / "plugins" / "win32_PaddleOCRv6_CUDA"
            if product == "base":
                actual = payload(actual_root)
            else:
                actual = payload(actual_root)
            if expected != actual:
                raise PreparationError(f"payload integrity mismatch for {product}")
            result["products"][product] = {
                "name": target.name,
                "path": str(target),
                "plugin_id": None if product == "base" else "win32_PaddleOCRv6_CUDA",
                "files": len(actual),
                "sha256": hashlib.sha256(json.dumps(actual, sort_keys=True).encode("utf-8")).hexdigest(),
            }
            print(f"Independent product verified: {target.name}", flush=True)

        for plugin_id, source in optional:
            target = ensure_new(products_root / product_name(version, label, "optional", plugin_id), description=f"optional plugin {plugin_id} product")
            prepare_plugin(complete, target, plugin_id, source, version)
            actual = payload(target / "UmiOCR-data" / "plugins" / plugin_id)
            result["products"][plugin_id] = {
                "name": target.name,
                "path": str(target),
                "plugin_id": plugin_id,
                "development_only": True,
                "files": len(actual),
                "sha256": hashlib.sha256(json.dumps(actual, sort_keys=True).encode("utf-8")).hexdigest(),
            }
            print(f"Explicit development product verified: {target.name}", flush=True)

        report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 0
    except (OSError, PreparationError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(f"product preparation error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
