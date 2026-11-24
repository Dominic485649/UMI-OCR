# GPU 兼容修复与依赖精简统一整合：进度与容量阻塞

日期：2026-11-18，续接记录：2026-11-19。**本地交付已完成：固定安装为本体 3.1.5、CUDA 3.0.7、PaddleVL 3.1.5。** 两份新精简运行包通过真实 GPU 工作流、实际归档重装及组合烟测；首轮 `WinError 112` 中断副本和存在文件回带的首批归档均未用于交付。未公开发布。

## 一、实际安装和候选版本

固定安装 `release/Umi-OCR` 没有更新，本轮重新读取清单确认：

| 组件 | 固定安装实际版本 | 本轮源码/候选目标 |
| --- | --- | --- |
| 本体 | 3.1.5 | 复用 3.1.5 已核验归档，不重编 Qt |
| CUDA | 3.0.6 | 3.0.7，新精简候选已实测 |
| PaddleVL | 3.1.4 | 3.1.5，新精简候选已构建并通过包内锁/定向测试；真实模型验收另列 |

组件独立维护版本，不为对齐主程序而联动改版。本轮不下载、修改、量化或删除模型，不增加 CPU 回退。

## 二、修复依据与硬件边界

- [原 Issue](https://github.com/Dominic485649/UMI-OCR/issues/4) 的直接失败点是 Paddle 微小 CUDA 运算自检，不是 llama.cpp 或 ccache。旧两核心分别只有 sm75/80/86/89 cubin，无 PTX。
- 官方 Paddle GPU 3.3.1 / CPython 3.13 / CUDA 12.9 wheel SHA-256 为 `71aed9d3d77f571eeee2e2deb6b33a06d18d82424bb04a81435480b7418fdab4`。新两核心逐个实查含 sm75/80/86/89/120 cubin，无 PTX，原覆盖未缩减。
- 兼容检查按每份核心提供者判断，考虑同主版本 cubin 的后代小版本兼容与普通 PTX 前向兼容，不取架构并集、不把“算力至少 7.5”当作充分条件。保留严格 float32 标量自检、同步、失败类型及日志位置，宿主不导入 Paddle。
- **MX250（sm61）明确不支持**，仅验证提前拒绝提示，不计实际 GPU OCR 通过。
- **RTX50 实机一直为 NOT_RUN。** RTX 4060 Laptop / 驱动 621.14 的结果不代替 RTX 5060 验收；没有向报告者发送候选或关闭 Issue。

## 三、文件级精简纠正

首批 raw pip 种子恢复了原精简终态已移出的成员。相同版本 pin 并不证明相同运行载荷，因此暂停首批归档作为安装输入，不回写首批的 PASS/FAIL、摘要或来源记录。

新规则使用独立旧最终载荷所有权清单和 Stored-ZIP 逻辑成员：不把固定安装中不属于旧归档的残留文件当作应继承的闭包，不按 `tests/include/src` 或后缀统一删除。

| 精确锁 | 锁定输入 | 保留成员 | 明确排除 | 排除逻辑字节 |
| --- | ---: | ---: | ---: | ---: |
| [CUDA](../build/runtime-inheritance-cuda-cu129.lock.json) | 11,092 | 6,252 | 4,840 | 1,086,002,675 |
| PaddleVL 独立插件项目中的 `tools/runtime_inheritance_vl_cu129.lock.json` | 13,558 | 8,706 | 4,852 | 1,086,773,594 |

最大的回带项是约 1.03 GB 的 `nvidia/nvjitlink/lib/x64/nvJitLink_static.lib`，旧精简运行包不含它；不是删除动态运行库。原始完整 wheel 和来源材料继续保留。

[精确投影工具](../build/tools/project_inherited_runtime.py)已接入两个正式构建入口：

- 复制时仅跳过锁定名称、大小和摘要都匹配的成员；补丁后独立核对完整保留集合，未知、缺失、篡改、占用或已冻结目录均拒绝。
- 实际移出的新候选原件留在外部审计目录；只读原始种子不变。GPU/依赖原生库、元数据和许可保留；具名 Distro 开发命令的内嵌完整入口单独核对，不删除 Python API。
- 未变运行成员逐字节继承。已明确核对的 pip RECORD 外部开发入口行变化，以及一处完整 AST 相同的引号/空行变化单列依据，保留本次真实输出，不假称它们全部字节相同。
- VL 继续继承已审定 CUDA 种子的五项可选包排除和具名开发命令排除，不恢复无关依赖；保留派生 OpenCV、ModelScope 下载子集、Stored-ZIP、科学计算子集与精简 llama。
- 对应源码必须含精确锁、实际 helper 及测试；运行标识明确声明为应用闭包，不冒充完整上游 wheel。

## 四、本次实际验证

证据根：[build/audit/gpu-compat-20261117-r1](../build/audit/gpu-compat-20261117-r1)。

| 验证 | 实际结果及范围 |
| --- | --- |
| [受影响的投影/聚合/分包链](../build/audit/gpu-compat-20261117-r1/inheritance-directed-r1/result.json) | 104 项通过，运行期间绑定输入未变 |
| [新增精确投影测试](../build/audit/gpu-compat-20261117-r1/inheritance-directed-r1/exact-inheritance-stderr.txt) | 15 项通过，含真实 Windows 共享冲突、原生代码/许可保护、未知成员、篡改及来源不变 |
| [VL 投影回归](../build/audit/gpu-compat-20261117-r1/inheritance-vl-projection-r1.log) | 16 项通过，使用项目专属夹具，不等于新 VL 真实模型验收 |
| [VL helper 快照入口](../build/audit/gpu-compat-20261117-r1/inheritance-vl-snapshot-r1.log) | 4 项通过：实际复制的 helper 在隔离子进程执行，覆盖 VL 正例、伪造开发入口、缺失 GPU 原生库及错误组件 |
| CUDA 新候选构建准备与包审计 | 精确逻辑闭包通过；新 staging 与覆盖层两轮审计通过；最简副本复制因磁盘满失败，不记为完整构建/打包通过 |
| [新精简 CUDA 真实工作流](../build/audit/gpu-compat-20261117-r1/exact-cuda-workflows-r2/result.json) | PASS：两图批量、两页 PDF、可搜索 PDF、JXL 二维码、真实释放、空闲拒绝、错误设备路径 |

[独立运行/源码绑定检查](../build/audit/gpu-compat-20261117-r1/exact-cuda-runtime-source-r1.json)另行确认：真实受测候选的 6,252 项逻辑 vendor 文件逐项等于精确锁，4,840 项排除成员在松散文件和 Stored-ZIP 中都不存在；9 项关键锁/工具/测试同时匹配当前工作区、实际导出源码与源码快照。它不授予最终归档或新 VL 验收通过。

新 CUDA 测试观察到实际独立 worker，自检为 PASSED、设备算力 8.9；实际 Paddle/CUDA 提供者路径和摘要匹配本候选原生锁。源码与模型摘要未变，宿主未导入 Paddle。这里不是沿用首批完整依赖候选的 GPU 结果。

为在容量阻塞下完成 CUDA 实测，将本轮新恢复的本体 1,793 文件逐文件同卷转移到新 CUDA 覆盖层，装配前后均按独立本体载荷清单核对，没有复制大型依赖或删除文件。该目录现为**两组件测试组合，不是纯插件分包输入或最终三包重装**。原绝对路径记录不改写，转移本身不冒充重新运行验收：[装配回执](../build/audit/gpu-compat-20261117-r1/exact-two-component-assembly-r1/result.json)。

原技术阶段的设备 mock、协议、七语言、VL/llama/表格及首批实际三组件 EXE/HTTP 记录继续保留。未变检查器和本体的旧证据仅在原输入摘要及未改行为范围内复用；首批有完整额外成员的 VL PASS 不代替新精简 VL 验收。Qt、离线预览等未变部分沿用[原精简终态](DEPENDENCY_TRIM_20261117_FINAL_REPORT.md)，没有重跑完整矩阵。

截图捕获、HDR、混屏、RTX50 实机及完整设备/模型/语言矩阵继续 NOT_RUN。

## 五、11 月 18 日容量失败与原候选位置（历史）

- 新 CUDA 原构建目录：`build/staging/gpu-compat-20261118-exact-r1/cuda307-r5`，含对应源码和快照。
- 当前实际受测的本体 + CUDA 两组件组合：`build/artifacts/gpu-compat-20261118-exact-r1/cuda307-r5`。
- `build/artifacts/gpu-compat-20261118-exact-r1/cuda307-r5-runtime` 是磁盘满中断的最简副本，**没有成功分包回执，可能有截断成员，不用于安装**。
- [原始失败日志](../build/audit/gpu-compat-20261117-r1/cuda-exact-build-r5-stderr.txt)保留 `WinError 112`；未在半成品上补拷贝冒充全新构建，也没有启动后续 VL 大规模复制。
- 新工作父目录使用普通 NTFS 无损压缩，合成探针明确完成压缩后核对字节、普通文件属性和实际分配；没有使用 WOF/CompactOS、改原始种子/现有安装或删除旧文件。压缩不保证足够空间，容量阻塞仍实际存在。

11 月 18 日中断时，VL 精简构建、两插件最终归档及重装、固定安装和归档保留处理均未完成。下一阶段只复用已核对的纯 CUDA 暂存和锁定输入，不在失败的最简拷贝上续写或改写历史审计。

### 11 月 19 日：VL 精简构建已完成

- 新 VL 构建首次在精确门禁处发现 `bin/distro.exe` 与原始 `RECORD` 不符。逐字节核对证明 EXE 仅 ZIP 时间戳不同，`RECORD` 仅该开发命令的摘要行不同。所有其它现有输入一致，无缺失保留成员。[输入差异](../build/audit/gpu-compat-20261117-r1/vl-r6-exact-input-diff.json) · [时间戳核对](../build/audit/gpu-compat-20261117-r1/vl-r6-pip-launcher-timestamp.json)。
- 使用相同的离线 hash-pinned wheel 和固定 `SOURCE_DATE_EPOCH` 重现这两个生成文件，保留失败时原字节；未替换任何 GPU 动态库、Python API 或模型。正式构建只在固定客户端依赖安装阶段固定该值，用后恢复环境，已在插件仓提交 `e080e517c3cee0071404e63f6819422488db65c9`。
- 在本轮新建、**未冻结**的 `vl315-r6` 继续与实际快照逐字节相同的构建尾段。仍执行完整精确门禁、原生运行/来源校验、插件 mock、4 项隔离 helper 快照测试、Stored-ZIP 审计和全量运行锁。8,706 项逻辑 vendor 成员保留；4,840 项随 CUDA 种子已排除，另 12 项本轮精确移到包外审计。没有整树复制或重写原始失败。另在**已精简聚合后的实际载荷**重跑[跨页表格检查](../build/audit/gpu-compat-20261117-r1/exact-vl-stored-tables-r2.json)，通过重复表头、分组 ID、宽度/图片隔断及合并单元格定向检查，不计为模型推理。详见[继续构建回执](../build/audit/gpu-compat-20261117-r1/vl-build-r6-continuation-r1.json)。
- 首次真实 VL 测试加载了本地模型并进入 Spotting 推理，测试进程提前退出、未留下最终验收回执；保留[请求记录](../build/audit/gpu-compat-20261117-r1/exact-vl-http-r2/http.jsonl)及同一任务的原始模型服务日志。此后一次重试在启动前测得可用显存 1,258 MiB，低于本轮测试预留的 4,096 MiB，未启动。不能把这次预检等同于首次退出的根因。未终止用户进程。

### 11 月 19 日：对应源码通过核验，运行归档因容量再次停止

两插件按现有最简规则从已审计暂存流式写入 `tar.xz`，没有创建整树副本。两份独立对应源码已写完，随后独立核对了全部成员字节、XZ 末尾和归档 SHA-256：CUDA 230 文件，PaddleVL 97 文件。源码归档可按[独立核验回执](../build/audit/gpu-compat-20261117-r1/stream-package-capacity-stop-r1.json)复用；这不是对未解决的公开对应源码或许可门禁的放行。

两份**运行归档写入时均触发 1.5 GiB 余量保护并退出**。CUDA `1,411,213,860` 字节、PaddleVL `1,814,026,495` 字节的文件只是失败现场，不可安装、重装或移入 release，保留原件。已通过逐文件闭包审计的暂存没有因此废弃，不需要重建 Qt、llama 或两个插件运行时。

容量核对时 D 盘可用 `1,587,245,056` 字节（约 1.48 GiB）。在 D 盘同时保留本轮运行归档、全新运行/源码重装、必要的固定事务副本和余量，按本轮实际逻辑载荷与首批较大归档大小**保守估算需先留约 26 GiB**；这不计 NTFS 压缩收益，也不假设删除任何失败副本。最近 RTX 4060 观测仅约 1.44 GiB 可用显存，仍未达到本轮 VL 真实验收所预留的 4 GiB。

两个运行归档重试使用新路径，通过任务打包器的 `--verified-source-receipt` 核对并复用上述源码，不覆盖半成品。共 4 项[流式打包及复用夹具](../build/audit/gpu-compat-20261117-r1/stream-pack-tests-r2-stderr.txt)通过，包括与原最简目录逐字节等价、重新解包、拒绝冲突/变更及安全复用。夹具不计为实际运行归档成功。没有进行组合重装、固定安装、归档归位或清理。正式发布入口和授权门禁没有变化。

### 11 月 19 日：两仓容量恢复与新精简 PaddleVL 实测

- 写入并执行 D 盘至少留 **10 GiB**、两仓合计至多 **300 GiB** 的硬标准。逐项退役已知失败输出及可恢复旧副本后，从实际 NTFS 文件分配重新核对：两仓 **284.38 GiB**，D 盘可用 **155.14 GiB**，未跟随重解析点。详见[清理预演、执行与复核](GPU_COMPAT_20261119_SPACE_RECOVERY.md)。对应源码和有效新精简暂存均保留。
- [新精简 PaddleVL 真实验收](../build/audit/gpu-compat-20261117-r1/exact-vl-http-r4/result.json)通过。RTX 4060 Laptop 上真的走 Spotting、复杂文档回环 HTTP、两个消费者复用同一模型服务 PID、13 个文档块、标题/表格/公式/图片、非空官方标题 KMeans 和 JSON／MD／TXT 导出。记录了本轮实际 Paddle/llama GPU 模块及摘要；四个本地模型与运行锁前后不变。此前中断和显存预检记录仍为历史，不补写通过。
- 新打包容量护栏与原最简/源码复用用例共[六项定向检查](../build/audit/gpu-compat-20261117-r1/stream-pack-tests-r3-stderr.txt)通过。VL 实测占用暂存时，写前检查拒绝打包，没有生成新半包；验收进程正常退出后在全新路径重试。

### 11 月 19 日：两份最终运行归档及对应源码

| Windows x64 运行归档 | 字节 | SHA-256 | 独立核验 |
| --- | ---: | --- | --- |
| CUDA 3.0.7 | 2,507,677,320 | `85bb0cafecd298f1a76651632f14149dad3f677758dad872b3243cf9629b9677` | [6,163 个实际文件](../build/audit/gpu-compat-20261117-r1/exact-pack-cuda-r3/result.json) |
| PaddleVL 3.1.5 | 3,041,557,572 | `8ad541c357da564e918560a888ac71d9932bba68cc9cb8d65a9124e61f3870f5` | [7,147 个实际文件](../build/audit/gpu-compat-20261117-r1/exact-pack-vl-r4/result.json) |

新归档由现有精简暂存直接流式生成，不创建中间 tar 或整树副本。已验证 tar 成员字节、XZ 首尾和松散／Stored-ZIP 的精确闭包。两份独立对应源码按原始逐成员核验回执及实际 SHA-256 复用、不重压；确认未混入私有解锁实现、运行包不内嵌源码，详见[最终载荷与来源边界](../build/audit/gpu-compat-20261117-r1/exact-final-delivery-boundaries-r1.json)。两份运行包均超出 GitHub 单附件 2 GiB，不影响本地交付；本轮不上传、不更改交付格式，也没有进行匿名下载核验。

### 11 月 19 日：归档重装与三组件 EXE 验收

- [全新重装](../build/audit/gpu-compat-20261117-r1/exact-reinstall-final-r1/result.json)使用未变本体 3.1.5 归档和两份新插件归档，组合 **15,103** 个运行文件，与各自独立载荷摘要完全一致；两份对应源码也实际在新路径恢复和逐成员核验。没有用首批或旧安装替代重装。
- [首次 EXE 检查记录](../build/audit/gpu-compat-20261117-r1/exact-reinstalled-combo-native-r1.json)的 INI 文本断言失败，程序日志已显示采用 `cuda129`；该驱动没有等待 Qt 配置缓存。这条失败记录和原驱动保留。只修正测试驱动，由 Qt 读回隔离旧值，允许缓存落盘再退出，不改程序。 [复测](../build/audit/gpu-compat-20261117-r1/exact-reinstalled-combo-native-r2.json)通过：实际 EXE、回环注册（CUDA 和 PaddleVL）、CLI 转发、正常退出，以及 `cuda126` 写入夹具后确实保存为 `cuda129`；恢复测试配置，未接触固定用户配置。此次组合烟测不重复模型推理或截图/HDR/混屏测试。

### 11 月 19 日：固定安装及归档归位

- [固定安装事务](../build/audit/gpu-compat-20261117-r1/exact-fixed-update-r1/result.json)已提交：替换或新增 **228** 个程序文件，退役 **714** 个旧载荷拥有的文件，**3,665** 个保留文件摘要不变，事务旧载荷备份已清完。固定安装为 `release/Umi-OCR`，没有终止用户进程、清只读属性或迁移用户状态。
- [独立核验](../build/audit/gpu-compat-20261117-r1/exact-local-delivery-final-r1.json)重新读取固定目录三组件版本、两个插件的 Paddle 核心摘要、原有两份配置和私有 DLL 样本，并核对六份保留运行归档；测试配置没有覆盖固定安装。
- 新运行归档已[归位并复核摘要](../build/audit/gpu-compat-20261117-r1/exact-local-archive-placement-r1/promotion.json)：[CUDA 3.0.7](../release/Umi-OCR-Plugin_v3.0.7_Windows_x64_CUDA.tar.xz)、[PaddleVL 3.1.5](../release/Umi-OCR-Plugin_v3.1.5_Windows_x64_PaddleVL.tar.xz)。对应源码仍在 `build`，没有复制进运行包或放进 `release` 顶层。只处理已列明的两份过保留旧运行归档，见[预演及结果](GPU_COMPAT_20261118_CLEANUP_PREVIEW.md)。交付后两仓实测合计 **288.19 GiB**，D 盘空闲 **149.08 GiB**，详见[容量记录](GPU_COMPAT_20261119_SPACE_RECOVERY.md#本地交付终态)。

## 六、首批归档保留为历史输入，暂停交付

| 首批运行归档 | 字节 | SHA-256 |
| --- | ---: | --- |
| CUDA 3.0.7 | 2,682,659,372 | `3808bb9f5dd7ec512ec64b3183dbbb8a9f5d629ea7259aa6685e0ac8ab75c832` |
| PaddleVL 3.1.5 | 3,216,833,256 | `ff655da24c31d01bb40cc8b9a3769a8b7a7920c543a7eb7cf0b035b53e68af11` |

[CUDA 首批打包](../build/audit/gpu-compat-20261117-r1/cuda-package-r1/result.json)、[VL 首批打包](../build/audit/gpu-compat-20261117-r1/vl-package-r1/result.json)和[首批重新解包](../build/audit/gpu-compat-20261117-r1/reinstall-r1/result.json)仍分别只对原载荷有效。它们当时没有更新固定安装。首批与最终精简归档的大小和摘要分别记录；不从早期归档推断本轮载荷或公开交付方式。

## 七、源码、许可与发布边界

早期技术修复已分别本地提交 `930d0a5db60eea4fe34ed273b95046e85f853703`、插件项目 `c8a02bcd8f3a38562eabaf28dcd0a0d9f958bbf7`。本阶段文件级边界修正及进度记录作为后续本地提交，不重写前两次提交；CPU 插件及其它原有修改不夹带。构建快照保留当时父 revision 与 local-changes 标记，后补文档/提交不回写旧归档。

运行包与独立对应源码/审计分离，默认不含 UI 解锁 DLL 或私有实现源码。CUDA 12.9 的 NVIDIA 再分发适用性不继承旧 12.6 快照；MuPDF 确切源码、科学库原生来源、NVIDIA/AGPL/私有组合等公开门禁继续保留，不以本次 GPU 通过替代。

[清理记录](GPU_COMPAT_20261119_SPACE_RECOVERY.md)只涉及两仓已核对的失败产物和可恢复副本，以及固定安装更新后[已列明的两份过保留归档](GPU_COMPAT_20261118_CLEANUP_PREVIEW.md)。原始来源、模型、用户配置、固定安装中的私有组件和唯一审计证据保留。没有推 main、打发行标签、上传 Release、匿名下载核验或发送新的 Issue 回复。

请审阅实际程序及[CUDA 文案](RELEASE_CUDA_3.0.7_DRAFT.md)、[PaddleVL 文案](RELEASE_PADDLEVL_3.1.5_DRAFT.md)。本地完成不等于公开发布获准；公开发布仍需当次程序和文案的明确同意，并满足来源、许可和附件限制。

[CUDA 文案](RELEASE_CUDA_3.0.7_DRAFT.md)与 [PaddleVL 文案](RELEASE_PADDLEVL_3.1.5_DRAFT.md)仍是未公开草稿；当次程序/文案没有取得公开发布批准。容量恢复和本地交付完成不自动解除公开审查及来源/许可门禁。
