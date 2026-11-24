# Umi-OCR 2.7.0 Pre-release Draft

Status: **artifact-driven public-release closure complete**. The final GPU and
CPU prerelease archives were created only after their strict public gates,
extraction audits, and final verifiers all passed. These remain local
prerelease artifacts; no remote publication was performed.

## Scope

2.7.0 makes the base package a plugin host. It retains the light UI, import and
export flows, PDF features, task queue, HTTP/CLI surface, and Windows tray. It
does not contain an OCR inference backend. With no healthy OCR plugin installed,
the UI must say that no OCR backend is installed; it must not describe CPU OCR
as available.

The supported capability types are `ocr` and `document`. They have separate
registries, configuration, task managers, QML managers, health checks, and
error paths. A structured-document plugin is not an OCR plugin in disguise.

## Planned Deliverables

| Deliverable | Archive status | Required before it can be published |
| --- | --- | --- |
| Base host | Final local prerelease archive | The clean host archive passes the base runtime/vendor, OpenCV, package-audit, source-mirror, and public-release gates; base regression and startup/HTTP/PDF/import checks passed. |
| GPU OCR plugin | Final local prerelease archive | The clean no-FFmpeg archive passes runtime/vendor, five-model GPU E2E, Paddle model/CUDA/cuDNN/OpenCV/MPL, AGPL/NVIDIA worker-boundary, and verified CPU evidence gates. |
| CPU OCR plugin | Final local prerelease archive | The clean ONNX Runtime CPU archive passes its independent runtime/vendor, five-model, OpenCV/MPL, E2E, package-audit, and public-release gates. |
| Structured-document plugin | NOT_INCLUDED | No document runtime, GGUF, F16, or mmproj artifact is present in the public staging; the official PaddleOCR-VL-1.6-GGUF candidate was surveyed but not claimed or redistributed. |

Only explicitly named final `.7z` artifacts may be placed in `release/`.
Unpacked plugin files, model weights, GGUF/mmproj files, llama.cpp binaries, and
PaddleOCR-VL source must not be added to the base package or its source mirror.

## Required Evidence

Before changing the status above, record the following for every actual archive:

| Item | Base | GPU | CPU | Document |
| --- | --- | --- | --- | --- |
| File list and size-sorted inventory | Required | Required | Required | Required |
| Extracted size, archive size, compression ratio | Required | Required | Required | Required |
| SHA-256 and `7z t` output | Required | Required | Required | Required |
| `Audit-Package.ps1` result after clean extraction | Required | Required | Required | Required |
| Dependency closure and duplicate-file report | Required | Required | Required | Required |
| License, corresponding source, build script, lock review | Required | Required | Required | Required |
| Hardware/input/command performance record | Host | GPU | CPU | Document |

The preliminary base closure measurement is stored in
`benchmarks/results/package-2.7.0-base.json`. It is a baseline input, not a
release measurement. Re-run it after a clean build and add the exact command,
hardware, driver, model revision, input set, timestamp, first-run latency,
steady-state latency, memory, and failure observations.

## Release Procedure

1. Build the base package and each eligible plugin from clean staging roots.
2. Extract each archive into an empty directory, run the package audit and
   `7z t`, then calculate SHA-256.
3. Run static checks, Qt/QML startup, real Windows Shell tray actions, OCR,
   batch, PDF, folder import, HTTP, CLI, startup and shutdown regressions.
4. Run measured baselines and record before/after numbers for any optimisation.
5. Review the release report, including all unverified items and license gates.
6. Create a local commit only after the preceding evidence is complete.
7. Before any GitHub repository creation, push, release, or pre-release upload,
   report account/organisation, visibility, remote URL, default branch, and
   migration plan and wait for explicit confirmation.

2.7.0 may be labelled a pre-release only after these gates pass. It must not be
presented as a final 3.0.0 replacement.

## Candidate artifact evidence

The following local candidates have not been published. `7z t` passed for both
on 2026-08-02; their complete file and duplicate-content inventories are in
`benchmarks/results/package-2.7.0-rc1-*-v5-20260802.json` and the v5 build logs.

| Candidate | Files | Extracted bytes | Archive bytes | Compression | SHA-256 |
| --- | ---: | ---: | ---: | ---: | --- |
| `Umi-OCR_v2.7.0-rc.1_Windows_x64.7z` | 2,313 | 571,542,712 | 197,368,708 | 34.53% | `9f0220371f7c64bf3dc5280f09574371f9ac04c85300f13677bc340450954aa9` |
| `Umi-OCR-Plugin_GPU-OCR_v2.7.0-rc.1_Windows_x64_CUDA12.6.7z` | 9,919 | 4,205,037,526 | 1,611,078,259 | 38.31% | `4adb6b6df693a7796c2238e5085fff43b76c7fa852bb25edf04724667754fba7` |

These predate the current artifact closure and must not be published. The
final local base, GPU, and CPU archives are recorded in
`LICENSES/archive-manifest.json`. No structured-document archive was created;
the structured-document capability is explicitly NOT_INCLUDED until a separate
artifact/runtime/model provenance chain and server-side E2E are supplied.

## Base artifact evidence (2026-08-09)

The clean host staging root
`build/staging/release-2.7-base-final-clean-20260809` was rebuilt from the
current source with the trimmed portable runtime, no OCR backend, no CUDA or
cuDNN payload, and no FFmpeg backend. Its base regression suite passed, then
the strict base verifier and package audit passed using the closed CPU
evidence staging. A fresh extraction of
`release/Umi-OCR_v2.7.0-rc.1-final-20260809.7z` passed `7z t`,
`Audit-Package.ps1 -RequirePublicRelease`, and the base verifier with exit code
0. The archive is 201,207,124 bytes with SHA-256
`37d703f23b05be765985ac3dafbdf74f7e2de48c478686efbcd2074fa9e24cdc`.

## CPU artifact evidence (2026-08-09)

The final clean staging root
`Umi-OCR-Plugin/build/staging/release-2.7-cpu-final-clean-20260809` passed both
the CPU artifact verifier in public-release mode and `Audit-Package.ps1` after
clean construction. It contains 36 vendor distributions, 118 native binaries,
and a 5,415-entry final runtime lock. The build records a 1,904-file pruning
manifest for unused development files, alternate PP-OCR configurations, and
CUDA/NVIDIA/DirectML-named payloads; the real five-model ONNX Runtime
CPUExecutionProvider adapter E2E returned 44 text items from the checked input.

The retained `pypdfium2` dependency is also verified as an actual embedded
binary closure rather than a generic wheel label. `pdfium.dll`
(`cc2058add54b9da299a4496d526b79c375c6f0eb3a9000552a45c60f83765d55`)
byte-matches both the official pypdfium2 5.12.1 Windows wheel and the
`pdfium-binaries` `chromium/7947` release asset. The source mirror contains
the wheel, source distribution, PyPI integrity/provenance data, release and
commit snapshots, and all 19 embedded notice files; the records distinguish the
pypdfium2 source revision `4a2636051ff4a841966be01484f4a70b4309b55c` from
the PDFium release revision `chromium/7947 @ a068e5317bb780d0afdf00d8b341938d9f36d2fe`.

The five actual model records are the official PaddlePaddle ONNX repositories
for `PP-LCNet_x1_0_doc_ori`, `UVDoc`, `PP-LCNet_x1_0_textline_ori`,
`PP-OCRv6_medium_det`, and `PP-OCRv6_medium_rec`. Each record locks the model
card snapshot, upstream revision, `inference.onnx` SHA-256, Apache-2.0 evidence,
notices, and unmodified status. The staging `LICENSES/RELEASE_EVIDENCE.md`,
`runtime-vendor-lock.json`, `model-rights.json`, `cpu-copyleft-components.json`,
and `cpu-e2e-evidence.json` are the authoritative local evidence, not this
summary.

The resulting CPU archive is
`Umi-OCR-Plugin/release/Umi-OCR-Plugin_CPU-OCR_v2.7.0-rc.1-final-20260809.7z`
(210,848,205 bytes, SHA-256
`618d1c3e3df8b41f771da885c8b5a34fb0c7efac071c54d8b243d678a58e0fe0`). A fresh
extraction passed `7z t`, `Audit-Package.ps1 -RequirePublicRelease`, and the
CPU verifier with exit code 0.

## GPU artifact evidence (2026-08-09)

The final clean staging root
`build/staging/release-2.7-final-clean-20260809` passed the strict artifact
verifier and `Audit-Package.ps1`. It deliberately contains no
`opencv_videoio_ffmpeg*.dll`: the prior v5 DLL was an FFmpeg 4.4.4 static LGPL
build without a relinkable closure, so it is recorded as `NOT_INCLUDED`, not
as a license pass. It also contains no `cusolverMg64_11.dll`.

`cuda-redistributable.json` records a scan of all 228 packaged PE files with
zero parse errors and zero direct imports of the excluded CUDA DLL. The 21
LICENSES files exactly match their source-mirror copies. The final candidate
ran the real CUDA batch/document/PDF/HTTP/CLI workflow on `gpu:0`, initialized
the five PP-OCRv6 models including UVDoc, and saved runtime-lock-tied evidence
for the separate JSON-lines worker. The cuDNN runtime DLL inventory satisfies
the current NVIDIA SLA requirements and retains the official SLA snapshot.
The AGPL-covered host does not load proprietary modules; only the independent
worker does. Document models remain explicitly NOT_INCLUDED.

The new archive is
`release/Umi-OCR-Plugin_GPU-OCR_v2.7.0-rc.1-final-20260809.7z`, with
SHA-256 `56dcf10ec7dfa854893329e21de5b89fbba1a7ecaf584a2d06ade14caf9833a9`.
It passed `7z t`, extraction audit, and the final strict verifier.

The migration isolates the host: the base archive is 87.69% smaller extracted
and 88.79% smaller compressed than the 2.6.0 monolith. The two archives
together are 2.85% larger extracted and 2.74% larger compressed than the
monolith because each independently carries its required runtime/source
closure. Duplicate-content waste is 1,899,991 bytes in the base archive and
2,000,214 bytes in the GPU archive. The largest remaining files are executable
runtime DLLs, OCR models, or corresponding source. No further size reduction is
approved without a per-file closure and license/source-delivery review.

## Controlled GPU performance (2026-08-02)

The comparable A/B run used the same machine, input corpus, model hashes,
driver, and Windows High Performance power scheme. No user desktop processes
were killed. GPU sampling during both runs reported RTX 4060 Laptop GPU driver
610.62, P4, 1050 MHz SM clock, about 1.97 GiB used of 8.0 GiB. The input set
contains 8 generated cases, 212,880 encoded bytes, SHA-256
`5b1d41a2c9f82de18be8e3d641b92887cf3fd5d15f6b5af946e7430a5bf423f3`.

| Preset | v4b median | v5 median | Change | v5 P95 | Stage evidence |
| --- | ---: | ---: | ---: | ---: | --- |
| speed | 59.289 ms | 59.722 ms | +0.73% | 67.063 ms | decode 2.555 ms, predict 57.109 ms, convert 0.024 ms |
| balanced | 67.855 ms | 66.958 ms | -1.32% | 68.786 ms | decode 2.602 ms, predict 64.125 ms, convert 0.058 ms |
| accuracy | 65.220 ms | 65.020 ms | -0.31% | 76.048 ms | decode 2.551 ms, predict 62.229 ms, convert 0.053 ms |

This passes the local gate: median latency stayed within +10%, process memory
increased about +1.1%, GPU memory did not increase, and correctness remained
`mean_cer=0.0`, `mean_box_iou=0.83`, `mean_miss_rate=0.0`. The stage split
shows the hot path is still Paddle inference, not image decode, conversion,
or task-queue overhead.

## Local evidence (2026-08-02)

- Base staging `build/staging/release-2.7-base-v5-20260802`: clean rebuilt
  startup/Qt/QML/import/HDR/no-backend regression and base audit passed.
- GPU staging `build/staging/release-2.7-gpu-v5-20260802`: plugin audit passed;
  CUDA/Paddle vendor, five local model caches, source mirror and runtime lock
  are present, and `aistudio-sdk` is absent.
- Combined staging `build/staging/release-2.7-combined-v5-20260802`: full
  OCR, batch, PDF, folder, HTTP, CLI, startup/shutdown, lifecycle and error
  recovery regression passed on RTX 4060 Laptop (`gpu:0`).
- A Windows DLL search-path defect was fixed by mounting plugin DLL directories
  into both `os.add_dll_directory` and the process `PATH`; the corrected
  combined smoke passed.
- The GPU OCR performance gate did not pass: against the prior baseline, median
  latency changed by `+47.46%` (speed), `+40.56%` (balanced), and `+45.09%`
  (accuracy). A repeat measurement stayed slow. The RTX 4060 was at P5/600 MHz
  with other desktop GPU users, so this is a failed, uncontrolled comparison,
  not evidence of a code regression. A controlled rerun requires approval to
  change power state or close unrelated applications.
- Real Windows Shell validation passed: the hidden-area `Umi-OCR` icon was
  registered, its context menu was shown, its screenshot action opened and
  cancelled a full-screen selection window, double-click restored the window,
  and `Exit Umi-OCR` terminated the candidate process.
- FFmpeg remains NOT_INCLUDED. No GitHub repository, push, release,
  PaddleOCR-VL model download, or llama.cpp update was performed.
- Independent plugin repo checks on 2026-08-09: the CPU ONNX staging has real
  vendor/model/source locks, a portable-host adapter E2E, and a final archive
  whose fresh extraction passed package audit and the CPU public-release gate.
  The document archive remains NOT_INCLUDED until a reviewed vendor/runtime
  lock and real service/model end-to-end test are supplied.
- The final 2026-08-09 `--require-public-release` gate used the clean base and
  GPU staging plus the extracted CPU archive evidence and returned exit code 0.
  Fresh extractions of all three final archives repeated their package audits
  and strict verifiers. Runtime vendor, five Paddle models, CUDA, cuDNN,
  OpenCV, MPL, AGPL/NVIDIA worker boundary, CPU OCR, and GPU E2E were PASS;
  FFmpeg and document models were NOT_INCLUDED.
