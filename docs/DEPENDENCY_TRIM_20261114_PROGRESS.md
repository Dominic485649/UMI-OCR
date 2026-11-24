# 全组件依赖裁切：进行中检查点（2026-11-15）

> **恢复事实：2026-11-15 04:21（+08:00）已按一次性定时任务实际恢复。** 恢复前没有发现本轮活动进程，原中断日志保持；旧清理已取得最终回执，分段统计见最新检查点，不以预演统计代替完成。投影读取边界已补齐并通过新定向测试，CUDA 五包裁切组合已在新记录中通过实际 GPU/PDF/二维码验证。Qt 原生链仍在推进，两个插件的最终归档与重装已完成；Paddle 原生重编的工具链阻塞仍保留。暂停及恢复事实分别见审计目录 `PAUSED_20261115_012051.md`、`RESUMED_20261115_0421.md`；下文历史“运行中/暂停”仅对应当时检查点。

这不是新版本发布或最终交付报告。固定安装仍为主程序 **3.1.4**、CUDA **3.0.5**、PaddleVL **3.1.3**，`release/Umi-OCR` 没有更新。已有实际依赖变化的 CUDA 源清单已独立升为 **3.0.6**，PaddleVL 的 VERSION 与权威插件清单已独立升为 **3.1.4**，其它组件不强制对齐。未推送、未打发行标签、未发布，也没有取得本轮公开发布审查同意。

## 2026-11-15 QtWebEngine 真实 DLL 链接及输入验收

- 原 r6 标准 CMake 目标实际自动重新生成 GN，随后编译 9 个 DevTools 对象并成功链接 Qt6WebEngineCore.dll。原续编计划中的“未重新生成”不符合实际执行；旧 r6 FAILED 回执不改写，新目标验收明确纠正执行范围。失败发生于链接后的旧响应文件摘要检查，不是 DLL 链接器返回失败。
- 实际对象响应文件与生成前快照的 4,649 条原始路径字符串多重集相同，无新增或缺失，但保留项顺序变化。静态库响应文件的 1,286 项顺序和完整字节、系统库响应字节保持。原独立对比记录显示本次重编的 9 个 DevTools 对象字节均变化；其余对象没有全量重哈希，不声称字节不变。
- 未修改严格验证器或放宽摘要门禁。原线程针对本次实际响应文件重新执行完整旧 Ninja 归属、旧 Mojo 闭包、多重集与完整生成字节比较，另用原 linked 模式严格核对本次快照。新图证明为 `165a3f26fc6c1c3b612f7d7aa3655ad131e4abe9df8be7621c75a7fc87574c38`，严格链接输入证明为 `7c9f76cf3706855cc62a1963f8245bb1af1cc693d013445eea6c3d6d96baac08`。该后置验收没有再次生成或链接；与 r6 标准目标内确实发生的重新生成分开记录。
- 新严格根图保持 9,455 项，原根为 9,496 项，无新增；实际对象从原 4,662 项减为 4,649 项。移除项限定于已禁用 Mojo 的旧闭包。旧图证明仍支持原修复范围和移除归属，不用于证明最终响应文件顺序或本次重编对象字节相同。
- 目标验收入口为 `evidence/qt-native-r6-targeted-link-acceptance-r1/result.json`。实际 DLL 为 177,318,912 字节，SHA256 `7f545e03976de3a2718e9d1b7a93690e61e5ab5709559f3f730d302e31d3d285`。主线程重算真实 DLL、实际响应文件、冻结生成文件和根图及绑定原件，读取原链接日志，未重复链接、完整成员比较或九对象哈希。独立复核为 `evidence/qt-native-r6-linked-primary-review-r1.json`，SHA256 `e8e3cabec91cbc392cfc2f436ea745af67f26c6ae353f0759cc37f29d91c96e3`。
- 本检查点仅确认真实 DLL 目标及其严格输入验收。剩余 build/install、PySide、最终 bundle/lock、ABI/QML、离线富预览、新本体归档和最终组合仍未验收。固定安装和用户数据未修改，未推送或公开发布。原失败、冻结输入、对象和日志继续保留，不扩大清理范围。

## 2026-11-15 DevTools 条件依赖修复与公开源码出口

- Qt r4 在通过真实 protobuf 生成目标后，继续到 Qt6WebEngineCore.dll 最终链接失败。原日志记录 32 条 LNK2019/LNK2001 诊断，链接器汇总 22 个唯一缺失符号，不能混作同一计数。实际根依赖图中，DevTools 是扩展 Mojo 的唯一活动直接消费者；两个扩展开关均为零，所需 common 实现不在实际链接闭包。原始 Qt 模板仍无条件加入这条依赖，先前三项补丁没有修改该模板。
- 新公开补丁 `build/patches/qtwebengine-6.11.2-devtools-extension-guard.patch` 仅将该 Mojo 依赖移入已有 `enable_extensions_core` 条件。其 SHA256 为 `fa2904f1823779d30a52ffb7aa914295d7c2bc5c6e34aeb3560c351edfad4d0a`。全部 18 项 DevTools 源/头文件、其它依赖和功能值保留，不启用扩展、不补入未用 provider、不忽略未解析符号。
- 原线程实际执行 6 项轻量 GN 夹具测试，通过关闭分支只排除该依赖、开启分支保留原 deps/configs 和全部源文件的检查。主线程读取测试源码、原始日志，并重算补丁、原/候选模板及回执摘要。没有把轻量图当完整 Qt 重新生成或 C++ 编译，也未由主线程重复执行这 6 项。
- 公开源码出口只增加这个精确补丁名，不放宽目录规则。主线程实际分两批运行 5 项定向测试，源码选择、实际补丁镜像、重新打开 ZIP 后的成员与字节核对通过；私有解锁材料、未审阅补丁、嵌套补丁及审计路径继续排除。两批共享实现与测试输入摘要相同。合成临时子树已由测试自身清理，原始日志和摘要保留。
- 新证据入口为 `evidence/qt-devtools-guard-primary-review-r1.json` 及 `evidence/qt-devtools-source-export-r1/result.json`。链接根因和原始材料保存在 `evidence/qt-link-extension-analysis-r1/result.json`，轻量 GN 结果保存在 `evidence/qt-devtools-guard-fixtures-r1/result.json`。
- 修复后完整 GN/实际链接、Qt 安装、PySide 和运行验收尚未由本检查点验收，不以补丁或夹具通过代替。原 r4 失败、旧源码归档和旧映射保留；已有插件归档不回写。固定安装未更新，模型、私有源码和用户数据未动，未推送或发布。

## 2026-11-15 最终插件归档、Qt 源码与旧清理终态

本节为后续真实终态，下方历史检查点保留当时状态，不把旧失败或等待记录改写为本次通过。

- Qt 九模块源码归档实际完成，合计 126,923,504 字节。主线程重算九份归档、各模块清单/输入记录、两份导出器、三项补丁及 27 项构建来源材料摘要，并核对固定提交和特殊链接。原 54,323 普通文件逐成员验证复用，未重复源码工作树比较或从归档重建。WebEngine 原归档沿用冻结来源记录；相关材料仍映射原路径，尚非共址公开源码包。入口：`evidence/qt-source-archives-completed-primary-review-r1.json`。
- Qt r3 续编真实失败于 protobuf TypeScript 生成链。全局 Python 3.15.1 与 PYTHONHOME 指定的 3.13.16 标准库错配，同环境负对照复现 WarningMessage 参数错误；固定 SDK PATH 正对照导入通过。主线程核对原日志、解释器、原插件及三条失败终态；PySide/finalize 只是因上游 FAILED 停止，没有开始完整编译。入口：`evidence/qt-python-resolution-primary-review-r1.json`。r4 串行恢复链已实际重做并通过原失败目标，主线程核对真实 Ninja ACTION、回执与 992,747 字节的生成文件摘要，见 `evidence/qt-actual-proto-r4-primary-review-r1.json`。启动输入与独立追加 recipe 已核对，见 `evidence/qt-serial-r4-primary-input-review-r1.json`。串行链继续原缓存；尚无可交付 Qt bundle/lock、完整 ABI/QML 或离线富预览终态。
- CUDA E r3 最终运行归档及独立源码归档已完成，正式全新重装核对 6,140 文件、3,985,147,709 逻辑字节；源码归档核对 320 文件、1,489,458,770 逻辑字节。主线程重算两件归档及绑定回执，比较完整运行清单并核对重装 SOURCE.txt，不重复原逐成员核验。GPU r5 仅按私有执行字节未变复用，未在 E 重跑。入口：`evidence/cuda-e-final-primary-review-r1.json`。
- PaddleVL 最终运行包与补充源码包共置于 E 插件交付根 `build/artifacts/vl-final-r2`。正式全新重装核对 7,738 文件、4,745,237,537 逻辑字节，包内/重装 CPU、KMeans、私有提供者和完整运行锁通过；最终源码核对 833 文件。主线程重算最终归档、回执与原 GPU 证据，核对实际重装源码指引和锁。最终运行包与首次重装归档相同，复用同次重装，不声称再次解包、重编或 GPU。入口：`evidence/vl-e-final-primary-review-r1.json`。
- PaddleVL 科学库三份官方同版本 sdist、原 PyPI 元数据/URL/摘要、原 wheel、raw/CRLF 差异诊断、独立原 inventory 及默认失败/显式恢复材料已实际进入最终源码归档。原 r1 初始源包覆盖缺口和失败保持。SciPy/OpenBLAS 开发版精确提交/构建及 NumPy/native 官方 wheel 精确来源仍未证明；公开来源和许可门禁不改为 PASS。
- 两插件归档的真实大小、摘要、源码绑定和未验收限制已更新到各自 Release 草稿。新 Qt 本体、最终三组件组合、固定安装更新及本轮公开发布审查仍未完成。本次没有修改固定安装或用户数据，没有模型、私有源码、推送、发行标签或公开发布操作。

### 旧运行现场退役的最终分段统计

`old-runtime-retirement-r3` 已终态 `READY_SCOPE_COMPLETED_WITH_PRESERVATIONS`，独立后验 PASS，无错误或阻塞。持久 journal 的实际新删除、历史 r2 与合计分开记录：

| 范围 | 文件数 | 逻辑字节 |
| --- | ---: | ---: |
| 新 r3 实际删除并后验消失 | 676,163 | 9,371,600,997 |
| 历史 r2 已确认删除 | 59,280 | 829,362,299 |
| 旧现场两阶段合计 | 735,443 | 10,200,963,296 |
| 当前源码引用而保留 | 143,346 | 2,645,789,405 |

153 组均完成，alreadyAbsent 为零。原执行后验重新哈希 18,269 个不同保留原件，历史证据未改变。主线程重算执行/后验回执及持久 journal 摘要，核对分段、总数、阻塞与错误字段，未再执行数十万路径后验或保留原件哈希。旧分类器名 `R2_DELETED_CONFIRMED_ABSENT` 本轮指新 journal，不能与 newDeleted 字段重复相加。入口：`evidence/old-runtime-retirement-r3/primary-readonly-review-r1.json`。

本表不包含下节独立 complete/runtime 退役，也不代表物理空间回收或并行构建期间磁盘空闲净增量。目录删除、只读属性清除及用户进程终止均为零；当前来源、保留候选、模型、私有源码、缓存、固定安装和兄弟项目未扩大纳入范围。最终归档、源材料、重装树及历史证据仍被后续装配和审计引用，继续保留。

## 2026-11-15 runtime 精确退役完成

- runtime 独立执行已终态 `RUNTIME_NONMODEL_RETIREMENT_VERIFIED`：实际删除 5,283 项、3,738,992,757 逻辑字节，持久回执与执行器实际路径消失后验一致；alreadyAbsent 为零，blocked 为 null，后验错误为空。实时进程快照 5,306 次，没有降低既定占用检查。
- runtime 最终保留 151 字节 Python 引导文件及 3,507 字节全 NUL 损坏样本。主线程重新计算这两个实际文件的大小和摘要，与原记录匹配；没有修改或删除它们。目录、模型删除及用户进程终止均为零，不访问 complete、不改保留 staging。
- 主线程读取终态并重算结果、压缩删除 journal、保留证据前后记录、原范围/预演/清单和先前 complete 结果摘要。未重复删除、逐条 journal 计数或全部路径后验；原执行与后验记录保持。入口：`evidence/cuda-runtime-retirement-primary-review-r1.json`。
- 与此前独立 complete 范围合计实际退役 11,605 文件、8,930,656,650 逻辑字节。这不是物理空闲增量，也不包含仍待自动终态的旧 r3 清理。未扩大删除范围或更改固定安装。

## 2026-11-15 科学源码补充与外置清单复核

- PaddleVL 已取得 SciPy、scikit-learn、NumPy 的官方同版本 sdist。主线程重算三份实际归档的大小/SHA，并核对保存的原 PyPI JSON 摘要及对应 sdist 的文件名、版本、URL、大小和摘要；不是重新下载或重新执行 tar 成员检查。现有原生 wheel 的精确构建来源仍未独立证明，特别是 SciPy 所用 OpenBLAS 开发版本的确切提交与构建。来源补充不等于公开发布门禁通过。
- 默认 Stored-ZIP 来源审计因最简树已外置输入清单而失败，日志原件保持。后继显式恢复已报告 1,743 成员验证及恢复清单与独立原件逐字节相同；主线程重算独立原件大小/SHA、原失败日志摘要，并读取原错误，没有重跑恢复或更改默认门禁。
- 原 E 盘运行/源码归档的冻结输入不改；新源码归档另行纳入上游源码、独立原清单及失败/恢复证据。最终成员、SOURCE.txt 与重装验收仍待终态。独立复核入口：`evidence/vl-scientific-sources-and-stored-primary-review-r1.json`。

## 2026-11-15 跨卷安装边界与对应源码核对
- 主线程使用目标 Python 3.13.16，在全新惰性夹具中实际验证 E 盘来源到 D 盘固定目录及同卷事务：正常提交、注入故障后的完整回滚、错误备份卷拒绝均通过。来源前后字节不变，合成配置、日志和未知数据保持；未操作真实固定安装、模型或私有材料，未启动夹具程序。没有修改更新器，也没有重复此前四十项测试或重新验证真实应用的占用发现。回执：`evidence/fixed-installation-cross-volume-r1/result.json`；小型输入、事务 journal 和结果保留用于复现。
- 主线程定位并重算派生 OpenCV 的匹配源码归档、源码清单、实际构建结果与原执行 recipe，以及匹配的封装和源码导出 recipe 摘要，均与既有回执一致。源码归档为 `build/artifacts/dependency-trim-native-20261114-r1/opencv-source-r1/opencv-4.10.0-71d3237a-source.tar.xz`，构建原件位于 `evidence/opencv-build-r3`。原工作树逐文件比较沿用原来源回执，没有冒充本次重做；材料已交给 CUDA/VL 分包线程实际纳入独立源码包，最终归档尚未验收。入口：`evidence/opencv-delivery-source-primary-review-r1.json`。旧官方 `LICENSES/opencv-artifact.json` 不是该派生 wheel 的来源证据。
- 已读取完成的 Jumbo 生成差异回执，并重新计算九份当前生成文件摘要，全部匹配其实际输出。原回执的十三处 include 逆替换与源码身份验证没有重跑，不扩张为整个 Qt 或应用验收。入口：`evidence/jumbo-generated-delta-primary-review-r1.json`。
## 2026-11-15 派生 Qt 正式接入与 E 盘分包工作根
- 正式 `Build-Release.ps1` 新增成对派生 Qt bundle/lock 参数；无参数沿用原行为，有参数时由严格投影器直接生成最终依赖树和新清单，不借用旧种子白名单，不重写版本遮蔽不匹配。十二项定向测试通过，覆盖真实 PowerShell AST 分支和真实严格投影器的不可执行合成载荷。主线程审阅差异、原始日志，核对当前及冻结脚本/测试和旧输入摘要；没有重复测试或启动正式本体构建。完整 `.build` 清理仍覆盖新增中间树。入口：`evidence/build-release-derived-qt-primary-review-r1.json`。
- 原 C1083 的实际 `platform_jumbo_42.obj` 已重新编译成功，主线程重算该对象摘要和大小，与 `evidence/qtwebengine-resume-r5-r3/targeted-result.json` 相符。完整 Qt/PySide 和应用验收仍在独立后续链中，不能把单个目标成功扩大为整体验收。
- D 盘不足原 CUDA 分包门槛，未降低门槛或增加删除范围。在既有 E 项目专属工作根下冻结约一 MiB 的标准工具副本，模块自然定位到副本根，没有修改或猴补 `ROOT/work_path`。实际执行本体/CUDA/VL 三组微型 prepare/verify/package/重装及四个越界拒绝检查，全部通过；这只是路径与工具链验证，不是真实组件交付通过。入口：`evidence/delivery-tooling-relocation-r1/probe-result.json`。
- 后续 CUDA 与 VL 大载荷分别限定在 E 交付根的独立工作树，各自累计新增上限 30 GiB。阶段前重新核对实际空间，扣除尚未分配预算后仍须保留 Qt 既有 80 GiB 保守门槛与额外 10 GiB；不把该值说成实测峰值。D 仅记录小型审计索引，继续保留 Qt 3 GiB 和额外 5 GiB。原 D 输入、原始路径/摘要和历史验收原件保持，新迁移与元数据派生另记；不以迁移冒充重建或重跑 GPU。
## 2026-11-15 新原生模型验收与 Qt 源码出口
- PaddleVL r5 单份 complete 构建通过，主线程重算构建输入、结果和原生完整清单，核对十项实际冻结源码与当时工作树一致。新 native 的真实 GPU OCR、复杂文档 HTTP、同进程共享服务及非空官方标题聚类通过，不复用旧服务 GPU PASS。主线程读取实际输入与结果，将十五项运行时捕获的原生提供者路径/摘要与派生 manifest 交叉核对，重算当前 runtime.lock 及 JSON/Markdown/文本导出，与记录一致；模型只比较原始前后摘要记录，没有再读大权重。仅 RTX 4060 实测，最终归档重装及固定安装仍未完成。入口：`evidence/vl-r5-primary-readonly-review-r1.json`。
- 新 bundle 的 subprocess 来源角色说明误沿用了旧完整构建记录的措辞，兼容 inputs/result 必须与 `original-build` 下的实际原件区分。该问题不改变已执行的原生二进制，但最终交付需精确修正说明并重新绑定清单与对应源码；旧 r5 GPU、清单、来源 proof 保持，不把修订后的源码当作旧验收输入。
- Qt Jumbo 生成器补丁的六项定向测试及同 MSVC 生成 include 探针已通过。主线程读取日志并核对补丁、测试、冻结生成器及结果绑定；不是重跑编译，也不是完整 Qt 验收。原缓存已进入独立恢复链，真实目标与最终应用结果另记。入口：`evidence/qt-jumbo-primary-review-r1.json`。
- 主线程补齐公开源码导出的单项 Jumbo 补丁白名单，四项定向测试实际通过，覆盖真实源码选择、精确补丁字节镜像及私有解锁/未审阅补丁排除。测试日志和冻结源码保留，仅删除已空、无占用的本轮临时子目录。入口：`evidence/qt-source-export-r1/result.json`。不放宽私有源码边界。
## 2026-11-15 07:21 complete 精确退役终态及后续 runtime 范围

- 已审阅的中断 `complete` 非模型副本实际删除 6,322 项、5,191,663,893 逻辑字节，执行器后验确认这些路径全部消失且错误列表为空；不是预演数。保留文件共 22 项、185,082,532 字节，其中 21 项位于模型目录，另一项为 151 字节的 Python 引导文件 `vendor/distutils-precedence.pth`。原回执使用保守 `.pth` 保护分类，不能把全部保留项称为模型权重；新分类说明不改写历史记录，不删除引导文件。目录删除为零，不终止进程、不清属性，不修改 runtime、保留 staging 或原审计证据。
- 主线程读取终态并重算回执及压缩 journal 摘要，二者绑定一致；前后保留证据记录逐字节相同。另列出 complete 剩余文件并读取引导配置，没有重复逐项路径后验或模型哈希。入口：`evidence/cuda-complete-retirement-execution-r1/execution-result.json`、`evidence/cuda-complete-retirement-primary-review-r1.json`、`evidence/cuda-complete-retained-classification-r1.json`。
- 通知后的 D 盘实际空闲采样为 18,123,898,880 字节，仍低于 CUDA 分包所需 20 GiB；不将逻辑删除量当作并行任务期间的净空闲增量，也不挪用 VL/Qt 预留。
- runtime 新只读预演的 5,285 项已全量核对，只证明其中 5,283 项、3,738,992,757 字节为同 SHA 非模型副本。主线程核对预演与清单摘要后，将原清理任务的后续执行严格限定在该子集；损坏的 3,507 字节文件、151 字节引导文件及所有目录继续原位保留。新范围包装须先通过定向自检，并在删除前重新核对占用、身份、来源及引用；实际完成只看新执行回执。入口：`evidence/cuda-runtime-retirement-scope-r1.json`。新 CUDA r4 仍保留同名引导文件，目前没有依据预防性修改已测固定安装更新器。

## 2026-11-15 正式交付衔接检查（后续）

- VL 源码外置的旧完整 bundle 隔离验证通过：精确外置六项来源材料，运行二进制与许可保持，实际 runtime 检查、最简分包入口、SOURCE.txt 及真实源码归档成员核验通过。主线程随后指出归档全成员大小写/路径形状检查和解压读取预算缺口；补强后的 r4 原始日志为 38 项通过，既有真实夹具只读复验通过，未复制大夹具或改写旧 producer/test 绑定。入口：`evidence/vl-llama-hardened-static-primary-review-r1.json`。代理后续 r5 工具修订另有测试，须随新完整候选绑定，不能套用本次旧修订记录。旧 r4 仍不满足最终最简交付。
- llama 新二进制静态回执已记录七组架构各 146 个 ELF 条目、四组 attention 量化组合及 39 个实际对象无缺项；主线程核对原始 cuobjdump 日志摘要与回执一致，未重复执行静态工具。九项自编译二进制逻辑体积合计仅净减 28,672 字节，部分文件增大，不夸大成整包或性能收益；尚无新模型 GPU 验收通过。
- QtWebEngine 的原恢复构建在 Blink Jumbo 编译中失败。已读取 `evidence/msvc-jumbo-path-r1/result.json`：同一编译器和选项下，长文本相对 include 复现 C1083，规范绝对 include 的隔离探针通过，实际目标源文件存在。该诊断不是 Qt 编译完成或运行验收；Qt 代理正在对 Jumbo 生成器做最小修正与独立恢复，旧失败记录、工具链及功能边界保持。

- llama r2 原生构建于本地 06:48 成功退出。主线程已读取插件审计 `llama-build-r2/result.json`，其状态为 `BUILT_NOT_BUNDLED_OR_CONSUMER_ACCEPTED`，列有九项二进制的路径、大小与摘要；此处只记录编译回执，不将其当作新服务实际运行通过。VL 代理继续精确源码外置、完整 bundle 与新原生消费者验收，原 r4 仍使用旧服务构件。既有配置比较不能替代最终架构、运行及收益验证。

- PaddleVL 配套主仓辅助工具已完成隔离相邻目录的小验证：实际脚本入口、pip 版本入口、微型最简 prepare/verify 通过，未执行完整构建或 GPU。主线程读取回执并重算隔离组合中的 12 项辅助工具摘要，与独立清单一致；保留 r4 冻结工具与当前主仓不同的事实，不用当前 HEAD 冒充历史来源。入口：插件审计 `host-build-closure-r1/result.json` 及本项目 `evidence/vl-host-closure-primary-review-r1.json`。配套材料仍须按最终构建输入封入最终对应源码交付。旧 r4 归档已完成，其封包回执为 `ARCHIVED_NOT_REINSTALL_ACCEPTED`；后续 `archive-reinstall-r4.json` 已记录重装 PASS，载荷逐文件一致且私有依赖导入通过；未执行模型 GPU，仍不能解除下述嵌套源码阻断。

- PaddleVL r4-runtime 的 `resources/llama.cpp/source` 仍有六项实际源码/构建材料，不能称为最终最简运行包。主线程已核对实际目录成员、共享 `prepare_minimal_distribution.classifications` 对运行树普通文件的归类，以及插件 `checks.bundledRuntime` 对原生清单完整成员的校验。不能直接删除嵌套源码，否则清单不匹配；也不能把封包成功等同于布局符合规范。现有 VL 代理负责在新构建中严格验证完整 bundle 后，将这六项及原清单绑定到外置对应源码，生成可追溯的派生运行清单，再冻结运行时锁。旧 r4、压缩输入和既有验收回执不改写。修正与新布局验收尚未完成。
- Qt 打包工具原先缺少正式第三方组件清单生成器要求的运行派生标记。四个发行版现已补齐标记并绑定源码 commit、实际输入回执及 RECORD；包验证器也校验这些绑定，未放松共享组件清单生成器。r3 的 34 项定向测试通过，其中打包 14 项、投影 20 项，覆盖实际 section 生成器正反例和来源绑定篡改拒绝。主线程读取原始日志并重算当前工具/测试、冻结源码快照、日志及总回执摘要，与记录一致；不是主线程重跑。入口：`evidence/qt-tool-validation-r3/result.json` 与 `evidence/qt-tool-validation-r3-primary-review-r1.json`。这些测试仍为合成输入和实际生成器逻辑验证，真实 bundle、真实依赖锁组件清单及原生应用验收仍为 NOT_RUN；旧测试与收尾输入摘要保持。
- 已读取 `Trim-Qt.ps1`：它依据实际 PE 依赖闭包计算保留根 DLL，不是直接按旧 manifest 的 `rootDlls` 删除。正式本体仍需在旧 manifest 复用分支中接入真实派生清单，不能将此前未经核实的直接删除说法当作已证实机制。

## 2026-11-15 05:49 后续真实验收与分包边界

- CUDA r4 新组合已实际重新执行 r5 消费者，结果 `CUDA_BATCH_PDF_QR_WORKFLOWS_PASS`。新 worker 与原生锁摘要均绑定本次运行；批量 OCR、两页 PDF、分层 PDF、JXL 二维码和失败/释放路径通过，原模型保持。入口：`evidence/cuda-r4-assembly-and-r5-probe-r1.json` 和 `CUDA_R4_RUNTIME_CHECKPOINT.md`。不是旧 EXE 验收复用。
- r2 CUDA 分包驱动已通过锁定源码转换和语法检查，但尚未执行分包。直接以独立 staging 分包的只读分类探测被正式门禁拒绝，因为松散源码已收进 ZIP；后续保留 overlay 与有界恢复流程，不补写原候选、不放松源码检查。实际启动仍须满足磁盘余量并避开并行 PaddleVL 所需空间。
- 中断分包的 `complete` 已证明非模型副本共 6,322 文件、5,191,663,893 字节，进入精确退役准备；模型、目录和所有原始来源/证据保留。实际删除只看新的执行回执，不将该数当作已释放空间。
- `runtime` 差异已由新只读证据定位：最后复制目的文件与源同为 3,507 字节，但内容全部 NUL；实际文件集合恰为复制顺序截至该项的前缀。原有效源码完整，没有最简分包的有意变换。保留损坏小文件和原始字节，不能称短截断或伪称已捕获具体文件系统内部时刻。入口：`evidence/cuda-runtime-copy-diagnosis-r1/diagnosis.json`。
- PaddleVL 独立插件 source 仍有主仓分包工具依赖。最终源码交付必须同时免费提供匹配的主仓构建源码与工具摘要，以及冻结构建脚本实际要求的相邻 Umi-OCR/Umi-OCR-Plugin 目录布局，不把当前子树单独叫作完整独立构建闭包；该配套核验尚在进行。正在生成的 r4 归档和冻结源码不回写。

## 2026-11-15 05:46 来源闭包与固定更新器检查点

- 补齐独立对应源码辅助工具后的 CUDA 正式 r4 构建成功，14 项输入执行前后摘要不变；构建日志摘要再次核对一致。只读来源校验通过，所有冻结 ZIP 成员与清单一致，新增的最简分包及发布校验辅助工具均在冻结源码内。
- r4 与已实际验收的 r3 插件逐文件比较：6,138 个文件中，仅重编的 `UmiOCR-CudaWorker.exe` 及其 `runtime.lock.json` 改变。不能把旧 EXE 的 GPU 通过直接用于新 EXE；新的组合和消费者验收另记 r5。证据：`cuda-r4-payload-comparison-r2.json`。首次只读探针误将独立 staging 当作组合布局，要求不存在的顶层 VERSION 而失败；已改为正式 `inspect_staging` 入口，原 r1 FAIL 和生产载荷原样保留，未降低产品门禁。
- PaddleVL 科学/下载 r4 最简候选已新执行复杂文档 HTTP 验收：OCR 与文档任务共享 PID 39860，13 块覆盖标题、表格、公式及图形，HTML 表格和 JSON/MD/TXT 导出通过，实际非空标题高度触发官方 KMeans。模型与运行时锁前后不变。主线程只读核对结果、输入和复用回执，并重算当前运行时锁，与实际验收绑定一致。证据：`vl-r4-primary-readonly-review-r1.json`；该只读复核不算重新执行 GPU，不包含尚未完成的新 llama 构件。
- 固定安装安全更新器及定向测试已完成，真实 Windows 文件句柄场景 **40 项 PASS，零跳过**。覆盖入口暂存、已知旧载荷替换/退役、普通失败回滚、占用、权限、链接/硬链接、未知文件和模型/私有数据保护；源码及测试摘要再次匹配测试回执。此次复用代理本轮已执行结果，未重复全量测试。工具尚未操作实际 release，不能据此声称固定安装更新完成。
- 固定更新器不承诺硬中断自动恢复或断电原子性。事务中出现新占用或权限阻塞则保留恢复现场；提交后备份清理受阻单独报告，不强写、不清只读、不终止进程。已有用户状态、模型与私有解锁文件原地保留，历史旧载荷归属必须来自独立核验清单。
- 中断 CUDA r1 的 complete/runtime 仅在做逐文件只读退役预演，未新增删除。并行封包和新组合执行前分别做容量预检，不把尚未完成的清理算作可用空间。Qt/PySide、llama 原生构建仍等待真实终态。

此检查点不覆盖之后的运行、归档或安装结果；固定路径版本与公开发布状态仍按本文开头。截图/HDR/混屏继续 NOT_RUN。

## 2026-11-15 CUDA 新裁切运行验收与来源门禁

- CUDA 正式 `dependency-trim-20261115-cuda-r3` 构建成功，执行前后锁定的八项输入摘要一致。新组合 `combined-image-r3` 通过真实 GPU 批量/PDF/分层导出/JXL 二维码、释放、未启动拒绝及无效 GPU 失败路径。原 21 个模型/配置摘要保持，不下载或修改权重。证据：`cuda-production-build-r3-result.json`、`cuda-production-consumers-r4/result.json`。
- 原可选包、开发启动器、nvBLAS/cuFFTW 包装器均缺席，ModelScope 完整载荷逐字节匹配独立派生 wheel。首个成功 predict 后已实际获取原生模块快照，观察到的 9 个 NVIDIA DLL 全部绑定当前候选路径与 SHA。启动阶段快照保留，不把未观察到的其它库当作无用。
- 分包前发现 CUDA 独立源码导出漏收最简分包及发布校验的四个辅助文件。新增隔离源码树导入测试验证补齐后的工具闭包。原 r1 分包任务由本会话主动停止，没有终止用户进程；保留其 complete/runtime 现场和 `cuda-delivery-package-r1-interrupted.json`，不算最终归档或重装成功。更正来源后的候选及验收另开新记录，不覆盖 r3。
- MuPDF 来源缺口已成为实际生产发布门禁，而非仅文档提醒。当前 `_mupdf.pyd` 摘要对应原生 MuPDF **1.29.0** 开发版，PyMuPDF **1.28.0** sdist 默认核心为 **1.28.0**，不能当作完整对应源码。未知替换二进制也不能继承已知版本或来源；只凭存在源码包、版本号或头文件一致均不得放行。6 项定向合成测试及既有状态门禁回归通过，实际候选原生摘要与原观察记录再次只读匹配，结果保持 **BLOCK**。证据：`pymupdf-corresponding-source-primary-r1.json`。
- 原生 Paddle 重编的 MSVC/CUDA 不兼容已有真实编译失败。源码未初始化 gitlink 的准确数为 **31**，最终核对纠正先前的 30；不改旧记录。Pillow 的现有图像、字体和颜色能力及 ZXing 读写格式保留，没有把无收益重编当作裁切成果。
- 主线程已独立核对 PaddleVL r1 科学计算 25 组结果完全相等、实际 HTTP 的共享服务 PID、原 PDF 页 2 的 22 个标识和有界坐标、JSON/MD/TXT 导出、模型回执和当前 runtime.lock。该核验不是新 GPU 执行，不扩张为新 ModelScope/llama/升版/重装通过。VL 新正式候选仍在推进。
- QtWebEngine 原生编译和后续匹配 PySide 链尚未终态，不以 Shiboken 已通过推断整个 Qt 完成。旧现场 r3 删除仍等待其真实后验回执。固定安装安全更新工具正在独立定向验证，尚未操作 release。

以上新证据均位于本轮 `build/audit/dependency-trim-20261114-r1`。最终归档、组合重装、固定安装与公开发布门禁仍未完成。截图/HDR/混屏继续 **NOT_RUN**。

## 2026-11-15 05:04 新增下载与可选包装器检查点

本节为恢复后的新证据，以下较早章节仍保留其当时边界；新组件尚未最终归档、重装或更新固定安装。

- ModelScope 原版 `1.38.1` 已生成独立 `1.38.1+umi.download.1` wheel，SHA256 `8eea9d27b594ca71030997f50683eb77698617f0e4005d2ed16bc2e02828206b`。原始 wheel、完整 sdist 和原许可另行保留，sdist 已加入正式对应源码锁；派生工具和测试进入本体与 CUDA 独立源码导出。
- 下载根仅保留实际使用的 snapshot 委托、异常、回调、常量及环境桥接。明确分离未用模型/训练导出、上传调度器及本产品未提供的 PyTorch 分布式日志分支，未修改 snapshot 参数或模型文件。原逻辑载荷 **22,560,381 → 62,548 字节**，此处不是归档大小或已更新安装的空间收益。
- 封装/RECORD/来源/共享归属定向测试 **14 项 PASS**。目标 Python 3.13.16 中原版与派生均通过完整参数委托、位置参数默认值、真实离线空缓存异常、隔离非模型文本目录命中、凭据目录桥接及初次/追加文件日志。socket 连接与 DNS 调用被拒绝护栏覆盖，实际网络尝试为零。当前工具重复封装产生相同 wheel 摘要。
- 首轮原版和派生探针均触发上游既存 `MS_CACHE_HOME` 字符串路径错误，保留各自 FAIL 原件；正常 `MODELSCOPE_CACHE` 路径的新轮次通过，不把旧环境别名失败改写为通过，也未额外改上游行为。
- CUDA 可选 `nvblas64_12.dll` 与 `cufftw64_11.dll` 已核对原始版本、唯一 RECORD 归属及摘要；候选全部 153 个 PE 无普通/延迟导入入边，名字字面量仅来自各自 DLL。核心 cuBLAS/cuBLASLt/cuFFT、算法、精度、GPU 架构与共享命名空间保留。包装器合计 **495,104 字节**，仍须在新正式候选执行消费者验收后才能称裁切完成。
- 包装器投影 **11 项 PASS**，覆盖派生身份、标准 RECORD、核心/许可保留、共享归属拒绝、原始摘要、未知成员、派生种子重复投影及复制期核心摘要约束。最初 bytes/StringIO 类型错误的原失败日志保留；修正后的新轮次通过。
- 本体/CUDA 的 pip 开发启动器排除仅指已核对完整入口摘要的 bin EXE，库 API 与未知命令保留。包含此前边界的主投影测试 **33 项 PASS**。真实 CUDA 种子的新增替换计划及 **2,948 个**已检查成员摘要通过只读核验，尚不代替新候选实际运行。
- 旧现场恢复的历史确认值仍仅为 r2 的 59,280 文件 / 829,362,299 字节；r3 已启动原安全执行与后验链，完成通知尚未到达，不能把预演统计说成已释放空间。原 184 份证据的前后摘要一致。
- QtWebEngine、匹配 PySide、PaddleVL 新候选与 llama 重编仍在独立推进。Paddle 原生重编受真实 CUDA/MSVC 工具链限制，不使用绕过开关。发现当前 PyMuPDF 二进制的 MuPDF 核心版本与旧锁定 sdist 不同，正在核对来源，旧源码记录不能冒充当前匹配证明。

新证据均在本轮审计目录 `evidence/`：`modelscope-download-package-r2.json`、`modelscope-package-unit-r2.log`、`modelscope-download-upstream-r2.json`、`modelscope-download-derived-r2.json`、`cuda-wrapper-unit-r2.log`、`cuda-new-projection-plans-r1.json`、`new-projection-source-selection-r2.log`。CUDA 包装器原始审查另见 `native-paddle-20261115-r1/evidence/cuda-native-wrapper-exclusions-r1.json`。上游失败与不满足闭包的静态分析轮次均原样保留。

## 已落地的图像依赖裁切

- OpenCV 保持 4.10.0 源码提交 `71d3237a093b60a27601c20e9ee6c3e52154e8b1`，实际重编 `core/imgproc/imgcodecs/python3`，不是简单替换成 headless wheel。禁用视频、FFmpeg、GUI、CUDA、OpenCL、GAPI 等未用后端；保留 JPEG NASM SIMD。
- 生成明确标识的 `opencv-contrib-python==4.10.0.84+umi.coreimg.1` 派生 wheel。兼容发行版名称供 PaddleX 检查使用；不声称提供完整 contrib。
- 原生绑定：20,842,496 字节，SHA256 `fbdb2c1f62ff1e83f5dfc9d56c8344d673de0dec0d17510b4fcafc7d37852661`。
- 派生 wheel：7,432,210 字节，SHA256 `6e58965db2144b82036116de78d2d076ec6ec19744fc75886141456f61e744c6`。不沿用官方 wheel 摘要。
- 本体 imagecodecs 仅保留 `_jpegxl`、`_jpegxr`、`_shared`、`_shared_cython`，辅助代码和原始许可保留；派生元数据版本为 `2026.8.16+umi.jxlxr.1`，重新生成实际载荷 RECORD，不改原始上游 wheel。
- 本体依赖根：**596,420,631 → 472,513,248 字节**，净减 **123,907,383 字节（约 118.2 MiB）**。这是本轮新目录的实测，不是固定安装或整个仓库已经减少的空间，也不是归档压缩后收益。

### 正式构建集成

`build/windows/Build-Release.ps1` 和 `Build-GpuPlugin.ps1` 已接入 `project_dependency_runtime.py`，使用独立输入锁 `build/runtime-subsets-windows.json` 和 `-DerivedOpenCvWheel`；缺少正确摘要时停止，不默默回退完整官方 OpenCV。

上游 requirements 锁继续记录原始输入 pin/hash；新派生锁、实际 METADATA/RECORD、逐文件转换回执分别记录最终载荷身份。固定摘要的补丁和 MSVC 包装器显式使用 LF 检出；补丁上下文空行的一个空格属于统一 diff 语法，按 patch 路径单独处理其外层空白检查，并以实际 `git apply --check` 验证补丁。组件文案生成器显示实际派生版本及原始输入 pin；派生 OpenCV 的原生/源码身份、许可与 RECORD 走单独验证，不伪称“未修改的官方 wheel”。

读取 Stored-ZIP 种子时保留 ZIP 内依赖，包括 bottle/six，不能只复制松散 site-packages/vendor。对最简分发外置的输入清单，仅显式投影读取器可以尝试恢复：恢复字节必须与原清单的大小及 SHA 完全一致；不改原树，不接受摘要不符或已存在但损坏的清单，默认严格读取行为不变。

## 本体新候选的实际验证

候选位于 `build/staging/dependency-trim-20261114-host-r2`，通过正式本体构建入口生成；选择 stored 容器、完整工作布局，未归档，未作为新发行版交付。

已通过：

- 本体构建、Stored-ZIP 容器审计和本地候选包审计；公开源码/当前版本发布门禁仍为 BLOCK，不冒充发布批准。
- `test_image_decoder.py`：AVIF、WebP、JPEG XL/XR、别名、颜色、透明度、EXIF 等现有图像消费者。
- `test_document_image_formats.py`：实际图片输入规范化与文档预览；该现有测试按其设计使用仓库 py_src，依赖与原生模块来源单独核对为新候选。
- 两个消费者的 cv2/imagecodecs/numpy/PIL/PySide6 等实际模块来源检查，以及派生发行版身份检查；Shiboken 内嵌 `signature_bootstrap.EmbeddableZipImporter` 的虚拟支持模块单独识别，并核对其候选 PySide6/shiboken6 提供者，不把虚拟文件名误判为包外回退。
- 未在本体进程导入 Paddle。

本体候选仍使用既有 Qt 二进制；这些结果不能代替正在构建的新 QtWebEngine 或两个插件模型消费者的验收。

## Qt / QtWebEngine 的真实进度与边界

- 匹配 Qt 6.11.2 的 Basic-only SDK 已编译。QtBase/ShaderTools 的本轮成功输入按逐文件 SHA 复用到新 SDK，其他模块在新目录构建；不谎称全部重编。
- QtWebEngine 第一轮因缺生成工具和关闭文档时仍引用不存在的文档目标而失败，原失败保留。WinFlex/Bison 固定资产后续通过认证 API 下载并核对同一原始摘要；gperf 3.1 已按固定 GNU 来源及 vcpkg 配方原生编译。
- 第二轮已生成实际 GN 图，`media_use_ffmpeg=false`，目标闭包不包含 FFmpeg；但另一旧参数 `use_webaudio_ffmpeg` 在本版本未声明，不能算作生效的开关。当前补丁已移除它，并要求后续 GN 查询严格拒绝未使用参数、输出可解析 JSON。
- 第二轮在 Chromium 编译阶段遇到头文件查找失败。头文件实际存在；同一 MSVC 语法探针中，未规范化相对路径恰好 260 字符时失败，绝对路径通过。显式 `cc_wrapper` 只规范化包含路径，不改变源码、C++ 标准、编译选项、ABI 或退出码；原失败命令包装后通过，参数保持单测通过。
- 第三轮已通过严格 GN 参数/JSON 图检查，包含路径问题已越过，但下一个较长的相对源文件名触发同类 C1083。包装器现已覆盖包含、源、obj/PDB/PCH 等路径，并固定编译器英文诊断以匹配 Ninja 依赖前缀；6 项参数保持单测及原 `stack_trace.cc` 失败参数的 `/Zs` 探针实际通过。未修改旧轮次的失败记录。
- 第四轮到达预编译头阶段后发现 `/FI` 头文件搜索标记不能按工作目录文件路径重写；已修复并保留 FI/Yc/Yu 的包含搜索语义。本机只有中文 MSVC 资源，请求 VSLANG=1033 仍回退中文，不能算作英文诊断已生效；现仅对 `/showIncludes` 的已知中文前缀作逐字节映射，让 Ninja 正确读取依赖，路径和错误诊断保持。10 项包装器测试和原失败 PCH 的真实编译均通过，生成了实际 PCH 并观察到可解析依赖前缀。
- 第五轮在新构建目录运行，实际调用审计目录内已核对 SHA 的包装器快照，避免源脚本后续编辑导致同一构建混用版本。后续完整编译仍未完成；尚无可交付的新 QtWebEngine DLL、匹配 PySide 或新 Qt 富预览验收。沙箱不禁用。
- PySide 必须按实际白名单重建，不能根据猜测模块列表：Core、Gui、Network、OpenGL、Qml、Quick、QuickControls2、Widgets、PrintSupport、WebChannel、WebEngineCore、WebEngineQuick。原生 QtSvg 等传递模块另由实际闭包保留。

## 科学计算、Paddle 与 CUDA

PaddleVL 标题重组实际调用 scikit-learn KMeans，不能因元数据 orphan 就删除 SciPy/sklearn/joblib/threadpoolctl。已在隔离覆盖层完成惰性导出及统计导入分离，标题算法结果不变、实际加载范围减少；尚未把未加载的模块物理删除或完成全流程文档模型验收，不能把导入范围减少说成最终包已经省下对应大小。

固定 Paddle 3.3.1 源码和 CUDA 12.6.85 NVCC 输入已经准备，但可用 MSVC 19.51 超出该 NVCC 明确支持范围。两份微软清单的下载及后续格式/编码恢复都未匹配微软发布摘要，没有用于取得编译器，不通过 `-allow-unsupported-compiler` 或偷换 CUDA 13 ABI 绕过。

CUDA 正式入口的新候选已构建：私有依赖根 3,908,279,406 → 3,829,280,714 字节，净减 78,998,692 字节。派生 OpenCV 证据通过，但 cuDNN、AGPL/NVIDIA 组合、模型 E2E、源码/当前版本发布门禁仍显示 BLOCK，不据本地构建完成声称可以公开分发。随后在全新本体/CUDA组合上，实际 GPU 批量 OCR、2 页 PDF、分层 PDF、JXL 二维码、模型释放、未启动拒绝及无效 GPU 的 batch 失败路径已通过；透明观察确认 worker 加载的确为该候选私有 OpenCV 派生二进制，原有权重摘要未变。此结果不是完整模型族准确率基准，也不自动把旧许可或公开发布门禁改为 PASS。

PaddleVL 的正式构建入口、完整模型/共享服务/HTTP 联合验收及 llama.cpp 内部裁切尚未完成；不削减模型族、语言、精度或 GPU 架构矩阵，不下载或删除唯一模型。

## 定向验证与原始证据

本轮已实际通过的工具测试：依赖投影/派生文案及门禁 14 项（包含输入检查与复制期间的元数据变化检测）、MSVC 包装器 6 项、运行容器直接回归 91 项、源码/本地构建工具 17 项、发布证据状态 16 项。较早通过且实现未改的闭包 12 项、原生子集 7 项、惰性初始化 6 项保留各自记录，不冒充本检查点重新执行。

主要原始证据位于 `build/audit/dependency-trim-20261114-r1`：

- `evidence/host-dependency-projection-r3.json`
- `evidence/host-production-build-r2.log`
- `evidence/host-production-consumers-r2/result.json`
- `evidence/dependency-projection-unit-r6.log`、`evidence/msvc-path-wrapper-unit-r2.log`
- `evidence/runtime-archive-directed-r1.log`
- `evidence/local-build-tools-directed-r2.log`
- `evidence/release-evidence-directed-r2.log`
- `evidence/partition-include-probe-r1/result.json`
- `evidence/partition-wrapper-probe-r2/result.json`
- `evidence/qtwebengine-build-r2` 和进行中的 `qtwebengine-build-r3`

前次失败的构建、元数据正文处理断言、虚拟模块来源断言、默认布局不匹配的旧小型 fixture 等均保留原始失败，不改写为通过。后续新目录记录区分修复后的结果。原 Qt FFmpeg 补丁的历史字节已独立留存，SHA 与原记录 `fba1824f…` 一致；不以当前修订补丁替代历史输入。

## 2026-11-15 恢复与新增定向验证

- QtWebEngine r5 原编译日志止于 **3023/20214**，没有技术完成回执；恢复时未发现相关活动进程。原 `inputs.json`、日志和部分构建缓存保留，不改写成成功。
- 新的 `evidence/qtwebengine-resume-r5-r1/inputs.json` 已记录续编输入通过：**7,446 个 SDK 文件**、原 MSVC 摘要、Python/CMake/Ninja 版本、CMakeCache、包装器快照和严格 GN JSON 图均匹配。保留 `media_use_ffmpeg=false`、`enable_webrtc=false`；实际图不包含 FFmpeg。复用中断缓存而非全新编译；后台任务尚未完成，不作 DLL/PySide/应用验收声明。
- 修复从本轮已裁切种子再次构建时因 local-version 被拒绝的问题：已知派生 OpenCV 必须逐成员等于独立锁 wheel；imagecodecs 的 **87 个文件**完整载荷摘要锁定为 `956700c0ad95d576bc1001cd5c9c8d048d073f5ae1347baab620bc7a5d53607b`。未知版本、额外成员、改码后自改 RECORD 都不接纳。实际本体/CUDA 种子只读核对通过，见 `derived-seed-readonly-r1.json`；没有据此声称重新完成组件运行验收。
- CUDA 五个未进入实际推理闭包的可选包纳入正式投影：bce-python-sdk、crc32c、future、psutil、pycryptodome。结合先前 7,219 份源码 AST/元数据证据，以及本次真实 RECORD 共享归属与三个 pip 命令入口检查，排除目标为 **711 个文件、8,933,494 字节**，其中包括已识别的开发命令。原种子不删除；RECORD 中 `../../bin` 只记录而不跟随。实际入口核对失败的首份预演保留为 FAILED，修正 crc32c 的真实入口后新 `cuda-exclusion-preflight-r2.json` 通过。
- GPU 分发输入锁、锁生成器排除规则及 Stored-ZIP 策略同步；统一原始输入锁和来源/许可原件保持。新 CUDA 候选 `build/staging/dependency-trim-20261115-cuda-r2` 正通过正式入口后台构建；模型复用，不下载。尚未完成该候选的 GPU 消费者，不能把预演数量当最终运行包已验收收益。
- 最新依赖投影定向测试 **24 项通过**，见 `dependency-projection-unit-r10.log`；包装器 **10 项通过**，见 `msvc-path-wrapper-unit-r4.log`。其它既有测试仍按各自旧记录和适用范围引用，没有例行重跑全仓测试。

### 旧现场精确退役

只读证明已完成：878,789 个同 SHA 程序文件、12,846,752,701 逻辑字节，239 个不同内容文件不在清单。原中断 `old-runtime-retirement-r1` 的部分计划保留，不执行或覆盖。

新完整预演 `old-runtime-retirement-r2/PREVIEW.md` 已交付展示：

- 当前源码仍有直接引用：**143,346 个文件、2,645,789,405 字节**，整组保留。
- 执行前原生句柄复核范围：**735,443 个文件、10,200,963,296 字节**；本次预演未发现占用。
- 预演 SHA256：`382c61c7f5fedbab2053a0d02d294c932a0fb40ff8f1c0d3ec88527795be7fa9`。
- 退役编排 **11 项合成夹具测试通过**，包括只读文件保留、不把原件缺失记作目标消失、活动引用/进程保留、改动目标/归档拒绝和中断真实回执，见 `retirement-orchestration-unit-r2.log`。

按已批准范围的后台执行已启动。最终只以 `execution-result.json` 和持久 `deletion-journal.jsonl.gz` 的实际删除回执统计；当前尚无完成回执，不记作已释放 9.50 GiB。只删逐文件复核通过的旧程序副本，不清只读、不终止进程、不递归删除目录；不动模型、用户状态、私有源码、当前来源/种子、固定安装或插件兄弟项目。

## 2026-11-15 04:21 定时恢复后的实际结果

- 恢复前本轮活动进程为 0，原暂停材料未覆盖。新的恢复记录为 `RESUMED_20261115_0421.md`。
- 完成投影器所有本轮元数据/派生包读取入口的有限预算读取，保持 Stored-ZIP 核验及松散输入的外部摘要约束。新增读取次数边界、负数/非整数预算、辅助许可超限、RECORD 在快照后增长等回归。`dependency-projection-unit-r11.log`：**29 项通过**。
- 原 MSVC 包装器内容摘要仍为 `66379469e58114becc19fbfe459bc74011f098bfb6f0c3dca33e94ebc1ec4661`，本次 `msvc-path-wrapper-unit-r5.log`：**10 项通过**；这不是 Qt 完整编译成功。
- 新 `cuda-production-consumers-r3/result.json` 实际 **PASS**：批量 GPU OCR、2 页 PDF、分层 PDF、JXL 二维码、模型释放、未启动拒绝、无效 GPU 失败路径。核验本次五个可选包及命令在组合松散/ZIP 内均不存在，实际 worker 加载候选私有派生 OpenCV，21 个模型/配置文件摘要与原已核验输入一致。被中断的 r2 日志和调用记录原字节保持。没有桌面截图、HDR 或混屏测试。
- `remaining-dependency-inventory-r1.json` 重算本体/CUDA 的真实逻辑闭包。两组件元数据 orphan 均为 0，这不等于所有内部冗余已经裁完。CUDA 仍保留上游 cuDNN 版本声明与部署覆盖、aistudio 离线补丁的显式差异，不改原始声明为伪 PASS。
- Qt 续编、Paddle 原生工具链、PaddleVL 科学计算/生产入口及旧删除 journal 恢复分别推进中，结果尚未汇总。版本、最终归档、固定安装和公开发布状态不变。

## 尚未交付的范围

- 全部组件的文件级/动态依赖闭包及剩余复杂库内部裁切。
- 旧运行现场退役已按新完整预演启动；待真实完成回执核对，不把证明、预演或开始执行当清理完成。
- 独立组件版本更新、最终归档、重新安装验收、固定安装更新及用户数据保留核对。
- 最终对应源码/许可/载荷绑定、Release 文案与清理回执及用户当次发布审查。

不主动执行桌面截图、HDR 显示或混屏测试，维持 NOT_RUN。私有 UI 解锁源码/材料及唯一模型不动。没有未经授权的推送、标签或公开发布。
