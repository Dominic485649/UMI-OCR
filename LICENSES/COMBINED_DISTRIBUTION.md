# Combined Distribution Licensing

This repository preserves the original Umi-OCR MIT license text in
[`LICENSE`](../LICENSE) without modification, including the copyright notice
for hiroi-sora. The original Umi-OCR portions received from that upstream
project continue to be available under that MIT grant.

This fork's added files and modifications are licensed under the GNU Affero
General Public License, version 3 or any later version. The complete license
text is in [`COPYING`](../COPYING).

The Windows release is a combined work that includes PyMuPDF. PyMuPDF 1.28.0
is supplied under AGPL-3.0 or an Artifex commercial license; this fork does
not use an Artifex commercial license. Therefore the complete combined release
is distributed under AGPL-3.0-or-later. Its PyMuPDF licensing notice is kept
verbatim in [`PyMuPDF-AGPL-3.0.txt`](PyMuPDF-AGPL-3.0.txt).

The base release archive includes the following at its root:

- `COPYING`, the full AGPL-3.0 text.
- `LICENSE`, the original MIT license and hiroi-sora attribution.
- `LICENSES/`, including this explanation, the PyMuPDF notice, and third-party
  notices.
- `source/`, a corresponding-source mirror containing the source files, build
  scripts, dependency locks, and these license files used for the release. Its
  `third_party/` directory also contains the locked PyMuPDF source distribution
  used by the combined release.

The CUDA install overlay carries its complete license and corresponding-source
bundle under `LICENSES/plugins/win32_PaddleOCRv6_CUDA/`, including `COPYING`,
`LICENSE`, `LICENSES/`, `source/`, and the source-snapshot files. Only the runtime
payload overlays `UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/`. This prevents
plugin installation from replacing the host's own notices or source provenance.

Charging for source delivery, build artifacts, updates, or support is allowed.
Those commercial terms must not remove or restrict any recipient's AGPL rights
to run, copy, modify, or redistribute the covered work.

The CUDA/cuDNN GPU OCR plugin is a separate worker-based aggregate: the
AGPL-covered host communicates with `worker.py` using simple JSON-lines IPC and
does not load the NVIDIA SDK into its address space. The worker's proprietary
runtime and its own vendor manifest remain subject to the NVIDIA agreements;
this note does not claim that CUDA or cuDNN is AGPL-covered or a system library.
