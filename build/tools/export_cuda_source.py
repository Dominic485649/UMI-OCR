"""Export a new public CUDA source tree, offline and without Git history."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from source_snapshot import files_for_repo, git_output, locked_sources, version_from_about

PLUGIN = "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/"
TOOLS = {
    "run_pip.py", "patch_paddlex_3_7_2.py", "generate_third_party_components.py",
    "verify_release_evidence.py", "strip_optional_models_3_7.py",
    "derive_uvdoc_grid_model.py", "split_lock.py", "source_snapshot.py",
    "package_tar_xz.py", "export_cuda_source.py", "record_gpu_e2e.py", "verify_public_payload.py", "freeze_gpu_runtime.py", "prepare_cuda_overlay.py",
    "staging_smoke.py", "measure_closure.py",
}
DOCS = {"BUILD_WINDOWS_CUDA.md", "BUILD_WINDOWS_CUDA_en.md", "PLUGIN_API.md", "README_CUDA_PLUGIN.md"}


def selected_sources(repo: Path) -> list[Path]:
    selected = []
    for relative in files_for_repo(repo, public=True):
        name = relative.as_posix()
        if (name.startswith(PLUGIN) or name.startswith("LICENSES/") or
            name in {"COPYING", "LICENSE", "SOURCE-CODE.md", "UmiOCR-data/about.json",
                     "UmiOCR-data/py_src/plugins_controller/host_api.py",
                     "build/requirements-gpu-plugin-windows-cu126.lock",
                     "build/sources-windows-cu126.lock.json",
                     "build/windows/Build-GpuPlugin.ps1", "build/windows/Audit-Package.ps1"} or
            name.startswith("build/tools/") and relative.name in TOOLS or
            name.startswith("docs/") and relative.name in DOCS or
            name.startswith("tests/") and relative.name in {
                "test_cuda_worker_client.py", "test_ocr_workflows.py", "test_public_payload.py",
                "test_release_evidence_status.py", "test_optional_model_strip.py", "test_cuda_overlay.py",
            }):
            selected.append(relative)
    required = {"COPYING", "LICENSE", PLUGIN + "umi-plugin.json", PLUGIN + "api.py", PLUGIN + "worker.py",
                "build/windows/Build-GpuPlugin.ps1", "build/tools/package_tar_xz.py", "build/tools/source_snapshot.py"}
    missing = required - {path.as_posix() for path in selected}
    if missing:
        raise RuntimeError(f"CUDA source export lacks required public files: {sorted(missing)}")
    return selected


def export_repository(repo: Path, output: Path, cache: Path) -> dict[str, object]:
    if output.exists() or output.is_symlink():
        raise RuntimeError(f"refusing to overwrite source repository: {output}")
    output = output.resolve()
    output.relative_to((repo / "build").resolve())
    selected = selected_sources(repo)
    archives = locked_sources(repo, cache)
    version = version_from_about(repo / "UmiOCR-data/about.json")
    files = [(repo / relative, relative) for relative in selected] + archives
    if len({relative.as_posix().casefold() for _, relative in files}) != len(files):
        raise RuntimeError("duplicate CUDA source export paths")
    output.mkdir(parents=True)
    manifest = {}
    for source, relative in files:
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        checksum = hashlib.sha256(target.read_bytes()).hexdigest()
        if checksum != hashlib.sha256(source.read_bytes()).hexdigest():
            raise RuntimeError(f"source changed while exporting: {relative}")
        manifest[relative.as_posix()] = checksum
    # The repository needs a root README, with links that remain valid after
    # exporting from the host's docs/ directory into this independent checkout.
    readme = output / "docs/README_CUDA_PLUGIN.md"
    if readme.is_file():
        content = readme.read_bytes()
        (output / "README.md").write_bytes(content)
        manifest["README.md"] = hashlib.sha256(content).hexdigest()
    (output / "VERSION").write_text(version + "\n", encoding="utf-8")
    manifest["VERSION"] = hashlib.sha256((output / "VERSION").read_bytes()).hexdigest()
    result = {
        "version": version, "scope": "public-cuda-only", "parent_revision": git_output(repo, "rev-parse", "HEAD").strip(),
        "git_history_included": False, "local_changes_included": True,
        "public_release_allowed": False, "current_source_e2e": "NOT_RUN", "files": manifest,
    }
    (output / "source-export.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--source-cache", type=Path)
    args = parser.parse_args(argv)
    try:
        repo = args.repo_root.resolve()
        version = version_from_about(repo / "UmiOCR-data/about.json")
        output = args.output_dir or repo / "build/artifacts" / f"{version.replace('.', '')}-plugin-repository"
        result = export_repository(repo, output, args.source_cache or repo / "build/cache/sources")
        print(f"Public CUDA source exported locally: {output}; version={version}; files={len(result['files'])}; E2E=NOT_RUN")
        return 0
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"CUDA source export error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
