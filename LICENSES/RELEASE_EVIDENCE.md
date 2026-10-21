# Release Evidence Report

Verification date: `2026-10-22`

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
ACCEPTED_WITH_LIMITATIONS, when present only for current_source_e2e, retains NOT_RUN manual scenarios and the original, source/payload-bound user publication decision. It is not a manual-test PASS.
These artifact-derived publication reports are generated after source publication; they are not asserted to be present in the canonical source commit.
