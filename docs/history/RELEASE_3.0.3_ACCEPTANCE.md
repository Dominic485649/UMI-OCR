# Umi-OCR 3.0.3 验收契约与冻结状态

本版合并此前 3.0.2 的动态批量队列、拖拽排序与移除、导入、文档右键单件重新 OCR、忽略区域、输出收尾、配置折叠与枚举热配置修复，以及旧源码刷新入口停用和组合候选 CUDA 对应源码串包修复。识别引擎、模型字节与精度、依赖锁和 Host API 兼容范围不变。

本文件区分交付要求、历史结果与 **2026-10-22 本轮 fresh 重建开始前**的冻结状态，不是最终产物通过证书。源码冻结后的实际交审答复及新门禁结果，写入新的具名审查/审计记录和产品 `LICENSES/` 派生元数据；不得回拷 PASS 修改 canonical source，或把旧报告改写成新通过。

## 历史：2026-10-21 R2 已实际完成的验收

R1（`2394ea5d`）的自动回归是中间记录，不覆盖随后补入的组合 CUDA 源码串包修复。包含该修复的 **R2 已重新构建并完成下列验收**，不能再描述为“R2 尚未重建”或“从未验收”。R2 内部冻结提交为 `b0518fff09d0c0dc730c2bd629a1e1415b354094`。

以下文件均属于历史目录 `build/audit/3.0.3/review-20261021-r2/`，只证明当时的 R2 文件，不是本轮新目录产物的 PASS。

| 历史 R2 范围 | 已有记录 |
|---|---|
| 纯本体、CUDA 组合与包内基础回归 | `base-tests.log`、`combined-tests.log`、`automated-local-candidates.json` |
| 旧刷新入口安全回归、组合 CUDA 来源边界与实际源码选择 | `helper-source-tests.log`、`cuda-overlay-tests.log`、`combined-cuda-source-validation.log`、`combined-cuda-source-selection.json` |
| 真实热 GUI、插件切换、语言/主题/HTTP 配置与归档重装后的复验 | `hot-ui-local.json`、`hot-ui-installed.json` |
| Windows Shell 托盘、退出前独立 HTTP 就绪与正常退出 | `tray-local.json`、`tray-installed.json` |
| 真实 CUDA 图片/PDF/双层 PDF、二维码、HTTP/CLI 与失败路径 | `gpu-workflows-local.json`、`gpu-workflows-installed.json` |
| 最终双归档全新安装与逐文件一致性 | `base-install-integrity.json`、`candidate-install-integrity.json` |
| 对应源码镜像/ZIP/成员哈希、来源、独立产品复制一致性与隐私核验 | `local-source-products-verified.json`、`source-products-verification.log` |
| 模型字节与原离线种子一致性 | `model-local-staging.json`、`model-product.json`、`model-installed.json` |

历史汇总入口为该目录的 `REVIEW_REQUEST.md`。R2 后续已实际交付程序及文案，并获用户推送同意，main/tag 已推送；旧 JSON 的创建时点状态不否定后来的授权。但该同意不延用于本轮新程序，R2 的自动化结果也不等于完整人工清单通过。

## 冻结截点：2026-10-22，本轮新构建尚未开始

| 项目 | 此截点记录 |
|---|---|
| 内部起始 HEAD | `b0518fff09d0c0dc730c2bd629a1e1415b354094`；不是尚未生成的新产物的最终来源声明 |
| 已有公开 host `main` / `v3.0.3` | `fa5613d4d184c46a4e212ce589f19caa96a3f7d6` |
| 已有公开 CUDA `v3.0.3` | `f9235da667bf87dbc070029169aa0c228701b9a0` |
| 源标签与二进制的区别 | 两个 `v3.0.3` 标签已公开；3.0.3 binary Release 尚未创建、上传或公开 |
| 本轮重建 | 计划修正正式门禁接线，在全新目录以 non-`LocalCandidate`、`-SkipArchive` prepare；此截点尚未构建 |
| 本轮真实本地验收、source/payload 冻结及正式门禁 | 尚无本轮实际结果；不得继承 R2 或更早 PASS、回执、绑定或归档哈希 |
| 本轮审查同意 | 仍须交付本轮实际程序和两份 Release 文案后取得；允许替换两个公开标签不等于已验收新程序 |
| 历史保留 | 3.0.2 标签、草稿、旧报告与冻结身份不改写 |

## 本轮交付顺序与证据归属

1. **新目录 prepare 与真实本地验收。** 使用批准的 fresh noncandidate `-SkipArchive` 路径，生成实际本体与 CUDA 组合程序，执行本轮基础/组合、热 GUI、托盘/HTTP/退出、GPU、源码/许可和模型核验。prepare 不是正式归档通过。
2. **固定实际 source 与 payload。** 分别冻结本体及 GPU overlay 的 canonical source、运行载荷、版本、来源、成员哈希和门禁绑定；不从旧包猜源，不刷新旧目录。
3. **交审。** 提供上述实际程序、两份 Release 文案、真实结果、未验收限制及本项目清理预演，明确请求用户审查。只有当次明确同意后才更新公开 main/tag；一般发布请求、旧版同意或历史 HDR 反馈不能替代。
4. **公开对应源码/tag。** 在获同意后更新与被冻结实际源码匹配的公开源码及两个 `v3.0.3` 标签。正式 fresh source gate 必须等标签匹配，不在此前伪填 PASS。
5. **fresh 正式门禁。** 对同一冻结本体与 GPU overlay 分别提供匹配 `artifact_kind`、版本及 source/payload binding 的显式 `--release-gates` 输入并实际验证。验证输出不能充当门禁输入；用户同意也不能补造未执行的技术测试。
6. **受限 finalize。** 仅在适用门禁满足后生成产物派生报告、正式归档，并从最终归档在新目录重装及复验，再发布和核验实际交付。不得重建或更换已审 source/payload，也不得把最终 PASS 回填进 canonical source 来重算快照。必需门禁未满足时保持阻塞。

最终产物的派生门禁报告位于本体 `LICENSES/`，CUDA overlay 位于 `LICENSES/plugins/win32_PaddleOCRv6_CUDA/`，包括 `source-delivery.json`、`current-source-e2e.json`、`RELEASE_EVIDENCE.json` 和 `RELEASE_EVIDENCE.md`。它们与源码中的本冻结状态有不同用途，不能互相冒充。

## 未完整验收的人工边界

R2 未完成下列全轮覆盖；在本轮取得实际新证据前，仍须如实列为未验收，不将任何旧 HDR 引语移用为本轮实测或同意。

- 原生 Explorer 文件/文件夹拖放、系统鼠标拖序与右键手势、默认外部阅读器行为；Qt 合成事件或路径分派观察不能替代。
- GUI 单件重新 OCR 的完整菜单流程、成功/失败/取消后的旧成功产物哈希保护，以及完整预览忽略区域过滤、保存和返回文档列表流程；后端回归不等于全流程通过。
- 本轮程序的人工 HDR 捕获与观感、混合 HDR/SDR、多显示器 DPI、负坐标及完整人工视觉清单；历史功能反馈不能补齐这些证据。

## 本轮实际结果仍须记录的内容

以下信息由后续真实交审包及产物元数据填写，**本源码冻结文档不预填数值或通过结论**。

- 新 prepare/组合程序的实际路径、构建入口与日志、最终源码版本/来源及本体与 GPU overlay 各自的 source/payload 绑定。
- 本轮包内回归、真实热 GUI、Windows 托盘、退出前 HTTP 就绪、正常退出、GPU 原始回执与适配器/运行时匹配、模型字节及对应源码/许可检查结果。
- 人工项逐项实测结果和仍未完成的限制，以及用户对实际程序和两份文案的明确审查答复、时间与所指对象。
- 获同意后实际更新的公开 commit/tag、fresh gate 输入/输出路径及结果；不能只凭已有 `v3.0.3` 标签视为匹配。
- 受限 finalize 的正式归档文件名、大小、SHA-256、归档重装后的逐文件与运行复验、最终可运行目录及实际发布下载核验。
- 本项目具体清理目标、理由、占用检查、链接边界、用户数据/历史证据保留项与结果；未列明的大文件、未知数据或新权限阻塞须停止该动作，不扩大到兄弟项目。
