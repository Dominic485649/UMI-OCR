# Windows CUDA Build Guide

This guide builds independent Umi-OCR 3.0.1 Windows x64 base and CUDA 12.6 plugin products. Versions come from `UmiOCR-data/about.json`. The product name, window title, `Umi-OCR.exe`, portable `.settings` location, and branding remain `Umi-OCR`.

## Prerequisites

- Windows 10/11 x64.
- An NVIDIA GPU with Windows driver `560.76` or newer. A system CUDA Toolkit is not required; the locked CUDA 12.6 and cuDNN DLLs ship in the portable package. A Toolkit installed through Scoop or elsewhere neither replaces nor participates in resolving the bundled runtime DLLs.
- Visual Studio 2026, MSVC 14.51, Windows SDK 10.0.28000.0, and the Desktop development with C++ workload. Scripts locate Visual Studio through `vswhere` and do not contain machine-specific absolute paths.
- CMake, Git, PowerShell 7, and `7z.exe` on `PATH`; Windows `tar.exe` and `curl.exe` are also used.
- Qt/PySide6 6.11.2. Offline builds require existing runtime, dependency, model and corresponding-source inputs. `-Offline` fails on missing or mismatched locked inputs without network fallback. Preparing or upgrading dependencies is a separately approved operation.

End users do not install Python, pip, the CUDA Toolkit, or any wheel.

### Why CUDA 12.6 remains selected

The current lock remains cu126; no current same-model, same-machine acceptance evidence supports switching to cu130/cu133. System Toolkit files do not replace portable runtime DLLs. A local build or copy-integrity check is not current-artifact GPU E2E acceptance.

## Reproducible Inputs

- `build/requirements-windows-cu126.in`: direct runtime dependencies.
- `build/constraints-windows-cu126.in`: validated transitive constraints.
- `build/requirements-windows-cu126.lock`: every wheel version and SHA256.
- `build/sources-windows-cu126.lock.json`: Python and official PP-OCRv6 model URLs, sizes, and SHA256 values.
- `UmiOCR-data/native-dlls.lock.json`: generated during the build and included in the package; records every native DLL path, file version, and SHA256.

Only regenerate the wheel lock when changing dependencies:

```powershell
pwsh -File .\build\windows\Resolve-Lock.ps1
```

## Offline Current-Source Build

Run from the repository root. These commands compile local native components, copy inputs and perform static audits; they do not start the product or GPU or download dependencies/models. Every output must be new. Seeds are read-only; no old staging directory is scanned, deleted or recreated.

```powershell
$repo = (Get-Location).Path
$run = Get-Date -Format 'yyyyMMdd-HHmmss'
$base = Join-Path $repo "build/staging/301-base-$run"
$gpu = Join-Path $repo "build/staging/301-gpu-$run"
pwsh -File ./build/windows/Build-Release.ps1 -StagingRoot $base `
  -ReuseDependencies -ReuseFromStagingRoot "$repo/build/staging/281-base-current" `
  -Offline -SkipTests -SkipArchive -LocalCandidate
pwsh -File ./build/windows/Build-GpuPlugin.ps1 -StagingRoot $gpu -BaseStagingRoot $base `
  -ReuseDependencies -ReuseVendorFromStagingRoot "$repo/build/staging/281-gpu-current" `
  -ReuseModels -SkipModels -Offline -SkipArchive -LocalCandidate
$python = "$base/UmiOCR-data/runtime/python.exe"
```

Base copies runtime/site-packages and the Qt manifest, then current public host source including untracked files, and rebuilds the launcher/HDR DLL. GPU copies vendor and already-derived models. `-SkipModels` prevents downloading/deriving models and requires `-ReuseModels` for a new staging tree. Missing seeds/source caches or hash/size mismatches fail without network fallback.

Optional assembly and independent public products never infer a sibling CPU/VL checkout:

```powershell
$complete = "$repo/build/artifacts/3.0.1-$run/complete"
pwsh -File ./build/windows/Assemble-Candidate.ps1 -Destination $complete `
  -BaseStagingRoot $base -GpuStagingRoot $gpu
& $python -B ./build/tools/prepare_products.py --complete-root $complete `
  --products-root "$repo/build/artifacts/3.0.1-products-$run"
& $python -B ./build/tools/export_cuda_source.py `
  --output-dir "$repo/build/artifacts/301-plugin-repository"
```

The local CUDA source export contains only its public adapters, required public build tools, docs, locks, licenses and locked corresponding-source materials, preserving relative paths. It creates no remote, Git history or release, and refuses existing outputs. `-CpuStagingRoot`, `-VlStagingRoot` and `--optional-plugin ID=PATH` are explicit development-only selections. `source_snapshot.py` defaults to public scope, includes untracked public sources and excludes vendor/models/cache/artifacts/user temporary data; direct snapshots also require the existing locked corresponding-source cache.

## tar.xz And Root Paths

Both Build scripts invoke `build/tools/package_tar_xz.py`: an inner POSIX tar and an outer xz stream, with installed 7-Zip standard LZMA2 probed by default. If the installed 7z-FLZMA2 cannot write xz, the existing portable Python standard LZMA2 implementation is used without downloading a tool. Both layers and SHA256 are verified. Existing archives and integrity reports are not overwritten. Omit `-SkipArchive` to create local-candidate archives, or invoke the helper with a fresh output.

Extract Base into the chosen application root to create `Umi-OCR.exe` and `UmiOCR-data/` directly. Extract CUDA into that same root to overlay `UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/`; there is no additional product-directory prefix. CUDA license and corresponding-source materials live under `LICENSES/plugins/win32_PaddleOCRv6_CUDA/`, preserving the host's root licenses, version and source records. GUI tools may require extracting both xz and tar layers; Windows `tar.exe -xf archive.tar.xz -C <application-root>` handles both.

## Verification

These commands skip runtime acceptance. `LocalCandidate` keeps public-release and current-source E2E gates at BLOCK/NOT_RUN. Historical hashes/PASS evidence are not current-artifact acceptance. Only after explicit approval run `Test-Release.ps1 -StagingRoot $complete -Kind combined -Device gpu:0`, then complete manual screenshot/HDR acceptance.

This entry point covers startup lazy imports and warmup reuse, Qt/QML D3D11 and polygon/cursor-anchored image behavior, decoders, UVDoc, screenshot/batch/PDF OCR, QR codes, HTTP/CLI, portable settings, the HDR shader, DPI geometry, and automated screen capture. The CUDA-unavailable checks isolate the GPU wheel or request a missing `gpu:N` device and require an explicit OCR failure with no CPU fallback. Do not install a CPU Paddle wheel into staging for this test.

Automated capture does not replace manual selection-window and HDR visual acceptance. Complete the manual steps in [HDR screenshot testing and calibration](https://github.com/Dominic485649/UMI-OCR/blob/v3.0.1/docs/HDR_TEST_WINDOWS.md) before release.

Use `-SkipScreenshotCapture` when the current desktop must not be read by an automated test. It skips only automated full-screen capture; all other regressions, clean-build work, auditing, and archiving still run. Manual screenshot acceptance must cover the omitted check.

## Qt Trimming

The release script combines `qmlimportscanner` output with `build/qt-runtime-whitelist.json`, then retains only used QML modules, plugins, Python extensions, and recursive DLL dependencies. After changing a QML import, Qt plugin, or PySide6 extension, run a clean build; an already-trimmed staging tree cannot validate the new dependency.

## License And Corresponding Source

This fork's changes and the combined distribution containing PyMuPDF are AGPL-3.0-or-later; the original MIT `LICENSE` and hiroi-sora attribution remain. The mirror uses the same public selector, including untracked current required files and GPL/AGPL/MPL corresponding-source materials. `LocalCandidate` freezes and verifies that mirror as `source-snapshot.zip`, member hashes and version provenance, then removes only its own newly generated expanded mirror. Public source publication remains BLOCK until separately confirmed. See the [combined-distribution note](../LICENSES/COMBINED_DISTRIBUTION.md).

## Release Rules

The base-package audit rejects PP-OCR V2-V5, PP-OCRv6 small/tiny, CPU Paddle, ONNX Runtime, DirectML, and model assets outside the base OCR package. Windows 7 is not supported or claimed compatible.
