# 2026-11-16 E 工作根候选副本清理预演

**仅供审阅，未执行删除，不构成整根删除许可。**

所有候选均位于 `E:/Umi-OCR-build`。下表路径相对于该根；逻辑字节不等于实际可释放磁盘空间。原生构建缓存、冻结清单后的新增项及其它目录不在本预演范围。

## 列明候选

| 相对路径 | 文件数 | 逻辑字节 | 依据 |
| --- | ---: | ---: | --- |
| `dependency-trim-20261114-r1/delivery-20261115-r1/Umi-OCR-Plugin/build/staging/vl-source-export-r2` | 833 | 655898085 | 源码展开副本与独立清单一致，归档已保留 |
| `dependency-trim-20261114-r1/delivery-20261115-r1/Umi-OCR-Plugin/build/staging/vl-source-export-r1` | 811 | 592195045 | 源码展开副本与独立清单一致，归档已保留 |
| `dependency-trim-20261114-r1/delivery-20261115-r1/Umi-OCR-Plugin/build/staging/vl-runtime-r1` | 7738 | 4745237537 | 运行或重装副本与独立载荷清单一致 |
| `dependency-trim-20261114-r1/delivery-20261115-r1/Umi-OCR-Plugin/build/staging/vl-reinstall-r1` | 7738 | 4745237537 | 运行或重装副本与独立载荷清单一致 |
| `dependency-trim-20261114-r1/delivery-20261115-r1/Umi-OCR-Plugin/build/staging/vl-complete-r1` | 8555 | 5338691076 | 完整候选与独立清单及来源补充一致，旧锁另行保留 |
| `dependency-trim-20261114-r1/delivery-20261115-r1/Umi-OCR/build/tmp/relocation-probe-r1` | 67 | 20101 | 合成夹具已逐字节保留，含模拟设置，不是真实用户安装 |
| `dependency-trim-20261114-r1/delivery-20261115-r1/Umi-OCR/build/tmp/fixed-cross-volume-r1` | 12 | 351 | 合成夹具已逐字节保留，含模拟设置，不是真实用户安装 |
| `dependency-trim-20261114-r1/delivery-20261115-r1/Umi-OCR/build/tmp/dependency-trim-20261114-r1` | 6140 | 3985147709 | 运行或重装副本与独立载荷清单一致 |
| `dependency-trim-20261114-r1/delivery-20261115-r1/Umi-OCR/build/artifacts/dependency-trim-cuda-306-20261115-r3/runtime` | 6140 | 3985147709 | 运行或重装副本与独立载荷清单一致 |
| `dependency-trim-20261114-r1/delivery-20261115-r1/Umi-OCR/build/artifacts/dependency-trim-cuda-306-20261115-r3/complete` | 6458 | 5470459259 | 完整候选与独立清单一致，旧锁及未覆盖元数据另行保留 |

| 合计 | 数值 |
| --- | ---: |
| 候选根 | 10 |
| 文件 | 44492 |
| 逻辑字节 | 29518034409 |

## 必须保留的材料

- D 盘内部来源归档及原冻结 RETAIN 集合的外部归档映射，见[迁回回执](../build/audit/dependency-trim-20261116-pip-r1/evidence/retained-source-archive-copy-r2.json)。
- 已核验的最终主程序、CUDA 与 PaddleVL 运行及独立源码归档，不属于删除候选。
- 原生诊断规则、对象、生成头和直接输入，见[原生诊断保留](../build/audit/dependency-trim-20261116-pip-r1/evidence/native-diagnostic-retention-copy-r1.json)与[规则输入补保留](../build/audit/dependency-trim-20261116-pip-r1/evidence/native-pch-input-retention-r1.json)。
- 本次差集中的原始候选标记、旧运行锁、原始输入清单及合成迁移/事务夹具，见[差集保留回执](../build/audit/dependency-trim-20261116-pip-r1/evidence/delivery-remainder-retention-r1.json)。
- 全部原日志、失败回执、独立载荷清单和迁移映射。原绝对路径不回写，迁移不冒充重建或运行重新通过。

## 核对范围和执行门禁

[当前候选字节核对](../build/audit/dependency-trim-20261116-pip-r1/evidence/delivery-hold-content-coverage-r1.json)已检查列明候选的完整文件集合和摘要。独立清单没有缺项、多项或摘要差异；合成夹具没有产品载荷清单，按完整观察集合保留。归档覆盖复用已绑定的 D 盘归档与独立清单，CUDA 源码归档另行流式核对，没有重新运行模型或读取固定安装。

| 新增差集保留 | 数值 |
| --- | ---: |
| 文件 | 83 |
| 字节 | 1,349,667 |

读取前后未发现 E 工作根内运行程序。该结果仅代表核对时点，执行清理前仍须重新检查占用、路径类型、具体载荷及保留副本。新进程、目录变化、未知内容、越界链接或权限拒绝均应停止相关动作，不能终止用户进程或换工具绕过。

原生 HOLD 缓存及预编译头尚未由本预演放行。其规则和直接输入已保留，不等于完整传递闭包或重建可用性已证明。E 根内本轮新增的保留归档、失败工作目录也不在上表中，不得将表内核对扩展成递归删除整个根。

本预演不删除真实用户配置、日志、任务资源、模型或私有解锁材料。固定安装更新仍以独立事务终态为准，不能用这里的清理核对替代安装验收。实际删除还需符合具体授权范围。

机器可读入口：[清理预演](../build/audit/dependency-trim-20261116-pip-r1/evidence/delivery-hold-cleanup-preview-r1.json)。完整交付状态见[本地交付审阅报告](DEPENDENCY_TRIM_20261116_LOCAL_DELIVERY_REVIEW.md)。
