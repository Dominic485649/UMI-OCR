# 3.0.0 Roadmap: umiocr 重制版

Status: the README has been reviewed and direct publication after final
validation is authorized. Umi-OCR 3.0.0 is a normal Release with tag `v3.0.0`.
The current source/runtime tests and artifact audits pass; the final archive,
source, privacy, and installation checks must pass before upload. Validation
results are recorded in `docs/RELEASE_3.0.0_REVIEW.md`. No trademark permission,
upstream endorsement, or new model authorization is claimed.

Python stays at 3.13.16 and is shared by the host and CUDA worker. This release
does not introduce a new interpreter, model, precision, or Linux build. Public
products are the base application in `Dominic485649/UMI-OCR` and the CUDA plugin
in the public `Dominic485649/UMI-OCR_plugins` repository. CPU and PaddleOCR-VL
are separate paid options, not public assets for this release. Plugin interfaces
remain open to third-party implementations without payment or author checks.
Contact: QQ group [AWJ | Umi-OCR](https://qm.qq.com/q/5XHoXCOU26).

## Product Boundary

3.0.0 keeps Umi-OCR attribution and preserves the existing product/executable/
settings identity until an explicit branding decision is made. The host remains
usable without an OCR backend and exposes a documented compatibility contract so
third parties can implement compatible `ocr` or `document` plugins themselves.

CPU OCR and structured-document/VLM inference may be offered as separately
priced plugins, build services, support, or hosted services only after a
license audit covers the exact code, binaries, models, weights, service terms,
distribution method, and corresponding-source obligations. A price does not
remove AGPL, LGPL, third-party, model, or trademark obligations, and no sales or
pre-sale text may claim rights that have not been confirmed.

## Milestones

| Milestone | Exit criterion |
| --- | --- |
| Plugin host hardening | Stable host API, documented migration path, compatibility tests, explicit disabled/conflict/unhealthy states |
| Release closure | Reproducible archives with inventories, hashes, audits, source delivery, and clean-install checks |
| Backend qualification | CPU, GPU, and document backends independently pass health, lifecycle, recovery, and end-to-end regressions |
| Performance evidence | Comparable first-run/steady-state, memory, batch, PDF, folder, HTTP, and CLI measurements with reproducible inputs |
| Rights review | Per-component written evidence or a documented distribution exclusion; no unresolved blocker is described as licensed |
| Commercial review | License-compatible source/service terms, model/service ownership boundary, and non-misleading user-facing copy |

## Non-goals Until Approved

- No automatic model download, chosen quantization, bundled GGUF/mmproj,
  llama.cpp binary, or PaddleOCR-VL weight distribution.
- The reviewed README and direct formal publication are approved. Remote
  publication is limited to the named main and CUDA repositories, with public
  base/CUDA binaries and required corresponding source. Final validation and
  privacy checks remain required.
- No claim that a third-party model, name, logo, AGPL-covered component, or
  vendor runtime has granted commercial, redistribution, or trademark rights.

The current open risks and required evidence are tracked in
`docs/LICENSE_AUDIT.md`; the local model/runtime consultation remains in
`docs/PADDLEOCR_VL_SURVEY.md`. Both must be refreshed against the final selected
inputs before a 3.0.0 decision.
