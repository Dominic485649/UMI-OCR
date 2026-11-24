# 2026-11-16 依赖裁切本地交付审阅
## 当前交付状态
本体与两个插件的最终运行归档、独立源码归档、三组件全新重装和定向组合验收已完成。固定安装事务已成功提交，最终载荷与原有保留文件的摘要核验通过。最终运行归档已移至 release 顶层，移动前后摘要一致；源码归档仍保存在 build。固定安装更新后未再次启动程序，运行验收采用本轮相同载荷的隔离组合结果。
本报告记录本地交付，不构成 GitHub 发布批准。尚未推送、打发行标签或发布 Release。
| 组件 | 本次及固定安装实际版本 | 固定安装事务开始前版本 | Host API |
| --- | --- | --- | --- |
| 本体 | 3.1.5 | 3.1.4 | 提供 2.9 |
| CUDA | 3.0.6 | 3.0.5 | >=2.7,<3.0 |
| PaddleVL | 3.1.4 | 3.1.3 | >=2.9,<3.0 |
实际本体构建对应源码提交：`ddca1e02f07e924e5aa60e339205a6b4f052edda`。后续交付文案提交不属于这个冻结源码快照。
### 本地归档位置
- 本体运行：[最终运行归档](../release/Umi-OCR_v3.1.5_Windows_x64.tar.xz)；独立源码：[本体源码目录](../build/artifacts/dependency-trim-host-315-20261116-r1)。
- CUDA 运行：[最终运行归档](../release/Umi-OCR-Plugin_v3.0.6_Windows_x64_CUDA.tar.xz)；独立源码：[CUDA 源码目录](../build/artifacts/dependency-trim-plugins-20261116-r1/CUDA)。
- PaddleVL 运行：[最终运行归档](../release/Umi-OCR-Plugin_v3.1.4_Windows_x64_PaddleVL.tar.xz)；独立源码：[PaddleVL 源码目录](../build/artifacts/dependency-trim-plugins-20261116-r1/PaddleVL)。
- 固定安装：[release/Umi-OCR](../release/Umi-OCR)，已完成完整载荷更新。release 顶层仅保留该目录及三个组件各自最新、紧邻上一版本的运行归档；本轮没有删除上一版本归档。
| 归档 | 字节 | SHA-256 |
| --- | ---: | --- |
| Umi-OCR_v3.1.5_Windows_x64.tar.xz | 166,775,836 | `869b0db1b65765da4f72a31bee8487f77f445b181e8439246a2ac7be6fcebaf4` |
| Umi-OCR_base_v3.1.5_CorrespondingSource.tar.xz | 1,858,881,040 | `00d905851ccf7283b603a646272ebf6da584cdd7d3b7dd144aca4471ed05a3a6` |
| Umi-OCR-Plugin_v3.0.6_Windows_x64_CUDA.tar.xz | 1,954,824,344 | `44d8b20ebad1f5b9133b410912c87c9aa02a9e1a48391143c60821649e8f580c` |
| Umi-OCR-Plugin_cuda_v3.0.6_CorrespondingSource.tar.xz | 1,475,154,496 | `9103e3061edd4ca81f63bbdbe394228bfbdb4415e727db4b119fa25f9f138685` |
| Umi-OCR-Plugin_v3.1.4_Windows_x64_PaddleVL.tar.xz | 2,185,447,440 | `c38437c586f29881cf74bd3ce6fda253b3d97141b176d5a2856043458a68a90a` |
| Umi-OCR-Plugin_vl_v3.1.4_CorrespondingSource.tar.xz | 263,118,584 | `f9086a35bf27f66ddbf3f55f42625982ac8b8006e166160bebea3aec5e7b5ac2` |
## 验收范围与剩余门禁
- **本次实际执行：** 官方 Qt 本体构建、包审计、最简分包、运行/源码归档，以及三组件全新归档重装。最终组合载荷逐成员摘要一致。
- **本次实际运行：** 纯本体绑定与 DLL 来源、真实 EXE、第二实例、回环注册接口、Qt 运行时、QML 首屏及离线 Markdown 富预览。验收使用隔离组合，不拿自建配置覆盖用户配置。
- **GPU 历史复用：** CUDA 与 PaddleVL 按未变执行字节、最终归档成员与原 GPU/沿袭证据复用。本次没有重新 GPU 推理，不把复用写成重新执行。
- **未执行：** 截图、HDR、混屏、完整设备/语言/模型/驱动矩阵、完整模型联网下载、源码完整重建及上传后的匿名下载核验。
- **未完成的内部裁切：** 官方 Qt DLL 内静态 FFmpeg 没有被文件级投影移除。Paddle 大型原生库仍保留，未声称内部裁切完成。
- **公开分发限制：** 宿主 MuPDF 确切对应源码绑定、部分科学库精确原生构建来源、NVIDIA 及 AGPL/私有解锁组合许可仍有独立门禁。没有因本地通过而解除。
| 本次可核对统计 | 数值 |
| --- | ---: |
| Qt 投影保留文件 | 553 |
| Qt 投影删除文件 | 3,240 |
| Qt 投影删除逻辑字节 | 333,000,562 |
| 原 wheel 单独忽略的字节码 | 2 |
| 最简本体运行文件 | 1,793 |
| 三组件重装载荷文件 | 15,671 |
这些数值不是完整安装空间节省或性能测量。忽略字节码不代表文件已删除。
主要证据位于 `build/audit/dependency-trim-20261116-pip-r1`：
| 事实 | 回执 |
| --- | --- |
| 本体最终归档与成员 | [host-package-r1/result.json](../build/audit/dependency-trim-20261116-pip-r1/evidence/host-package-r1/result.json) |
| 三组件全新重装 | [combined-reinstall-r1/result.json](../build/audit/dependency-trim-20261116-pip-r1/evidence/combined-reinstall-r1/result.json) |
| 真实 EXE/CLI 与产品恢复 | [normal-exe-restore-r1.json](../build/audit/dependency-trim-20261116-pip-r1/normal-exe-restore-r1.json) |
| 重装 Qt/QML/富预览 | [combined-host-acceptance-r1/result.json](../build/audit/dependency-trim-20261116-pip-r1/evidence/combined-host-acceptance-r1/result.json) |
| GPU 复用边界 | [combined-plugin-gpu-reuse-r1.json](../build/audit/dependency-trim-20261116-pip-r1/evidence/combined-plugin-gpu-reuse-r1.json) |
| 固定安装精确预演 | [fixed-preview-r1/preview.json](../build/audit/dependency-trim-20261116-pip-r1/evidence/fixed-preview-r1/preview.json) |
固定更新预演仅退役独立旧所有权清单覆盖的程序载荷，模型、配置、日志、私有解锁 DLL 和未知文件均原地保留。不终止用户进程。正式事务为 COMMITTED，实际最终版本已读取核对；15,671 项最终载荷匹配，3,664 项原有保留文件摘要不变，33 项受保护载荷独立核对。事务替换或新增 180 文件、退役 8,212 项旧程序载荷，备份清理无阻塞，旧载荷备份剩余为零。这不是磁盘物理释放量测量。
## 清理边界与程序、文案审查
E 工作根尚未删除。原冻结 RETAIN 集合已通过内部来源归档和独立归档映射保存在 D 盘；交付类 HOLD 候选副本已有字节覆盖核对，但未执行删除；原生 HOLD 已形成精确候选与保留补集，补集在 D 留存并核验；冻结后新增项也已单独核对。整根最终预演已完成，但实际删除仍未批准或执行。这不是整根删除许可。
已将原生诊断精确清单复制到 D 盘，源/目标逐文件摘要一致，已有历史摘要全部匹配。原始绝对路径记录没有改写，不声称迁移后重新构建或运行。
| 已迁回的原生诊断材料 | 数值 |
| --- | ---: |
| 文件 | 2,142 |
| 字节 | 462,772,822 |
| 历史摘要不匹配项 | 0 |
入口：[诊断材料保留回执](../build/audit/dependency-trim-20261116-pip-r1/evidence/native-diagnostic-retention-copy-r1.json)。另外，最终插件归档及原审计已按独立回执迁回 D 盘；这不等于整个 E 工作根已经保留完成。
已补充[预编译头缓存归属回执](../build/audit/dependency-trim-20261116-pip-r1/evidence/native-pch-ownership-r1/receipt.json)。主线程核对统计与引用闭合，并抽查 CMake、GN 各一条实际生产规则；没有独立重验全部缓存归属。原临时物理观测未完整落盘，补充回执明确注明，不以新提取记录冒充原始逐项记录。
| 规则与直接输入保留 | 文件数 | 新复制字节 |
| --- | ---: | ---: |
| 新增保留 | 280 | 52,388,131 |
| 复核并复用原诊断副本 | 47 | 0 |
| 核对 D 盘原地审计材料 | 4 | 0 |
全部列明输入均已绑定 D 盘保留位置及核对摘要，入口为[补保留回执](../build/audit/dependency-trim-20261116-pip-r1/evidence/native-pch-input-retention-r1.json)及[主线程抽查回执](../build/audit/dependency-trim-20261116-pip-r1/evidence/native-pch-ownership-primary-review-r1.json)。原大 toolchain 规则未哈希的记录保持不变，本次按源文件与已保留副本补充摘要绑定，不回填旧记录。
这些材料仅覆盖直接输入与规则，不是完整传递头闭包或可重建性证明。没有读取、哈希或删除 PCH 载荷，相关缓存仍保留在 E 盘，不将候选逻辑体积记作已释放空间。
原 RETAIN 集合的内部来源归档 r1 在预检阶段遇到 Qt SDK 内部硬链接而停止，尚未创建归档或成员清单。原失败、日志及[失败分析](../build/audit/dependency-trim-20261116-pip-r1/evidence/retained-source-archive-r1/failure-analysis.json)保留。没有修改或删除 E 盘原件。
后继 r2 内部保留驱动已通过[硬链接定向测试](../build/audit/dependency-trim-20261116-pip-r1/evidence/retention-hardlink-tests-r1.json)：完整枚举别名、核对同根与文件身份、拒绝越界别名和错误身份，归档保存独立普通文件字节并记录原关联，不声称还原 NTFS 硬链接关系。共享运行包的硬链接拒绝规则没有改变。测试通过不代表完整来源归档通过，后继实际封存终态另记。
后继 r2 来源归档已完成逐成员验证，并复制到 D 盘项目保留目录。复制时核对源流 SHA-256，并独立重哈希目标；复用同一完整归档的原逐成员验证，没有声称再次解包或重建。原路径和回执不改写，新增[迁回映射回执](../build/audit/dependency-trim-20261116-pip-r1/evidence/retained-source-archive-copy-r2.json)绑定 D 盘位置。
| 冻结 RETAIN 集合的保留结果 | 数值 |
| --- | ---: |
| 归档普通文件 | 400,817 |
| 归档目录 | 44,221 |
| 原文保留的符号链接 | 13 |
| 已逐项验证的归档成员 | 445,051 |
| 另行保留并重哈希的插件最终归档 | 4 |
| 内部来源归档字节 | 4,239,375,952 |
内部归档为 [Umi-OCR_InternalRetainedSources_20261116_r2.tar.xz](../build/retained/dependency-trim-20261114-r1/source-archive-r2/Umi-OCR_InternalRetainedSources_20261116_r2.tar.xz)，SHA-256 为 `3027290c9ae966933d06521b151e0bfa062e5c9c71fe77d00495cf3591c3a0fa`。这是内部保留材料，不是新增公开发行附件；归档大小不代表已释放空间。原始 E 盘材料及本轮 E 盘归档均未删除，HOLD 内容没有因此被放行。
候选副本已完成当前字节与独立清单核对，未覆盖的原始锁、清单和合成夹具已另行复制保留。具体路径、保留项、当时占用和未放行范围见[候选副本清理预演](DEPENDENCY_TRIM_20261116_CLEANUP_PREVIEW.md)。本轮未删除这些 E 盘候选副本，原生 HOLD 缓存及 E 整根仍未放行。运行归档已由 build 移至 release；原保留回执中的旧位置通过本次归位回执衔接，不改写原记录。
本轮解包后留下的空祖先目录已有[具体清理预演](../build/audit/dependency-trim-20261116-pip-r1/evidence/empty-extraction-cleanup-preview-r1.json)，已在固定安装通过后按该预演重新检查空树、路径与进程占用，删除两棵空祖先树中的六个目录，删除文件数为零。清理范围未扩大到其它目录。
程序和文案须一并审查，以下为本次组件草稿：
- [本体依赖裁切文案](RELEASE_BASE_DEPENDENCY_TRIM_DRAFT.md)
- [CUDA 3.0.6 文案](RELEASE_CUDA_3.0.6_DRAFT.md)
- [PaddleVL 3.1.4 文案](RELEASE_PADDLEVL_3.1.4_DRAFT.md)
本次构建、归档重装、组合验收、固定安装更新及本地运行归档归位已完成。E 工作根清理和公开发布尚未完成；来源、许可及当次审查门禁保持，不将本地交付完成等同于全部任务完成。
### 固定安装与本地归位终态证据
- [固定安装完整核验回执](../build/audit/dependency-trim-20261116-pip-r1/evidence/fixed-update-r1/result.json)与[正式事务回执](../build/tmp/dependency-trim-20261116-fixed-transaction-r1/result.json)共同绑定实际载荷及原有数据保留结果。
- [运行归档路径映射](../build/audit/dependency-trim-20261116-pip-r1/evidence/local-archive-promotion-r1.json)记录原路径、最终路径及移动前后核验摘要；对应源码、原审计和历史路径记录原样保留。
- [空目录实际清理回执](../build/audit/dependency-trim-20261116-pip-r1/evidence/empty-extraction-cleanup-r1.json)仅涉及预演列明的 D 盘解包祖先目录，不涉及 E 盘清理。
- [主线程收尾核对](../build/audit/dependency-trim-20261116-pip-r1/evidence/local-delivery-completion-review-r1.json)核对独立终态、驱动摘要、载荷清单一致性、当前版本和最终路径。载荷、用户数据及归档摘要采用刚完成的事务和移动核验，未重复全载荷哈希、GPU 或固定目录运行测试。
### E 工作根收尾的独立状态
[整根清理审阅与最终预演](DEPENDENCY_TRIM_20261116_E_ROOT_CLEANUP_REVIEW.md)已列出原生材料的完整互斥分区、D 留存位置、内容核验及尚未验证限制。新增原生补集已逐成员核验，已有 D 诊断和直接输入副本已重核源/目标摘要；llama 全目录、库、生成输入和历史证据保守留存。
全根逐项预演已覆盖当前全部文件、目录和链接，并明确将 E:/Umi-OCR-build 本身列为最后移除目标。没有以笼统 HOLD 遗留未列明路径，但实际永久删除仍需当次范围批准及执行前检查；后继严格执行器已发现冻结只读属性和进程可检查性阻塞，详见[执行器审阅](DEPENDENCY_TRIM_20261116_E_DELETE_EXECUTOR_REVIEW.md)。此状态不等于 E 根已删除，也不代表完整传递闭包或搬迁后重建通过。
删除工具已补齐为 r2，并在 D 专属合成夹具完成定向回归。工具及自测绑定见[执行器补充交接](../build/audit/dependency-trim-20261116-pip-r1/evidence/e-root-executor-handoff-r2.json)。本体、插件和固定安装未因此再次修改，真实 E 删除仍未执行，也没有通过清只读、改权限或忽略不可检查进程放行。
