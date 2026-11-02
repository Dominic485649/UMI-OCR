# Release Evidence Report

Verification date: `2026-11-01`

Artifact kind: `base`

| Gate | Status | Evidence |
| --- | --- | --- |
| runtime_vendor | PASS | `LICENSES/runtime-vendor-lock.json` |
| paddle_models | NOT_INCLUDED | `LICENSES/model-rights.json` |
| cuda | NOT_INCLUDED | `LICENSES/cuda-redistributable.json` |
| cudnn | NOT_INCLUDED | `LICENSES/cudnn-redistributable.json` |
| opencv | PASS | `LICENSES/opencv-artifact.json` |
| ffmpeg | NOT_INCLUDED | `LICENSES/ffmpeg-build.json` |
| mpl | NOT_INCLUDED | `LICENSES/mpl-components.json` |
| agpl_nvidia | NOT_INCLUDED | `LICENSES/agpl-integration.json` |
| cpu_ocr | NOT_INCLUDED | `LICENSES/cpu-document-gates.json` |
| document_models | NOT_INCLUDED | `LICENSES/cpu-document-gates.json` |
| source_delivery | BLOCK | `LICENSES/source-delivery.json` |
| current_source_e2e | BLOCK | `LICENSES/current-source-e2e.json` |

A PASS records only the verified artifact-specific condition. It does not resolve another gate.
ACCEPTED_WITH_LIMITATIONS is limited to current_source_e2e. It preserves the actual NOT_RUN scenarios and the original source/payload-bound user decision; it never invents manual, HDR or OCR success.
Only validation_scope=cuda-startup-hotfix for CUDA 3.0.4 with the unchanged official host 3.0.3 baseline may retain gpu_ocr_e2e=NOT_RUN alongside independently verified gpu_worker_startup=PASS and current program/notes/untested-OCR approval. Other component gates are not waived.
These artifact-derived publication reports are generated after source publication; they are not asserted to be present in the canonical source commit.
