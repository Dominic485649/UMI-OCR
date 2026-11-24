# 启动、小文件与设置整合实施记录

开始：2026-10-28。收尾：2026-10-29。依据用户要求整合 [原提案](STARTUP_AND_SMALL_FILES_OPTIMIZATION_PROPOSAL.md) 与 [设置更新](SETTINGS_GPU_UPDATE_3.1.0.md)。本轮交付是本地非最终候选，不覆盖固定安装、不 push、tag 或公开发布。

## 组件和实际产物

| 组件 | 版本 | 最终构建输入 |
| --- | --- | --- |
| 主程序 | 3.1.0 | `build/staging/startup-small-files-20261029-base-stored-r2` |
| CUDA | 3.0.5 | `build/staging/startup-small-files-20261029-cuda-r1`，安装覆盖层另存本项目 artifacts |
| PaddleVL | 3.1.0 | 授权插件项目 `build/staging/startup-small-files-20261029-vl-r2`，安装覆盖层另存本项目 artifacts |

三个实际 tar.xz 的路径、SHA-256 和发行文案见 [候选审查](RELEASE_REVIEW_STARTUP_2026-10-29.md)。主程序 r2 修复真实七语验收发现的 About 泰米尔语长标题裁切，插件内容没有因此重建。

实际归档已经各自解到独立新目录，再把已核对的插件目录同卷重命名装配到 `build/tmp/startup-small-files-20261028-r1/startup-small-files-20261029-reinstalled-r1`。固定 `release/Umi-OCR` 不动。

原重装在最后写 JSON 时因磁盘耗尽退出，截断 `result.json` 和原始错误保留。恢复空间后，用新的 `recovered-verification.json` 对全部 23817 个安装文件独立重验，确认与三个实际归档的联合载荷完全一致。不把此复核冒称为重新解压或原工具首次退出成功。

归档重装后的组合原生 Qt 验收 R4 全部通过，包含模型切换、两插件 GPU 下拉、任务来源独立读写、七语及 About pending→ready/复制，并恢复自有配置为空。随后在同一重装根串行通过 CUDA 普通图、PaddleVL 普通图与原 PDF 第 2 页的实际 GPU 验收，以及正常主 EXE、第二个真实 EXE 的 CLI 转发、HTTP 后端注册和无效后端 804/INVALID_OPTIONS 应答。最终自有配置、状态和 138 个已按源码核验的缓存均原字节保留在审计/工作目录，没有采用或删除用户数据。`final-payload-20261029-r1/result.json` 确认全部 23817 个产品文件与三个归档联合载荷完全相等，22357 个文件不大于 64 KiB，逻辑大小 9752271428 字节，文件系统分配空间 9793194776 字节；产品 NTFS 压缩属性文件数为 0。

## 启动实现与结论

- 观测默认关闭。S0 为外部进程创建前的统一时钟，S4 为真实 Qt 首帧，S5 另加实际可操作与外部应答；S6 只覆盖具名非必要任务。
- 使用独立配置、持久缓存、自有 PID/端口和正常退出，不清系统缓存，不关闭安全软件，不杀测量 GUI。
- About 的详细平台、CPU、RAM 信息从 QML 装载前同步路径迁到受控后台线程，GUI 定时提交只读通知对象。保留旧同步初始化接口，不重复替换全局 QML 上下文。
- 覆盖成功、失败、取消、销毁、晚到结果和退出。About 等待、失败、取消文案完成六份翻译编译，简中使用源文。
- 同散文件布局正常 EXE 的交错对照为八对有效样本，另有预热。配对差值区间包含零，结论 INCONCLUSIVE，不能宣称稳定总体提速。
- 实测确认平台诊断在 QML 装载返回后开始，不把这个路径变化换算为未经证明的总耗时收益。不采用旧交接中无法绑定原始证据的约 24 ms 数字。
- r2 只改变非启动页面的 About 布局，没有重复性能对照，不将旧实测当成本轮 r2 的新跑结果。

## 小文件布局与来源

- 宿主 `app.zip`、`dependencies.zip`；两个插件各有独立 `vendor.zip`。均保存原始 Python 字节，ZIP_STORED、不压缩、构建不预编译 pyc、不启动时整体解包。
- 原生 DLL/PYD、模型、真实路径资源、Qt/QML、dist-info、许可证继续外置，未生成 RCC。
- 显式整包或单模块白名单、固定时间戳和顺序，包含必要的 namespace 目录。第三方成员保留原 wheel RECORD，另对独立种子或规范源码输入核验，不只是清单自证。
- 缺档、损坏、冲突、未完成装配、未声明容器和 legacy 声明明确拒绝，不回退旧散文件。
- baidubce、networkx、huggingface_hub 等路径约束包保持外置，没有为了文件数放宽资源或模型目录规则。
- 取消本轮构建中无差别按后缀/目录名裁剪的规则。旧种子已有裁剪不算本轮新成果，也不假称已还原全部历史裁剪。
- 聚合原文件为主程序 107、CUDA 259、VL 1743。容器和新增证据有开销，完整目录差异还包含源码交付形态，不把所有差异归因于 ZIP，更不宣称内容被压缩。
- 正常 EXE 为未聚合的外置模块生成了 138 个常规 pyc 缓存，共 2711423 字节。它们不是构建预编译或容器成员；已逐项验证与独立归档源码及完整嵌套代码对象一致，不执行缓存，也不按后缀直接忽略或删除。运行后文件数仍可能增加，不能把干净载荷数当作永久上限。

## 验证、成本和限制

已完成宿主实际 EXE、第二 EXE CLI 转发、回环 HTTP；修复后的本体实际 Qt 七语、About pending→ready 和复制。CUDA 普通图，VL 普通图和原 PDF 第 2 页均通过直接 worker 验收，实际模块来自本轮私有 ZIP。worker 原 JSON stop 与服务原 shutdown 路径分别留证，Windows 服务 terminate 不称为优雅 JSON 退出。

新增聚合/启动/生命周期/来源/打包/重装定向测试均逐组保留真实日志，不用纯 fixture 替代实际 GUI/GPU，也不把重复执行的批次加总成不同用例。磁盘故障后增加按卷簇大小、额外余量和原子验收记录保护，并做微型故障注入；没有用这些微型通过覆盖旧的大文件记录失败。

本轮最小 GPU 请求保持 8192 context、单槽、4096 输出，模型原精度和原始文件不变。密集图历史质量 FAIL 保留，不重跑完整资源矩阵，不宣称已测最大输入/输出。

分别记录组件构建、外层归档生成/校验、实际解包/组合核验和 worker 内部初始化/请求时间。完整直接复制未计时，不报告端到端搬运更快。归档压缩参数不同且有并行任务，耗时不作压缩器 A/B 结论。

仅对明确列出的本轮自有暂存和已完成副本做可逆 NTFS 压缩，前后核对原字节。不将其节省计作 ZIP 收益，原未压缩运行记录不改写，最终安装根保持未压缩。小文件在满盘时压缩失败的原记录也保留，未改权限、未强制重试，未删除大文件。

CUDA 公开证据中的 cuDNN、AGPL/NVIDIA 与公开源码/current-source 门禁仍有 BLOCK。本轮许可/来源材料保留核对不等于获得公开发行资格。必须等待本次实际程序和文案审查，并满足正式门禁后才可发布。

## 审计和源码边界

审计根：`build/audit/startup-small-files-20261028-r1`。旧暂停和交接文件仅为历史，不代表当前仍暂停。

- `startup-performance-20261029-r1.json` 与独立原始样本：启动统计与不确定结论。
- `independent-archive-inputs-20261029-r1`、`base-r2-independent-source-20261029-r1.json`：真实成员和独立来源。
- `stored-base-native-ui-20261029-r4`、各 `stored-*-acceptance-20261029-r1`：本体七语及实际 GPU 输出。
- `stored-combined-native-ui-20261029-r4/report.json`：实际归档重装根的组合原生 Qt 全部 required PASS，正常退出和配置还原。
- `reinstalled-cuda-acceptance-20261029-r1`、`reinstalled-vl-acceptance-20261029-r1`：重装根实际 GPU 请求、真实 ZIP 模块来源、同服务复用和释放记录。
- `reinstalled-native-cli-20261029-r1`：正常主 EXE、真实第二 EXE CLI、组合 HTTP 注册和明确拒绝路径，不是性能或 HTTP GPU 推理样本。
- `final-payload-20261029-r1/result.json`：全部 23817 文件逐字节匹配、无 NTFS 压缩、自有状态和源码绑定缓存原样移出保留；不改写原运行的绝对路径证据。
- `reinstalled-first-model-cost-20261029-r1.json`：最终重装根单次原 worker 初始化/请求时间及 VL 服务首次就绪时间，派生自已有观测；注明与早期副本压缩并行，不作无干扰性能或提速结论。
- `native-cli-control-preflight-20261029-r1.json`：首次目录内控制器被严格占用检查拒绝；后续只换到目录外的标准库控制解释器，未放宽检查或更换实际被测 EXE。
- `archive-7zip-20261029-r1`：实际最终归档与独立完整性检查。
- `reinstalled-archives-20261029-r1/recovered-verification.json`：恢复空间后的独立全安装字节复核，原失败不改写。
- `source-license-20261029-r1` 及 clarification、`base-r2-source-license-reuse-20261029-r1.json`：对应源码与许可材料，明确复用边界和公开 BLOCK。
- `executed-packaging-tools-20261029-r1`、原执行安装工具：保留实际执行代码字节，后续工具加固不冒充早先使用了新代码。
- `plugin-startup-only-20261029-r1.json/.patch`：相对原 dirty 基线只列本轮插件增量，不全量提交插件项目。
- `native-generated-cache-20261029-r1`：最终还原首次白名单拒绝、原查询源码/失败日志及 138 个自有运行缓存的源码绑定核验；`generated-bytecode-fixtures-20261029-r2` 为 6 项定向测试 PASS，r1 异常类型预期失败保留。
- `compact-nonresident-early-ui-20261029-r2`：仅继续无损压缩前次已核对的四个早期自有宿主副本，全文件哈希不变，未删除文件或压缩最终安装。
- `CLEANUP_PREVIEW.md`：清理预演，没有执行旧程序或大文件删除。

主仓库开始基点为 f4a0ca1b。运行实现、构建与审计工具已在本地源码检查点 `ab61602ab6030acfe8db5eda292146fe9eab34af` 提交，未推送。`local-source-checkpoint-20261029-r1.json` 核对当前宿主 232 个源码/资源文件及 CUDA 12 个文件与实际候选规范快照一致。

这个提交发生在候选构建之后，不能冒充当时的构建 Git 基点；产品仍绑定原始 source-snapshot 与 dirty provenance。本次收尾提交只包含新验收驱动、源码绑定缓存核验器及定向测试、最终实施与审查材料，没有改动已冻结产品的运行代码。收尾提交身份单列于本轮审计的 `local-closeout-20261029-r1.json`，不推送；插件原 dirty 与原索引保留。
