# 本轮本地交付归档保留与清理预演

日期：2026-11-18。以下为当时的预演及中断记录，不代表后续已删除。11 月 19 日在两仓容量硬门槛下另行核对、实施的 build 清理，见[两仓回收记录](GPU_COMPAT_20261119_SPACE_RECOVERY.md)；它不提前删除下列 release 归档，release 的实际执行结果仍以本轮归位/保留回执为准。

## 允许在新固定安装就绪后处理的具体旧归档

依据本项目主程序、CUDA、PaddleVL 各自仅保留最新及紧邻上一版本的规则，**仅当新归档重装、组合验收和固定安装更新均完成**，且复核旧文件身份/摘要、链接和占用后，处理以下两项：

| 具体路径（相对本项目） | 当前大小（字节） | 理由 |
| --- | ---: | --- |
| `release/Umi-OCR-Plugin_v3.0.5_Windows_x64_CUDA.tar.xz` | 1,682,277,376 | 新版 3.0.7 与上一版 3.0.6 已就绪后，3.0.5 超出独立保留范围 |
| `release/Umi-OCR-Plugin_v3.1.3_Windows_x64_PaddleVL.tar.xz` | 2,113,106,912 | 新版 3.1.5 与上一版 3.1.4 已就绪后，3.1.3 超出独立保留范围 |

合计 3,795,384,288 字节为文件逻辑大小，不声称等于实际可用空间增量。该两文件最终执行前另生成逐项 SHA-256、文件身份和当时进程检查的机器预演；目标变更、占用、权限或链接异常时停止，不换工具绕过，不清只读。

## release 应保留

- 固定完整安装：`release/Umi-OCR`，包含本体 3.1.5、新 CUDA 3.0.7、新 PaddleVL 3.1.5；用户配置、日志、任务资源、模型及私有 DLL 原地保留。
- 本体 3.1.5 和 3.1.4 运行归档。
- CUDA 3.0.7 和 3.0.6 运行归档。
- PaddleVL 3.1.5 和 3.1.4 运行归档。

独立源码、锁、完整来源、审计、哈希与原始失败不放入 release；继续保存在 build。新归档仅本地归位，不代表公开发布，不做匿名下载核验。

## 本轮不执行的 build 清理

- `build/gpu-compat-20261117-r1` 的官方输入、原始预验证闭包、生成器、r1/r2 profile、原始 cuobjdump、安装/编译日志、模型/来源摘要具有复现与审计价值，保留。
- `build/staging/gpu-compat-20261118-cuda307-r2` 是首批 VL 的实际已记录种子，保留；r4 与对应首批最简树因文件回带已暂停作为交付输入，但作为原始验证/失败定位材料保留，不再称为最终交付。
- 首轮空候选和 r3 的重复补丁失败候选虽可作为后续退役候选，本轮没有额外批准其大文件删除范围，先保留失败原件和完整映射。不得仅凭 r1/r3 名称或时间清理。
- 本轮隔离 GPU/EXE 验收目录、归档新重装及来源恢复目录作为实际验证输入/输出保留，不把它们冒充可任意清理缓存。
- 不清理 `D:/Code/Python/Umi-OCR-Plugin`、其它兄弟项目、`D:/AI/models`、旧 E 根或用户数据；插件项目的新失败构建也不顺带删除。
- `build/private/ui-unlock-v1` 为私有实现及构建材料，明确保留，不是缓存，也不进入 Git 或公开源码。

公开发布时的 build 清理仍须用户对当次程序、文案和具体预演明确同意。此预演不扩大为任意 build 或大文件清理授权。

## 本轮容量阻塞后的保留范围

D 盘在新 CUDA 最简副本生成时报告 `WinError 112`。失败后观察可用约 0.3 GB；没有为腾空间提前删除旧 Release 归档、旧构建、原始来源、模型或兄弟项目。

以下均保留，**不是新批准的删除目标**：

- `build/staging/gpu-compat-20261118-exact-r1/cuda307-r5`：已通过精确闭包与包审计的新 CUDA 程序、对应源码及快照；不是最终归档重装通过。
- `build/artifacts/gpu-compat-20261118-exact-r1/cuda307-r5`：原新 CUDA 覆盖层后来与本轮新恢复的未变本体作逐文件同卷转移，现为两组件测试组合，不再冒称纯插件分包输入。迁移原记录不改写。
- `build/artifacts/gpu-compat-20261118-exact-r1/cuda307-r5-runtime`：磁盘满时中断的最简副本，没有成功分包回执，可能含截断成员，不作为安装输入或假称可用归档。
- `build/tmp/gpu-compat-20261118-exact-r1`：本轮受控临时环境、实际回归输入/输出和空迁移祖先目录；旧恢复回执和实际转移清单保留。
- `build/audit/gpu-compat-20261117-r1`：新旧完整逻辑文件锁、原失败、磁盘满日志、源码绑定、实机回归、NTFS 合成能力探针及逐文件装配记录。

普通 NTFS 压缩只用于本轮全新工作父目录，未使用 WOF/CompactOS、未修改原始种子或固定安装。合成探针在明确完成压缩后核对原始字节、非重解析点和实际分配大小，随后只删除脚本自建的微小探针文件。它没有解除容量阻塞，也不等于 GPU 验收。

当前不会清理未列明的大文件来绕过容量阻塞。最终两归档保留处理仍必须等新固定安装真正就绪，再执行本预演原有的两项精确范围。

11 月 19 日流式运行归档再次受容量保护中断：`build/artifacts/gpu-compat-20261118-exact-r1/cuda307-pack-r2/Umi-OCR-Plugin_v3.0.7_Windows_x64_CUDA.tar.xz`（1,411,213,860 字节）、`build/artifacts/gpu-compat-20261118-exact-r1/vl315-pack-r2/Umi-OCR-Plugin_v3.1.5_Windows_x64_PaddleVL.tar.xz`（1,814,026,495 字节）在当时保留为失败现场、不可安装。它们同目录的**对应源码归档完整且已独立核验，后续保留复用**，不作为清理目标。[源码与容量回执](../build/audit/gpu-compat-20261117-r1/stream-package-capacity-stop-r1.json)。

## 11 月 19 日的本地实际执行结果

固定安装完成后，两份新运行归档已[同卷归位并重新核对摘要](../build/audit/gpu-compat-20261117-r1/exact-local-archive-placement-r1/promotion.json)。按[最终逐项预演](../build/audit/gpu-compat-20261117-r1/exact-local-archive-placement-r1/retention-preview.json)，只删除了本页具名的 CUDA **3.0.5**、PaddleVL **3.1.3** 两份 release 旧运行归档，共 **3,795,384,288 逻辑字节**，没有连带删除源码或同方案之外的其它归档。[执行回执](../build/audit/gpu-compat-20261117-r1/exact-local-archive-placement-r1/retention-result.json)

固定目录与各组件最新及上一版的六份 `.tar.xz` 已独立复核。两仓 build 清理的另外授权、具体目标、排除项及容量账本以[实际回收记录](GPU_COMPAT_20261119_SPACE_RECOVERY.md)为准，不改写上文历史预演。
