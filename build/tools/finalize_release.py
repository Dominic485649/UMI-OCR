"""Freeze a review product, then archive that same product behind existing gates.

The external freeze manifest is an integrity record, NOT approval or release
acceptance. Only Audit-Package and verify_release_evidence can authorize an
archive. No source/runtime refresh, candidate promotion, build, or publication
operation is provided here.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile


def adjacent(name):
    # -I must not import modules from the product, an archive, or the cwd.
    spec = importlib.util.spec_from_file_location("umi_finalize_" + name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gates = adjacent("release_gate_inputs")
overlay = adjacent("prepare_cuda_overlay")
packaging = adjacent("package_tar_xz")
privacy = adjacent("verify_public_payload")

# Only outputs actually derived by the base/GPU verifier may change. In
# particular source/LICENSES, notices, source ZIP/JSON/provenance and licenses
# themselves are NOT exempt. CPU-specific reports are deliberately absent.
DERIVED_REPORTS = frozenset({
    "runtime-vendor-lock.json", "model-rights.json", "cuda-redistributable.json",
    "cudnn-redistributable.json", "opencv-artifact.json", "ffmpeg-build.json",
    "mpl-components.json", "agpl-integration.json", "cpu-document-gates.json",
    "gpu-e2e-evidence.json", "source-delivery.json", "current-source-e2e.json",
    "RELEASE_EVIDENCE.json", "RELEASE_EVIDENCE.md",
})
SOURCE_RECORDS = ("source-snapshot.zip", "source-snapshot.json", "source-provenance.json")


class FinalizationError(RuntimeError):
    pass


def plain(path):
    path = Path(path)
    if str(path).startswith(("\\\\", "//")) or path.drive and not path.is_absolute():
        raise FinalizationError("Network/device/drive-relative release paths are not supported")
    for part in path.parts[1 if path.anchor else 0:]:
        if part not in {".", ".."}:
            overlay.snapshot_relative("host/" + part)
    # The overlay helper checks lexical prefixes BEFORE resolve hides '..'.
    return overlay.plain_path(path)


def below(path, parent, description):
    path, parent = plain(path), plain(parent)
    if parent not in path.parents:
        raise FinalizationError(f"{description} must stay under {parent}")
    return path


def repository(path):
    repo = plain(path)
    if not repo.is_dir() or not (repo / "build").is_dir():
        raise FinalizationError("An existing product repository with build/ is required")
    return repo


def audit_input(repo, path, description, *, new=False):
    path = below(path, repo / "build/audit", description)
    if path.suffix != ".json":
        raise FinalizationError(f"{description} must be a JSON file")
    if new:
        if path.exists():
            raise FinalizationError(f"Refusing to overwrite {description}: {path}")
    elif not path.is_file():
        raise FinalizationError(f"Missing {description}: {path}")
    return path


def identity_version(document):
    value = document.get("version")
    if isinstance(value, dict):
        if any(type(value.get(key)) is not int or value[key] < 0 for key in ("major", "minor", "patch")):
            raise FinalizationError("Version components must be non-negative integers")
        value = ".".join(str(value[key]) for key in ("major", "minor", "patch"))
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value):
        raise FinalizationError("Invalid product version")
    return value


def version_label(document, version):
    value = document.get("version")
    prerelease = value.get("prerelease", "") if isinstance(value, dict) else ""
    if not prerelease:
        return version
    number = value.get("prereleaseNumber")
    if not isinstance(prerelease, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", prerelease) or type(number) is not int or number < 0:
        raise FinalizationError("Invalid prerelease label")
    return f"{version}-{prerelease}.{number}"


def tree_records(root):
    """Reject links/private paths before opening files; never follow junctions."""
    pending = [root]
    files, directories, folded = {}, set(), set()
    while pending:
        current = pending.pop()
        overlay.reject_link(current)
        if current != root:
            relative = current.relative_to(root)
            name = relative.as_posix()
            overlay.snapshot_relative("host/" + name)
            if name.casefold() in folded:
                raise FinalizationError("Case-colliding product paths")
            folded.add(name.casefold())
            if overlay.private_path(relative) or privacy.forbidden(name):
                raise FinalizationError(f"Private/generated state must not be shipped: {name}")
            if any(part.casefold() in privacy.FORBIDDEN_PLUGINS for part in relative.parts):
                raise FinalizationError("Non-public plugin paths are not permitted")
        if current.is_dir():
            if current != root:
                directories.add(name)
            pending.extend(current.iterdir())
        elif current.is_file():
            # Reparse-point checks do not detect NTFS hard links. In particular,
            # a derived report must not make Audit overwrite an outside file.
            if current.stat().st_nlink > 1:
                raise FinalizationError(f"Hard-linked product files are not permitted: {name}")
            files[name] = gates.digest(current)
        else:
            raise FinalizationError("Product contains a non-regular file/directory")
    return files, directories


def inspect_product(repo, root, kind, *, validate_source=False):
    if kind not in {"base", "gpu"}:
        raise FinalizationError("Only the independent base and CUDA overlay can be finalized")
    root = below(root, repo / "build", "Product")
    if not root.is_dir():
        raise FinalizationError("An existing, already prepared product tree is required")
    files, directories = tree_records(root)
    metadata = gates.checked_metadata_root(root, kind)
    if kind == "gpu":
        expected = root / "LICENSES/plugins" / gates.PLUGIN_ID
        if metadata != expected:
            raise FinalizationError("GPU finalization requires the actual prepared install overlay, not standalone staging")
        plugin = root / "UmiOCR-data/plugins" / gates.PLUGIN_ID
        document = gates.read_json(plugin / "umi-plugin.json")
        if document.get("id") != gates.PLUGIN_ID:
            raise FinalizationError("Wrong CUDA plugin identity")
    else:
        if metadata != root or not (root / "Umi-OCR.exe").is_file():
            raise FinalizationError("An independent base application is required")
        plugins = root / "UmiOCR-data/plugins"
        if plugins.exists() and (not plugins.is_dir() or any(plugins.iterdir())):
            raise FinalizationError("The base product must not contain an inference plugin or plugin state")
        if (root / "LICENSES/plugins").exists():
            raise FinalizationError("The base product must not contain plugin metadata")
        document = gates.read_json(root / "UmiOCR-data/about.json")
    version = identity_version(document)
    if version != identity_version(gates.read_json(repo / "UmiOCR-data/about.json")):
        raise FinalizationError("Product version does not match the current repository")
    required = {"COPYING", "LICENSE", "SOURCE-CODE.md", "VERSION", "source", "LICENSES", *SOURCE_RECORDS}
    allowed = required | {"NOTICE.md", "source-export.json"}
    if kind == "base":
        allowed |= {"UmiOCR-data", "Umi-OCR.exe"}
    names = {child.name for child in metadata.iterdir()}
    if not required <= names or names - allowed:
        raise FinalizationError("Missing or unexpected product/source records; local candidates cannot be promoted")
    if not (metadata / "source").is_dir() or not (metadata / "LICENSES").is_dir():
        raise FinalizationError("Canonical source and licenses must already be present")
    for name in required - {"source", "LICENSES"}:
        if not (metadata / name).is_file():
            raise FinalizationError(f"Required product record is not a file: {name}")
    if (metadata / "VERSION").read_text("utf-8-sig").strip() != version:
        raise FinalizationError("VERSION differs from the actual product")
    if not (metadata / "LICENSES/Apache-2.0.txt").is_file():
        raise FinalizationError("Prepare the license before freezing; finalization cannot create license texts")
    actual_version, binding, source = gates.artifact_inputs(root, kind)
    if actual_version != version:
        raise FinalizationError("Inconsistent product identity")
    if validate_source:
        validate_snapshot(metadata, root, kind, version, source)
        result = privacy.verify(root)
        if result["status"] != "PASS":
            raise FinalizationError("The existing public-payload privacy/archive check failed")
    prefix = metadata.relative_to(root).as_posix()
    prefix = "" if prefix == "." else prefix + "/"
    mutable = {prefix + "LICENSES/" + name for name in DERIVED_REPORTS}
    immutable = {name: value for name, value in files.items() if name not in mutable}
    summary = {
        "schema_version": 1, "purpose": "immutable-review-product-not-approval",
        "artifact_kind": kind, "release_version": version,
        "version_label": version_label(document, version), "package_root": str(root),
        "metadata_relative": metadata.relative_to(root).as_posix(), "binding": binding,
        "immutable_files": gates.tree_binding(immutable),
        "directories": gates.tree_binding({name: "directory" for name in directories}),
        "source_records": {name: files[prefix + name] for name in SOURCE_RECORDS},
    }
    return root, metadata, summary, files, directories


def execution_sources(directory, excluded):
    """Hash original application code only, not third-party/vendor closures."""
    records = {}
    pending = [directory]
    while pending:
        for path in pending.pop().iterdir():
            relative = path.relative_to(directory)
            if relative.parts[0] in excluded:
                continue
            overlay.reject_link(path)
            if path.is_dir():
                pending.append(path)
            elif path.suffix in {".py", ".qml", ".js"}:
                records[relative.as_posix()] = gates.digest(path)
    return records


def app_archive_sources(metadata, archive_path, expected):
    """Inspect ZIP data; never import/unmarshal/execute artifact code.

    merge_runtime.py retains original .py bytes plus checked-hash .pyc, with
    co_filename relative to py_src before adding that namespace to ZIP names.
    Recompile canonical text (without executing it) using the existing normal
    optimization level and tool interpreter; do not trust the .pyc header alone.
    """
    import marshal

    sources = {}
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        names, folded = set(), set()
        for member in members:
            name = member.filename.rstrip("/") if member.is_dir() else member.filename
            overlay.snapshot_relative("host/" + name)
            if name in names or name.casefold() in folded or stat.S_ISLNK(member.external_attr >> 16):
                raise FinalizationError("app.zip contains duplicate/colliding/link members")
            names.add(name)
            folded.add(name.casefold())
            if name != "py_src" and not name.startswith("py_src/"):
                raise FinalizationError("app.zip members must stay in the canonical py_src namespace")
            if not member.is_dir() and not name.endswith((".py", ".pyc")):
                raise FinalizationError("Unsupported executable/resource member in app.zip")
        files = {member.filename: member for member in members if not member.is_dir()}
        for name, member in files.items():
            if name.endswith(".py"):
                with archive.open(member) as stream:
                    checksum = overlay.digest(stream)
                if expected.get(name) != checksum:
                    raise FinalizationError("app.zip source member differs from canonical source")
                sources[name] = checksum
            else:
                original = name[:-1]
                if original not in files or original not in expected:
                    raise FinalizationError("app.zip bytecode lacks its canonical original .py member")
                canonical = metadata / "source/UmiOCR-data" / original
                data = canonical.read_bytes()
                filename = original.removeprefix("py_src/")
                try:
                    code = compile(data, filename, "exec", dont_inherit=True, optimize=0)
                except (SyntaxError, ValueError) as exc:
                    raise FinalizationError("Canonical app.zip source cannot be compiled for comparison") from exc
                expected_pyc = (importlib.util.MAGIC_NUMBER + b"\x03\x00\x00\x00" +
                                importlib.util.source_hash(data) + marshal.dumps(code))
                if archive.read(member) != expected_pyc:
                    raise FinalizationError("app.zip bytecode differs from its canonical source/toolchain")
    return sources


def validate_execution_source(metadata, root, kind, source):
    # Independent source/payload digests do not themselves prove that the
    # execution code is the source that was published. Bridge only original
    # materialized code and the known app.zip representation; this is NOT a
    # reproducible-build claim about native binaries, RCC/QM or dependencies.
    prefix = "UmiOCR-data/" if kind == "base" else f"UmiOCR-data/plugins/{gates.PLUGIN_ID}/"
    excluded = {"runtime", "site-packages", "plugins"} if kind == "base" else {"vendor", "models"}
    expected = {}
    for name, checksum in source.items():
        if not name.startswith(prefix):
            continue
        relative = Path(name.removeprefix(prefix))
        if relative.parts[0] not in excluded and relative.suffix in {".py", ".qml", ".js"}:
            expected[relative.as_posix()] = checksum
    actual = execution_sources(root / prefix, excluded)
    if kind == "base":
        if "main.py" not in expected:
            raise FinalizationError("Canonical host main.py is missing")
        archive = root / "UmiOCR-data/app.zip"
        if archive.exists():
            packed = app_archive_sources(metadata, archive, expected)
            for name, checksum in packed.items():
                if name in actual and actual[name] != checksum:
                    raise FinalizationError("Loose and archived execution source disagree")
                actual[name] = checksum
    if not expected or any(expected.get(name) != checksum for name, checksum in actual.items()):
        raise FinalizationError("Execution source differs from canonical source")
    if {name for name in expected if name.endswith(".py")} != {name for name in actual if name.endswith(".py")}:
        raise FinalizationError("Execution Python source member set differs from canonical source")


def validate_snapshot(metadata, root, kind, version, source):
    validate_execution_source(metadata, root, kind, source)
    if kind == "gpu":
        overlay.validate_records(metadata, root / "UmiOCR-data/plugins" / gates.PLUGIN_ID, require_version=True)
        return
    manifest = gates.read_json(metadata / "source-snapshot.json")
    provenance = gates.read_json(metadata / "source-provenance.json")
    expected = {"host/" + name: value for name, value in source.items()}
    if not gates._same_binding(manifest, expected):
        raise FinalizationError("Canonical source differs from the frozen source manifest")
    if (not isinstance(provenance, dict) or provenance.get("scope") != "public" or
            provenance.get("version") != version or type(provenance.get("files")) is not int or
            provenance["files"] != len(manifest) or
            provenance.get("archive_sha256") != gates.digest(metadata / "source-snapshot.zip")):
        raise FinalizationError("Source provenance scope/version/count/archive hash is invalid")
    with zipfile.ZipFile(metadata / "source-snapshot.zip") as archive:
        members = archive.infolist()
        names = [member.filename for member in members]
        if len(names) != len(manifest) or set(names) != set(manifest) or len({name.casefold() for name in names}) != len(names):
            raise FinalizationError("Source ZIP member set is not the canonical source tree")
        for member in members:
            overlay.snapshot_relative(member.filename)
            if member.is_dir() or stat.S_ISLNK(member.external_attr >> 16):
                raise FinalizationError("Source ZIP contains a directory/link")
            with archive.open(member) as stream:
                if overlay.digest(stream) != manifest[member.filename]:
                    raise FinalizationError("Source ZIP member bytes differ from its manifest")
    identity = "UmiOCR-data/about.json"
    if source.get(identity) != gates.digest(root / identity):
        raise FinalizationError("Base source identity differs from the execution payload")


def freeze(repo, root, kind, manifest):
    repo = repository(repo)
    manifest = audit_input(repo, manifest, "freeze manifest", new=True)
    root, _, summary, _, _ = inspect_product(repo, root, kind, validate_source=True)
    if root == manifest or root in manifest.parents:
        raise FinalizationError("Freeze manifest must stay outside the product")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return summary


def checked_command(command, repo, environment):
    result = subprocess.run(command, cwd=repo, env=environment, check=False)
    if result.returncode:
        raise FinalizationError("Required release audit/verifier failed; no formal archive was created")


def check_report(metadata, kind, binding, release_gates, receipt_hash):
    report = gates.read_json(metadata / "LICENSES/RELEASE_EVIDENCE.json")
    if (not isinstance(report, dict) or report.get("artifact_kind") != kind or
            report.get("public_prerelease_allowed") is not True or report.get("local_candidate") is not False or
            report.get("validation_errors") != [] or
            report.get("release_gate_input") != {"name": release_gates.name, "sha256": receipt_hash}):
        raise FinalizationError("The fresh verifier report does not authorize this public artifact")
    source, current = report.get("source_delivery", {}), report.get("current_source_e2e", {})
    if (not isinstance(source, dict) or source.get("status") != "PASS" or source.get("verified") is not True or
            not isinstance(current, dict) or current.get("verified") is not True or
            current.get("publication_authorized") is not True or
            current.get("status") not in {"PASS", "ACCEPTED_WITH_LIMITATIONS"} or
            not gates._same_binding(current.get("binding"), binding)):
        raise FinalizationError("Fresh source/current-product gate results are missing or unbound")
    statuses = report.get("gates")
    required = {"runtime_vendor", "paddle_models", "cuda", "cudnn", "opencv", "ffmpeg", "mpl",
                "agpl_nvidia", "cpu_ocr", "document_models", *gates.RELEASE_GATES}
    if kind == "gpu":
        required.add("gpu_ocr_e2e")
    if (not isinstance(statuses, dict) or set(statuses) != required or
            statuses.get("source_delivery") != source["status"] or
            statuses.get("current_source_e2e") != current["status"] or
            any(status not in {"PASS", "NOT_INCLUDED"} for name, status in statuses.items() if name not in gates.RELEASE_GATES)):
        raise FinalizationError("A recorded component/publication gate is blocked")


def archive_matches(path, files, directories):
    """Prove the bytes actually archived, not only a pre/post tree checksum."""
    seen_files, seen_directories, seen = {}, set(), set()
    with tarfile.open(path, "r:xz") as archive:
        for member in archive:
            name = packaging._safe_relative(member.name)
            if name in seen:
                raise FinalizationError("Duplicate finalized archive member")
            seen.add(name)
            if member.isdir():
                seen_directories.add(name)
            elif member.isfile():
                stream = archive.extractfile(member)
                if stream is None:
                    raise FinalizationError("Unreadable finalized archive member")
                with stream:
                    seen_files[name] = overlay.digest(stream)
            else:
                raise FinalizationError("Links/special files cannot enter a formal archive")
    if seen_files != files or seen_directories != directories:
        raise FinalizationError("Archive bytes/member set differ from the audited immutable product")


def finalize(repo, root, kind, manifest, release_gates, output):
    repo = repository(repo)
    manifest = audit_input(repo, manifest, "freeze manifest")
    release_gates = audit_input(repo, release_gates, "release-gates input")
    if manifest == release_gates:
        raise FinalizationError("The freeze manifest is not a publication receipt")
    root, metadata, summary, _, _ = inspect_product(repo, root, kind, validate_source=True)
    expected = gates.read_json(manifest)
    if not gates._same_binding(expected, summary):
        raise FinalizationError("Product root/source/payload differs from the reviewed freeze manifest")
    for path in (manifest, release_gates):
        if root in path.parents:
            raise FinalizationError("Audit inputs must stay outside the product")
    receipt = gates.read_json(release_gates)
    if (not isinstance(receipt, dict) or type(receipt.get("schema_version")) is not int or receipt["schema_version"] != 1 or
            receipt.get("artifact_kind") != kind or receipt.get("release_version") != summary["release_version"] or
            receipt.get("publication_authorized") is not True or
            not isinstance(receipt.get("current_source_e2e"), dict) or
            not gates._same_binding(receipt["current_source_e2e"].get("binding"), summary["binding"])):
        raise FinalizationError("Release-gates identity/authorization/product binding is invalid")
    output = plain(output)
    allowed = (repo / "release", repo / "build/artifacts")
    if not any(output == directory or directory in output.parents for directory in allowed):
        raise FinalizationError("Formal archives must stay in this repository's release/ or build/artifacts/")
    if output == root or root in output.parents or output in root.parents:
        raise FinalizationError("Archive output and product must be disjoint")
    if output.exists() and not output.is_dir():
        raise FinalizationError("Archive output root is not a directory")
    name = (f"Umi-OCR_v{summary['version_label']}_Windows_x64.tar.xz" if kind == "base" else
            f"Umi-OCR-Plugin_GPU-OCR_v{summary['release_version']}_Windows_x64_CUDA12.6.tar.xz")
    archive = plain(output / name)
    integrity = plain(output / (name + ".integrity.json"))
    if archive.exists() or integrity.exists():
        raise FinalizationError("Refusing to overwrite an archive or its integrity report")
    frozen_hash, receipt_hash = gates.digest(manifest), gates.digest(release_gates)

    def unchanged():
        for path, expected_hash in ((manifest, frozen_hash), (release_gates, receipt_hash)):
            plain(path)
            if not path.is_file() or gates.digest(path) != expected_hash:
                raise FinalizationError("Freeze/release-gates inputs changed during finalization")
        current = inspect_product(repo, root, kind)
        if not gates._same_binding(current[2], summary):
            raise FinalizationError("Source/source records/provenance/payload/static notices changed during finalization")
        return current

    audit = plain(repo / "build/windows/Audit-Package.ps1")
    verifier = plain(repo / "build/tools/verify_release_evidence.py")
    powershell = shutil.which("pwsh") or shutil.which("pwsh.exe")
    if not powershell or not audit.is_file() or not verifier.is_file():
        raise FinalizationError("Existing PowerShell audit and artifact verifier are required")
    environment = os.environ.copy()
    environment["PATH"] = str(Path(sys.executable).parent) + os.pathsep + environment.get("PATH", "")
    checked_command([
        powershell, "-NoProfile", "-NonInteractive", "-File", str(audit),
        "-PackageRoot", str(root), "-Kind", "base" if kind == "base" else "plugin",
        "-ReleaseGates", str(release_gates), "-RequirePublicRelease",
    ], repo, environment)
    unchanged()
    checked_command([
        sys.executable, "-I", "-B", "-S", "-X", "utf8", str(verifier),
        "--repo-root", str(repo), "--staging-root", str(root), "--kind", kind,
        "--cache-root", str(repo / "build/cache"), "--release-gates", str(release_gates),
        "--require-public-release",
    ], repo, environment)
    _, _, _, files, directories = unchanged()
    check_report(metadata, kind, summary["binding"], release_gates, receipt_hash)

    # Write only to a new private workspace until audit, verifier, immutable
    # checks, and actual archive-byte comparison ALL succeed. Publication uses
    # no-clobber hard links on the same volume; no rename-overwrite fallback.
    work_parent = plain(repo / "build/artifacts")
    work_parent.mkdir(parents=True, exist_ok=True)
    # Own this new workspace explicitly: TemporaryDirectory's implicit cleanup
    # can both retry permission failures and turn a completed publication into
    # an exception after the formal files already exist.
    temporary = Path(tempfile.mkdtemp(prefix="finalize-", dir=work_parent))
    published = False
    try:
        packed = temporary / "verified.tar.xz"
        result = packaging.create_archive(root, packed)
        current = unchanged()
        if current[3] != files or current[4] != directories:
            raise FinalizationError("Derived reports changed while archiving")
        archive_matches(packed, files, directories)
        result.update({"archive": str(archive), "root": str(root),
                       "frozen_manifest_sha256": frozen_hash, "release_gate_input_sha256": receipt_hash})
        staged_integrity = temporary / "integrity.json"
        packaging._write_integrity(staged_integrity, result)
        current = unchanged()
        if current[3] != files or current[4] != directories:
            raise FinalizationError("Derived reports changed before archive publication")
        plain(output)
        plain(archive)
        plain(integrity)
        if archive.exists() or integrity.exists():
            raise FinalizationError("Archive/integrity output appeared during finalization")
        output.mkdir(parents=True, exist_ok=True)
        os.link(staged_integrity, integrity)
        try:
            # The formal archive is the LAST publication action; every fallible
            # verification has already finished. link() refuses an existing name.
            os.link(packed, archive)
        except OSError:
            overlay.reject_link(integrity)
            if integrity.samefile(staged_integrity):
                integrity.unlink()
            raise
        published = True
    finally:
        try:
            # Exactly one attempt, with no permission-reset/retry handler and no
            # GC finalizer that could later try again. Never remove formal files.
            shutil.rmtree(temporary)
        except OSError as exc:
            phase = "verified archive published successfully" if published else "finalization failed before publication"
            warning = {"workspace": str(temporary), "error": type(exc).__name__}
            print(f"WARNING: {phase}; workspace cleanup failed ({type(exc).__name__}). "
                  f"Remaining workspace retained for manual review: {temporary}. No automatic retry.", file=sys.stderr)
            if published:
                result["cleanup_warning"] = warning
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "finalize"))
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--kind", choices=("base", "gpu"), required=True)
    parser.add_argument("--frozen-manifest", type=Path, required=True)
    parser.add_argument("--release-gates", type=Path)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args(argv)
    if args.command == "freeze" and (args.release_gates is not None or args.output_root is not None):
        parser.error("freeze does not accept publication gates or an archive output")
    if args.command == "finalize" and args.release_gates is None:
        parser.error("finalize requires an explicit --release-gates input")
    try:
        if args.command == "freeze":
            result = freeze(args.repo_root, args.package_root, args.kind, args.frozen_manifest)
        else:
            result = finalize(args.repo_root, args.package_root, args.kind, args.frozen_manifest,
                              args.release_gates, args.output_root or args.repo_root / "release")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, zipfile.BadZipFile, tarfile.TarError) as exc:
        print(f"Release {args.command} failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
