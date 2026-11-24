# 3.1.1 更名候选程序与发布检查

本轮用户已通过 [Release 文案](RELEASE_3.1.1_DRAFT.md)，并要求准备更名后的实际程序及发布检查后交审。**文案通过不等于当次实际程序通过，也未授权 push、标签或 GitHub Release。**

## 当前状态

新主程序已在全新目录离线构建，冻结完整对应源码和运行载荷，生成非最终审查归档，并从三归档全新重装组合。组合包七语的实际文档锚点、逐字符位置及裁剪范围及原生滚动位置检查通过；正常 EXE、真实第二实例转发和回环后端注册检查通过。独立人工审查配置、只读清理预演和冻结原件复核均已完成，22 项核心证据汇总于 [final-summary-r1.json](../build/audit/release-311-candidate-20261101-r1/final-summary-r1.json)。当前状态是 **READY_FOR_PROGRAM_REVIEW_PUBLICATION_BLOCKED：可交用户审查程序，正式发行门禁仍未放行。**

本轮未修改现有 `release/Umi-OCR`、真实配置、任务数据或旧归档。该固定安装仍是此前的本地版本，尚未含本次首页更名；请审查下面的独立候选，不要用旧固定安装代替本次程序验收。

## 实际对象

| 对象 | 版本/身份 | 本轮处理 |
| --- | --- | --- |
| 主程序 | 3.1.1 | 正式 builder 的 non-LocalCandidate、`-SkipArchive` prepare；全新编译启动器/原生模块，完整对应源码保留 |
| CUDA 插件 | 3.0.5 | 原已核验归档复用；仅本地组合审查，不冒称正式发行门禁通过 |
| PaddleVL 插件 | 3.1.1 | 原归档复用，仅本地组合，不在本次公开附件范围 |
| CPU 插件 | 不变 | 未构建、未安装、不在公开附件范围 |

- 实际审查程序：`build/tmp/release-311-candidate-20261101-r1/reinstalled-r1/Umi-OCR.exe`。
- 待后续正式门禁/finalize 使用的未改动主程序原件：`build/staging/release-311-base-20261101-r1`。
- 主程序冻结清单：[frozen-base-r1.json](../build/audit/release-311-candidate-20261101-r1/frozen-base-r1.json)。冻结不代表用户同意或公开放行。
- 本轮审计根：`build/audit/release-311-candidate-20261101-r1`；工作根：`build/tmp/release-311-candidate-20261101-r1`。

### 主程序审查归档（不是正式 Release 附件）

`build/artifacts/release-311-candidate-20261101-r1/Umi-OCR_v3.1.1-review_Windows_x64.tar.xz`

- 字节：`300621128`
- SHA-256：`7fd8fa3f30e263220be1c00990e73063fdd73ad5b7e04ddf278397d9af414ee7`
- 冻结清单 SHA-256：`f83a9287346a6418f4b922193244246c52257336fc10bbb01b99d619418f66c8`

该归档含完整对应源码，因此体积不同于先前缺少完整 `source/` 镜像的本地候选。新旧归档及审计不覆盖、不改名冒充，不将本归档称为正式发行完成。

## 已完成的定向检查

1. [开工基线](../build/audit/release-311-candidate-20261101-r1/baseline.json)：源码为 `edb157a78a768b381b711236912dafaa10442426`。与先前 3.1.1 运行源码相比，只有首页 QML 和六个 QM 共七项运行输入变化；88 项依赖 DLL 重新按锁核验。插件没有因此重建或升版。
2. [全新主程序构建](../build/audit/release-311-candidate-20261101-r1/base-build-r1/result.json)：离线正式 prepare，63.677 秒，构建期间源码未变；规范公共源码快照含 545 项。
3. [纯本体真实原生窗口](../build/audit/release-311-candidate-20261101-r1/base-native-command-r1.json)：七语实际下拉切换、首页字符串、链接目标以及编译 QML/QM 来源通过，正常退出，自建状态恢复到精确原载荷。长译文的逐字符可见性以组合包 r4 证据为准，不扩大第一轮文本相交判定的含义。链接仅核对，未打开外部浏览器或真实剪贴板；未启动模型。
4. [实际截图](../build/audit/release-311-candidate-20261101-r1/base-native-r1/homepage-zh_CN.png)：简中“仓库链接”和[英文 Repository link](../build/audit/release-311-candidate-20261101-r1/base-native-r1/homepage-en_US.png)均已实际查看，版本显示为 3.1.1。
5. [冻结、归档及独立 7-Zip 检查](../build/audit/release-311-candidate-20261101-r1/base-package-command-r1.json)：完整源码/载荷检查后冻结，包前/包后逐字节一致，独立 `7z t` 通过。仅生成本地审查归档，未执行正式 finalize。
6. [全新归档组合重装](../build/audit/release-311-candidate-20261101-r1/reinstalled-r1/result.json)：24,363 个文件与三个归档载荷匹配，360.998 秒；没有触及固定安装。
7. [组合包七语真实窗口 r4](../build/audit/release-311-candidate-20261101-r1/combo-native-r4/report.json)：52.528 秒。直接读取真实 `QTextDocument`，逐字符检查仓库链接的 `anchorHref`，并按窗口和所有裁剪祖先核对逐字符的光标位置矩形。七种语言均完整可见；长译文通过有界原生 `Flickable.contentY` 滚动后核验，**不是鼠标滚轮验收**。实际查看了[简中](../build/audit/release-311-candidate-20261101-r1/combo-native-r4/homepage-zh_CN.png)和[泰米尔语](../build/audit/release-311-candidate-20261101-r1/combo-native-r4/homepage-ta.png)截图。编译 QML/QM、业务模块来源、无模型边界、正常退出与[精确载荷恢复](../build/audit/release-311-candidate-20261101-r1/combo-native-r4-restore.json)通过。
8. [真实正常 EXE / 第二 EXE / HTTP](../build/audit/release-311-candidate-20261101-r1/normal-exe-r1/native-cli-result.json)：主程序启动，第二个真实 `Umi-OCR.exe --all_pages` 正常转发；回环注册表包含 CUDA/VL 的 OCR 与 VL 文档能力，无效后端返回 `804 / INVALID_OPTIONS`，正常退出。此场景为独立 100% 配置，不作为默认 125% 或性能对照证明；未请求模型推理。
9. [EXE 生成状态保留与恢复](../build/audit/release-311-candidate-20261101-r1/normal-exe-restore-r1.json)：本次实际核验 138 个生成缓存，142 个自建状态/缓存文件按原字节移出保留；不是按 `.pyc` 后缀删除。24,363 个产品文件恢复精确一致。
10. [首页验收判定契约](../build/audit/release-311-candidate-20261101-r1/home-visibility-fixtures-r4.json)：5 项测试通过，覆盖缺语言、重复语言、未运行、缺可见证据、错误目标、提前退出及安全阻断，未加载 Qt 或启动程序。首页专用档不会冒称复验模型设置，也不会放宽 `base` / `combined` 的原有必需项。

纯本体已执行驱动的原字节另存 [executed-base-driver-r1.py](../build/audit/release-311-candidate-20261101-r1/executed-base-driver-r1.py)，SHA-256 为 `77ecf0ff9cbc2602c9d99772ff06bb68f3b4635ed0b055f40b99d6aa4a5de03d`。其后增加的组合首页专用档与协调器只用于验收，单独绑定实际执行版本，不回写已冻结程序的对应源码，也不冒称早期源码快照已包含这些晚到工具。

## 发行门禁检查（尚未放行）

[实际只读检查](../build/audit/release-311-candidate-20261101-r1/release-gate-preflight-r1.json)保留产品原报告，不改写任何历史 BLOCK。

| 检查 | 当前结论 | 说明 |
| --- | --- | --- |
| 主程序运行时/依赖、OpenCV、纯本体结构与完整源码 | 通过 | 正式 prepare 与冻结已核验；公共包不包含 OCR 后端、CPU 或 PaddleVL 载荷 |
| 主程序 `source_delivery` | BLOCK／后置待办 | 缺当次明确正式门禁输入和匹配的公开 `v3.1.1` 源码标签；用户实际程序审查前不能先 push/tag |
| 主程序 `current_source_e2e` | BLOCK／后置待办 | 不以七语首页检查冒称正式全套门禁通过；需要实际冻结 source/payload 绑定、正式回归/GUI/托盘与当次人工确认 |
| CUDA 3.0.5 完整 canonical `source/` | 缺失 | 归档有来源记录和源码快照不等于具备正式 finalize 所需的完整源码目录，不允许删候选标记或复制旧 PASS 强行晋升 |
| CUDA cuDNN 附加功能证据 | BLOCK | 原报告 `material_additional_functionality=false`，当前证据为空；此为缺证状态，不作法律授权已获的结论 |
| CUDA 独立 worker 边界及 GPU E2E | BLOCK | 原报告 `manifest_process_boundary=false`，GPU 当前工作流证据未放行；保留原始事实，不能以回环注册或 UI 成功代替 |
| CUDA `source_delivery` / `current_source_e2e` | BLOCK | 仍需独立版本的完整准备、正式证据及匹配公开 `v3.0.5` 标签 |

只读查询确认，目前尚无主仓库 `v3.1.1` 或插件仓库 `v3.0.5` 标签。本轮未创建它们。CUDA 既有包的本地完整性及历史 GPU 记录可按各自范围参考，不能把未变插件或曾经通过解释为当前公开发行条件自动满足。

## 验收范围与未验收限制

- 本次运行改动只有首页名称及翻译。未改动的文档解析、模型参数、GPU 质量/性能矩阵采用先前记录及源码未变依据，不宣称本轮全部重跑。
- 当前不提供整体启动提速、识别质量提升、多卡或资源极限的新承诺。不下载模型、不改权重、精度或量化。
- 用户真实桌面/HDR 截图、混合 HDR/SDR、多屏及完整原生鼠标/Explorer 流程未由本次自动化替代。正式门禁要求的当次人工确认与未测限制须如实处理，不能沿用旧版同意或旧 HDR 成功反馈。
- 公开范围仍仅主程序与 CUDA 独立包；PaddleVL 在本地组合中存在不表示获准公开分发。

## 重试记录与证据边界

- 原组合 r1 通过了当时的判定，但[实际截图复核](../build/audit/release-311-candidate-20261101-r1/visibility-followup-r2.json)发现长译文链接可能在滚动区下方，控件与视口相交不等于链接可见。r1 驱动原字节已另存 [executed-combo-driver-r1.py](../build/audit/release-311-candidate-20261101-r1/executed-combo-driver-r1.py)，不改旧报告。
- r2 窗口滚轮尝试未能到达日语链接；r3 在俄语的逐光标 `linkAt` 检查中停止。两轮均保留原始 `INCOMPLETE`、截图、日志和实际驱动：[r2 保留记录](../build/audit/release-311-candidate-20261101-r1/combo-native-r2-preservation.json)、[r3 保留记录](../build/audit/release-311-candidate-20261101-r1/combo-native-r3-preservation.json)。只在无占用且原载荷匹配后移出自建状态，没有把失败重标为通过。
- r4 改为真实文档逐字符 `anchorHref` 与字符矩形检查，并明确记录原生 `contentY` 滚动。它证明七语链接及目标正确、滚动后可见，**不能据此宣称外部鼠标滚轮已验收**。这些调整只在外置验收驱动，不改变冻结程序、QML/QM 或归档。
- [人工审查配置首次准备记录](../build/audit/release-311-candidate-20261101-r1/manual-review-setup-retry.json)：独立控制解释器未提供 PySide6 导入路径，写配置前停止。修正为沿用真实 EXE 协调器已验证的 INI 标量格式，不为写配置引入 Qt 依赖；不影响此前候选自己的 Qt 验收。

## 人工审查副本

人工审查副本仅在已验证的完整组合载荷外添加两份本任务自建配置，来源与摘要记录于 [manual-review-ready-r1.json](../build/audit/release-311-candidate-20261101-r1/manual-review-ready-r1.json)。没有复制或读取固定安装的真实设置。

- 启动文件：[独立候选 Umi-OCR.exe](../build/tmp/release-311-candidate-20261101-r1/reinstalled-r1/Umi-OCR.exe)。这是完整安装根中的启动器，不要只复制该 EXE 到别处运行。
- 简中、真实首页默认、未写缩放值，使用程序新配置默认 125%；主题也使用程序默认。
- OCR HTTP 功能关闭、单实例通信使用独立端口、模型懒加载、关闭窗口即退出；审查配置中的全局截图快捷键暂关，以免干扰现有程序。
- 没有带入旧任务、模型路径或个人设置。除当前更名外的未变功能，不能把新空配置与用户原安装的配置差异当成运行回归结论。
- 配置只在可交互审查副本，不进入冻结主程序或审查归档；该副本因此是“精确产品载荷＋两份自有配置”，不是“毫无配置的原归档”。本配置尚未由用户操作；用户启动后产生的配置、日志和任务均应视作用户数据，不静默清理。

## 清理预演与最终记录

[只读清理预演](../build/audit/release-311-candidate-20261101-r1/cleanup-preview-r1.json)已完成：当前删除清单为空、可回收字节为 0，**没有执行永久清理**。核对的本轮目录无链接/junction，记录时候选、冻结原件及固定安装均无运行占用；这一占用快照不代替将来操作前的再次检查。

| 保留的具体目录 | 理由 |
| --- | --- |
| `build/staging/release-311-base-20261101-r1` | 同一冻结主程序及完整对应源码，是后续正式门禁/finalize 原件 |
| `build/artifacts/release-311-candidate-20261101-r1` | 当前审查归档，不与旧归档互换或改名冒充正式包 |
| `build/tmp/release-311-candidate-20261101-r1` | 人工审查安装、运行协调器、自建状态原件和失败复现输入仍有引用 |
| `build/audit/release-311-candidate-20261101-r1` | 原始日志、真实截图、哈希、冻结清单和失败/通过证据均保留 |

固定安装、主程序及插件各自最新/上一版本归档保持原状；上一轮保留的旧安装/数据、仍使用的插件输入与离线依赖种子均不删除。不清理模型、对应源码、依赖缓存、未知数据、插件项目或兄弟项目，也不运行旧清理脚本。

[最终总览](../build/audit/release-311-candidate-20261101-r1/final-summary-r1.json)已确认运行输入自构建后未变、冻结原件完整源码仍一致，主程序审查归档 SHA-256 再次匹配，七语/EXE/重装与原始失败记录分别绑定。已通过文案 SHA-256 仍为 `81ffb8e031edf25321471b525420952b9a81fa598a011dea0d203004d2e94079`，未改动正文。

请审查本次独立实际程序；本说明、已通过文案、验收结果、未测限制及清理预演共同构成当次交审材料。程序验收与正式源码、CUDA 证据等门禁未闭合前，不推送 main、发行标签或 GitHub Release。
