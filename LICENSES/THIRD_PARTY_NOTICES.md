# Third-Party Notices

Windows 分为本体、CUDA 与 PaddleVL 独立组件。最简运行包保留适用许可与版权声明，但不附送源码或内部审计树；完整对应源码和第三方来源材料独立提供。下文 `LICENSES/`、`source/` 及审计报告的相对路径均指完整构建/源码材料，不保证这些材料位于用户运行目录。每个运行包与其材料逐项绑定；BLOCK 仍表示不具备正式公开发行资格，不能因精简而忽略。

The repository has mixed license facts: root `LICENSE` is MIT, root `COPYING`
contains the AGPLv3 text, and `UmiOCR-data/about.json` plus
`COMBINED_DISTRIBUTION.md` declare the fork additions and combined release
`AGPL-3.0-or-later`. Do not collapse those files into a single SPDX assertion.
AGPL 覆盖内容的对应源码和来源指引仍须交付，包括适用的网络交互源码提供义务；对应源码可在运行包旁独立取得，不要求嵌入同一个运行归档。

## Offline Markdown Preview (3.1.2)

The base application now includes the unmodified Qt WebEngine 6.11.2 runtime
from the locked PySide6 wheel, including QtWebEngineProcess and Chromium
resources. Qt/PySide and Chromium third-party obligations remain separate.
`LICENSES/QtWebEngine/manifest.json` binds the exact same-version official
source archive and a read-only collection of 2,170 license/notice/attribution
files in `third-party-notices.zip`. The full source archive is retained under
`source/third_party/qtwebengine-everywhere-src-6.11.2.tar.xz`; this does not claim
that this project rebuilt Qt or Chromium. LGPL/GPL texts are retained here.

The fixed offline preview uses markdown-it 15.0.3 (MIT), DOMPurify 3.4.17
(MPL-2.0 OR Apache-2.0), KaTeX 0.19.1 and its fonts (MIT), and highlight.js
11.12.0 (BSD-3-Clause). `LICENSES/markdown-preview/` retains each original npm
source/distribution archive, license and an input/runtime hash manifest.
No CDN, model download or package lifecycle script is used by the preview.

## PaddleOCR Model Weights

The GPU plugin ships exactly five checked weights:

- PP-LCNet_x1_0_doc_ori_infer
- UVDoc_grid_infer
- PP-LCNet_x1_0_textline_ori_infer
- PP-OCRv6_medium_det_infer
- PP-OCRv6_medium_rec_infer

`model-rights.json` records the PaddlePaddle Hugging Face repository, immutable
revision, Apache-2.0 model-card evidence, local filename, and SHA-256 for each
one. The verifier only marks a model redistributable when its local
`inference.pdiparams` hash matches that official revision. The full Apache-2.0
text is `Apache-2.0.txt`. Preserve PaddlePaddle attribution and any upstream
notice in the record.

`UVDoc_grid_infer` is derived from `UVDoc_infer`: the build transforms
`inference.json` with `build/tools/derive_uvdoc_grid_model.py`; its weight file
is byte-identical to the recorded upstream artifact. The modification notice in
`model-rights.json` must remain with that directory.

These records concern model weights. They do not rely on the PaddleOCR Python
package license as evidence for the weights.

## NVIDIA CUDA And cuDNN

CUDA and cuDNN are proprietary SDK components, not OSS dependencies.
`cuda-redistributable.json` inventories every packaged CUDA binary with its
SHA-256 and compares it against the CUDA Toolkit EULA Attachment A. A file not
listed there is not approved for public redistribution.

The Attachment A evidence is retained as
`LICENSES/evidence/nvidia/cuda-toolkit-eula-2026-08-07.html` (SHA-256
`6180cc2a02db890cf87ba52f078b7a222b04dcb3c2650865763d4f32ad663a5c`). It is a
current NVIDIA EULA HTML snapshot accessed on 2026-08-07; the page does not
identify a CUDA-release-specific revision. The manifest records the applicable
CUDA 12.6 runtime and each exact filename-to-Attachment-A match.

`cudnn-redistributable.json` inventories each cuDNN runtime DLL and records
the cuDNN SLA/Supplement evidence, including its distribution requirements and
the older license text shipped by the wheel. The current SLA snapshot is
`LICENSES/evidence/nvidia/cudnn-sla-2026-08-09.html` (SHA-256
`a8a92467aa1dc30f3b18eaee84b381169086841453ace5c4fa17ded31e9d7752`). The
release record proves the package contains only the permitted runtime `.dll`
files, the Umi-OCR application supplies material additional functionality,
the worker alone accesses the private DLL directories, and NVIDIA notices are
preserved.

The CUDA/cuDNN and AGPL boundary is separately recorded in
`agpl-integration.json`. The host adapter now starts `worker.py` as an
independent process and exchanges only JSON-lines path/base64 requests and
JSON OCR results. The host manifest declares no vendor or DLL search paths;
only the worker loads Paddle/OpenCV/CUDA/cuDNN. Dynamic loading and NVIDIA
redistribution permission are still checked independently; no system-library
claim or linking exception is added.

## OpenCV And FFmpeg

The packaged `opencv-contrib-python` version is 4.10.0.84, so the OpenCV
component license is Apache-2.0. That does not replace notices for its bundled
third-party libraries. Release builders remove the optional
`opencv_videoio_ffmpeg*.dll` video-I/O backend from both package types; the
OCR paths do not use OpenCV video I/O. `ffmpeg-build.json` reports
`NOT_INCLUDED` only when no such DLL is present.

`opencv-artifact.json` records the actual `cv2.pyd`, OpenCV license files, and
the FFmpeg backend field when present. Its all-package third-party notice inventory is:
FFmpeg; libwebp and libwebpmux; Vulkan headers; libjpeg-turbo; libspng; QUIRC;
Flatbuffers; Protobuf; OpenJPEG; TIFF; and OpenEXR. The notice retains
Linux/macOS-specific entries, but this Windows artifact does not assert those
entries as Windows payload components.

If a future archive includes that backend, the verifier rejects `--enable-gpl`
and `--enable-nonfree`, and requires the exact source archive, build
inputs/modifications, and a relinkable LGPL closure. An OpenCV Apache notice
is not a substitute. `LGPL-2.1.txt` remains in the archive.

## MPL-2.0 Files

`mpl-components.json` identifies the actual MPL-covered material and ties it
to source archives that are hashed in the release tree:

- certifi 2026.6.17: `certifi/cacert.pem`
- tqdm 4.68.4: the bundled `LICENCE`
- validate-pyproject files vendored by setuptools 83.0.0, identified by its
  `setuptools/config/_validate_pyproject/NOTICE`

MPL is file-level copyleft. `source/third_party/` contains the matching
certifi, tqdm, setuptools, and validate-pyproject source archives. The
verifier checks that the released files match their source form. For the
vendored validate-pyproject 0.25 files, `setuptools` 83.0.0 is the exact
shipped source form; `error_reporting.py` differs from upstream only by its
recorded import of setuptools' vendored `fastjsonschema_exceptions`. Recipients
can obtain the MPL-covered source form from those source archives, and the
`NOTICE` remains with the files.

## CPU And Document Plugins

The public 3.0.0 release contains only the base application and the CUDA OCR
plugin. Neither product includes a CPU OCR plugin, PaddleOCR-VL plugin, GGUF,
mmproj, or VLM runtime. Their artifact-specific gates are `NOT_INCLUDED`.
This release makes no redistribution claim for those excluded plugins or models.

CPU and PaddleOCR-VL are separate paid options. Payment does not waive any
applicable license, notice, or corresponding-source obligation for separately
distributed binaries. Their availability does not restrict third-party plugin
development, installation, authorship, or source origin.

`aistudio-sdk` remains excluded from the GPU vendor closure because no reviewed
redistribution evidence is recorded for it.
