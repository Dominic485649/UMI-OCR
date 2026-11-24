# 界面与文档分页：3.1.1 本地更新

日期：2026-11-01。用户要求“继续，覆盖后我来验收”。本轮仅进行本地构建、归档、全新重装和固定安装更新；**不 push、不创建标签或 GitHub Release，不将本地覆盖同意解释为公开发行同意。**

> **本地更新已完成，固定程序可交用户验收。** 新安装来自本次最终归档的全新重装，原配置/任务数据按原字节保留；旧安装与两个更早归档完整保留，未终止用户进程、未删除旧大文件。未公开发布。

## 独立组件与安装位置

| 组件 | 版本 | 本轮处理 |
| --- | --- | --- |
| 主程序 | 3.1.1 | 由已提交的界面/文档分页源码离线重建 |
| CUDA 插件 | 3.0.5 | 无源码变化，复用已核验最终归档，没有重建或重新压缩 |
| PaddleVL 插件 | 3.1.1 | 文档页面及回调有变化，独立离线重建 |

固定安装位置为 `D:\Code\Python\Umi-OCR\release\Umi-OCR`，入口为 [Umi-OCR.exe](../release/Umi-OCR/Umi-OCR.exe)。主程序版本不是 Host API 版本；实际 Host API 为 `2.8`，插件按各自清单范围及本轮联合运行判断兼容，不要求组件同版。

详细功能说明及源码阶段的原生验证见[设置布局与文档解析分页调整](UI_AND_DOCUMENT_PAGING_2026-10-30.md)。本轮主要交付：

- 全局设置不再自动弹出“小贴士”；新配置默认 125%，已有合法缩放不改写。
- 识别模型和类别参数位于截图 OCR、批量图片和批量文档各自设置区。模型仍为唯一共享入口，各类别参数独立保存。
- 悬浮提示限宽，长说明与 URL 自动换行。
- 文档解析采用与批量文档一致的双栏布局；导入后、未解析时即可逐页浏览真实原页。
- 已完成页结果即时可见，文本、Markdown、JSON、结构块随当前页切换；支持当前页/整篇、滚动、取消保留和整篇导出。

## 实际归档

| 归档 | 字节 | SHA-256 |
| --- | ---: | --- |
| `Umi-OCR_v3.1.1_Windows_x64.tar.xz` | 201138352 | `b3cc19090d57fa04c2062f059754f0b6920ef5b607959eb68fb4e4e53d75049e` |
| `Umi-OCR-Plugin_v3.0.5_Windows_x64_CUDA.tar.xz` | 1779686648 | `2889768d3a5c7429dff30b68b58d37575880967507c87e44bf2ef3e8a9f8e907` |
| `Umi-OCR-Plugin_v3.1.1_Windows_x64_PaddleVL.tar.xz` | 2545860052 | `22b0a1b1fe8b4a14079acec1c061d6998e71a8f7acc4780bc4aab3a6db554062` |

两个新包均绑定包前/包后完整载荷，并经独立 `7z t` 检查。PaddleVL 使用已采用的标准 XZ preset 1，没有试验压缩算法。CUDA 原归档仅复验身份和完整载荷；旧 overlay 已不完整，因此从原最终归档恢复本轮独立输入，没有修改旧审计或重新声称打包通过。

## 本轮验证与证据

审计根为 [build/audit/ui-local-update-20261101-r1](../build/audit/ui-local-update-20261101-r1/final-summary-r1.json)，工作根为 `build/tmp/ui-local-update-20261101-r1`。所有正式结果使用本轮全新路径，旧失败和历史审计不改写。

已完成：

- [开工基线](../build/audit/ui-local-update-20261101-r1/baseline.json)：界面源码与上一阶段冻结摘要一致；主依赖种子的 88 项 DLL、PaddleVL vendor 的 13923 项锁定文件及 llama.cpp 清单已核验，拒绝链接/junction。
- [主程序重建](../build/audit/ui-local-update-20261101-r1/base-build-r1/result.json)、[PaddleVL 重建](../build/audit/ui-local-update-20261101-r1/vl-build-r1/result.json)：正式构建入口、独立新目录、完全离线，无构建期间源码变化。
- [纯本体原生检查](../build/audit/ui-local-update-20261101-r1/base-native-command-r1.json)：实际候选的 Python/Qt/QML/QM，正常退出，自建状态移出保留后产品字节恢复。
- [主程序归档](../build/audit/ui-local-update-20261101-r1/base-package-command-r1.json)、[PaddleVL 归档](../build/audit/ui-local-update-20261101-r1/vl-package-command-r1.json)：完整输入及输出摘要、独立 7-Zip 检查通过；[CUDA 复用记录](../build/audit/ui-local-update-20261101-r1/cuda-reuse-r1.json)明确未重新构建。
- [重装工具定向回归](../build/audit/ui-local-update-20261101-r1/archive-guard-fixtures-r1.json)：10 项，包含精确解包、哈希/成员错误、越界/链接拒绝、容量不足先停止、正式结果完整写入后发布，以及新任务根与历史根隔离。
- [切换工具定向回归](../build/audit/ui-local-update-20261101-r1/switch-fixtures-r1.json)：5 项小型自有目录场景，覆盖便携数据字节、旧原件身份、未知代码/缓存隔离、配置变化/占用停止及晋升失败后回退。占用为模拟，实际切换仍必须进行实时 CIM 检查。

- [三归档全新重装](../build/audit/ui-local-update-20261101-r1/reinstalled-r1/result.json)：23,817 个完整产品文件与独立归档载荷逐项匹配，实际耗时 358.575 秒；旧固定安装未在重装过程中改动。
- [实际组合包原生场景](../build/audit/ui-local-update-20261101-r1/packaged-native-r1/result.json)：8 组检查通过，正常退出，无 Qt 警告/错误；宿主业务模块逐项绑定本包 `app.zip` 与对应源码快照，自建状态原件移出后产品恢复精确载荷。已[实际查看代表截图](../build/audit/ui-local-update-20261101-r1/visual-review-r1.json)，包括 OCR 设置、未解析第三页、JSON 首屏/双向滚动、末尾结构块与三行长提示；没有用源码阶段的旧图替代。

- [正常 EXE 与真实第二 EXE](../build/audit/ui-local-update-20261101-r1/normal-exe-r1/native-cli-result.json)：实际单实例 CLI 转发及回环 `/api/backends` 包含 CUDA/VL OCR、VL 文档后端；无效 backend 明确返回 `804/INVALID_OPTIONS`，未请求推理，正常退出。
- [正常 EXE 自建状态恢复](../build/audit/ui-local-update-20261101-r1/normal-exe-restore-r1.json)：138 个新缓存逐项绑定归档源码、缓存头部及完整嵌套代码对象；142 个自建文件原字节移出保留，组合产品恢复精确的 23,817 文件载荷。该有限冒烟自有配置为 100%，125% 缺省由独立原生场景验证，不混为同一次配置。

- [固定目录安全切换](../build/audit/ui-local-update-20261101-r1/switch-result-r1.json)：23,817 个产品文件和 7 个便携数据文件逐项核对；旧目录的 27,276 个文件及其真实文件身份完整保留。复制的数据共 3,451,868 字节；其余 3,452 个额外项只留旧目录，没有混入新产品。
- [固定新路径有限加载](../build/audit/ui-local-update-20261101-r1/fixed-probe-r1.json)：使用固定安装自己的 Python 3.13.16、Qt/PySide6 6.11.2，四个 Stored 容器与实际模块来源匹配，未启动 GUI、模型或 HTTP；审计钩子禁止打开真实便携配置。

- [归档归位](../build/audit/ui-local-update-20261101-r1/archive-placement-result-r1.json)：4 次同卷重命名均核对真实文件身份与 SHA；release 顶层实际保留固定程序和 6 个规范归档。两个更早归档完整移入本轮保留区，删除文件为零；旧打包/验收记录未修改。

上述交付结果由[最终证据总览](../build/audit/ui-local-update-20261101-r1/final-summary-r1.json)关联。用户手动验收与真实模型推理尚未执行，不视为本轮自动检查的通过项。

源码阶段的定向回归复用依据：业务实现和六语 QM 与 `ui-refinement-20261030-r1/final-summary-r1.json` 的冻结摘要一致，本轮只独立修改相应版本。实际包内窗口场景另行执行；未重跑与本次改动无关的 GPU、模型质量和性能矩阵。

## 用户状态、目录与归档生命周期

已按[当次切换预演](../build/audit/ui-local-update-20261101-r1/switch-plan-r1.json)完成：旧固定目录同卷保留至 `build/tmp/ui-local-update-20261101-r1/old-install-preserved`，再将已从归档全新重装并验收的组合根同卷移至固定位置，没有边运行边覆盖或先删旧安装。

- 明确的 `.settings`、`.pre_settings`、`themes.json`、`plugins/.plugins_state`、日志和任务数据按原字节带入同一相对位置，不解释或重写配置，不强制改旧缩放。
- 未知文件、旧缓存及代码原件仅留在旧安装；不导入新产品。拒绝全部重解析点/硬链接，不修改权限、不终止用户进程。
- 旧程序和数据原件完整保留，待用户验收；本轮不授权永久删除大文件或清理插件项目。
- release 顶层实际只保留固定目录及各组件最新/紧邻上一版：主程序 3.1.1/3.1.0、CUDA 3.0.5/3.0.4、PaddleVL 3.1.1/3.1.0。
- 更早的主程序 3.0.3、PaddleVL 3.0.0 归档仅同卷移至 `build/tmp/ui-local-update-20261101-r1/older-release-archives-preserved`，记录原路径、新路径、SHA 和真实文件身份，不永久删除、不改写历史打包证据。
- [轻量清理记录](../build/audit/ui-local-update-20261101-r1/empty-directory-cleanup-r1.json)：仅非递归删除本轮已结束阶段的 `base-package-tmp-r1`、`vl-package-tmp-r1`、`archive-guard-fixtures-r1` 三个空目录；先核对路径、重解析点、空目录和实际进程引用，再执行不会递归删除子文件的操作。删除文件为零；构建种子、对应源码、锁、模型、原始日志、运行状态原件和全部审计证据均保留。

## 对应源码、许可与未执行限制

主程序源码阶段提交为 `6d77dcbf535f8b8ffd1b971ce1cb6470f61f7f76`，版本提交为 `e8bd065a`。正式构建的对应源码快照包含当时的 541 项宿主来源；插件按独立 `source-records`/源码包保留，不覆盖宿主根的来源及许可。

本轮重装根适配与包内原生测试已在主仓库本地提交 `2bd6c828`，没有 push。它们及本轮交付说明晚于候选构建，仅用于本地交付与验证，单独记录实际执行源码摘要；不冒称已包含在较早生成的产品源码快照。插件项目既有未提交工作未撤销或全量提交；[两个版本文件的独立增量](../build/audit/ui-local-update-20261101-r1/plugin-version-delta-r1.json)保存开工原件、当前冻结字节及 LF 补丁，不把既有差异合并提交。

**未执行/未放行：**真实模型推理、GPU 质量/性能矩阵、用户真实文档验收、用户真实配置下 GUI 启动、GitHub 推送/标签/Release。逐页结果采用受控回调，原始 PDF 预览使用真实渲染。未下载或量化模型、未更改模型精度，不作模型/商标权利获授权的表述。

构建日志原有 `source_delivery: BLOCK`、`current_source_e2e: BLOCK` 是公开发行证据门禁，仍保留；本地候选构建和有限针对性运行不把这些门禁改为通过。公开发行必须另行提交当次程序、文案、验收与清理范围给用户审查，等当次明确同意。

## 手动验收重点

直接使用固定安装内的 `Umi-OCR.exe`，无需重新解压或安装插件。请重点检查各 OCR 页面内的模型/参数入口、全局设置不再自动弹小贴士、长提示自动换行，以及多页文档导入后未解析即可翻页、解析过程中已完成页可见、JSON/结构块随页切换与滚动。

本次会保留已有合法缩放；如果原配置并非 125%，打开后仍应保留原值。125% 是新配置/缺失值/主动重置的默认值，不以清空用户配置来实现。

## Release 文案草稿（未发布）

### Umi-OCR 3.1.1：设置布局与逐页文档预览

本次更新优化 OCR 设置的入口和长提示展示，并使文档解析可以在整篇完成前浏览原始页和已完成页结果。新配置默认 125%；已有合法缩放保持不变。识别模型仍在各 OCR 页面共享同一选择，类别参数继续独立。

文档解析采用与批量文档一致的双栏布局，文本、Markdown、JSON 和结构块随当前页统一切换；补齐 JSON 双向滚动、结构块滚动/选中联动、取消保留已完成页和整篇导出。

组件分别为主程序 3.1.1、CUDA 3.0.5、PaddleVL 3.1.1，不要求同版。此文案仅是本地审查草稿；验收范围以本次实际记录为准，不宣称已经重跑真实模型质量或性能矩阵，也不表示已获公开发行批准。
