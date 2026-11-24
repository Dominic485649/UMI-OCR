# E 工作根永久清理收尾审阅
> 必要材料已在 D 盘保留并核验，整根逐项清理预演及独立集合检查已完成。尚未执行 E 盘删除，实际删除审批与执行前的新鲜检查仍未完成。
## 精确范围与当前观察
目标仅为 `E:/Umi-OCR-build` 本身及其全部后代。固定安装、D 盘保留材料、插件兄弟项目、`D:/AI/llama.cpp`、模型及私有 UI 解锁源码不在删除范围。跨会话转述不代替实际删除审批，本轮不启动删除。
当前全根只读盘点结果如下。逻辑字节不是实际磁盘释放量，也不代表可直接删除。
| 范围 | 数量或逻辑字节 |
| --- | ---: |
| 普通文件 | 628,907 |
| 目录，不含根本身 | 75,890 |
| 符号链接 | 13 |
| 普通文件逻辑字节 | 98,914,348,624 |
| 相对冻结盘点新增项 | 3 |
| 冻结项目元数据变化或缺失 | 0 |
新增项仅为 `retention-20261116-r1` 空工作目录、`retention-20261116-r2` 目录及其中的内部来源归档。该归档 E 原件与 D 保留副本已重新哈希一致。失败归档的原始日志、回执留在 D，不因空目录可清理而丢弃。
首次目录枚举返回的文件身份字段为零，仅能用于大小、时间、属性差集。后继 r2 使用实际路径状态查询，独立重做完整盘点。随后核对符号链接目标与硬链接完整别名，未发现根外链接；原内部来源归档的普通成员当前身份全部匹配。这是身份沿袭核对，不冒充再次内容哈希或完整重建。
## 原生 HOLD 已收敛为完整分区
按照原冻结规则的首匹配优先级，重新解析实际 Ninja 生产边，并核对相应编译器命令及输出参数。不用文件后缀、basename 或目录名代替生产证据。
| 集合 | 文件数 | 逻辑字节 |
| --- | ---: | ---: |
| 全部原生 HOLD | 183,593 | 49,487,268,249 |
| 编译中间输出候选 | 22,424 | 6,434,720,335 |
| PCH 编译副输出候选 | 148 | 30,182,211,584 |
| 候选并集 | 22,572 | 36,616,931,919 |
| 保守保留补集 | 161,021 | 12,870,336,330 |
| 补集中已有 D 副本 | 2,392 | 515,080,420 |
| 补集中本轮新增 D 留存 | 158,629 | 12,355,255,910 |
两个清单互斥且完整覆盖原生 HOLD，冻结路径、大小、元数据和统计均经过独立分区核对。候选不代表已重建成功或取得删除批准。
- 主线程机器执行实际读取 35,484 份 Ninja，核对当前输出触发的 27 个定义文件、427 个编译定义。代理更宽调查的定义数量不冒充本次执行数量。
- 检测到 `QtWebEngineCore.stamp` 与 `QtWebEngineCoreSandbox.lib` 的多重生产归属，两件均保守留存，不静默选取一条规则后放行。
- 库、DLL、EXE、生成头和源码、PDB、资源、规则、响应文件、日志、生成数据库及未证实输出全部进入保留补集。
- llama 实际源根位于 `D:/AI/llama.cpp`，不在 E 清理范围。本轮将 llama 构建目录全部保留，包含可能用于历史 attention 静态证据的编译对象，不以 E 源归档替代外部源树证明。
- 原临时聚合遗漏的嵌套 install 项已按正确规则补回：四份 gn.exe、四份 install.ninja，以及 OpenCV 配置/安装脚本，全部进入保留补集。
- 原有诊断副本仅覆盖 QtWebEngine r5，不被扩大表述为其它轮次的完整诊断。其它失败现场、规则和生成状态通过补集保留。
原生补集归档已完成。已有 D 副本逐件重核源/目标摘要，其余材料的新内部归档逐成员流式验证通过。不覆盖原回执，不恢复或改写旧绝对路径，不将保存材料称为搬迁后可原位续编。历史九项 DevTools 变更对象已逐项确认属于保留集合，不在可退役候选中。
## 留存证据与尚未完成项
- [实际身份全根盘点](../build/audit/dependency-trim-20261116-pip-r1/evidence/current-workroot-delta-r2/result.json)
- [链接边界与原归档身份沿袭](../build/audit/dependency-trim-20261116-pip-r1/evidence/workroot-boundary-review-r1.json)
- [新增工作目录和归档副本核验](../build/audit/dependency-trim-20261116-pip-r1/evidence/new-retention-directories-review-r1.json)
- [原生精确分类](../build/audit/dependency-trim-20261116-pip-r1/evidence/native-hold-classification-r1/result.json)
- [互斥完整分区与 D 留存计划](../build/audit/dependency-trim-20261116-pip-r1/evidence/native-retention-copy-plan-r1.json)
- [实际生产边及定义抽查](../build/audit/dependency-trim-20261116-pip-r1/evidence/native-classification-primary-samples-r1.json)
- [补集归档驱动定向夹具](../build/audit/dependency-trim-20261116-pip-r1/evidence/native-complement-retention-directed-tests-r1.json)
- [原生补集实际归档与逐成员核验](../build/audit/dependency-trim-20261116-pip-r1/evidence/native-complement-retention-r1/result.json)
- [历史变更对象保留绑定](../build/audit/dependency-trim-20261116-pip-r1/evidence/native-historical-object-retention-review-r1.json)
- [原冻结 RETAIN 集合迁回映射](../build/audit/dependency-trim-20261116-pip-r1/evidence/retained-source-archive-copy-r2.json)
- [候选交付副本覆盖与清理预演](DEPENDENCY_TRIM_20261116_CLEANUP_PREVIEW.md)
- [运行归档最终路径映射](../build/audit/dependency-trim-20261116-pip-r1/evidence/local-archive-promotion-r1.json)
- [固定设置及程序入口的有限范围引用检查](../build/audit/dependency-trim-20261116-pip-r1/evidence/fixed-workroot-reference-review-r1.json)
固定设置和已列明入口文本未发现 E 工作根的字面引用；没有据此声称所有动态构造路径、系统环境或第三方代码均不存在引用。没有重新启动应用、运行 GPU、读取模型载荷或私有解锁材料。
全根逐项留存/候选覆盖、原生补集归档和整根最终预演均已完成，没有未列明的当前路径。实际永久删除尚未执行，也未取得本线程当次实际删除批准。后续执行器的严格前置检查另有只读属性及进程可检查性阻塞，不将内容覆盖完成等同于实际执行可以放行。完整传递输入闭包、迁移后重建和工具链重装未验证，不将这些限制隐藏为 PASS。公开发布的来源、许可及当次程序/文案审查门禁不变。
## 实际保留结果与整根最终预演
| 本次原生补集实际结果 | 数值 |
| --- | ---: |
| 新归档普通文件 | 158629 |
| 新归档逻辑字节 | 12355255910 |
| 已逐成员核验 | 158629 |
| 复用并重核源/目标的 D 副本 | 2392 |
| 复用副本逻辑字节 | 515080420 |
| 内部归档压缩字节 | 1674493564 |
内部补集归档：[Umi-OCR_NativeRetainedComplement_20261116_r1.tar.xz](../build/retained/dependency-trim-20261114-r1/native-complement-r1/Umi-OCR_NativeRetainedComplement_20261116_r1.tar.xz)。
SHA-256：
da54978ef58ac98c414dfc91cce09a44894500b2c9119464f0e7d984c11d0a23
该内部归档不是公开发布附件。既有来源归档、运行/对应源码归档、原始审计、PCH 直接输入和历史诊断继续保留；不以新补集替代或删除它们。
| 整根最终预演 | 数值 |
| --- | ---: |
| 已有 D 内容保留覆盖的普通文件 | 606335 |
| 对应 E 原件逻辑字节 | 62297416705 |
| 实际生产证实的编译/PCH 退役候选 | 22572 |
| 候选逻辑字节 | 36616931919 |
| 目录，不含根本身 | 75890 |
| 已留存原文的符号链接 | 13 |
| 精确清单项目，含根本身 | 704811 |
清理目标包含以下全部内容，但本轮不执行删除：
| 精确根或路径 | 依据 |
| --- | --- |
| E:/Umi-OCR-build/dependency-trim-20261114-r1 | 冻结 RETAIN、交付候选副本、原生补集及编译中间候选已逐项归类，没有未知余项。 |
| E:/Umi-OCR-build/retention-20261116-r1 | 原归档预检失败留下的空工作目录，原失败证据已保留 D。 |
| E:/Umi-OCR-build/retention-20261116-r2 | 仅含本轮来源保留归档，E/D 当前内容摘要一致。 |
| E:/Umi-OCR-build 本身 | 仅在后代按精确清单移除后，检查为空、无占用且无路径变化，再最后移除。 |
[整根最终预演回执](../build/audit/dependency-trim-20261116-pip-r1/evidence/whole-workroot-preview-r1/result.json)绑定完整逐项清单和所有前置回执。[独立核对回执](../build/audit/dependency-trim-20261116-pip-r1/evidence/whole-workroot-preview-primary-review-r1.json)确认清单与实际盘点集合一致、分类互斥、根本身已列入且 D 留存位置存在。
逐项清单为 build/audit/dependency-trim-20261116-pip-r1/evidence/whole-workroot-preview-r1/entries.jsonl，体积较大，不作为聊天附件重复发送。
清单 SHA-256：
1f49f4d28ae36d6cf428c642b59123d440a38a3ddc86d3dbba5e24d5b820863a
预演前后没有观察到从 E 工作根运行的程序。预演重新核对全根实际身份和元数据，并重算最终 D 归档摘要；原源文件内容验证复用已绑定的归档成员与副本核验，不冒充本次再次逐源文件哈希。
**实际执行门禁：**永久删除不进回收站，不能撤销。必须先取得当前具体范围的实际删除批准，再重新核对全清单、保留证据、进程占用及根内链接边界。遇到新增未知文件、链接越界、活动进程或权限拒绝时停止相关动作，不终止用户进程，不换工具绕过。D 保留材料、固定安装、兄弟项目和外部源码不进入删除范围。

执行器仅在 D 合成夹具运行。工具、自测成功/原失败、新鲜占用及当前阻塞详见[执行器审阅](DEPENDENCY_TRIM_20261116_E_DELETE_EXECUTOR_REVIEW.md)。原冻结预演和交接索引保持不变，后续执行器及其门禁材料独立交接，不回写历史“尚未实现”记录。
后继 r2 执行器与 D 合成自测已准备完成，见[准确路径与摘要补充交接](../build/audit/dependency-trim-20261116-pip-r1/evidence/e-root-executor-handoff-r2.json)。r1 原件和回执保留但不用于真实执行。当前冻结只读项及进程可检查性仍阻塞，实际 E 删除没有执行；执行器存在不代表获得本线程删除授权或真实门禁通过。
