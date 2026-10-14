# PaddleOCR-VL 1.6 本地部署选型调研报告

> 调研日期：2026-07-26
> 目标环境：RTX 4060 Laptop（8188 MiB 显存，sm_89）+ Core Ultra 9 185H + 31.4 GB 内存 + CUDA 13.3
> 本地 llama.cpp：`D:\AI\llama.cpp`，commit `bf2c86ddc`（tag `b10002-9-gbf2c86ddc`，2026-07-14）
> **本报告为纯调研，未下载任何模型、未修改/编译 llama.cpp。**

---

## 0. 结论速览

| 问题 | 结论 |
|---|---|
| llama.cpp 是否已支持 PaddleOCR-VL？ | **已支持，且当前本地版本已包含**。无需升级即可跑 1.6 |
| 8 GB 显存够用吗？ | **绰绰有余。F16 全精度主模型 + F16 mmproj 合计仅 1.69 GiB 权重** |
| 需要低比特量化吗？ | **不需要（为省显存而量化没有意义）**。量化只换速度，不换可行性 |
| 8 GB 下最关键的约束是什么？ | **不是主模型精度，而是「mmproj 视觉编码器（841 MiB，且没有低精度官方版）+ 视觉图计算缓冲 + PP-DocLayoutV3 同卡占用 + 上下文长度」四者之和** |

---

## 1. PaddleOCR-VL 1.6 公开可得的模型格式

### 1.1 模型基本信息（来自官方 config.json，实测抓取）

来源：<https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6/raw/main/config.json>

| 项 | 值 |
|---|---|
| 架构 | `PaddleOCRVLForConditionalGeneration`（NaViT 风格视觉塔 + ERNIE-4.5-0.3B 语言塔） |
| 语言塔 | `hidden_size=1024`，`num_hidden_layers=18`，`num_attention_heads=16`，`num_key_value_heads=2`（GQA），`head_dim=128`，`intermediate_size=3072` |
| 词表 | `vocab_size=103424`，`tie_word_embeddings=false`（输入/输出 embedding 不共享，各占约 105M 参数） |
| 最大上下文 | `max_position_embeddings=131072` |
| 位置编码 | mrope / 3D rope，`mrope_section=[16,24,24]`，`rope_theta=500000` |
| 视觉塔 | `hidden_size=1152`，`num_hidden_layers=27`，`patch_size=14`，`spatial_merge_size=2`（SigLIP-so400m 量级，约 0.43B 参数） |
| 权重精度 | `bfloat16` |
| 总参数量 | 约 0.9B（官方称 0.9B / 1.0B 级） |

图像切分（来自 `preprocessor_config.json`，<https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6/raw/main/preprocessor_config.json>）：
- `min_pixels=112896`，`max_pixels=1003520`，`patch_size=14`，`merge_size=2`
- → 单图最多 `1003520 / 14² = 5120` 个 patch，经 2×2 merge 后 **最多 1280 个图像 token**
- 官方 README 提到文本 spotting 场景可把 `image_max_pixels` 调到 `1605632` → 8192 patch → **2048 图像 token**

发布信息：
- 发布方：**PaddlePaddle（百度）**
- 许可证：**Apache-2.0**（HF 模型卡 YAML `license: apache-2.0`，仓库内有 11,376 字节的 LICENSE 文件）
  证据：<https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6>
- 基座：`PaddlePaddle/PaddleOCR-VL-1.5` 微调，1.5 的基座是 `baidu/ERNIE-4.5-0.3B-Paddle`
- 官方说明 1.6 与 1.5 **架构完全兼容，可即插即用替换**

> ⚠️ 「Apache-2.0」是 HF 模型卡上的公开声明。是否可商用请以许可证原文与官方条款为准，本报告不做商用性判断。

### 1.2 原始 safetensors

| 仓库 | 文件 | 体积 |
|---|---|---|
| `PaddlePaddle/PaddleOCR-VL-1.6` | `model.safetensors` | 1,917,255,968 B = **1.786 GiB** |
| | `tokenizer.json` | 11,189,060 B |
| | `modeling_paddleocr_vl.py` 等自定义代码 | ~150 KB |

证据：<https://huggingface.co/api/models/PaddlePaddle/PaddleOCR-VL-1.6/tree/main?recursive=true>
发布方 PaddlePaddle，许可证 Apache-2.0。

### 1.3 GGUF（含 mmproj）

#### A) 官方 GGUF —— `PaddlePaddle/PaddleOCR-VL-1.6-GGUF`（**唯一官方来源**）

| 文件 | 字节 | 换算 |
|---|---|---|
| `PaddleOCR-VL-1.6-GGUF.gguf`（F16/BF16） | 935,769,056 | **892.4 MiB** |
| `PaddleOCR-VL-1.6-GGUF-mmproj.gguf`（F16） | 881,770,560 | **840.9 MiB** |
| `chat_template.jinja` | 1,831 | — |
| **主模型 + mmproj 合计下载** | 1,817,539,616 | **1.693 GiB** |

- 发布方：**PaddlePaddle**
- 许可证：**Apache-2.0**（模型卡 YAML）
- **官方只提供 F16/BF16 一档，没有任何官方量化版本**
- 下载量：705,670（远高于所有第三方版本之和）
- 证据：<https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6-GGUF>，文件清单 <https://huggingface.co/api/models/PaddlePaddle/PaddleOCR-VL-1.6-GGUF/tree/main?recursive=true>

官方 README 给出的 llama.cpp 用法：
```bash
llama-server \
    -m /path/to/PaddleOCR-VL-1.6-GGUF.gguf \
    --mmproj /path/to/PaddleOCR-VL-1.6-GGUF-mmproj.gguf \
    --port 8080 --host 0.0.0.0 --temp 0
```
配合 PaddleOCR 侧：
```bash
paddleocr doc_parser -i <image> --pipeline_version v1.6 \
    --vl_rec_backend llama-cpp-server --vl_rec_server_url http://127.0.0.1:8080/v1
```
官方支持任务：OCR、公式识别、表格识别、图表识别、印章识别、text spotting。

#### B) `SanjeevSOLANKI/PaddleOCR-VL-1.6-GGUF` —— **量化 + mmproj 齐全，第三方首选**

| 文件 | 字节 | 换算 |
|---|---|---|
| `PaddleOCR-VL-1.6-Q4_K_M.gguf` | 300,219,360 | 286.3 MiB |
| `PaddleOCR-VL-1.6-Q5_K_M.gguf` | 341,474,272 | 325.7 MiB |
| `PaddleOCR-VL-1.6-Q6_K.gguf` | 385,307,616 | 367.5 MiB |
| `PaddleOCR-VL-1.6-Q8_0.gguf` | 498,316,256 | 475.2 MiB |
| `PaddleOCR-VL-1.6-mmproj.gguf` | 881,770,560 | 840.9 MiB（**与官方 mmproj 字节数完全一致**） |

- 发布方：个人用户 SanjeevSOLANKI
- 许可证：模型卡声明 **Apache-2.0（继承自基座）**
- 制作方式：用 llama.cpp 的 `llama-quantize` 从官方 F16 GGUF 做**静态 k-quant，无 imatrix 校准**
- 模型卡自述推荐 Q4_K_M，并声称"在排版良好的页面上与 F16 同值、约 1.7× 于 F16 的速度、约 1.6 GB 显存"
  → ⚠️ **这是作者自述，无第三方基准佐证，请视为宣称而非实测**
- 模型卡明确提示：**所有量化档都必须搭配 mmproj**；建议使用训练时的提示词 `OCR:` 而非自定义指令；**重复循环（repetition loop）在 F16 上也存在，不是量化引入的**
- 证据：<https://huggingface.co/SanjeevSOLANKI/PaddleOCR-VL-1.6-GGUF>，文件清单 <https://huggingface.co/api/models/SanjeevSOLANKI/PaddleOCR-VL-1.6-GGUF/tree/main?recursive=true>

#### C) `Mungert/PaddleOCR-VL-1.6-GGUF` —— **档位最全，且提供量化 mmproj**

主模型（节选）：

| 文件 | 字节 | 换算 |
|---|---|---|
| `PaddleOCR-VL-1.6-bf16.gguf` | 935,768,864 | 892.4 MiB |
| `PaddleOCR-VL-1.6-f16_q8_0.gguf` | 789,787,424 | 753.2 MiB |
| `PaddleOCR-VL-1.6-q8_0.gguf` | 498,316,064 | 475.2 MiB |
| `PaddleOCR-VL-1.6-q6_k_m.gguf` | 436,606,048 | 416.4 MiB |
| `PaddleOCR-VL-1.6-q5_k_m.gguf` | 411,747,424 | 392.7 MiB |
| `PaddleOCR-VL-1.6-q4_k_m.gguf` | 382,084,192 | 364.4 MiB |
| `PaddleOCR-VL-1.6-q4_k_s.gguf` | 326,431,840 | 311.3 MiB |
| `PaddleOCR-VL-1.6-iq4_xs.gguf` | 312,390,752 | 297.9 MiB |
| `PaddleOCR-VL-1.6-q3_k_m.gguf` | 303,981,664 | 289.9 MiB |
| `PaddleOCR-VL-1.6-imatrix.gguf` | 756,768 | 739 KiB（imatrix 校准数据） |

mmproj（**这是本仓库最大的独有价值**）：

| 文件 | 字节 | 换算 |
|---|---|---|
| `PaddleOCR-VL-1.6-f32.mmproj` | 1,755,815,968 | 1.635 GiB |
| `PaddleOCR-VL-1.6-bf16.mmproj` | 881,770,528 | 840.9 MiB |
| `PaddleOCR-VL-1.6-f16.mmproj` | 880,415,776 | 839.6 MiB |
| `PaddleOCR-VL-1.6-q8_0.mmproj` | 597,566,368 | **569.9 MiB** |

- 发布方：个人用户 Mungert
- 许可证：**未找到公开证据**（HF API 未返回 license 字段，README 未见明确声明）
- 注意：Mungert 的 `q4_k_m`（364.4 MiB）明显大于 mradermacher 的同名档（286.3 MiB），说明两者对 embedding / output 层的处理策略不同，**同名档位不可互相比较体积**
- 证据：<https://huggingface.co/api/models/Mungert/PaddleOCR-VL-1.6-GGUF/tree/main?recursive=true>

#### D) `mradermacher/PaddleOCR-VL-1.6-GGUF` / `-i1-GGUF` —— **⚠️ 没有 mmproj，单独下载无法做 OCR**

静态量化仓库：

| 文件 | 字节 | 换算 |
|---|---|---|
| `PaddleOCR-VL-1.6.Q2_K.gguf` | 218,461,248 | 208.3 MiB |
| `PaddleOCR-VL-1.6.Q3_K_S.gguf` | 244,405,312 | 233.1 MiB |
| `PaddleOCR-VL-1.6.Q3_K_M.gguf` | 258,024,512 | 246.1 MiB |
| `PaddleOCR-VL-1.6.Q3_K_L.gguf` | 269,952,064 | 257.4 MiB |
| `PaddleOCR-VL-1.6.IQ4_XS.gguf` | 282,760,256 | 269.7 MiB |
| `PaddleOCR-VL-1.6.Q4_K_S.gguf` | 293,229,632 | 279.7 MiB |
| `PaddleOCR-VL-1.6.Q4_K_M.gguf` | 300,219,456 | 286.3 MiB |
| `PaddleOCR-VL-1.6.Q5_K_S.gguf` | 337,400,896 | 321.8 MiB |
| `PaddleOCR-VL-1.6.Q5_K_M.gguf` | 341,474,368 | 325.7 MiB |
| `PaddleOCR-VL-1.6.Q6_K.gguf` | 385,307,712 | 367.5 MiB |
| `PaddleOCR-VL-1.6.Q8_0.gguf` | 498,316,352 | 475.2 MiB |
| `PaddleOCR-VL-1.6.f16.gguf` | 935,769,152 | 892.4 MiB |

i1（imatrix）仓库另有 IQ1_S/IQ1_M/IQ2_*/IQ3_* 等更低档（164 MiB 起）。

- 发布方：个人用户 mradermacher
- 许可证：模型卡 YAML **`apache-2.0`**，`base_model: PaddlePaddle/PaddleOCR-VL-1.6`
- **两个仓库的文件清单里都不含 mmproj / 视觉投影器文件**，README 中还有一行注释 `<!-- ### skip_mmproj: -->`
  → **必须另外从官方仓库或 Mungert 取 mmproj，否则只是个纯文本 LLM**
- 证据：<https://huggingface.co/api/models/mradermacher/PaddleOCR-VL-1.6-GGUF/tree/main?recursive=true>、<https://huggingface.co/api/models/mradermacher/PaddleOCR-VL-1.6-i1-GGUF/tree/main?recursive=true>

#### E) `cstr/paddleocr-vl-1.6-GGUF` —— **不建议，格式存疑**

| 文件 | 字节 | 换算 |
|---|---|---|
| `paddleocr-vl-1.6-f16.gguf` | 2,392,874,944 | 2.229 GiB |
| `paddleocr-vl-1.6-q8_0.gguf` | 1,479,572,288 | 1.378 GiB |
| `paddleocr-vl-1.6-q4_k.gguf` | 1,299,217,216 | 1.210 GiB |

- 体积远大于官方 F16（892 MiB），且**无独立 mmproj 文件**，疑似把视觉塔合并进单文件或含大量 F32 张量
- 许可证：**未找到公开证据**
- **是否能被 llama.cpp 的 mtmd 正常加载，未找到公开证据 —— 需补充调研**
- 证据：<https://huggingface.co/api/models/cstr/paddleocr-vl-1.6-GGUF/tree/main?recursive=true>

#### F) 其它格式（非 llama.cpp 路线，仅列出供参考）

| 仓库 | 格式 | 说明 |
|---|---|---|
| `litert-community/PaddleOCR-VL-1.6` | LitertLM | 端侧 |
| `translate-studio/PaddleOCR-VL-1.6-8bit` / `-6bit`、`olragon/...-8bit`、`matrixmaven/...-bf16` | MLX | 仅 Apple Silicon |

证据：<https://huggingface.co/api/models?search=PaddleOCR-VL-1.6&full=true&limit=100>

### 1.4 llama.cpp 对该架构的支持状态

**已合并，且你的本地版本已包含。**

| 项 | 值 | 证据 |
|---|---|---|
| 支持 PR | **#18825「model: Add PaddleOCR-VL model support」**，作者 megemini，assignee ngxson | <https://github.com/ggml-org/llama.cpp/pull/18825> |
| 合并时间 | **2026-02-19** | 同上（`merged_at: 2026-02-19T16:05:26Z`） |
| **最低 commit** | **`237958db3`**（本地 git log：`237958db3 2026-02-20 model: Add PaddleOCR-VL model support (#18825)`） | 本地 `D:\AI\llama.cpp` 只读 git log |
| 后续修复 | PR **#19799**「chat: fix llama-server image placeholder issue for PaddleOCR-VL」，合并 2026-02-22，修复 llama-server 需要 `media_marker` 而非 `image` 的聊天模板问题 | <https://github.com/ggml-org/llama.cpp/pull/19799> |
| 前身 WIP | PR #16701（ngxson，未合并，被 #18825 取代） | <https://github.com/ggml-org/llama.cpp/pull/16701> |

本地代码实测确认（只读 grep，未修改）：

| 文件 | 证据 |
|---|---|
| `D:\AI\llama.cpp\src\llama-arch.cpp:136` | `{ LLM_ARCH_PADDLEOCR, "paddleocr" }` |
| `D:\AI\llama.cpp\src\models\paddleocr.cpp` | 语言塔实现 |
| `D:\AI\llama.cpp\tools\mtmd\models\paddleocr.cpp` | 视觉塔实现 |
| `D:\AI\llama.cpp\tools\mtmd\clip-impl.h:355,409` | `PROJECTOR_TYPE_PADDLEOCR` / `{ PROJECTOR_TYPE_PADDLEOCR, "paddleocr" }` |
| `D:\AI\llama.cpp\docs\multimodal.md:38` | 官方文档列出 PaddleOCR-VL 并指向 PR #18825 |
| `D:\AI\llama.cpp\build\bin\` | `llama-server.exe`、`llama-mtmd-cli.exe`、`llama-quantize.exe` 等均已编译 |

**结论：本地 `bf2c86ddc`（2026-07-14）远新于 `237958db3`（2026-02-20），PaddleOCR-VL 支持与 #19799 模板修复均已包含。1.6 与 1.5 架构兼容，因此 1.6 GGUF 可直接加载，无需升级 llama.cpp。**

### 1.5 已知问题（务必知悉）

| 问题 | 状态 | 证据 |
|---|---|---|
| 同一 chat session 连续发多张图会触发 tokenization 错误，**每次请求只能一张图** | PR #18825 说明中列出的限制 | <https://github.com/ggml-org/llama.cpp/pull/18825> |
| llama-server 报 `The model produced output that does not match the expected peg-native format`（HTTP 500），特定页面复现 | **Issue #25339，2026-07-06 提出，仍 open**。报告环境为 build 9864 + Q8 + CUDA。缓解办法：去掉复杂 system 指令 | <https://github.com/ggml-org/llama.cpp/issues/25339> |
| 重复循环（repetition loop）在高度重复版面上出现，**F16 全精度同样存在，非量化引起** | 第三方模型卡自述 | <https://huggingface.co/SanjeevSOLANKI/PaddleOCR-VL-1.6-GGUF> |
| llama.cpp 官方多模态文档给 PaddleOCR-VL 标注 "may have degraded performance" | 社区博客引用官方文档 | <https://blog.ngxson.com/using-ocr-models-with-llama-cpp> |
| 结构化版面抽取（Markdown/HTML 输出）**必须走官方 PaddleOCR 流水线**，裸 llama.cpp 只给扁平文本 + LaTeX | 第三方模型卡自述 + 官方 README 的 `paddleocr doc_parser` 用法 | 同上 |

⚠️ **Issue #25339 的报告版本 build 9864 早于你的 b10002，但该问题至今未关闭，升级 llama.cpp 并不能确定规避。**

---

## 2. 各精度体积 / 显存 / 8 GB 可行性

### 2.1 KV cache 计算（基于 config.json 实测参数）

```
每 token KV 元素数 = 2 (K+V) × n_layer(18) × n_kv_heads(2) × head_dim(128) = 9,216
F16 KV：9,216 × 2 B = 18,432 B = 18 KiB / token
```

得益于 GQA（`num_key_value_heads=2`），**KV cache 极小**：

| 上下文 `-c` | F16 KV cache | Q8_0 KV cache（约） |
|---|---|---|
| 4,096 | **72 MiB** | ~38 MiB |
| 8,192（插件默认） | **144 MiB** | ~77 MiB |
| 16,384 | **288 MiB** | ~153 MiB |
| 32,768 | **576 MiB** | ~306 MiB |
| 65,536 | **1,152 MiB** | ~612 MiB |
| 131,072（模型上限） | **2,304 MiB (2.25 GiB)** | ~1,224 MiB |

> llama-server 中 `-c` 是所有并发 slot 共享的总量（`-np N` 会把它切分），所以提高 `-np` 不额外增加 KV 总量，但会增加计算缓冲。

### 2.2 显存占用估算表（8188 MiB 上限）

固定项：
- **mmproj F16 = 841 MiB（必须常驻，且官方无更低精度版本）**
- CUDA context / cuBLAS 句柄等运行时开销：约 **250–400 MiB**
- 视觉塔计算图缓冲（5120 patch × 27 层，`hidden=1152`、`intermediate=4304`）：约 **300–900 MiB**（是否启用 flash-attn 影响很大；本地已编译 FA 支持）
- 语言塔计算图缓冲：**< 100 MiB**

| 主模型精度 | 下载体积 | 权重显存 | +mmproj F16 | +KV@8K | +运行时&计算图 | **总计估算** | 8 GB 可行性 |
|---|---|---|---|---|---|---|---|
| **F16 / BF16（官方）** | 892.4 MiB | 892 MiB | 1,733 MiB | 1,877 MiB | +0.6~1.4 GiB | **≈ 2.5–3.3 GiB** | ✅ **完全放得下，余量 ≥ 4.8 GiB** |
| **Q8_0** | 475.2 MiB | 475 MiB | 1,316 MiB | 1,460 MiB | +0.6~1.4 GiB | **≈ 2.1–2.9 GiB** | ✅ 完全放得下 |
| **Q6_K** | 367.5 MiB | 368 MiB | 1,209 MiB | 1,353 MiB | +0.6~1.4 GiB | **≈ 2.0–2.8 GiB** | ✅ 完全放得下 |
| **Q5_K_M** | 325.7 MiB | 326 MiB | 1,167 MiB | 1,311 MiB | +0.6~1.4 GiB | **≈ 1.9–2.7 GiB** | ✅ 完全放得下 |
| **Q4_K_M** | 286.3 MiB | 286 MiB | 1,127 MiB | 1,271 MiB | +0.6~1.4 GiB | **≈ 1.9–2.7 GiB** | ✅ 完全放得下 |
| **Q3_K_* / Q2_K / IQ*** | 164–270 MiB | 164–270 MiB | ~1.0–1.1 GiB | ~1.15–1.25 GiB | 同上 | **≈ 1.8–2.6 GiB** | ✅ 放得下，但**质量风险高，不建议** |
| （对照）mmproj F32 | 1.635 GiB | — | +1,675 MiB | — | — | 比 F16 mmproj 多 **834 MiB** | ⚠️ 无必要 |

**关键判断：即使把上下文拉满到 131,072（KV 2.25 GiB）、mmproj 用 F32（1.64 GiB）、主模型用 F16（892 MiB），总计也只有约 5.5–6.5 GiB —— 仍在 8188 MiB 之内。**

**→ 因此：在 8 GB 显存上，没有任何一档 PaddleOCR-VL 1.6 精度是「放不下」的；也没有任何一档需要部分 offload 到内存。**
**→ 量化在这里换到的是「速度 + 内存占用」，不是「可行性」。**

### 2.3 真正会撑爆 8 GB 的三个场景（❗️必读）

1. **PP-DocLayoutV3 与 llama-server 同卡竞争**
   Umi-OCR 插件 `D:\Code\Python\Umi-OCR-Plugin\win32_PaddleOCRVL_1_6\api.py` 会在 **同一张 GPU（默认 `gpu:0`）** 上同时跑：
   - Paddle Inference 的 PP-DocLayoutV3 版面检测
   - llama.cpp 的 llama-server
   PP-DocLayoutV3 权重仅 130,806,572 B ≈ 124.8 MiB（<https://huggingface.co/api/models/PaddlePaddle/PP-DocLayoutV3/tree/main?recursive=true>，发布方 PaddlePaddle，许可证 Apache-2.0），
   但 **Paddle Inference 的 CUDA context + cuDNN workspace 通常额外吃 0.6–1.5 GiB** —— 这部分**未找到官方公开数值，属经验估算，需实测确认**。
   → 8 GB 的实际预算应按「llama.cpp 可用 ≈ 6.0–6.5 GiB」来做。

2. **`concurrency` / `-np` 调高**
   插件把 `resources.concurrency` 直接传给 `-np`。每增加一个 slot，计算缓冲线性增长；且 PR #18825 已说明**单请求只能处理一张图**。
   → **8 GB 设备强烈建议保持 `concurrency = 1`（插件默认值）**。

3. **`contextLength` 拉到 131072**
   多花 2.16 GiB KV，而 block 级流水线根本用不到（见第 3 节）。
   → **不要动插件默认的 8192，除非确认被截断。**

### 2.4 速度权衡（证据强度说明）

- 语言塔仅约 0.36B 参数 + 0.21B embedding，**解码是显存带宽瓶颈**：F16 → Q8_0 大致把每 token 权重读取量减半。
- 但 **OCR 场景中视觉塔（27 层 × 5120 patch）的 prefill 往往占据主要耗时，而 mmproj 精度基本不变**，所以主模型从 F16 降到 Q4 的端到端加速远小于纯文本 LLM 的直觉。
- SanjeevSOLANKI 模型卡自述 Q4_K_M "~1.7× faster than F16"，**这是发布者自述，无独立复现，仅供参考**。
- 本报告**未在本机做任何实测**（用户明确禁止下载/运行模型）。

---

## 3. 文档场景（表格 / 公式 / 版面）的上下文需求

### 3.1 单次请求的 token 构成

| 组成 | token 数 |
|---|---|
| 图像 token（`max_pixels=1003520`，14px patch + 2×2 merge） | **≤ 1,280** |
| spotting 模式（`image_max_pixels=1605632`） | **≤ 2,048** |
| 提示词（`OCR:` / `Table Recognition:` / `Formula Recognition:`） | < 20 |
| 输出（插件默认 `maxOutputTokens=4096`） | ≤ 4,096 |

### 3.2 两种调用模式的上下文需求

**模式 A：Umi-OCR 插件的 block 级流水线（当前实现）**
PP-DocLayoutV3 先切出标题/正文/表格/公式/图片区域，再把**每个 block 单独**送给 llama-server。

- 单请求峰值 ≈ 1,280（图）+ 4,096（出）+ 20 ≈ **5,400 token**
- **插件默认 `contextLength=8192` 已有约 34% 余量，足够**
- 只有在**超大跨页表格**（HTML/OTSL 输出可轻易上千 token）或**长公式段**时才可能触顶

**模式 B：整页单次送入（不经版面切分）**
- 图像 token 仍受 `max_pixels` 上限约束（≤1,280 / ≤2,048），不会爆炸
- 但输出可能是整页 Markdown，需要把 `maxOutputTokens` 提到 8K–16K
- 建议 `-c 16384`

### 3.3 上下文长度对显存的影响（结论）

**由于 GQA 只有 2 个 KV head，KV cache 每 token 仅 18 KiB，上下文对 8 GB 显存几乎不构成压力：**

| 场景 | 建议 `-c` | KV 显存代价 |
|---|---|---|
| block 级流水线（插件默认） | **8,192** | 144 MiB |
| 大表格 / 长公式安全垫 | **16,384** | 288 MiB（**仅比 8K 多 144 MiB，性价比极高**） |
| 整页单次解析 | 16,384–32,768 | 288–576 MiB |
| 拉满 | 131,072 | 2,304 MiB（**纯浪费，无实际收益**） |

> ⚠️ 注意：上下文变大还会**间接**增大 llama.cpp 的 compute buffer 与 prompt cache 占用，但相比 KV 本身仍是小头。

---

## 4. 精度建议（文档 / 表格 / 公式 / 版面场景）

### 方案 1：官方 F16 主模型 + 官方 F16 mmproj —— **推荐度 ★★★★★（首选）**

```
PaddlePaddle/PaddleOCR-VL-1.6-GGUF
├─ PaddleOCR-VL-1.6-GGUF.gguf         892.4 MiB
└─ PaddleOCR-VL-1.6-GGUF-mmproj.gguf  840.9 MiB
下载合计 1.693 GiB
```

| 维度 | 评价 |
|---|---|
| 质量 | **上限，无量化损失**。表格 HTML 结构、LaTeX 公式这类「长结构化输出」对权重精度最敏感，全精度最稳 |
| 显存 | ≈ 2.5–3.3 GiB，**8 GB 下余量充足**，与 PP-DocLayoutV3 共存也没问题 |
| 速度 | 最慢的一档，但视觉塔占大头，差距被摊薄 |
| 风险 | **最低** —— 官方发布、官方 README 直接给的命令、下载量 70 万、许可证明确 Apache-2.0 |

**理由：既然 8 GB 完全放得下全精度，为省 400 MiB 显存去承担 OCR 结构化输出的质量风险，是不划算的交易。**

### 方案 2：Q8_0 主模型 + 官方 F16 mmproj —— **推荐度 ★★★★☆（速度/质量平衡）**

```
主模型（二选一，字节数几乎一致）：
  SanjeevSOLANKI/PaddleOCR-VL-1.6-GGUF → PaddleOCR-VL-1.6-Q8_0.gguf    475.2 MiB
  mradermacher/PaddleOCR-VL-1.6-GGUF   → PaddleOCR-VL-1.6.Q8_0.gguf    475.2 MiB
mmproj（必须另取）：
  PaddlePaddle/PaddleOCR-VL-1.6-GGUF   → ...-mmproj.gguf               840.9 MiB
下载合计 1.286 GiB
```

| 维度 | 评价 |
|---|---|
| 质量 | Q8_0 是公认接近无损的一档；**但无 PaddleOCR-VL 专项 OmniDocBench 对比数据，未找到公开证据** |
| 显存 | ≈ 2.1–2.9 GiB，比 F16 省约 417 MiB |
| 速度 | 解码权重读取量约为 F16 的一半 |
| 风险 | 中低。**必须确保 mmproj 与主模型同源（同一 1.6 权重）**，否则加载失败或输出乱码 |

⚠️ 若选 mradermacher，请务必记住**该仓库不含 mmproj**，mmproj 只能从官方仓库取。

### 方案 3：Q4_K_M 主模型 + 官方 F16 mmproj —— **推荐度 ★★☆☆☆（仅追求速度时）**

```
SanjeevSOLANKI/PaddleOCR-VL-1.6-GGUF → PaddleOCR-VL-1.6-Q4_K_M.gguf   286.3 MiB
PaddlePaddle/PaddleOCR-VL-1.6-GGUF   → ...-mmproj.gguf                840.9 MiB
下载合计 1.100 GiB
```

| 维度 | 评价 |
|---|---|
| 质量 | ⚠️ 语言塔只有约 0.36B 参数，**小模型对低比特量化更敏感**；表格 HTML 标签闭合、LaTeX 括号配对这类长结构化输出最容易在低比特下崩坏 |
| 显存 | ≈ 1.9–2.7 GiB（相比方案 1 只省约 600 MiB —— **在 8 GB 上这点节省毫无意义**） |
| 速度 | 发布者自述 ~1.7× F16（**无第三方验证**） |
| 风险 | 中高。且这些量化是**静态 k-quant，无 imatrix 校准**（SanjeevSOLANKI 自述） |

**不推荐档位（明确列出）：Q3_K_*、Q2_K、IQ1_*、IQ2_*、IQ3_*。**
理由：省下的显存（相对 F16 最多约 730 MiB）在 8 GB 上没有任何实际价值，却把一个 0.36B 语言塔压到 2–3 bit，文档结构化输出的失败风险显著上升。**未找到任何针对 PaddleOCR-VL 低比特档的 OmniDocBench 公开评测数据。**

### 三方案速查

| | 方案 1 F16 | 方案 2 Q8_0 | 方案 3 Q4_K_M |
|---|---|---|---|
| 推荐度 | ★★★★★ | ★★★★☆ | ★★☆☆☆ |
| 下载 | 1.693 GiB | 1.286 GiB | 1.100 GiB |
| 显存估算 | 2.5–3.3 GiB | 2.1–2.9 GiB | 1.9–2.7 GiB |
| 8 GB 可行 | ✅ | ✅ | ✅ |
| 质量 | 最高 | 接近最高 | 有风险 |
| 来源可信度 | 官方 | 第三方（Apache-2.0 声明） | 第三方（Apache-2.0 声明） |

---

## 5. 各来源发布方 / 许可证 / 体积汇总

| 仓库 | 发布方 | 许可证 | 含 mmproj | 主模型体积范围 | 证据 |
|---|---|---|---|---|---|
| `PaddlePaddle/PaddleOCR-VL-1.6` | PaddlePaddle（百度） | **apache-2.0**（模型卡 + LICENSE 文件） | — | safetensors 1.786 GiB | <https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6> |
| `PaddlePaddle/PaddleOCR-VL-1.6-GGUF` | PaddlePaddle（百度） | **apache-2.0**（模型卡） | ✅ 840.9 MiB | 仅 F16：892.4 MiB | <https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6-GGUF> |
| `SanjeevSOLANKI/PaddleOCR-VL-1.6-GGUF` | 个人 SanjeevSOLANKI | **apache-2.0**（模型卡自述继承自基座） | ✅ 840.9 MiB | Q4_K_M 286.3 – Q8_0 475.2 MiB | <https://huggingface.co/SanjeevSOLANKI/PaddleOCR-VL-1.6-GGUF> |
| `mradermacher/PaddleOCR-VL-1.6-GGUF` | 个人 mradermacher | **apache-2.0**（模型卡 YAML） | ❌ **无** | Q2_K 208.3 – f16 892.4 MiB | <https://huggingface.co/mradermacher/PaddleOCR-VL-1.6-GGUF> |
| `mradermacher/PaddleOCR-VL-1.6-i1-GGUF` | 个人 mradermacher | **apache-2.0**（模型卡 YAML） | ❌ **无** | IQ1_S 157.2 – Q6_K 367.5 MiB | <https://huggingface.co/mradermacher/PaddleOCR-VL-1.6-i1-GGUF> |
| `Mungert/PaddleOCR-VL-1.6-GGUF` | 个人 Mungert | **未找到公开证据** | ✅ q8_0 569.9 / f16 839.6 / f32 1.635 GiB | q3_k_m 289.9 – bf16 892.4 MiB | <https://huggingface.co/Mungert/PaddleOCR-VL-1.6-GGUF> |
| `cstr/paddleocr-vl-1.6-GGUF` | 个人 cstr | **未找到公开证据** | ❌ 无独立 mmproj，格式存疑 | q4_k 1.210 – f16 2.229 GiB | <https://huggingface.co/cstr/paddleocr-vl-1.6-GGUF> |
| `PaddlePaddle/PP-DocLayoutV3`（版面检测，插件必需） | PaddlePaddle（百度） | **apache-2.0**（模型卡） | — | `inference.pdiparams` 124.8 MiB + `inference.json` 1.14 MiB + `inference.yml` | <https://huggingface.co/PaddlePaddle/PP-DocLayoutV3> |

> **许可证说明**：以上「apache-2.0」均为 Hugging Face 模型卡上的公开声明。第三方量化仓库的许可证声明是发布者自述，其法律效力与原始许可证的传递性本报告不作判断。Mungert 与 cstr 两个仓库**未找到公开的许可证证据**，**不要假定其可用于任何特定用途**。

---

## 6. `D:\AI\llama.cpp\models\` 建议目录布局

### 6.1 现状

`D:\AI\llama.cpp\models\` 目前**只有 `ggml-vocab-*.gguf` 测试词表**（约 76 MB）+ `templates\` + `.editorconfig`，**没有任何真实模型**。这些是 llama.cpp 仓库自带的**被 git 跟踪的文件**。

### 6.2 建议布局（按来源分目录，避免与 git 跟踪文件混淆）

```
D:\AI\llama.cpp\models\
├─ ggml-vocab-*.gguf              ← 仓库自带，勿动
├─ templates\                     ← 仓库自带，勿动
└─ vlm\                           ← 新建，统一放自备模型（未被 git 跟踪）
   └─ paddleocr-vl-1.6\
      ├─ PaddleOCR-VL-1.6-GGUF.gguf          ← 主模型（插件 service.mainModel）
      ├─ PaddleOCR-VL-1.6-GGUF-mmproj.gguf   ← 视觉投影器（插件 service.mmprojModel）
      ├─ chat_template.jinja                 ← 官方仓库自带，备用
      └─ SOURCE.txt                          ← 记录来源 URL / 精度 / SHA256 / 下载日期
```

若要同时保留多档精度对比：

```
   └─ paddleocr-vl-1.6\
      ├─ mmproj\
      │  └─ PaddleOCR-VL-1.6-mmproj-F16.gguf    ← 只需一份，所有精度共用
      ├─ f16\
      │  └─ PaddleOCR-VL-1.6-F16.gguf
      ├─ q8_0\
      │  └─ PaddleOCR-VL-1.6-Q8_0.gguf
      └─ SOURCE.txt
```

**PP-DocLayoutV3 不是 GGUF，属于 Paddle Inference 模型目录，建议放到 llama.cpp 仓库之外**：

```
D:\AI\models\PP-DocLayoutV3\
├─ inference.json      ← 插件 api.py 的 _required_dir() 会强制校验此文件存在
├─ inference.pdiparams
└─ inference.yml
```

### 6.3 与 Umi-OCR document 插件配置项的对应关系

插件配置来自 `D:\Code\Python\Umi-OCR-Plugin\win32_PaddleOCRVL_1_6\config.py`：

| 插件配置项 | 应填路径 |
|---|---|
| `service.serverExecutable` | `D:\AI\llama.cpp\build\bin\llama-server.exe` |
| `service.mainModel` | `D:\AI\llama.cpp\models\vlm\paddleocr-vl-1.6\PaddleOCR-VL-1.6-GGUF.gguf` |
| `service.mmprojModel` | `D:\AI\llama.cpp\models\vlm\paddleocr-vl-1.6\PaddleOCR-VL-1.6-GGUF-mmproj.gguf` |
| `pipeline.layoutModelDir` | `D:\AI\models\PP-DocLayoutV3`（**目录内必须有 `inference.json`**） |
| `pipeline.cudaDevice` | `gpu:0` |
| `resources.gpuLayers` | `-1`（全部上 GPU，8 GB 足够） |
| `resources.contextLength` | `8192`（默认）或 `16384`（大表格保险） |
| `resources.maxOutputTokens` | `4096`（默认） |
| `resources.concurrency` | **`1`（8 GB 强烈建议不要调高）** |

插件实际拼出的 llama-server 命令行（`api.py` 第 117–135 行）：
```
llama-server.exe -m <mainModel> --mmproj <mmproj> -ngl <gpuLayers> -c <contextLength> -np <concurrency> --host <host> --port <port> --temp 0
```
> 注意：插件**没有传 `--jinja` 或 `--chat-template-file`**。官方 README 给的命令同样没传，而 PR #19799 的模板修复已内置在 llama.cpp 里（你的版本已包含），预期可用。**但这一点未实测，需在首次启动后确认输出正常。**

---

## 7. 升级 llama.cpp 的风险评估

### 7.0 核心结论：**当前没有升级的必要**

你的 `bf2c86ddc`（2026-07-14 / b10002-9）已包含：
- PaddleOCR-VL 支持（`237958db3`，2026-02-20，PR #18825）
- llama-server 聊天模板 media_marker 修复（PR #19799，2026-02-22）

而唯一已知的 1.6 相关公开 issue #25339 **至今 open**，升级并不能确定解决。
**建议：先用现有构建实测，出问题再考虑升级。**

### 7.1 若坚持升级：`update.ps1` 的具体风险

`D:\AI\llama.cpp\update.ps1` 的关键行为（已只读通读全文）：
1. 进入 MSVC x64 DevShell
2. `git pull --ff-only --recurse-submodules` → 失败即 `throw`
3. `git submodule sync --recursive` + `git submodule update --init --recursive`
4. CMake configure，参数：`--fresh -G Ninja -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=native -DLLAMA_BUILD_SERVER=ON -DGGML_CCACHE=OFF`
5. `cmake --build build --parallel $Jobs`（默认 `$Jobs = 8`）

当前工作区状态（只读 `git status --porcelain`）：
```
 D CLAUDE.md          ← 已跟踪文件被删除，未 stage
?? qwen-embedding.pid
?? scripts/local/
?? update.ps1
```

| 风险 | 等级 | 说明 |
|---|---|---|
| **`CLAUDE.md` 的未 stage 删除会阻断 `git pull`** | **中** | 若上游在这段时间修改过 `CLAUDE.md`，`git pull --ff-only` 会报 "Your local changes to the following files would be overwritten by merge" 并 `throw`，构建不会开始（**不会损坏任何东西**）。若上游未动该文件，pull 成功且删除状态保留 |
| **未跟踪文件 `update.ps1` / `scripts/local/` 被上游同名文件覆盖** | **低** | git 只在上游新增了完全同路径文件时才会报错中止。`update.ps1` 在仓库根目录、`scripts/local/` 都不是 llama.cpp 上游的常见路径。**但一旦冲突，git 会中止而非覆盖**，你的文件仍然安全 |
| **`scripts/local/qwen-embedding.ps1` 被破坏** | **无** | 该脚本是未跟踪文件，`git pull` 不碰它。它只硬编码引用 `D:\AI\llama.cpp\build\bin\llama-server.exe`（第 10 行），**路径在重建后不变** |
| **`qwen-embedding.pid` 指向的服务在重建期间失效** | **低但真实** | 重建会覆盖 `build\bin\*.exe` 与 `*.dll`。如果 qwen-embedding 服务**正在运行**，Windows 会锁定 exe/dll 导致链接失败，或服务在重启后行为改变。**升级前务必先停掉该服务** |
| **llama-server 的 CLI/API 变更打破插件** | **中** | 你当前 HEAD 恰好是 `server : refactor prompt cache state ownership (#25649)` —— server 内部改动频繁。插件依赖的是稳定 flag（`-m --mmproj -ngl -c -np --host --port --temp`）和 `/v1/models` 端点，**历史上很稳定，但不保证** |
| **`--fresh` + `GGML_CCACHE=OFF` = 每次全量重编** | **确定** | 没有增量，没有 ccache。每次跑 `update.ps1` 都是从零编译 |

### 7.2 重编译时间与磁盘

| 项 | 数值 | 说明 |
|---|---|---|
| 当前 `build\` 大小 | **1.3 GB**（其中 `build\bin\` 66 MB） | 只读 `du -sh` 实测 |
| 重建峰值磁盘 | **估计 2–4 GB**（中间 .obj + 链接临时文件） | **估算，非实测** |
| D: 可用空间 | **95 GB** | `df -h` 实测 → **磁盘完全不是瓶颈** |
| 重建耗时 | **估计 20–45 分钟** | **估算，非实测**。依据：单一 CUDA arch（`native` → 仅 sm_89，比多 arch 快很多）、16 线程 CPU、但 `$Jobs` 默认只有 **8**。可考虑 `.\update.ps1 -Jobs 14` 提速（nvcc 每 job 约 1–2 GB 内存，31.4 GB 内存够用） |

### 7.3 CUDA 13.3 + sm_89 已知问题

| 项 | 结论 | 证据 |
|---|---|---|
| CUDA 13.3 是否被 llama.cpp 支持 | **是**。llama.cpp 官方 release 已提供 Windows x64 CUDA 13.3 构建产物 | <https://github.com/ggml-org/llama.cpp/releases> |
| sm_89（Ada / RTX 40 系）是否被 CUDA 13.3 支持 | **是**，CUDA 13 未移除 sm_89 | 同上及 <https://insiderllm.com/guides/llamacpp-build-errors-fixes/> |
| `CMAKE_CUDA_ARCHITECTURES=native` 是否可靠 | **在本机已被验证** —— 现有 `build\bin\ggml-cuda.dll` 就是用该配置编译出来的 | 本地文件实测 |
| CUDA 13.x 专有问题 | 检索到的是 **Docker `server-cuda13` 镜像在受支持 GPU 上启动失败**（Issue #22561），与**本机源码编译**路径不同 | <https://github.com/ggml-org/llama.cpp/issues/22561> |
| **CUDA 13.3 + sm_89 + 源码编译的已知阻断性问题** | **未找到公开证据** | — |

`update.ps1` 已内置两项防护，可降低 CUDA 环境风险：
- 强制 Ninja 生成器，规避 VS 生成器找 CUDA MSBuild toolset 的老问题
- 校验 `$CudaRoot\include\cccl` 存在，避免 CUDA 安装不完整导致的编译中途失败

### 7.4 若要升级，建议的安全顺序（**仅为建议，本次未执行**）

1. 停掉正在运行的 qwen-embedding 服务（`qwen-embedding.pid`）
2. 备份 `build\bin\` 整个目录（66 MB，便于回滚）
3. 记录当前 commit：`bf2c86ddc0685f580595954056c2e77ebabfab4f`
4. 先单独跑 `git pull --ff-only --recurse-submodules` 看是否被 `CLAUDE.md` 阻断；被阻断时自行决定如何处理（本报告不替你决定）
5. 再跑 `.\update.ps1 -SkipVsDevShell`（若已在 DevShell）或直接 `.\update.ps1 -Jobs 14`
6. 失败可用 `git checkout bf2c86ddc` 回滚源码，再重建

---

## 8. 需要用户决定的问题

### Q1. 选哪个模型来源？

| 选项 | 优点 | 缺点 |
|---|---|---|
| **(a) `PaddlePaddle/PaddleOCR-VL-1.6-GGUF`（官方）** | 官方发布、许可证明确 apache-2.0、下载量 70 万、README 直接给 llama.cpp 命令、mmproj 齐全 | **只有 F16 一档**，无量化选择 |
| (b) `SanjeevSOLANKI/PaddleOCR-VL-1.6-GGUF` | Q4_K_M/Q5_K_M/Q6_K/Q8_0 + mmproj **一站齐全**，声明 apache-2.0 | 个人发布、静态量化无 imatrix、性能数据为自述 |
| (c) `mradermacher/...-GGUF` / `-i1-GGUF` | 档位最全（含 imatrix i1 系列），声明 apache-2.0 | **不含 mmproj，必须混搭官方 mmproj** |
| (d) `Mungert/PaddleOCR-VL-1.6-GGUF` | 唯一提供 **q8_0 量化 mmproj（569.9 MiB）** 与 f32 mmproj | **许可证未找到公开证据** |
| (e) `cstr/paddleocr-vl-1.6-GGUF` | — | 体积异常、无独立 mmproj、许可证未找到公开证据、**兼容性需补充调研** |

> 提示：mmproj 与主模型可以来自不同仓库（只要都是 1.6 权重），但**混搭前请自行校验 SHA256 与来源一致性**。

**→ 请决定：主模型取哪个仓库？mmproj 取哪个仓库？**

### Q2. 选哪个量化精度？

调研结论是 **8 GB 显存对所有档位都不构成限制**，所以这是一个纯粹的「质量 vs 速度」取舍，不是「能不能跑」的问题：

- [ ] **F16（892.4 MiB）** —— 本报告推荐度 ★★★★★，质量上限，显存仍有 ≥4.8 GiB 余量
- [ ] **Q8_0（475.2 MiB）** —— 推荐度 ★★★★☆，省 417 MiB，解码约快一档
- [ ] **Q6_K（367.5 MiB）** —— 未单独成方案，介于 Q8_0 与 Q5 之间
- [ ] **Q5_K_M（325.7 MiB）** —— 未单独成方案
- [ ] **Q4_K_M（286.3 MiB）** —— 推荐度 ★★☆☆☆，速度优先时才考虑
- [ ] **Q3_K_* / Q2_K / IQ***  —— **本报告不推荐用于文档/表格/公式场景**

**mmproj 精度也需单独决定**：
- [ ] F16（840.9 MiB，官方，**默认建议**）
- [ ] q8_0（569.9 MiB，仅 Mungert 提供，许可证未找到公开证据）
- [ ] f32（1.635 GiB，无必要）

**→ 请决定：主模型精度 + mmproj 精度。**

### Q3. 是否升级 llama.cpp？

- [ ] **不升级（本报告倾向）** —— 现有 `bf2c86ddc` 已完整支持 PaddleOCR-VL，零风险，立即可用
- [ ] 升级 —— 需先接受：`CLAUDE.md` 未 stage 删除可能阻断 `git pull`；需先停 qwen-embedding 服务；全量重编估计 20–45 分钟；llama-server 内部改动可能影响插件

**→ 请决定：升级 / 不升级 / 先实测再定。**

### Q4. 上下文长度设多少？

- [ ] **8192**（插件默认，KV 144 MiB，block 级流水线够用）
- [ ] **16384**（KV 288 MiB，只多花 144 MiB，为大表格/长公式留安全垫）
- [ ] 32768 或更高（KV ≥576 MiB，仅整页单次解析场景需要）

**→ 请决定：`resources.contextLength` 取值。**

### Q5. PP-DocLayoutV3 与 llama-server 是否同卡？

插件默认 `pipeline.cudaDevice = gpu:0`，两者会共用同一张 4060。
本机另有 **Intel Arc 核显**，但 PP-DocLayoutV3 的 Paddle 推理路径**只支持 NVIDIA GPU**（插件注释明确："CUDA 不可用时解析失败，不会切换 CPU"）。

**→ 请决定：是否接受同卡共存（预计仍有充足余量），或需要进一步实测 Paddle 侧的实际显存开销。**

---

## 9. 本报告中标注为「估算 / 未验证 / 需补充调研」的条目

| 条目 | 状态 |
|---|---|
| llama.cpp CUDA 运行时开销 250–400 MiB、视觉计算图 300–900 MiB | **估算**，基于架构参数推导，未实测 |
| PP-DocLayoutV3 的 Paddle Inference CUDA 运行时开销 0.6–1.5 GiB | **估算**，未找到官方公开数值 |
| 重编译耗时 20–45 分钟、峰值磁盘 2–4 GB | **估算**，未实测（用户禁止编译） |
| Q4_K_M "~1.7× faster than F16" | **发布者自述**，无第三方复现 |
| 各量化档在 OmniDocBench 上的实际质量差异 | **未找到公开证据** |
| `cstr/paddleocr-vl-1.6-GGUF` 是否能被 llama.cpp mtmd 加载 | **需补充调研** |
| `Mungert` / `cstr` 仓库许可证 | **未找到公开证据** |
| 插件不传 `--jinja` 时 llama-server 的模板行为 | **需首次启动后实测确认** |
| 本机实际推理速度（tok/s、单页耗时） | **未实测**（用户禁止下载/运行模型） |

---

## 附录：证据 URL 汇总

**模型仓库**
- <https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6>
- <https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6-GGUF>
- <https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6/raw/main/config.json>
- <https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6/raw/main/preprocessor_config.json>
- <https://huggingface.co/api/models/PaddlePaddle/PaddleOCR-VL-1.6-GGUF/tree/main?recursive=true>
- <https://huggingface.co/api/models/PaddlePaddle/PaddleOCR-VL-1.6/tree/main?recursive=true>
- <https://huggingface.co/SanjeevSOLANKI/PaddleOCR-VL-1.6-GGUF>
- <https://huggingface.co/api/models/SanjeevSOLANKI/PaddleOCR-VL-1.6-GGUF/tree/main?recursive=true>
- <https://huggingface.co/mradermacher/PaddleOCR-VL-1.6-GGUF>
- <https://huggingface.co/api/models/mradermacher/PaddleOCR-VL-1.6-GGUF/tree/main?recursive=true>
- <https://huggingface.co/api/models/mradermacher/PaddleOCR-VL-1.6-i1-GGUF/tree/main?recursive=true>
- <https://huggingface.co/api/models/Mungert/PaddleOCR-VL-1.6-GGUF/tree/main?recursive=true>
- <https://huggingface.co/api/models/cstr/paddleocr-vl-1.6-GGUF/tree/main?recursive=true>
- <https://huggingface.co/PaddlePaddle/PP-DocLayoutV3>
- <https://huggingface.co/api/models/PaddlePaddle/PP-DocLayoutV3/tree/main?recursive=true>
- <https://huggingface.co/api/models?search=PaddleOCR-VL-1.6&full=true&limit=100>

**llama.cpp**
- <https://github.com/ggml-org/llama.cpp/pull/18825>（PaddleOCR-VL 支持，2026-02-19 合并）
- <https://github.com/ggml-org/llama.cpp/pull/19799>（llama-server 模板修复，2026-02-22 合并）
- <https://github.com/ggml-org/llama.cpp/pull/16701>（前身 WIP，未合并）
- <https://github.com/ggml-org/llama.cpp/issues/25339>（peg-native format 报错，2026-07-06，open）
- <https://github.com/ggml-org/llama.cpp/issues/22561>（CUDA 13 Docker 镜像问题）
- <https://github.com/ggml-org/llama.cpp/releases>
- <https://blog.ngxson.com/using-ocr-models-with-llama-cpp>

**PaddleOCR 官方文档**
- <https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/PaddleOCR-VL.html>

**本地只读证据**
- `D:\AI\llama.cpp\src\llama-arch.cpp:136`、`src\models\paddleocr.cpp`、`tools\mtmd\models\paddleocr.cpp`、`tools\mtmd\clip-impl.h:355,409`、`docs\multimodal.md:38`
- `D:\AI\llama.cpp\update.ps1`
- `D:\AI\llama.cpp\scripts\local\qwen-embedding.ps1:10`
- `D:\Code\Python\Umi-OCR-Plugin\win32_PaddleOCRVL_1_6\config.py`、`api.py:110-150,224-250`
