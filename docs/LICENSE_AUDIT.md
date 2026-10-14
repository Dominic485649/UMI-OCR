# 许可证与模型权利审计报告

> **3.0.0 当前审计状态：** 本次公开交付范围仅为主程序与 CUDA 插件，CPU 与 PaddleOCR-VL 不纳入上传清单。主项目为 `Dominic485649/UMI-OCR`，CUDA 插件公开仓库为 `Dominic485649/UMI-OCR_plugins`；两者均已创建。2026-10-14 对当前 base/CUDA 产物的严格证据门禁通过：实际携带的运行时、模型、CUDA/cuDNN、OpenCV、MPL 源码和进程边界为 PASS，未携带的 CPU、VL 与 FFmpeg 为 NOT_INCLUDED，CUDA 实测证据绑定当前源码与运行时哈希。最终归档仍需通过解压、安装和递归隐私检查。每个最终产品内的 `LICENSES/RELEASE_EVIDENCE.json` 与对应源码材料是该产品的证据，详见 [3.0.0 发布审查](RELEASE_3.0.0_REVIEW.md)。原 MIT 版权及第三方声明保留，不构成新的权利授权。下文旧元数据和旧产物记录属于历史审计，不能代替本次产物验证。

> **2026-08-09 supersession notice:** the historical findings below describe
> the pre-closure audit and are retained for provenance. They are not the
> current release decision. The historical artifact-driven result for that release is
> `build/staging/release-2.7-final-clean-20260809/LICENSES/RELEASE_EVIDENCE.md`
> (and the extracted archive copy): `runtime_vendor`, `paddle_models`,
> `cuda`, `cudnn`, `opencv`, `mpl`, `agpl_nvidia`, `cpu_ocr`, and
> `gpu_ocr_e2e` are **PASS**; `ffmpeg` and `document_models` are
> **NOT_INCLUDED**. The final strict public-release gate returned 0. The
> cuDNN files are the inventoried runtime DLLs covered by the current NVIDIA
> SLA snapshot, and the AGPL/NVIDIA boundary is implemented as a separate
> JSON-lines worker process; no system-library or automatic dynamic-linking
> exception is claimed. The five PaddlePaddle model records are independently
> locked to official Apache-2.0 model-card evidence.

> 2026-08-02 update: local 2.7.0 v5 base/GPU and combined staging passed the
> full functional suites. `aistudio-sdk` was removed from the GPU lock/vendor
> by a version-locked offline PaddleX guard; this closes only that local
> closure item and grants no license to reintroduce or redistribute it.

- **审计对象**：Umi-OCR fork（本仓库）2.6.0 产物闭包，面向 2.7.0 预发布与 3.0.0 收费计划
- **审计日期**：2026-08-02
- **审计范围**：`LICENSE` / `COPYING` / `LICENSES/`、`build/requirements-base-windows.lock`（15 项）、`build/requirements-gpu-plugin-windows-cu126.lock`（73 项，明确排除未授权的 `aistudio-sdk`）、`build/sources-windows-cu126.lock.json` 的 5 个模型、Qt/PySide6 LGPL 义务、名称与商标
- **一手证据来源**：`build/staging/release-2.7-base-v5-20260802/UmiOCR-data/site-packages/*.dist-info/METADATA`（基础包 15 项）与 `build/staging/release-2.7-gpu-v5-20260802/UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/vendor/*.dist-info/METADATA`（GPU 73 项）。**88 条归档锁定条目全部有本地 dist-info 元数据覆盖，无缺口；GPU 的 5 项重复闭包按插件独立携带。**
- **本报告不构成法律意见。** 所有"未确认"项均需在发布前取得书面/可归档的一手证据。

> **重要声明**：本报告中没有任何一项被表述为"已获得授权""已确认可商用"。凡未取得一手证据的，一律标注"未确认"并列出所需证据。

---

## 一、摘要

### 1.1 目前可以做什么（基于已核实的一手证据）

| 事项 | 依据 |
| --- | --- |
| 保留上游 MIT 与 hiroi-sora 署名，在此基础上以 AGPL-3.0-or-later 发布 fork 新增代码 | 上游 [`LICENSE`](https://github.com/hiroi-sora/Umi-OCR/blob/main/LICENSE) 为 MIT，`Copyright (c) 2023 hiroi-sora`；MIT 允许再许可与派生 |
| 对**源码交付、构建产物、更新、技术支持**收费 | AGPL-3.0 §4 明确允许收费；`LICENSES/COMBINED_DISTRIBUTION.md` 已正确表述此点 |
| 分发绝大多数宽松许可依赖（MIT / BSD / Apache-2.0 / PSF / 0BSD），条件是保留其许可证与声明 | 各包 dist-info METADATA（见第二节表格） |

### 1.2 目前不能做什么（已核实存在阻碍的事项）

1. **不得公开分发 GPU 插件归档**——5 个模型权重缺乏再分发许可证据（见第四节），NVIDIA cuDNN/CUDA SLA 与 AGPL 声明存在正面冲突（见 §2.4）。v5 已从运行时闭包移除无授权的 `aistudio-sdk 0.3.8`，但这不解决其它阻塞项。
2. **不得声称"已获得模型授权"或"模型可商用"**——证据不足（见第四节）。当前 `build/windows/Build-GpuPlugin.ps1` 生成的 `NOTICE.md` 已自带同样的禁令，本审计确认该禁令仍然有效，**不得解除**。
3. **不得把 `LICENSES/THIRD_PARTY_NOTICES.md` 当作已完成的逐发行版第三方声明**——它已补充 PyMuPDF、Qt/copyleft 与 OpenCV/FFmpeg 的一般说明，但仍未逐项列出其余锁定发行版及其完整许可证/源码入口（见 §5.3）。
4. **不得在任何文案中把 Umi-OCR 名称/图标表述为本项目的权利**——名称与图标属于上游（见第六节）。

### 1.3 待确认项清单（汇总）

| # | 待确认项 | 需要的证据 | 章节 |
| --- | --- | --- | --- |
| U-01 | `aistudio-sdk 0.3.8` 的许可证（若未来重新引入） | 上游发布方书面许可，或 PyPI/仓库中的 LICENSE 文件；当前 v5 不携带该包 | §2.3 |
| U-02 | 5 个 `.tar` 模型权重的再分发许可 | bcebos 直链对应的授权页面，或 PaddlePaddle 官方对**该 tar 制品**的书面许可 | 四 |
| U-03 | NVIDIA cuDNN 9.x 的 `cudnn*64_9.dll` 是否在可分发清单内 | NVIDIA 书面确认，或与所装 wheel 版本对应的 SLA 文本 | §2.4 |
| U-04 | NVIDIA SLA §2.5 与 AGPL-3.0 组合发行的兼容性 | NVIDIA 书面豁免，或将 CUDA/cuDNN 移出 AGPL 组合作品边界的架构方案 | §2.4 |
| U-05 | PySide6 LGPL-3.0 重链接信息是否已随归档提供 | 归档内实际存在的 LGPL 文本 + 重链接说明 + 未修改 Qt 的声明 | 五 |
| U-06 | `opencv-contrib-python` 内置 FFmpeg DLL 的 LGPL 义务 | FFmpeg 对应源码位置与版本、LGPL 文本 | §2.2 |
| U-07 | `python-bidi 0.6.11` 具体是 LGPL-2.1 还是 LGPL-3.0 | 上游仓库 COPYING/COPYING.LESSER 版本号 | §2.3 |
| U-08 | UVDoc 权重是原作者 MIT 权重转换还是百度重训 | PaddleX 训练/转换说明 | 四 |
| U-09 | 3.0.0 使用"umiocr 重制版"名称的风险 | 上游对名称使用的书面表态 | 六 |

---

## 二、逐项组件表格

> **证据方法说明**：许可证字段取自**实际装入产物的 wheel 自带 `.dist-info/METADATA`**（一手证据，等同该版本在 PyPI 上发布的元数据）。证据 URL 给出对应 PyPI 项目页以便复核。凡 METADATA 与上游仓库口径不一致或字段缺失的，单独在"未确认点"列注明。

### 2.1 基础包闭包（`build/requirements-base-windows.lock`，15 项）

| 组件 | 版本 | 许可证 | 证据来源(URL) | 再分发是否明确允许 | 风险 | 未确认点 |
| --- | --- | --- | --- | --- | --- | --- |
| bottle | 0.13.4 | MIT | [pypi](https://pypi.org/project/bottle/0.13.4/) | 是 | 低 | — |
| fonttools | 4.63.0 | MIT | [pypi](https://pypi.org/project/fonttools/4.63.0/) | 是 | 低 | 另有 `LICENSE.external`，内含其他条款，未逐条核 |
| imagecodecs | 2026.6.26 | BSD-3-Clause | [pypi](https://pypi.org/project/imagecodecs/2026.6.26/) | 是 | 中 | 该包静态链接大量编解码器（JPEG2000/HEIF 等），其中部分可能涉专利或异构许可，未逐个核 |
| numpy | 2.3.5 | BSD-3-Clause | [pypi](https://pypi.org/project/numpy/2.3.5/) | 是 | 低 | METADATA `License` 字段是版权行而非 SPDX，凭 classifier 判定 |
| opencv-contrib-python | 4.10.0.84 | Apache-2.0（wheel 层 MIT） | [pypi](https://pypi.org/project/opencv-contrib-python/4.10.0.84/) | 是（主体） | **高** | 见 §2.2：内含 LGPL 的 FFmpeg DLL；`LICENSE-3RD-PARTY.txt` 含两处 LGPL |
| pillow | 12.3.0 | MIT-CMU | [pypi](https://pypi.org/project/pillow/12.3.0/) | 是 | 低 | — |
| psutil | 7.2.2 | BSD-3-Clause | [pypi](https://pypi.org/project/psutil/7.2.2/) | 是 | 低 | — |
| **pymupdf** | 1.28.0 | **AGPL-3.0 或 Artifex 商业许可** | [pypi](https://pypi.org/project/pymupdf/1.28.0/) ・ [官方 about](https://pymupdf.readthedocs.io/en/latest/about.html) | 是（选 AGPL 分支） | **高** | 见第三节。选 AGPL 即触发全组合作品 AGPL |
| **pynput** | 1.8.2 | **LGPL-3.0** | [pypi](https://pypi.org/project/pynput/1.8.2/) | 是 | 中 | 纯 Python 包，LGPL 重链接义务形态与 C 库不同；未在 NOTICES 中声明 |
| **pyside6** | 6.11.1 | **LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only** | [pypi](https://pypi.org/project/PySide6/6.11.1/) | 是（选 LGPL 分支） | **高** | 见第五节 |
| **pyside6-addons** | 6.11.1 | 同上 | [pypi](https://pypi.org/project/PySide6-Addons/6.11.1/) | 是 | **高** | 同上 |
| **pyside6-essentials** | 6.11.1 | 同上 | [pypi](https://pypi.org/project/PySide6-Essentials/6.11.1/) | 是 | **高** | 同上 |
| **shiboken6** | 6.11.1 | 同上 | [pypi](https://pypi.org/project/shiboken6/6.11.1/) | 是 | **高** | 同上 |
| six | 1.17.0 | MIT | [pypi](https://pypi.org/project/six/1.17.0/) | 是 | 低 | — |
| zxing-cpp | 3.1.0 | Apache-2.0 | [pypi](https://pypi.org/project/zxing-cpp/3.1.0/) | 是 | 低 | — |

### 2.2 opencv-contrib-python 专项（专利与内嵌 LGPL）

**非自由算法**：opencv-python 官方明确说明非自由算法未被编入 wheel——

> "Non-free algorithms such as SURF are not included in these packages because they are patented / non-free and therefore cannot be distributed as built binaries."
> —— [github.com/opencv/opencv-python](https://github.com/opencv/opencv-python)

SIFT 自 OpenCV 4.3.0 起因专利到期而纳入常规构建。因此 **`OPENCV_ENABLE_NONFREE` 相关的专利风险在本闭包中不成立**，任务书中假设的该风险点经核查**不适用**。

**但发现另一项此前未被记录的问题**：该 wheel 实际附带 FFmpeg 动态库——

```
site-packages/cv2/opencv_videoio_ffmpeg4100_64.dll
```

且其 `LICENSE-3RD-PARTY.txt` 中出现两处 `GNU LESSER GENERAL PUBLIC LICENSE` 段落，以及 FreeType、IJG、zlib 等条款。**FFmpeg 以 LGPL 分发意味着 §5 的重链接与源码义务同样适用于这个 DLL**，而 `LICENSES/THIRD_PARTY_NOTICES.md` 完全未提及。→ 待确认项 **U-06**。

### 2.3 GPU 插件闭包（`build/requirements-gpu-plugin-windows-cu126.lock`，73 项）

**A. 需要特别关注的条目**

| 组件 | 版本 | 许可证 | 证据来源(URL) | 再分发是否明确允许 | 风险 | 未确认点 |
| --- | --- | --- | --- | --- | --- | --- |
| **nvidia-cublas-cu12** | 12.6.4.1 | NVIDIA Proprietary | [pypi](https://pypi.org/project/nvidia-cublas-cu12/12.6.4.1/) | 有条件 | **极高** | **U-03/U-04** |
| **nvidia-cuda-runtime-cu12** | 12.6.77 | NVIDIA Proprietary | [pypi](https://pypi.org/project/nvidia-cuda-runtime-cu12/12.6.77/) | 有条件 | **极高** | 同上 |
| **nvidia-cudnn-cu12** | 9.9.0.52 | NVIDIA Proprietary（cuDNN SLA） | [pypi](https://pypi.org/project/nvidia-cudnn-cu12/9.9.0.52/) ・ [cuDNN EULA](https://docs.nvidia.com/deeplearning/cudnn/latest/reference/eula.html) | **未确认** | **极高** | 同上，另见下文 |
| **nvidia-cufft-cu12** | 11.3.0.4 | NVIDIA Proprietary | [pypi](https://pypi.org/project/nvidia-cufft-cu12/11.3.0.4/) | 有条件 | **极高** | 同上 |
| **nvidia-curand-cu12** | 10.3.7.77 | NVIDIA Proprietary | [pypi](https://pypi.org/project/nvidia-curand-cu12/10.3.7.77/) | 有条件 | **极高** | 同上 |
| **nvidia-cusolver-cu12** | 11.7.1.2 | NVIDIA Proprietary | [pypi](https://pypi.org/project/nvidia-cusolver-cu12/11.7.1.2/) | 有条件 | **极高** | 同上 |
| **nvidia-cusparse-cu12** | 12.5.4.2 | NVIDIA Proprietary | [pypi](https://pypi.org/project/nvidia-cusparse-cu12/12.5.4.2/) | 有条件 | **极高** | 同上 |
| **nvidia-nvjitlink-cu12** | 12.6.85 | NVIDIA Proprietary | [pypi](https://pypi.org/project/nvidia-nvjitlink-cu12/12.6.85/) | 有条件 | **极高** | 同上 |
| **crc32c** | 2.8 | **LGPL-2.1-or-later** | [pypi](https://pypi.org/project/crc32c/2.8/) | 是 | 中 | copyleft，未在 NOTICES 声明 |
| **python-bidi** | 0.6.11 | **LGPL（版本不明）** | [pypi](https://pypi.org/project/python-bidi/0.6.11/) | 是 | 中 | **U-07**。METADATA 仅有泛化 classifier，无 SPDX；同时附 `COPYING` 与 `COPYING.LESSER` |
| certifi | 2026.6.17 | **MPL-2.0** | [pypi](https://pypi.org/project/certifi/2026.6.17/) | 是 | 中 | 弱 copyleft，文件级源码提供义务 |
| tqdm | 4.68.4 | **MPL-2.0 AND MIT** | [pypi](https://pypi.org/project/tqdm/4.68.4/) | 是 | 中 | 同上 |
| ujson | 5.13.0 | BSD-3-Clause AND TCL | [pypi](https://pypi.org/project/ujson/5.13.0/) | 是 | 低 | TCL 许可条款未逐条核 |
| pypdfium2 | 5.11.0 | BSD-3-Clause, Apache-2.0, 依赖许可 | [pypi](https://pypi.org/project/pypdfium2/5.11.0/) | 是 | 中 | 内嵌 PDFium 及其依赖树，未逐层核 |
| pycryptodome | 3.23.0 | BSD + Public Domain | [pypi](https://pypi.org/project/pycryptodome/3.23.0/) | 是 | 低 | 加密出口管制未评估 |
| paddlepaddle-gpu | 3.3.1 | Apache-2.0 | [pypi](https://pypi.org/project/paddlepaddle-gpu/3.3.1/) | 是 | 中 | 通过 `--extra-index-url paddlepaddle.org.cn` 取得，非 PyPI 源；wheel 内嵌第三方库未逐个核 |

**B. 其余宽松许可条目（均为一手 METADATA 读取，再分发允许，风险低）**

| 组件 | 版本 | 许可证 | 组件 | 版本 | 许可证 |
| --- | --- | --- | --- | --- | --- |
| aiohappyeyeballs | 2.7.1 | PSF-2.0 | packaging | 26.2 | Apache-2.0 OR BSD-2-Clause |
| aiohttp | 3.14.1 | Apache-2.0 AND MIT | paddleocr | 3.7.0 | Apache-2.0 |
| aiosignal | 1.4.0 | Apache-2.0 | paddlex | 3.7.2 | Apache-2.0 |
| annotated-types | 0.7.0 | MIT | pandas | 3.0.3 | BSD-3-Clause |
| anyio | 4.14.2 | MIT | prettytable | 3.18.0 | BSD-3-Clause |
| attrs | 26.1.0 | MIT | propcache | 0.5.2 | Apache-2.0 |
| bce-python-sdk | 0.9.72 | Apache-2.0 | protobuf | 7.35.1 | BSD-3-Clause |
| chardet | 7.4.3 | 0BSD | py-cpuinfo | 9.0.0 | MIT |
| charset-normalizer | 3.4.9 | MIT | pyclipper | 1.4.0 | MIT |
| click | 8.4.2 | BSD-3-Clause | pydantic | 2.13.4 | MIT |
| colorama | 0.4.6 | BSD | pydantic-core | 2.46.4 | MIT |
| colorlog | 6.10.1 | MIT | python-dateutil | 2.9.0.post0 | Apache-2.0 / BSD 双许可 |
| filelock | 3.29.7 | MIT | pyyaml | 6.0.2 | MIT |
| frozenlist | 1.8.0 | Apache-2.0 | requests | 2.34.2 | Apache-2.0 |
| fsspec | 2026.6.0 | BSD-3-Clause | ruamel.yaml | 0.19.1 | MIT |
| future | 1.0.0 | MIT | safetensors | 0.8.0 | Apache-2.0 |
| h11 | 0.16.0 | MIT | setuptools | 83.0.0 | MIT |
| hf-xet | 1.5.1 | Apache-2.0 | shapely | 2.1.2 | BSD-3-Clause |
| httpcore | 1.0.9 | BSD-3-Clause | typing-extensions | 4.16.0 | PSF-2.0 |
| httpx | 0.28.1 | BSD-3-Clause | typing-inspection | 0.4.2 | MIT |
| huggingface-hub | 1.23.0 | Apache-2.0 | tzdata | 2026.3 | Apache-2.0 |
| idna | 3.18 | BSD-3-Clause | urllib3 | 2.7.0 | MIT |
| imagesize | 2.0.0 | MIT | wcwidth | 0.8.2 | MIT |
| modelscope | 1.38.1 | Apache-2.0 | yarl | 1.24.2 | Apache-2.0 |
| modelscope-hub | 0.1.7 | Apache-2.0 | multidict | 6.7.1 | Apache-2.0 |
| networkx | 3.6.1 | BSD-3-Clause | opt-einsum | 3.3.0 | MIT |

（`numpy`、`opencv-contrib-python`、`pillow`、`psutil`、`six`、`bottle`、`fonttools`、`imagecodecs`、`pymupdf`、`pynput`、`pyside6*`、`shiboken6`、`zxing-cpp` 在两个闭包间共享，见 §2.1。）

### 2.4 NVIDIA 组件专项：与 AGPL 的正面冲突

从**实际装入产物的 wheel 自带许可证文本**读取（`nvidia_cudnn_cu12-9.9.0.52.dist-info/licenses/License.txt`，以及 `nvidia_cublas_cu12-12.6.4.1.dist-info/License.txt`）：

**(a) 分发授权是有条件的**，条件包括：

> "(i) Your application must have material additional functionality, beyond the included portions of the SDK.
> (ii) The distributable portions of the SDK shall only be accessed by your application."

**(b) 存在明确禁止开源化的条款（§2.5）**：

> "You may not use the SDK in any manner that would cause it to become subject to an open source software license. As examples, licenses that require as a condition of use, modification, and/or distribution that the SDK be (i) disclosed or distributed in source code form; (ii) licensed for the purpose of making derivative works; or (iii) redistributable at no charge."

同一条款在 NVIDIA [现行 cuDNN EULA](https://docs.nvidia.com/deeplearning/cudnn/latest/reference/eula.html) 中依然存在。

> **冲突分析**：`LICENSES/COMBINED_DISTRIBUTION.md` 声明"完整的组合发行按 AGPL-3.0-or-later 分发"。AGPL-3.0 恰好要求以源码形式披露、允许制作派生作品、且不得限制免费再分发——这正是 NVIDIA §2.5 逐条列举的禁止情形。若 GPU 插件归档被认定为与 AGPL 本体构成**同一个组合作品**，则两套条款无法同时满足。
> **注**：若 CUDA/cuDNN 仅作为**独立聚合（mere aggregation）**的系统库随附、且不与 AGPL 代码构成单一作品，冲突可能不成立。该边界认定**未确认**，需法律意见。→ **U-04**

**(c) cuDNN 可分发文件清单与实际产物不匹配**：

wheel 内自带的 SLA 文本（版本标注 `v. January 28, 2020`）第 2 节写的是：

> "The following portions of the SDK are distributable under the Agreement: the runtime files .so and .h, cudnn64_7.dll, and cudnn.lib."

而产物实际装入的是 **8 个 `*64_9.dll`**：`cudnn64_9.dll`、`cudnn_adv64_9.dll`、`cudnn_cnn64_9.dll`、`cudnn_engines_precompiled64_9.dll`、`cudnn_engines_runtime_compiled64_9.dll`、`cudnn_graph64_9.dll`、`cudnn_heuristic64_9.dll`、`cudnn_ops64_9.dll`。该文本中 `cudnn64_9` 出现次数为 **0**。

NVIDIA 现行在线 EULA 已把措辞放宽为 "the runtime files .so and .dll"，字面上可覆盖 `*64_9.dll`；但**随产物分发的那份文本并不是这一版**。以哪一版为准**未确认**。→ **U-03**

---

## 三、AGPL-3.0 组合作品分析（本体 + PyMuPDF）

### 3.1 现状认定

- 上游 Umi-OCR 为 MIT（[证据](https://github.com/hiroi-sora/Umi-OCR/blob/main/LICENSE)），MIT 允许在派生作品上叠加更严格的许可。
- 本 fork 新增/修改部分声明为 AGPL-3.0-or-later（`COPYING`，`UmiOCR-data/about.json` 中 `license.type` 亦为 `AGPL-3.0-or-later`）。
- PyMuPDF 1.28.0 为 **AGPL-3.0 或 Artifex 商业许可**双授权（wheel METADATA 原文：`Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License`；官方说明见 [pymupdf about](https://pymupdf.readthedocs.io/en/latest/about.html)）。本项目未采购 Artifex 商业许可，故落入 AGPL 分支。
- 结论：**Windows 发行包整体处于 AGPL-3.0-or-later 之下**。这与 `LICENSES/COMBINED_DISTRIBUTION.md` 的现有表述一致。

### 3.2 对"收费插件 / 支持服务"的具体含义

| 商业模式 | AGPL-3.0 下的处理 | 依据 |
| --- | --- | --- |
| 对**构建产物**收费 | 允许 | AGPL-3.0 §4："You may charge any price or no price for each copy that you convey" |
| 对**源码交付**收费 | 允许，但价格不得超过合理的物理交付成本，且若已按 §6 提供二进制则须以同等便利提供源码 | AGPL-3.0 §6 |
| 对**技术支持 / 更新订阅**收费 | 允许 | AGPL-3.0 §4 允许为担保或支持另行收费 |
| **闭源**收费插件 | **不可行**，若该插件与 AGPL 本体构成组合作品 | AGPL-3.0 §5/§13 |
| 收费但**限制接收者再分发** | **不可行** | AGPL-3.0 §10："You may not impose any further restrictions" |
| 提供**网络服务**（SaaS / HTTP API） | 必须向**所有网络用户**提供完整对应源码 | AGPL-3.0 §13。本项目自带 HTTP 服务（`docs/http/`），该条款**直接适用** |

> **对 3.0.0 收费计划的关键提示**：AGPL 不阻止收费，但阻止**独占**。任何一位付费用户在拿到二进制后，都有权把完整对应源码免费再分发给所有人。因此"收费 + 闭源插件"的组合在当前 AGPL 边界下不成立；可行的收费形态是**服务、支持、托管、预构建产物与更新通道**。
> 若要摆脱 AGPL 约束，唯一的合规路径是**采购 Artifex 商业许可以替换 PyMuPDF 的 AGPL 分支**，并同时解决 PySide6（Qt 商业许可）与本 fork 自身的许可声明。该路径的成本与可行性**未确认**。

### 3.3 §13 网络条款的额外暴露

本项目内置 HTTP 服务（`bottle` + `docs/http/`）。一旦用户通过网络与之交互，AGPL §13 要求向该用户提供修改版的完整对应源码。**这一义务不因收费而免除，也不因用户是付费方而免除。**

---

## 四、模型权重再分发结论

### 4.1 一手核查结果

对 `build/cache/models/` 下 5 个已缓存 `.tar` 逐个解包检视（未新增下载）：

| 模型 | 大小 | tar 内是否含许可证文本 | 内容清单 |
| --- | --- | --- | --- |
| `PP-LCNet_x1_0_doc_ori_infer.tar` | 6.6 MiB | **有**（`README.md` front-matter：`license: Apache License 2.0`） | README.md, config.json, inference.json/yml/pdiparams, .msc, .mv |
| `PP-LCNet_x1_0_textline_ori_infer.tar` | 6.6 MiB | **无** | inference.json/yml/pdiparams, 2 个 demo 文件 |
| `PP-OCRv6_medium_det_infer.tar` | 59.4 MiB | **无** | inference.json/yml/pdiparams |
| `PP-OCRv6_medium_rec_infer.tar` | 73.3 MiB | **无** | inference.json/yml/pdiparams |
| `UVDoc_infer.tar` | 30.8 MiB | **无** | inference.json/yml/pdiparams |

对全部解包内容执行 `licen[cs]e|copyright|apache|BSD|GPL|non-commercial` 全文检索，**仅 1 个 README 命中**；其余 4 个 tar 中的命中全部来自 `.pdiparams` 二进制的偶然字节匹配，非许可证文本。

### 4.2 来源与发布方

- 下载基址：`https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/`（`build/sources-windows-cu126.lock.json`）
- 这是一个**百度对象存储（BOS）裸桶直链**，只返回二进制，**没有任何授权页面、许可证文件或条款声明**。
- 发布方推定为 PaddlePaddle / PaddleX 团队，但**该 URL 本身不承载任何许可证声明**。

### 4.3 旁证（不等于对本制品的授权）

| 旁证 | 内容 | 局限 |
| --- | --- | --- |
| [PaddleOCR 仓库 LICENSE](https://raw.githubusercontent.com/PaddlePaddle/PaddleOCR/main/LICENSE) | Apache-2.0 | 经核查该文本**完全未提及模型或权重**，仅覆盖代码 |
| [HF: PaddlePaddle/PP-OCRv6_medium_det_safetensors](https://huggingface.co/PaddlePaddle/PP-OCRv6_medium_det_safetensors) | `license: apache-2.0`，owner 为 PaddlePaddle | 这是 **safetensors 变体**，与 bcebos 上的 `.tar` 是**不同制品**，哈希不同 |
| [HF: PaddlePaddle/UVDoc](https://huggingface.co/PaddlePaddle/UVDoc) | `license: apache-2.0`，owner 为 PaddlePaddle | 同上；且未提及原作者 |
| [github.com/tanguymagne/UVDoc](https://github.com/tanguymagne/UVDoc) | UVDoc 原始实现与预训练权重为 **MIT** | 无法确认 PaddleX 版权重是原权重转换还是重训 → **U-08** |
| tar 内 `PP-LCNet_x1_0_doc_ori/README.md` | `license: Apache License 2.0` | 仅覆盖 5 个中的 1 个 |

### 4.4 结论

> **证据不足，不得公开分发。**
>
> 5 个模型中，**只有 `PP-LCNet_x1_0_doc_ori` 一项**在制品内自带许可证声明（Apache-2.0）。其余 4 项——包括决定性的 `PP-OCRv6_medium_det` 与 `PP-OCRv6_medium_rec`——**所分发的 `.tar` 制品本身不携带任何许可证文本，其下载 URL 也不承载任何授权声明**。
>
> HuggingFace 上同名模型标注 apache-2.0 是**有力旁证但不是对本制品的授权**：那是不同的制品（safetensors vs. paddle inference tar），哈希不同，且 `sources-windows-cu126.lock.json` 锁定的是 bcebos 的 tar。
>
> **在取得下列任一证据之前，GPU 插件归档不得公开分发，也不得在任何文案中声称模型已获授权：**
> 1. bcebos 模型基址对应的官方授权页面，明确覆盖这 5 个 `.tar` 文件名；**或**
> 2. PaddlePaddle 官方对这 5 个具体制品（附 SHA-256）再分发权的书面确认；**或**
> 3. 改为从**自带 LICENSE 文件**的来源（如 HuggingFace `PaddlePaddle/*` 仓库）获取模型，并把 LICENSE 一并打入归档——同时更新 `sources-windows-cu126.lock.json` 的 URL 与哈希。

**现状确认**：`build/windows/Build-GpuPlugin.ps1` 生成的 `NOTICE.md` 已包含"本归档中的模型权重尚未完成再分发许可审计……不得公开分发本归档"的禁令。**本审计确认该禁令应当保留，直到上述证据之一到位。**

---

## 五、Qt / PySide6 的 LGPL 义务（7z 分发形态）

### 5.1 许可证事实

PySide6 / PySide6-Addons / PySide6-Essentials / shiboken6 6.11.1 的 METADATA 均为：
`LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`，并附 `LicenseRef-Qt-Commercial.txt`。本项目未采购 Qt 商业许可，落入 **LGPL-3.0** 分支。

产物以**动态链接**方式使用 Qt（`site-packages/PySide6/Qt6Core.dll`、`Qt6Gui.dll`、`Qt6Quick.dll` 等 27+ 个 DLL 独立存在，未静态链接）——这是 LGPL 下相对有利的形态。

### 5.2 "打包成 7z 分发"具体要求什么

依据 [Qt 官方 LGPL 义务说明](https://www.qt.io/licensing/open-source-lgpl-obligations)，逐条落到 7z 归档形态：

| # | 义务 | 在 7z 归档中的具体做法 | 当前状态 |
| --- | --- | --- | --- |
| 1 | **提供 LGPL-3.0 许可证全文** | 归档内放入 `LICENSES/LGPL-3.0.txt`（LGPL-3.0 需连同 GPL-3.0 全文一起给） | **缺失**——`LICENSES/` 下只有 PyMuPDF 一份，无 LGPL 文本 |
| 2 | **显著声明使用了 LGPL 库**，不得隐瞒 | 在 `NOTICE.md` 与"关于"界面列出 Qt/PySide6 及其 LGPL 状态 | **缺失**——`THIRD_PARTY_NOTICES.md` 未提 PySide6 |
| 3 | **保证用户可替换 Qt 并重新链接** | 动态链接已满足技术前提；还须提供"如何用自己编译的 Qt 替换归档内 DLL"的说明 | **缺失** → **U-05** |
| 4 | **提供 Qt 的完整对应源码或书面获取指引**，含一切修改 | 若未修改 Qt，可给出精确版本号 + 官方源码下载地址；若修改过必须给出修改后源码 | **缺失**——`sources-windows-cu126.lock.json` 的 `thirdPartySources` 只锁了 PyMuPDF，未锁 Qt 源码 |
| 5 | **"sufficient installation information"**，LGPLv3 禁止封闭设备 | 7z 解压即可替换 DLL，天然满足 | 满足 |
| 6 | **不得限制接收者的 LGPL 权利**；分发渠道条款不得冲突 | 收费/授权文案中不得含"禁止再分发/禁止逆向"字样 | 需在 3.0.0 商业条款中检查 |

> Qt 官方原文（关于第 3 项）："The user is allowed to change and re-link the library used in the application or device – including reverse engineering."

### 5.3 与现有 `THIRD_PARTY_NOTICES.md` 的差距

现文件只覆盖了 PyMuPDF 一项，并声明"其余组件保留各自声明"。这对宽松许可可能勉强够用，但对**LGPL 组件（PySide6/shiboken6、pynput、crc32c、python-bidi、opencv 内嵌 FFmpeg）与 MPL 组件（certifi、tqdm）而言不够**——这些许可证要求**主动的、显著的**声明与源码获取途径。

另发现一处**文档与构建不一致**：`THIRD_PARTY_NOTICES.md` 称"锁定清单为 `build/requirements-windows-cu126.lock`"，而实际构建使用的是拆分后的 `requirements-base-windows.lock` 与 `requirements-gpu-plugin-windows-cu126.lock`。

### 5.4 GPU 插件归档对应源码镜像（待实际产物验证）

`build/windows/Build-Release.ps1` 通过 `Copy-ReleaseSource` 生成 `source/` 对应源码镜像，`Audit-Package.ps1` 也校验 `source\...` 一系列路径。

审计时，**`build/windows/Build-GpuPlugin.ps1` 中不存在任何 `source/` 镜像逻辑**（当时确认无 `Copy-ReleaseSource`、无 `git ls-files`），`Audit-Package.ps1` 的 plugin 分支也只校验 `COPYING`、`LICENSE`、`NOTICE.md` 三个文件。

当前工作树已补入 GPU 插件的最小对应源码镜像和审计规则：归档应随附插件
适配器、构建脚本、依赖锁和许可证。该修补尚未经过一次干净 GPU 构建、解压和
审计，因此 **B-08 仍为未关闭项**；更不能据此推断第三方 vendor 与模型的全部
来源/许可问题已经解决。

而该归档生成的 `NOTICE.md` 明确声明插件适配器源码为 **AGPL-3.0-or-later**。AGPL §6 要求二进制分发时**随附对应源码或附具书面提供承诺**。当前归档二者皆无（仅依赖 GitHub 上有源码，这不构成 §6 意义上的"书面承诺"）。

---

## 六、商标与命名风险

**以下仅陈述已核实的事实与可识别的风险，不作法律结论，不判断"可以"或"不可以"。**

### 6.1 事实

1. 上游项目 `hiroi-sora/Umi-OCR` 以 **MIT** 许可发布，版权行为 `Copyright (c) 2023 hiroi-sora`（[证据](https://github.com/hiroi-sora/Umi-OCR/blob/main/LICENSE)）。
2. **MIT 许可证文本中不包含任何商标授权条款。** 已核对本仓库 `LICENSE` 全文：授予的是"use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software"，**软件**的权利，未提及名称、标识或商标。
3. 上游 README 使用 "Umi-OCR" 名称与图标（`https://tupian.li/images/2022/10/27/icon---256.png`），图标为上游资产。
4. 历史审计时 `UmiOCR-data/about.json` 的作者和主页仍属于上游。3.0.0 准备稿保留 `Umi-OCR` 名称，作者并列为 Dominic485649 与 hiroi-sora，主页改为本分支仓库；这一导航修订不表示获得上游品牌许可或背书。
5. 当前 README 继续声明保留原 Umi-OCR 的 MIT `LICENSE`、hiroi-sora 版权与署名，不以会变化的行号作为长期证据。
6. `build/windows/Build-GpuPlugin.ps1` 生成的 `NOTICE.md` 已含"Umi-OCR 名称与图标属于上游项目 hiroi-sora/Umi-OCR。本插件不主张任何商标权利"。
7. **未找到公开证据**表明 "Umi-OCR" 已在任何司法辖区注册为商标；也**未找到**上游发布过商标使用政策。

### 6.2 3.0.0 命名为"umiocr 重制版"并收费的风险点

| 风险 | 说明 |
| --- | --- |
| 版权许可 ≠ 商标许可 | MIT 授予软件的复制与销售权，**不授予名称使用权**。二者在法律上是分离的。这是事实陈述，不是对本案的结论。 |
| 未注册商标仍可能受保护 | 多数司法辖区对**未注册**标识仍提供一定保护（如中国《反不正当竞争法》对"有一定影响的商品名称"、普通法的 passing off）。是否构成需个案认定。 |
| 混淆可能性 | "umiocr 重制版"包含完整原名，且面向同一用户群、同一功能领域。**收费**这一点会加强"商业性使用"的认定。 |
| 图标 | 图标是独立的**著作权**客体。若沿用上游图标，MIT 覆盖的是仓库内代码资产，需单独确认图标文件是否在 MIT 覆盖范围内。 |
| 缓解方向（仅供参考，非结论） | ① 使用不含原名的独立品牌；② 保留 "based on Umi-OCR by hiroi-sora" 形式的**说明性**署名而非产品名；③ 事先取得上游书面表态 → **U-09** |

---

## 七、发布前必须解决的阻塞项清单

共 **12 项**（P0 阻断 4 项 / P1 高优 5 项 / P2 中优 3 项）。

### P0 —— 阻断 GPU 插件公开分发，不解决不得发布

| # | 阻塞项 | 判定依据 | 解决方式 |
| --- | --- | --- | --- |
| **B-01（v5 本地闭合）** | `aistudio-sdk 0.3.8` 无任何许可证授权 | PyPI JSON 中 license/license_expression/home_page/author 全为 null；wheel 内无 LICENSE 文件；无公开仓库；v5 GPU lock 为 73 项且 vendor 无 `aistudio_sdk*` | 保持离线 PaddleX 补丁和审计禁带规则；任何重新引入都必须先取得书面许可 |
| **B-02** | 5 个模型权重再分发证据不足 | 4/5 的 tar 无任何许可证文本；bcebos 直链无授权声明 | 改用自带 LICENSE 的来源并更新 lock 的 URL/SHA-256；或取得书面确认。**在此之前保留 `NOTICE.md` 中的禁令** |
| **B-03** | NVIDIA SLA §2.5 与 AGPL-3.0 组合声明冲突 | wheel 自带 License.txt §2.5 明文禁止使 SDK 受开源许可约束 | 需法律意见界定"独立聚合"边界；或取得 NVIDIA 书面豁免；或调整归档结构使 CUDA/cuDNN 不落入 AGPL 组合作品 |
| **B-04** | cuDNN 可分发文件清单与实际产物不匹配 | 随附 SLA（2020-01-28 版）只列 `cudnn64_7.dll`，产物实为 8 个 `*64_9.dll` | 以现行 EULA（"the runtime files .so and .dll"）为准并在归档内替换为该版本文本；或取得 NVIDIA 书面确认 |

**B-01 实施证据**：`paddlex 3.7.2` 的 METADATA 仍声明 `Requires-Dist: aistudio-sdk>=0.3.5`，但本项目只使用随归档分发的本地 inference tar。`build/tools/patch_paddlex_3_7_2.py` 将 AI Studio 导入降为在线下载路径的可选依赖，并在构建后删除 `aistudio_sdk/` 与 dist-info；`build/tools/split_lock.py` 将其列入显式 GPU 运行时裁剪集合。v5 combined 回归在无该包的 vendor 中通过真实 Paddle CUDA OCR、PDF、HTTP/CLI 与错误路径测试。

### P1 —— 合规缺口，发布前必须补齐

| # | 阻塞项 | 判定依据 | 解决方式 |
| --- | --- | --- | --- |
| **B-05（v5 候选已闭合）** | `THIRD_PARTY_NOTICES.md` 尚非完整逐发行版清单 | `LICENSES/THIRD_PARTY_COMPONENTS.md` 由两份拆分 lock 与实际 dist-info 生成，列出名称、版本、许可证元数据、源码 URL 和随 wheel 的 notice 文件；基础/GPU 审计均强制校验根目录与 source 镜像 | 每次清洁构建重新生成并复核；逐项许可证全文和专有组件义务仍按 B-09/B-10 处理 |
| **B-06（本地候选已修复）** | LGPL-2.1 / LGPL-3.0 / GPL-3.0 许可证全文 | `LICENSES/LGPL-2.1.txt`、`LGPL-3.0.txt`、`GPL-3.0.txt` 已进入候选归档及对应源码镜像，`Audit-Package.ps1` 已校验 | 保持该审计断言；公开发布前仍须完成 B-05 的逐发行版声明 |
| **B-07（v5 候选已闭合）** | 未提供 Qt 重链接信息与对应源码指引 | `LICENSES/THIRD_PARTY_NOTICES.md` 现写明 PySide6/Qt 6.11.1、官方 Qt/PySide 源码入口、同名 DLL 替换步骤和未修改声明；v5 基础/GPU 归档审计均校验该文件 | 保留该说明；若改变 Qt/QML 模块，必须重新做干净裁剪与启动验证 |
| **B-08（本地候选已修复）** | GPU 插件 `source/` 对应源码镜像 | `Build-GpuPlugin.ps1` 现生成源码镜像；插件审计已验证源码、构建脚本、依赖锁和 GPU 插件源码存在 | 保持该审计断言，并在每次归档构建后复验 |
| **B-09** | opencv wheel 内嵌 FFmpeg（LGPL）未声明 | 产物含 `cv2/opencv_videoio_ffmpeg4100_64.dll`；`LICENSE-3RD-PARTY.txt` 含两处 LGPL | 在第三方声明中列出 FFmpeg 及其版本、LGPL 文本与源码获取途径；或改用 headless 变体规避 |

### P2 —— 发布前应处理

| # | 阻塞项 | 判定依据 | 解决方式 |
| --- | --- | --- | --- |
| **B-10** | MPL-2.0 组件（certifi、tqdm）的文件级源码义务未落实 | METADATA 一手读取 | 在第三方声明中给出这两项的源码获取地址 |
| **B-11** | 商业条款尚未针对 AGPL §10 / LGPL 做审查 | AGPL §10 禁止附加限制；Qt LGPL 义务第 6 项 | 3.0.0 的收费/授权文案中不得出现限制再分发、禁止逆向工程的条款 |
| **B-12** | 文档与构建不一致 | `THIRD_PARTY_NOTICES.md` 引用 `requirements-windows-cu126.lock`，实际构建用拆分后的两个 lock | 更新文档引用；UVDoc 同时补上游 MIT 署名（tanguymagne/UVDoc） |

---

## 附录：审计方法与可复核性

- **依赖许可证**：读取实际装入产物的 `.dist-info/METADATA` 的 `License` / `License-Expression` / `Classifier: License` 字段。该文件由 wheel 自带，等同于该版本在 PyPI 发布的元数据，属一手证据。已验证 v5 的 15 + 73 条归档锁定条目**全部**有本地 dist-info 覆盖，无遗漏。
- **模型**：对 `build/cache/models/` 下**已存在的**缓存 tar 解包检视，未新增任何下载。
- **专有组件条款**：直接读取 wheel 内 `License.txt`，并与 NVIDIA 在线 EULA 比对。
- **本次审计未修改 `build/`、`UmiOCR-data/` 下任何现有文件，未执行 git commit，未推送，未创建 release。**
