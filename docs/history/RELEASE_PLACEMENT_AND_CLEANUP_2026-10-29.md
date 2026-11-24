# 程序归位与空间整理结果

日期：2026-10-29。**本次明确授权的安装归位和36987项精确清理已经完成并闭合。** 仅为本地非最终候选交付，没有push、打标签或发布。

## 固定程序与归档

最新完整程序现在位于 `D:\Code\Python\Umi-OCR\release\Umi-OCR`。组件独立版本为主程序3.1.0、CUDA3.0.5、PaddleVL3.1.0，没有为了对齐而改版。

从实际归档在全新目录重装并验收的完整候选，只进行了一次同卷移动。切换后全部23817个原产品文件与三个独立归档的联合载荷完全一致，文件身份未变；续跑清理前再次核对这些文件的完整SHA。没有复制第二套10GB程序，没有只改版本号冒充新程序。

原 `build/tmp/startup-small-files-20261028-r1/startup-small-files-20261029-reinstalled-r1` 是已经移出的历史暂存位置，不再作为最终程序目录。原构建、重装和运行绝对路径不回写；新旧位置关系、字节核对和新路径检查分别记录。

`release`顶层现在只有固定安装`Umi-OCR`和以下六个归档，符合各组件独立的“最新版本+紧邻上一版本”保留规则：

| 组件 | 最新归档 | 上一版本归档 |
| --- | --- | --- |
| 主程序 | `Umi-OCR_v3.1.0_Windows_x64.tar.xz` | `Umi-OCR_v3.0.3_Windows_x64.tar.xz` |
| CUDA | `Umi-OCR-Plugin_v3.0.5_Windows_x64_CUDA.tar.xz` | `Umi-OCR-Plugin_v3.0.4_Windows_x64_CUDA.tar.xz` |
| PaddleVL | `Umi-OCR-Plugin_v3.1.0_Windows_x64_PaddleVL.tar.xz` | `Umi-OCR-Plugin_v3.0.0_Windows_x64_PaddleVL.tar.xz` |

当前归档位置与哈希见[候选审查说明](RELEASE_REVIEW_STARTUP_2026-10-29.md)、[归档归位记录](../build/audit/release-placement-cleanup-20261029-r1/archive-placement-20261029-r1/result.json)和原精确清单。六个保留归档在清理结束后重新核对了完整SHA。

## 实际删除结果

执行依据为[原精确清单](../build/audit/release-placement-cleanup-20261029-r1/installation-and-cleanup-proposal.json)，SHA-256：`e9e68e2151be62ff6271621d2e0d024b5ffb27a385672b1d44fbab5ef9eafba5`。用户[本次明确确认](../build/audit/release-placement-cleanup-20261029-r1/authorization-20261029-r1.json)包含两个具名项目及全部N1/N2/A1/A2/A3/I1组；没有复用上一轮775项授权。

合计永久删除**36987个精确叶文件**，逻辑字节285354675208 B，删除前分配空间**281546792960 B（262.21 GiB）**。删除目录0，终止进程0，没有越过清单删除模型、源码、许可、缓存、用户状态、历史审计或未知文件。

| 组 | 具名范围 | 实际文件数 | 删除前分配GiB |
| --- | --- | ---: | ---: |
| N1 | 主项目退役构建/解包/运行副本的原生叶文件 | 32712 | 197.731 |
| N2 | 插件项目退役构建/解包/运行副本的原生叶文件 | 3346 | 33.202 |
| A1 | 主项目build内重复/过期产品归档 | 18 | 17.521 |
| A2 | 插件项目build内重复产品归档 | 1 | 1.495 |
| A3 | release内被本轮替代的旧同版本候选档 | 3 | 3.991 |
| I1 | 切换后旧安装中与原装配清单一致的原生叶文件 | 907 | 8.271 |

N2/A2仅限 `D:\Code\Python\Umi-OCR-Plugin` 内原清单的精确路径，没有扩大到其源码、模型、缓存或其他兄弟项目。历史产品不全是字节相同的副本，退役不能伪称哈希去重；其未列明内容和全部目录仍保留，不能再直接当完整运行时或打包输入。

D盘删除阶段可用空间为21231308800 → 302535450624 B，约19.77 → 281.76 GiB，整卷净增约**261.98 GiB**。与262.21 GiB文件分配空间合计的差异包含本次审计开销和其他活动，不能简单等同或全部归因。

## 旧状态和程序新增状态

旧安装先整棵同卷保留到 `build/tmp/release-placement-cleanup-20261029-r1/old-install-preserved`，新固定安装通过验证后才清理I1。I1从该保留位置删除，绝不指向新固定安装。

旧安装其余**25851个文件**和全部原目录仍在。旧`.settings`、`.pre_settings`、`themes.json`、插件状态、日志和任务原件的身份/大小/mtime/属性保持，没有读取配置内容或自动复制到新程序。该保留目录已经移除部分原生载荷，不是完整可运行程序。

新程序正常运行后新增的**144个非归档文件、2792418逻辑字节**也全部保留，包含设置、日志、缓存及其他非目标。没有为了恢复早先“空白配置”而删除或回滚，未读取这些新增状态正文。当前完整安装共23961个文件，即23817个原产品文件加144个保留的新状态文件。

## 首轮停止与安全续跑

首次清理`execution-r1`检测到新固定目录中的运行实例，在第一个unlink前按门禁停止，实际删除0项。原始FAIL、空删除清单和占用日志保留在[停止记录](../build/audit/release-placement-cleanup-20261029-r1/execution-r1/STOPPED_BEFORE_DELETION.md)，没有改写为PASS。

原进程自行退出后，只读复查未发现项目进程；用户[确认继续同一清单并保留新状态](../build/audit/release-placement-cleanup-20261029-r1/continuation-instruction-20261029-r1.json)。`execution-r2`重新核对目标、原产品完整SHA及当前状态保护基线，沿用原锁定的叶文件删除函数完成清理，未重复安装切换、未终止进程、未绕过占用。

## 清理后的当前占用

这是删除完成后的新鲜Windows文件分配空间查询，不是旧缓存盘点。已测普通文件的分配空间合计如下：

| 项目 | 普通文件数 | 已测分配GiB |
| --- | ---: | ---: |
| 主项目 `D:\Code\Python\Umi-OCR` | 844203 | 84.282 |
| 插件项目 `D:\Code\Python\Umi-OCR-Plugin` | 145372 | 7.086 |
| **合计** | **989575** | **91.368** |

主项目主要保留区域为：`build/artifacts`32.704 GiB、`build/staging`20.219 GiB、固定安装9.123 GiB、六个归档7.677 GiB、`build/audit`7.049 GiB、Git3.500 GiB、`build/tmp`3.436 GiB。插件项目主要为`build/staging`6.676 GiB。模型、对应源码/许可、来源材料、当前有用种子、缓存、用户状态和历史证据均按确认范围保留，没有把剩余目录一概当作无效缓存。

所有已计入普通文件的分配空间查询均成功；扫描状态`READ_ONLY_PARTIAL`仅因插件项目CPU隔离测试的3个重解析点按边界未跟随：

- `build/isolation-test/UmiOCR-data/runtime`
- `build/isolation-test/UmiOCR-data/plugins/win32_PaddleOCRv6_CPU/models`
- `build/isolation-test/UmiOCR-data/plugins/win32_PaddleOCRv6_CPU/vendor`

91.368 GiB不含这些链接目标、目录/MFT等卷级开销及扫描结束后新写的报告/提交；不把它冒充完整卷级占用。原[测量JSON](../build/audit/release-placement-cleanup-20261029-r1/execution-r2/remaining-space-r1.json)保留真实状态不改写。

## 验证、追溯与未执行项

- 原叶执行器23项、续跑状态保护9项微型安全测试通过，失败/错误/跳过均为0。它们针对本次执行器，不替代产品全量验收。
- N1/N2每个文件在unlink前读取完整SHA并持久写入意图，随后再次核对身份；I1及所有归档与已知SHA逐项比对。36987条意图、36987条删除事件、实际清单和原授权集合准确闭合。
- 85个互不重叠作用域中的全部非目标文件集合、真实ID、大小、mtime和属性保持；全部原目录集合/ID/属性保持，不拿正常删除引起的目录mtime或索引大小变化冒充文件变更。
- 固定新路径的四个Stored容器、真实Qt原生DLL和宿主模块来源检查在本次切换后通过。原GUI/GPU/CLI/HTTP验收绑定未改动的归档载荷，未声称本次清理重新执行完整GUI/GPU/性能矩阵。
- 没有重建组件、下载或量化模型、改动公开许可结论，未push、打标签或发布。公开发行仍遵循[CLAUDE.md](../CLAUDE.md)和独立的程序/文案审查门禁。

完整[实际执行报告](../build/audit/release-placement-cleanup-20261029-r1/execution-r2/EXECUTION_RESULT.md)、[闭合证据](../build/audit/release-placement-cleanup-20261029-r1/execution-r2/closure.json)和[原执行结果](../build/audit/release-placement-cleanup-20261029-r1/execution-r2/result.json)均保留。上一轮775项、16.65 GiB的清理另见[旧执行结果](../build/audit/space-cleanup-20261029-r1/EXECUTION_RESULT.md)，不重复计入本次。
