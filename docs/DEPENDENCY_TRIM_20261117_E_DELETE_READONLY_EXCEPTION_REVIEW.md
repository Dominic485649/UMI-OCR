# E 工作根删除执行器 r3：限定只读例外后继审阅

> r3 的 55 组 Windows 定向自测仅在 D 盘自建夹具执行并通过。真实 E 文件预检、清除只读属性和删除均未执行。本文件补充而不改写 [r2 审阅](DEPENDENCY_TRIM_20261116_E_DELETE_EXECUTOR_REVIEW.md)及其原始回执。

## 范围与执行权

接收原始请求的会话保有唯一真实 E 删除执行权。本线程只准备后继代码、D 合成测试、派生计划及证据交接；没有终止用户进程、提权、修改 ACL 或执行真实 E 操作。

[父会话记录](../build/audit/dependency-trim-20261116-pip-r1/evidence/whole-workroot-delete-parent-approval-r1.json)保存该会话收到的直接用户决定，SHA256 为 `750aaa224e0948c86ac6012f7d0b04fbbe7cb5a055523731b1372b38e80d52fe`。它不是本线程取得的授权转移，也不能替代实际执行工具的权限审批。

限定属性例外恰好覆盖原冻结清单中的 **45 个普通 Git pack 文件，324,413,322 字节**：

- 仅 `.git/objects/pack/` 下的 `.idx`、`.pack`、`.rev`，分类均为 `CONTENT_PRESERVED_IN_D`。
- 原身份、大小、摘要、D 留存位置和根身份全部绑定；每项冻结 `nlink=1`，不是目录、reparse 或其它硬链接别名。
- 仅从属性 `33` 清除 `FILE_ATTRIBUTE_READONLY` 得到 `32`，不改变其它属性位，不引入 `NORMAL` 位，不更改 ACL，不使用 `IGNORE_READONLY` disposition 标志。
- 默认仍拒绝只读。没有精确计划、父记录和原范围的共同绑定，或出现其它只读项、实际属性变化、新增对象、占用、权限拒绝，均不得自动扩大例外。

完整整根范围仍由原 [最终预演](../build/audit/dependency-trim-20261116-pip-r1/evidence/whole-workroot-preview-r1/result.json)、[独立核对](../build/audit/dependency-trim-20261116-pip-r1/evidence/whole-workroot-preview-primary-review-r1.json)及原 `704,811` 项清单绑定。例外计划没有替换原清单，也不声称已重新扫描 E。

## 实现与中断边界

1. 先验证 D 材料及读租约、占用门禁、根与全树实际身份/访问资格；为批准成员预先请求 `FILE_WRITE_ATTRIBUTES`。完整预检先于任何清位。
2. 在同一已打开原件句柄核对内容和身份后，记录持久 `ATTRIBUTE_INTENT`，再仅清只读位，记录 `ATTRIBUTE_SET`，复核后提交 `ATTRIBUTE_COMMIT`。
3. 属性后检查包含 file ID、卷、类型、大小、硬链接计数、创建时间、LastWriteTime、其它属性位和内容摘要。ChangeTime、访问时间另记观察值，不声称它们在元数据操作或读取后不变。
4. 全部批准清位提交后，再完整预检一次，才进入原父句柄相对、单 basename、链接优先、目录后序、根最后的删除流程。原 manifest 字节和摘要保持不变；只在本次运行内记录有效属性状态。
5. 属性与名字删除分别按完整有效 COMMIT 计数。持久 COMMIT 后、内存更新前中断，从日志重放重建计数。SET 成功但没有 COMMIT，不冒充已经确认提交，也不能写作“没有变化”。
6. 只读恢复可报告 `ORIGINAL_READONLY`、`APPROVED_AFTER_UNCONFIRMED` 或异常属性，不自动补清、恢复属性或继续删除。**部分清位后不可直接重跑执行命令**；原冻结属性与现场不再相同，新 run 会拒绝，须保留原日志并先只读核对。

进程可检查性策略没有放宽。仍使用 r2 常驻 PowerShell 工作器，每次 mutation 重新采集；不可检查 PID、坏响应、过期、超时或退出均 fail closed。r2 历史 E 采样的“观察到 E 占用 0、不可检查 216”不是本次新鲜 E 验收，也不是可终止进程名单。CIM 采样不是系统级进程启动互锁；本轮没有完整并发压力或实际整根吞吐证明。

## 实际定向验证

[55 组自测原始回执](../build/audit/dependency-trim-20261116-pip-r1/evidence/e-root-delete-selftest-r3/result.json)状态为 `DIRECTED_WINDOWS_DELETION_FIXTURES_PASS_REAL_E_NOT_RUN`，`pythonOptimize=0`。开始前捕获工具字节并直接编译，测试期间持有工具读租约，结束后再次核对摘要。

| 验证范围 | 实际结果及限制 |
| --- | --- |
| 原 43 组句柄、范围、链接、硬链接、占用、日志及恢复回归 | 在 r3 上重新执行通过；拒绝与中断用例按预期阻塞，不将这些单项状态误读为总自测失败 |
| 批准例外的 check-only | 不清位、不删除，通过 |
| 精确属性阶段及随后删除 | D 夹具的 3 个合成 pack 文件实际清位，现场核对其它属性、身份、创建/写入时间、内容与 D 副本，再完成夹具删除 |
| 默认无例外、缺少 D 副本、新只读项、扩大集合或其它属性位 | 在清位前拒绝，通过 |
| 属性 INTENT、SET、COMMIT 各边界中断 | 日志与恢复分开报告清位和删除；SET 后无 COMMIT 报未确认，部分清位后盲重跑拒绝，通过 |
| COMMIT 已持久但内存未更新 | 从有效日志重建清位计数，通过 |
| 属性权限失败与 INTENT fsync 失败 | WinError5 注入后停止，未改 ACL；fsync 失败在清位前阻塞，通过 |

夹具使用专属 D 目录和合成批准，并非把父会话对真实 45 项的决定转移到本线程。没有执行真实 E CLI check-only、实际 E 权限测试、清位、删除、断电测试或物理回收空间测量；也没有再次运行产品、GPU、截图/HDR/混屏测试。

## 计划与摘要

[45 项例外计划](../build/audit/dependency-trim-20261116-pip-r1/evidence/e-root-readonly-exception-plan-r1.json)由 [D 材料准备工具](../build/audit/dependency-trim-20261116-pip-r1/tools/prepare_readonly_exception_plan_r1.py)从既有精确只读子集、原根身份、预演和父记录派生；[准备回执](../build/audit/dependency-trim-20261116-pip-r1/evidence/e-root-readonly-exception-plan-preparation-r1.json)明确记录 `realEOpened=false`、`readonlyCleared=false`、`deletionAttempted=false`。本步没有重新读取完整原清单或重新哈希 D 大归档；实际执行 CLI 必须从原完整清单的同一流重建计划比对，并重新持有 D 留存资格和租约。

下列摘要分别绑定不同对象，不可互换：

| 对象 | SHA256 |
| --- | --- |
| 原 manifest | `1f49f4d28ae36d6cf428c642b59123d440a38a3ddc86d3dbba5e24d5b820863a` |
| 例外计划文件原始字节 | `6498d2d5d31f5dcbc570faea0f79dff2917b5c1b6833a6305a0d71b28b31d3b0` |
| 例外计划 executionScopeSha256 | `4db668fc912016683fd05e422ff330566363f2add58ca162e3ed92084e8413a3` |
| 55 组自测回执原始字节 | `622d4648338b34cfa9f0f9767bb6543d039e308b9bd523bbd95a7e9faf6e27bb` |

原 manifest 是冻结目录项范围；计划文件原始 SHA 用于材料完整性；`executionScopeSha256` 是计划在加入该字段前的规范化语义摘要，绑定父记录、原 manifest、精确成员及允许属性转换。它不是文件摘要。

## 工具与调用契约

| 文件 | SHA256 |
| --- | --- |
| [r3 执行器](../build/audit/dependency-trim-20261116-pip-r1/tools/e_root_delete_executor_r3.py) | `7d0fe5ab2249474a0c1c0f25ddac2fd30618b23f03f1c8ebda718ba540d8228b` |
| [r3 Native 原语](../build/audit/dependency-trim-20261116-pip-r1/tools/e_root_delete_win32_r3.py) | `38f6814a08c12b7067b073aed1f9d9357cff9c32cb7c4b713d4977c22fde5948` |
| [复用的 r2 占用工作器](../build/audit/dependency-trim-20261116-pip-r1/tools/e_root_delete_occupancy_r2.ps1) | `7dea62b63976aaad0140284c01e35f4be56cf521ffeaa88d784bb4d96b78781f` |
| [r3 自测脚本](../build/audit/dependency-trim-20261116-pip-r1/tools/test_e_root_delete_executor_r3.py) | `d8f2c43bd9ca14afe0180f3f67bc81a9a283c4c682a680b7163db21186718010` |

- 仅使用 Windows 原生 Python，以 `-I -B -X utf8` 运行；拒绝 `-O`。默认不执行 mutation。
- `--readonly-plan`、`--readonly-plan-sha256`、`--parent-approval`、`--parent-approval-sha256` 必须成组给出，路径及原始摘要必须与封存材料一致。
- 原 `--preview-sha256`、`--review-sha256` 仍必需。输出 `--out` 必须是本审计 evidence 下不存在的新目录，不能覆盖历史结果。
- 真实执行还要求 `--execute`、`--approve-permanent-delete E:/Umi-OCR-build`、匹配的 `--selftest-sha256`，以及以本例外计划 `executionScopeSha256` 作为 `--scope-sha256`。这些参数只是防误操作校验，不提供用户或工具授权。
- 只读恢复使用 `--reconcile` 绑定原日志及同一例外计划，不会自动再次清位或删除。

[机器可读 r3 补充交接索引](../build/audit/dependency-trim-20261116-pip-r1/evidence/e-root-executor-handoff-r3.json)封存工具、成功回执、父记录、原子集、计划及本审阅的实际摘要。r1/r2 原件、失败记录、旧自测与原交接索引保持原样，不回写为 r3 通过。

本后继仅用于交回唯一执行者审阅；没有解除占用、权限、来源、许可或 GitHub 发布门禁，也不表示真实 E 已删除。现有 D 夹具、日志、未决属性状态和旧证据保留用于复现，本阶段不作无关清理。
