# Umi-OCR 3.1.1 纯本体交付记录

## 当前状态

**Umi-OCR v3.1.1 已于 2026-11-02 14:45:08（UTC+08:00）作为最新正式版公开。** 主程序对应源码、标签、正式本体归档和校验和均已交付；重新安装、实际 EXE／第二实例 CLI，以及公开附件的完整匿名下载 SHA-256 核验均已通过。公开正文与本轮绑定文案一致。

- [GitHub Release](https://github.com/Dominic485649/UMI-OCR/releases/tag/v3.1.1)
- [直接下载 Windows x64 基础包](https://github.com/Dominic485649/UMI-OCR/releases/download/v3.1.1/Umi-OCR_v3.1.1_Windows_x64.tar.xz)
- [下载 SHA-256 校验和](https://github.com/Dominic485649/UMI-OCR/releases/download/v3.1.1/Umi-OCR_v3.1.1_Windows_x64.tar.xz.sha256)

实际公开附件仅为基础包与其校验和。完整匿名下载取得 299,413,580 字节，SHA-256 为 `61b17b7befc83f3db8ef768d946be285f2ea2a36103dd9e25a5f49d48d451d07`，与正式包及 GitHub 附件摘要相同；流式核验未落地重复大文件。

本记录依据当次已批准的主程序与文案，以及 2026-11-02 用户原文“cuda不发布”“截图后续不再测试”。不把后台完成通知或本文件当作新的人类确认。

## 公开范围与不做的操作

- 本次唯一公开组件：**Umi-OCR 3.1.1 Windows x64 基础程序**。
- CUDA 3.0.5、PaddleVL 3.1.1 和 CPU 插件均不作为本次附件；CUDA 插件仓库的 main、标签和 Release 未更新。
- 不下载模型、不更改权重或量化精度，不新增模型或商标授权主张。
- 固定安装 `release/Umi-OCR` 及其中用户配置、任务和已安装插件未覆盖。此次同步的是本地最终本体归档。

## 正式归档与对应源码

- 文件：`Umi-OCR_v3.1.1_Windows_x64.tar.xz`
- 大小：**299,413,580 字节**。
- SHA-256：`61b17b7befc83f3db8ef768d946be285f2ea2a36103dd9e25a5f49d48d451d07`
- 本地最终归档：[release/Umi-OCR_v3.1.1_Windows_x64.tar.xz](../release/Umi-OCR_v3.1.1_Windows_x64.tar.xz)
- 对应源码：[v3.1.1](https://github.com/Dominic485649/UMI-OCR/tree/v3.1.1)
- 公开源码提交：[3a8e49c982b2ea967d0104d81dbabd55f08bc579](https://github.com/Dominic485649/UMI-OCR/commit/3a8e49c982b2ea967d0104d81dbabd55f08bc579)

运行载荷 **1,866 项文件**保持已审原字节，绑定 SHA-256 为 `51ccc30910c0d83cdb9401884901679aa9511ab1ad44e84ef971aa99a3289fbe`。新的纯本体 canonical 源码为 **532 项文件**，绑定 SHA-256 为 `b1a4d9190d44734d27ad8f2a49c4e16e616852de705bdbca24f6ac18ec991d7b`。

原镜像中的 16 项 CUDA 插件实现和原生 worker 源码已排除；正式审计必需的共享构建脚本、来源锁与许可材料仍保留。已逐项核验 canonical `source/`、源码 ZIP、清单与公开 Git 提交的成员及原字节一致，未把内部工作仓库 main 直接推送为公开源码。

## 实际核验与复用边界

- 本次实际执行：相关五组门禁普通模式和 `-O` 模式回归各 **126 项**；纯本体源码门禁导入闭包合成检查（14 项，执行源为初轮纯本体；最终源码的全部 Python 输入与其相同，未冒称重跑）；正式结构、来源及许可审计；匿名公开标签/提交核验；受限 finalize；独立 7-Zip 完整性检查；正式归档全新重新安装；正常 EXE、真实第二实例 CLI 转发及正常退出。
- 正式本体重装 **2,428 项产品文件**与正式归档逐项一致，程序运行后自建状态原字节保留并移出，恢复原产品后再次核验。
- 基础档、联合档、hot GUI 和 Shell 托盘采用此前同一宿主原字节的真实记录，原始日志与当时输入保留；只按实际不变输入复用，不声称本次重跑。
- **没有执行新的截图、窗口截图验收、截图 OCR、人工 HDR、混屏或模型推理。** 完整桌面捕获、人工 HDR、混合 HDR/SDR 及多屏覆盖保留 **NOT_RUN**。本轮专用受限验收状态为 `ACCEPTED_WITH_LIMITATIONS`，不是手动 PASS，也不宣称 HDR 捕获成功。
- 包内不含 OCR 推理插件或模型；首次 OCR 使用需要另行安装已公开、兼容的插件。

## 本地归档保留与审计

本地旧同名归档原 SHA-256 为 `b3cc19090d57fa04c2062f059754f0b6920ef5b607959eb68fb4e4e53d75049e`，已同卷移入 `build/artifacts/release-311-baseonly-20261102-r1/superseded-local-main-r1/`。旧原件未删除，历史审计记录未改写；新旧路径及哈希映射保存在本轮归档放置记录中。

固定安装、用户数据、各插件归档、主程序上一版本、模型、源码、依赖缓存及历史失败证据保留。没有执行旧清理脚本，没有删除既有程序、归档、模型或用户大文件，没有终止用户进程；正式打包工具只按既有生命周期清理其在本轮工作根内自行创建的临时副本。

本轮具名审计根：`build/audit/release-311-baseonly-20261102-r1/`。主要记录包括 `scope-and-authorization-r1.json`、`base-product-prepared-r2.json`、`source-verification-r2.json`、`formal-finalize-r1.json`、`reinstalled-baseonly-runtime-r1.json`、`archive-placement-result-r1.json`、`main-release-publication-r1.json` 和 `final-summary-r1.json`；原始输入、失败尝试和日志按各自时间截点保留，不回填为新的通过记录。
