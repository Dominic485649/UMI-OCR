# 设置布局与文档解析分页调整

日期：2026-10-30。主仓库起点 `f0978fd6`。本轮为源码与原生界面定向调整，**不覆盖 `release/Umi-OCR`，不重打归档，不 push 或公开发布**。当前固定安装仍保留上一轮已验收载荷及用户设置。

## 界面行为

- 全局设置不再自动弹出截图中的“小贴士”。不修改“不再提示”记录，其他错误、确认弹窗及操作提示不受影响。
- 新配置、缺失缩放项及主动重置的默认缩放为 **125%**；已有有效缩放值保留，未批量改写用户 `.settings`。
- 截图 OCR、批量图片 OCR、批量文档各自在设置区顶部显示识别模型和本类别识别参数。模型仍共用唯一 `Global/ocr.api`；各类别参数仍分别保存，不迁移键、不增加配置副本。
- 插件管理只保留共享预热、自动清理、插件服务和设备设置，不再重复显示三个任务参数组。
- 通用悬浮提示最大宽度约为 `480 × 界面缩放`，并受窗口宽度限制；长说明、URL 自动换行，短提示保持自然宽度。

## 文档解析

文档解析 UI 的实际源文件位于已授权插件项目 [StructuredDocument.qml](../../Umi-OCR-Plugin/win32_PaddleOCRVL_1_6/StructuredDocument.qml)，不是主仓库内另建的同名页面。

### 与批量文档统一的布局

复用 `DoubleSwitchableLayout`、`Panel`、`TabPanel`、`Button_`、`HProgressBar`：左侧为任务控制、输入文档与原始页面预览，右侧为“设置 / 结果”。设置的高级/重置控制栏与批量文档一致；结果保留纯文本、Markdown、JSON、结构块、复制及整篇导出。

不照搬后端不支持的暂停/继续、文件夹递归或批量文档队列能力。运行中不能清空/替换输入或重置参数，但可以切换已导入文档和翻页。取消只作用于本页任务，不停止共享模型服务。

### 导入后即可逐页预览

原有页码控件依赖 `structuredResult.data.pages`，因此必须等解析结果返回才可翻页。现在源文档页数由现有后台预览连接器独立返回：

- 导入后即可使用上一页、下一页、页码输入和总页数浏览原始页面；图片按实际文档页数处理。
- 不启动模型、不预渲染整本 PDF，不拿“已完成解析页数”冒充源文档总页数。
- 元信息和图片均受渲染代次/会话保护；快速换文档、翻页或清空后，旧结果不能回写。
- 读取失败、加密文档有明确提示，不伪造成功预览。

### 结果翻页与滚动

- 补齐已有 worker → API → `MissionDocument.onPartial` → 页面控制器 → QML 的逐页结果接线。宿主绑定原始输入路径，不使用 worker 临时渲染图片路径。
- 每页完成后即可查看该页结果，不必等整篇完成。解析中、尚无结果、失败和未完整结束有明确区分。
- 文档/页码选择同时控制页面预览与当前页文本、Markdown、JSON、结构块；另有“当前页 / 整篇”范围选择。
- 文本、Markdown 使用独立滚动视口；JSON 支持水平和垂直滚动；结构块保留列表滚动与区域联动。
- 结果按输入文档分别保存，后台完成别的文档不会切走正在浏览的文档或跳回第一页。
- 取消/失败保留本轮已完成页；最终重组结果替换临时页数据。接纳新任务失败时保留原有结果；清空输入/结果不重置解析参数。
- 页面控制器冻结跨线程结果，并在主线程实际交付时复查任务代次；新任务和页面关闭会让旧回调失效。

## 验证记录

工作与审计根为 `build/tmp/ui-refinement-20261030-r1`、`build/audit/ui-refinement-20261030-r1`。插件相关源文件原件保存在插件项目对应审计根；未撤销或全量提交插件项目原有修改。[最终证据总览](../build/audit/ui-refinement-20261030-r1/final-summary-r1.json)将当前源码、原生载荷、各项报告与插件增量的摘要关联，旧失败记录不改写。

已完成的定向回归：

- [模型设置与来源回归](../build/audit/ui-refinement-20261030-r1/model-settings-center-r6.json)：12 组检查，包括未预建来源时首次打开、多页面共享入口、类别隔离、重载及模型切换；新增同一事件循环立即隐藏旧控件的回归，先捕获旧实现失败，再修改源码通过。
- [已有设置行为回归](../build/audit/ui-refinement-20261030-r1/model-settings-ui-r4.json)：14 组检查，覆盖三个真实配置组件、只提交一次、繁忙拒绝、任务快照与服务边界。
- [共享分组折叠](../build/audit/ui-refinement-20261030-r1/config-folding-r2-command.json)、[枚举](../build/audit/ui-refinement-20261030-r1/config-enum-r2-command.json)和[全局左栏](../build/audit/ui-refinement-20261030-r1/global-sidebar-r2.json)：三个相关回归均 exit 0。
- [文档页面契约](../build/audit/ui-refinement-20261030-r1/document-page-contracts-r11.json)：6 组页面契约及 8 个真实任务/交付竞争场景，覆盖 125% 默认与旧值保留、解析前翻页、真实 Python→QML 序列、取消与最终结果、接纳失败保留和清空进度。

上述四项均在最终共享设置组件修改后重新执行，检查范围包含相关展示依赖，不例行重跑无关推理功能。
- [逐页回调边界](../build/audit/ui-refinement-20261030-r1/partial-delivery-r1.json)：真实 `ManagedApi` 的路径接线、异常解绑定、结果冻结、旧任务拒绝和同步极快完成。
- [翻译定向检查](../build/audit/ui-refinement-20261030-r1/translations-r3.json)：在最终源码上重新执行三个定向测试并通过，含实际 QtCore 加载每条活动 QM 译文。58 个新增 QML 上下文/文案对应当前七语（简中源文及六个翻译）；六语 QM 的编译仍以本轮 `translation-compile-r2.json` 为准，没有把加载复验说成重新编译。

### 真实原生窗口

[最终原生记录](../build/audit/ui-refinement-20261030-r1/native-r10.json)为 **PASS**：8 组功能/隔离边界检查完成，正常退出，Qt 警告和错误均为零，实际耗时 31.45 秒。[源沙盒清单](../build/audit/ui-refinement-20261030-r1/native-source-r10.json)记录 251 个输入副本及原路径、SHA-256、便携依赖和自建文档来源；使用当前 Python/QML 源码，不以旧 `app.zip` / `ui.rcc` 代替。

- 实际点击三类 OCR 页面模型下拉并检查入口同步；重建时旧控件立即隐藏，布局完成后只有唯一一组设置。
- 未开始解析即查看真实 PDF 第 1/2/3 页，切换单页图片再切回 PDF，两者页数独立。
- 通过真实页面控制器传入受控逐页结果；解析未结束即查看第 2 页，文本滚轮到底、JSON 分别纵向/横向滚动、结构块滚到第 100 项并实际点击联动区域。
- 失败页明确显示；取消只针对当前任务并保留完成页，最终结果替换临时结果但不抢页。整篇复制使用本进程记录边界，未触及真实剪贴板；原控制器实际导出 TXT、Markdown、JSON 到自有空目录。
- 长无空格 URL 和中文提示覆盖浅/深两主题、100%/125%/150%、窄/宽窗口共 12 组；另实际悬停模型文件设置行，提示宽 600 像素、3 行，内容完整。
- 七语热切后保留页码和结果控件；输入未变，无模型导入、HTTP 监听或残留子进程。

已实际查看的代表截图：

- [模型与参数在截图 OCR](../build/audit/ui-refinement-20261030-r1/native-r10-ocr-settings-125.png)
- [未解析即可预览第 3 页](../build/audit/ui-refinement-20261030-r1/native-r10-document-page3-before-parsing.png)
- [长文本滚到末尾](../build/audit/ui-refinement-20261030-r1/native-r10-document-text-bottom.png)
- [JSON 首屏](../build/audit/ui-refinement-20261030-r1/native-r10-document-json-start.png)、[纵向滚动](../build/audit/ui-refinement-20261030-r1/native-r10-document-json-vertical.png)、[双向滚动](../build/audit/ui-refinement-20261030-r1/native-r10-document-json-scroll.png)
- [末尾结构块选中与区域联动](../build/audit/ui-refinement-20261030-r1/native-r10-document-blocks-scroll.png)
- [真实模型文件提示限宽换行](../build/audit/ui-refinement-20261030-r1/native-r10-tooltip-wrapped-125.png)

这些是当前源码的真实 Qt 界面验收，不冒充已更新安装包或真实模型推理验收。

## 原始失败与修正边界

- 首次原生运行暴露任务来源在属性绑定内创建的循环。来源创建已移至组件完成阶段，布局函数保持只读，并补充首次打开的回归；原失败记录不改为通过。
- Python 返回的 `QVariantList` 在 QML 中不是普通 JS 数组。逐页结果改用显式序列归一化，回归通过真正 Python→QML 方法调用，不只使用 JS 字面量模拟。
- 旧 Qt 工具清单有一个 DLL 摘要末位不符，编译按门禁停止。新工具从现有锁定 wheel 独立提取并验证；旧 DLL 与新副本字节相同，不改历史清单。六语 QM 以[新工具记录](../build/audit/ui-refinement-20261030-r1/qt-tools-r1.json)及[本次编译结果](../build/audit/ui-refinement-20261030-r1/translation-compile-r2.json)为准。
- 原生窗口发现区域 Canvas 的隐式 `region` 信号参数遮蔽外层区域对象，改为显式 `onPaint: function(paintRegion)`；窗口实际绘制及末尾结构块点击联动继续验收。
- 主题/缩放/语言切换触发共享分组背景的 `childrenRect.height` 自引用循环，改为显式内容容器高度加上下间距，并补做共享组件定向验证。
- 模型切换后，已登记 `destroy()` 的旧设置组要到下一事件循环才真正删除，曾在截图同帧与新组同时可见。现在重建时立即隐藏旧控件，不改变规范值或销毁时序；新增回归在修改前明确失败，修改后通过，原生同时检查延迟销毁前及布局完成后的实际子项。
- JSON 首次截图曾被判断为异常留白；[追加诊断](../build/audit/ui-refinement-20261030-r1/native-r7-visual-diagnosis.json)证明这是横向右移后短坐标行被正常裁切，不是丢失内容或动画中间帧。保留首屏及两方向分别滚动的实际截图，不为正常裁切修改产品逻辑。
- 原始停止、驱动诊断、输入快照和失败截图均保留，不改写旧验收。

## 未执行与交付边界

未下载或量化模型，未改推理精度、资源预算或组件版本；不宣称重新完成 GPU、质量、性能矩阵或包内/归档验收。原生场景中的逐页推理结果使用受控任务回调，原始 PDF 预览使用真实文档渲染。

本轮轻量源沙盒不复制模型、vendor 或完整运行时，每份源码快照约 2.8 MB；只借用已核验便携依赖。必要原件、失败和复现输入、锁定 Qt 工具、补丁复放保留；它们被清单及诊断引用，不作为无效缓存删除。本轮没有扩大清理旧审计、缓存、用户状态或其他项目。

## 插件独立增量

插件项目开工时已有大量未提交工作，本轮只改 `win32_PaddleOCRVL_1_6/StructuredDocument.qml`、`win32_PaddleOCRVL_1_6/page.py`；未修改其 `i18n.csv`，未全量提交或撤销原有差异。

- [增量清单](../build/audit/ui-refinement-20261030-r1/plugin-delta-r1.json)同时记录开工原件、当前源码、冻结副本和补丁摘要。
- 补丁位于插件项目 `build/audit/ui-refinement-20261030-r1/delta-r1/ui-document-paging.patch`，SHA-256：`32d2c870d4097fa6d375f8636a1b156c1333218077e6a94b1caa149c8bea7ad2`。
- [补丁复放验证](../build/audit/ui-refinement-20261030-r1/plugin-delta-check-r2.json)在插件项目本轮全新临时副本执行 `git apply --check` 和实际复放，两个文件均与冻结源码一致。补丁约定 LF；Git 按现有设置写出的 CRLF 被单列原始摘要，未改 Git 配置或原件。
- 原件 SHA-256 / 当前 SHA-256：QML 为 `1baf4d42fe0d385c71731dfc8777ba522077308cee982cb8b75c0ec4c83e9ae9` / `256ae41fce11c3c75846a536d843e39b603c11833349fbb6a072bce1a573c35a`；控制器为 `c9d5e1a7788d799af8ddfd59fe4ef21dabe0883c5de54c0f54ff29482321fefa` / `8f17dcada68c7919f791997518a456b60375c1097c1a99e1e4fe73255a483960`。
