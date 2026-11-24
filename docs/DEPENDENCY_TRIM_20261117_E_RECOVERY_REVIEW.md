# E 工作根中断恢复记录

> 本记录封存恢复依据与定向验证，不代表永久清理已经完成。实际结果以恢复运行回执和结束后的完整核验为准。

## 已确认的中断状态

目标仍仅为 `E:\Umi-OCR-build` 本身及原冻结清单内后代。没有扩大到其它 E 盘目录、D 盘固定安装/保留材料、插件项目或外部源码树。

原后台命令未取得结束回执。恢复前已检查原执行链不再运行，并保持原始日志不变，执行只读 reconcile：

- 已持久提交的目录项删除：**43,356**，不是全部普通文件计数。
- 已持久提交的限定只读转换：**45**，无未决属性转换。
- 未决删除意图：**1**；`dependency-trim-20261114-r1/build/qt-sdk-r3/install/share/qt6/wayland/protocols/xdg-output` 仍为原对象，不冒充已删除。
- 原日志没有截断尾记录。
- 原冻结总范围 704,811 项，因此尚待处理 **661,455** 项；根目录本身仍须最后删除。

证据：

- [只读恢复回执](../build/audit/dependency-trim-20261116-pip-r1/evidence/e-root-interrupted-reconciliation-r1/result.json)，SHA-256 `07897fb03b09ff98a8696b247b1eccb4060488c69be7089286d19efc8e2e13c9`。
- [原始中断日志](../build/audit/dependency-trim-20261116-pip-r1/evidence/e-root-permanent-delete-20261117-r1/journal.jsonl)，SHA-256 `018a9d1478f4ebdddc3b2e93e601f164d86555120c64d3cf9cbcc19dc04294e8`。
- [原始进度输出](../build/audit/dependency-trim-20261116-pip-r1/evidence/e-root-permanent-delete-20261117-r1.console.log)。

## 恢复契约

原清单、原只读批准、原属性计划和旧日志不改写。恢复入口复用已验收的句柄相对打开、同句柄内容核验、D 材料读租约、路径/身份/共享拒绝及范围进程检查。

1. 原日志以实际 SHA 保持读租约，校验完整哈希链并恢复已提交集合；不按进度输出估算提交数。
2. 已提交目录项从待处理集合扣除；任何原名字重新出现均作为未知或 replacement 拒绝，不递归补删。
3. 只读位仅沿用原 45 项的已提交转换状态，**恢复阶段不再次清位，也不允许新增属性转换**。
4. 仅有已提交子项删除所影响的目录允许正常的目录 mtime 变化。目录卷、file ID、类型、属性、重解析边界及其它文件身份检查不放宽。
5. 硬链接以原完整组减去已提交名字计算剩余数量，继续核对实际完整别名；不机械要求恢复后的名字仍有原始 nlink。
6. 新运行独立记录日志，并绑定上段日志 SHA、已提交计数、删除集合摘要及恢复代码/自测摘要。不得将新运行计数冒充原阶段重新执行。
7. 删除意图和提交结果仍各自同步持久化；中间 `MARKED`、`CLOSED` 等状态随后续持久屏障落盘。新鲜占用快照仍同步保存，复用快照明确标记并维持五秒上限。没有声称跨卷断电原子性。
8. 遇实际身份变化、新未知项、目标权限或共享拒绝即停止；不提权、不改 ACL、不终止用户进程，也不改用绕过只读的处置标志。

全机进程字段缺失仍是明确保留的可见性限制，不称这些进程均已被排除。范围进程策略和组合证据独立于原 r3 的 55 组自测，不混用结论。

## 定向验证

[恢复自测回执](../build/audit/dependency-trim-20261116-pip-r1/evidence/e-root-resume-selftest-r1/result.json) SHA-256：

`68175784a70a6737b9c0da8e036a4789548359c2e93e2e4c6ddd2a8f4dafe018`

六组 D 自建夹具全部通过，未打开或修改真实 E 文件：

| 用例 | 实际边界 |
| --- | --- |
| 完整恢复 | 原阶段已清位、已删一个硬链接别名及 13 个链接；目录 INTENT 后中断。恢复只删除余下三项，合并两段精确覆盖全部 22 项，只读转换总计仍为一次。 |
| 新未知文件 | 全树预检拒绝，新删除数为零。 |
| 内容改变并恢复原 mtime | 内容摘要仍拒绝，不能用大小/时间匹配取代内容核验。 |
| 真实共享冲突 | 目标读句柄导致预检拒绝，新删除数为零。 |
| 根目录替换 | file ID 不符拒绝，不清扫新根或保存的旧原件。 |
| 意图持久化失败 | 拒绝开始新的删除，不补写成功计数，保留失败现场。 |

[恢复入口](../build/audit/dependency-trim-20261116-pip-r1/tools/resume_e_root_parent_r1.py) SHA-256：`6b06fae1c927f5499a61d8a1b3eee1d43b006499884d76ac1de527bf3c3398b6`。

[自测脚本](../build/audit/dependency-trim-20261116-pip-r1/tools/test_resume_e_root_parent_r1.py)与原 r3、范围进程检查及组合入口的精确摘要均在自测回执内绑定。

## 实际运行与后续核验

恢复运行已改为独立终端启动，不依赖 Claude SDK 的原后台清理进程继续存活。终端退出信号只触发结果检查，不等于删除成功。

- 新输出目录：`build/audit/dependency-trim-20261116-pip-r1/evidence/e-root-permanent-delete-resume-20261117-r1`。
- 新控制台日志：`build/audit/dependency-trim-20261116-pip-r1/evidence/e-root-permanent-delete-resume-20261117-r1.console.log`。
- [结束后只读核验工具](../build/audit/dependency-trim-20261116-pip-r1/tools/verify_e_root_completion_r2.py)将核对 E 卷仍可用且身份一致、根路径确实消失、全部恢复链与原 704,811 项集合/类型/逻辑字节一致、45 项转换不重复、D 保留内容重新哈希匹配以及四个固定安装哨兵未变。

固定安装仍沿用此前已验收的主程序 3.1.5、CUDA 3.0.6、PaddleVL 3.1.4。本次不重跑 GPU 或截图/HDR/混屏验收，不把四个哨兵核对扩大为全部用户数据重新哈希。公开来源、许可及当次发布审查门禁不变；没有推送、发行标签或 Release。
