# Windows CUDA Build Guide

This guide describes the build contract for independent Umi-OCR Windows x64 base and CUDA 12.6 plugin products. Versions come from `UmiOCR-data/about.json`. The product name, window title, `Umi-OCR.exe`, portable `.settings` location and branding remain `Umi-OCR`; the product version does not change Host API compatibility.

**Dated snapshot (2026-10-22, before this round's fresh rebuild):** Historical 3.0.3 R2 completed base/combined, hot GUI, tray/HTTP/exit, GPU, archive reinstallation and source/model checks. Both public `v3.0.3` source tags exist, but neither binary Release has been created, uploaded or published. This round is to repair formal gate wiring and prepare fresh noncandidate products with `-SkipArchive`; that build has not run at this cutoff, and R2 PASS, hashes and approval do not carry over. The user must review this round's actual program and both texts before main/tag updates; the formal source gate waits for matching tags, then restricted finalization follows. See the [3.0.3 acceptance contract](RELEASE_3.0.3_ACCEPTANCE.md), [review requirements](RELEASE_3.0.3_REVIEW.md) and [source-delivery contract](../SOURCE-CODE.md).

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

## Offline Examples and This Round's Formal Preparation

Run from the repository root. Building compiles local native components, copies inputs and performs static audits; it does not start the product or GPU or download dependencies/models. Every output must be new. Seeds are read-only; no old staging directory is scanned, deleted or recreated.

The following `-LocalCandidate` commands are retained development examples with path names from the 3.0.2 preparation phase, **not this round's formal 3.0.3 prepare/finalize commands** or proof that the old seeds remain available. This round's approved workflow uses fresh non-`LocalCandidate`, `-SkipArchive` preparation; actual paths, read-only seeds and base/CUDA overlay outputs must be identified in its new build records. Independent GPU staging is not automatically a formal overlay: obtain the real GPU receipts and freeze the materials first, then generate the actual overlay once and freeze that overlay. Complete real local acceptance, freeze the actual source/payload and obtain review approval before public-tag matching, fresh gates and restricted finalization. Simply omitting `-SkipArchive`, or using the development assembly/splitting examples below, must not bypass that sequence.

```powershell
$repo = (Get-Location).Path
$run = Get-Date -Format 'yyyyMMdd-HHmmss'
$base = Join-Path $repo "build/staging/302-base-$run"
$gpu = Join-Path $repo "build/staging/302-gpu-$run"
# 首次升级示例；清理旧版本后，改为当版验收记录中的有效只读 seed。
$baseSeed = "$repo/build/staging/301-base-20261018"
$gpuSeed = "$repo/build/staging/301-gpu-20261018"
pwsh -File ./build/windows/Build-Release.ps1 -StagingRoot $base `
  -ReuseDependencies -ReuseFromStagingRoot $baseSeed `
  -Offline -SkipTests -SkipArchive -LocalCandidate
pwsh -File ./build/windows/Build-GpuPlugin.ps1 -StagingRoot $gpu -BaseStagingRoot $base `
  -ReuseDependencies -ReuseVendorFromStagingRoot $gpuSeed `
  -ReuseModels -SkipModels -Offline -SkipArchive -LocalCandidate
$python = "$base/UmiOCR-data/runtime/python.exe"
```

Base copies runtime/site-packages and the Qt manifest, then current public host source including untracked files, and rebuilds the launcher/HDR DLL. GPU copies vendor and already-derived models. `-SkipModels` prevents downloading/deriving models and requires `-ReuseModels` for a new staging tree. Missing seeds/source caches or hash/size mismatches fail without network fallback.

Optional assembly and independent public products never infer a sibling CPU/VL checkout:

```powershell
$complete = "$repo/build/artifacts/3.0.2-$run/complete"
pwsh -File ./build/windows/Assemble-Candidate.ps1 -Destination $complete `
  -BaseStagingRoot $base -GpuStagingRoot $gpu
& $python -B ./build/tools/prepare_products.py --complete-root $complete `
  --products-root "$repo/build/artifacts/3.0.2-products-$run"
& $python -B ./build/tools/export_cuda_source.py `
  --output-dir "$repo/build/artifacts/302-plugin-repository-$run"
```

The local CUDA source export contains only its public adapters, required public build tools, docs, locks, licenses and locked corresponding-source materials, preserving relative paths. It creates no remote, Git history or release, and refuses existing outputs. `-CpuStagingRoot`, `-VlStagingRoot` and `--optional-plugin ID=PATH` are explicit development-only selections. `source_snapshot.py` defaults to public scope, includes untracked public sources and excludes vendor/models/cache/artifacts/user temporary data; direct snapshots also require the existing locked corresponding-source cache.

## tar.xz And Root Paths

Both Build scripts invoke `build/tools/package_tar_xz.py`: an inner POSIX tar and an outer xz stream, with installed 7-Zip standard LZMA2 probed by default. If the installed 7z-FLZMA2 cannot write xz, the existing portable Python standard LZMA2 implementation is used without downloading a tool. Both layers and SHA256 are verified. Existing archives and integrity reports are not overwritten. Omit `-SkipArchive` to create local-candidate archives, or invoke the helper with a fresh output.

Extract Base into the chosen application root to create `Umi-OCR.exe` and `UmiOCR-data/` directly. Extract CUDA into that same root to overlay `UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/`; there is no additional product-directory prefix. CUDA license and corresponding-source materials live under `LICENSES/plugins/win32_PaddleOCRv6_CUDA/`, preserving the host's root licenses, version and source records. GUI tools may require extracting both xz and tar layers; Windows `tar.exe -xf archive.tar.xz -C <application-root>` handles both.

## Verification

Preparation and `-SkipArchive` do not mean public-release or current-source E2E has passed; old R2 hashes/PASS are not this round's evidence. Within the approved scope, run `Test-Release.ps1 -StagingRoot $complete -Kind combined -Device gpu:0` against the actual combined tree, and separately record hot GUI, real Windows tray/pre-quit HTTP readiness, normal exit, raw GPU receipts, source/model checks and manual limitations. GPU formal gates bind the actual CUDA overlay, not the independent GPU staging tree.

Freeze the actual base/GPU overlay source and payload, then present the program and both texts for review. Only after explicit approval update main/tags. After tags match, run fresh formal source/runtime gates, then restricted finalization, formal archives, clean reinstallation and publication verification. Do not prefill formal PASS before the tags match. `LocalCandidate` is a development path, not a substitute for this round's formal workflow.

This entry point covers startup lazy imports and warmup reuse, Qt/QML D3D11 and polygon/cursor-anchored image behavior, decoders, UVDoc, screenshot/batch/PDF OCR, QR codes, HTTP/CLI, portable settings, the HDR shader, DPI geometry, and automated screen capture. The CUDA-unavailable checks isolate the GPU wheel or request a missing `gpu:N` device and require an explicit OCR failure with no CPU fallback. Do not install a CPU Paddle wheel into staging for this test.

Automated capture does not replace manual selection-window and HDR visual acceptance. Complete the manual steps in [HDR screenshot testing and calibration](https://github.com/Dominic485649/UMI-OCR/blob/v3.0.1/docs/HDR_TEST_WINDOWS.md) before release.

Use `-SkipScreenshotCapture` when the current desktop must not be read by an automated test. It skips only automated full-screen capture; all other regressions, clean-build work, auditing, and archiving still run. Manual screenshot acceptance must cover the omitted check.

## Qt Trimming

The release script combines `qmlimportscanner` output with `build/qt-runtime-whitelist.json`, then retains only used QML modules, plugins, Python extensions, and recursive DLL dependencies. After changing a QML import, Qt plugin, or PySide6 extension, run a clean build; an already-trimmed staging tree cannot validate the new dependency.

## License And Corresponding Source

This fork's changes and the combined distribution containing PyMuPDF are AGPL-3.0-or-later; the original MIT `LICENSE` and hiroi-sora attribution remain. The mirror uses the same public selector, including untracked current required files and GPL/AGPL/MPL corresponding-source materials. The actual `source/`, `source-snapshot.zip`, member hashes and provenance must match the frozen product and public commit/tag; `LocalCandidate` development records do not replace the formal source gate.

Final derived `source-delivery.json`, `current-source-e2e.json` and `RELEASE_EVIDENCE.*` belong in artifact `LICENSES/`, with CUDA overlay metadata under `LICENSES/plugins/win32_PaddleOCRv6_CUDA/`. Never copy later PASS reports back into canonical source, change the frozen mirror or regenerate its snapshot to claim that the results were frozen source content. Only this round's fresh gates establish compliance; no automatic success of the script wiring is asserted. See the [combined-distribution note](../LICENSES/COMBINED_DISTRIBUTION.md).

## Release Rules

The base-package audit rejects PP-OCR V2-V5, PP-OCRv6 small/tiny, CPU Paddle, ONNX Runtime, DirectML, and model assets outside the base OCR package. Windows 7 is not supported or claimed compatible.
