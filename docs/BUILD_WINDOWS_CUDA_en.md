# Windows build and minimal distribution

The target is Windows x64. Application, CUDA and PaddleVL versions are independent; compatibility follows Host API ranges, Python ABI, platform and actual integration checks. Current runtime locks remain Python 3.13.16, Qt/PySide6 6.11.2 and CUDA 12.6.

## Build inputs

Use PowerShell 7 (`pwsh`), Git, CMake, the Visual Studio C++ toolchain and Windows SDK. Reuse verified runtime/wheel/model/source inputs offline. Missing or mismatched inputs fail without network fallback. Do not regenerate dependency locks, download models or change quantization merely to repackage.

`Build-Release.ps1` and `Build-GpuPlugin.ps1` create fresh complete staging trees. PaddleVL is built in its separately authorized plugin project. Build only changed components; unchanged CUDA execution payload does not need recompilation.

The builders default to `-DistributionLayout minimal`:

- `-StagingRoot` retains complete corresponding source and evidence inputs.
- `-MinimalRoot` is a new runtime tree, defaulting to `<StagingRoot>-runtime`.
- `-DistributionRecord` is a new external JSON under the project's `build/audit/` by default.
- `-DistributionLayout complete` retains legacy-layout compatibility only.
- `-RuntimeLayout stored` retains the existing Stored-ZIP policy, native dependencies and original source bytes.
- `-SkipArchive` prepares trees without authorizing release; `LocalCandidate` never grants public-release approval.

Use paths and read-only seeds identified in the current build records, not historical machine-specific examples. CUDA `-SkipModels` prevents downloads/derivation; fresh builds must reuse verified model inputs explicitly.

## Runtime and separate source

`build/tools/prepare_minimal_distribution.py` provides `prepare`, `verify` and `package`. It classifies every file, rejects unknown root contents, preserves runtime bytes and binds both the actual minimal tree and external complete materials. Local archive integrity is not public-source acceptance.

The base extracts directly to `Umi-OCR.exe` and `UmiOCR-data/`. Plugin archives overlay `UmiOCR-data/plugins/<plugin-id>/` without another product-directory prefix. Separate source mirrors/ZIPs, development documentation and audit reports are not installed. Required licenses, attribution, source directions, TLS certificates and runtime resources remain.

Matching corresponding source is a separate artifact, clearly offered beside the runtime without an extra charge. Original source snapshots, dependency/source locks and evidence remain traceable. See [source delivery](../SOURCE-CODE.md).

## Gates and verification

The existing `Audit-Package.ps1` and `verify_release_evidence.py` gates still inspect complete materials. `Finalize-Release.ps1 -DistributionRecord` additionally verifies the actual minimal payload, requires current approval to bind `minimal_distribution_record_sha256`, and compares archive bytes with that runtime tree. Do not strip files silently after an older gate passed or turn a source/licensing BLOCK into a PASS.

Use directed checks for classification/source bindings, downloader progress/cancellation/failures/path safety, real QML controls, archive reinstallation, actual startup, plugin discovery and representative OCR/document operations. Record which unchanged inputs and earlier evidence are reused. Capture, HDR and mixed/multiple-monitor tests remain NOT_RUN; no additional capture testing is requested.

After acceptance, reinstall the final component archives in a new directory and update `release/Umi-OCR`, retaining settings, logs, task assets, downloaded `model/` contents and local private components. Never overwrite a running installation or terminate user processes.

Publication still requires review of this round's actual program, Release text, limitations and cleanup preview. A local installation update is not public-release authorization. Do not rewrite historical evidence or remove source/model/dependency caches as routine cleanup.

[Full Chinese guide](BUILD_WINDOWS_CUDA.md) · [Documentation](README.md) · [History](HISTORY.md)
