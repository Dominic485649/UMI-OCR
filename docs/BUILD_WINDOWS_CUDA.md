# Windows 构建与最简分发

目标为 Windows x64。主程序版本读取 `UmiOCR-data/about.json`，CUDA 读取插件清单，PaddleVL 读取授权插件工程中的 `VERSION` 与清单；不要求同版。兼容性依据 Host API、Python ABI、平台和实际联合运行。

## 环境与输入

- PowerShell 7（`pwsh`）、Git、CMake、Visual Studio C++ 工具链和 Windows SDK。
- 锁定的 Python 3.13.16、Qt/PySide6 6.11.2、CUDA 12.6 依赖与对应源码。
- `build/requirements-base-windows.lock`、`build/requirements-gpu-plugin-windows-cu126.lock`、`build/sources-windows-cu126.lock.json` 和 Qt 白名单。
- 离线模式只复用已核验的完整 runtime、wheel、模型和来源材料；缺失即失败，不回退联网。不重新解析依赖锁、不下载或量化模型来完成普通分包。

用户不需要安装系统 Python、pip 或 CUDA Toolkit；运行仍需要兼容的 NVIDIA GPU 和驱动。

## 构建边界

`build/windows/Build-Release.ps1` 和 `Build-GpuPlugin.ps1` 在全新 `-StagingRoot` 内构建完整输入。只有变动组件需要重建；重新分包未变 CUDA 不需要重编译。PaddleVL 使用授权独立工程的 `Build-Plugin.ps1`，不把兄弟工程作为主程序的隐式源码来源。

两个主构建入口与 PaddleVL 默认 `-DistributionLayout minimal`：

- `-StagingRoot` 保留完整源码、锁定依赖来源和审计所需材料。
- `-MinimalRoot` 指定新的运行目录，默认 `<StagingRoot>-runtime`。
- `-DistributionRecord` 指定新的外置分包 JSON；默认在相应 `build/audit/` 具名生成。
- `-DistributionLayout complete` 仅供旧布局兼容，不用于本轮最简交付。
- `-RuntimeLayout stored` 按原策略聚合 Stored-ZIP；不压缩/混淆原始 Python，不裁掉需要落地的原生扩展与资源。
- `-SkipArchive` 只准备输入与运行目录，不等于验收或正式发布通过。`LocalCandidate` 不是公开发行授权。

构建命令的种子、工作根和输出路径应来自本轮实际记录，不能复制历史文档中的机器目录当作当前有效输入。`-ReuseDependencies -Offline` 保持依赖锁；CUDA 的 `-SkipModels` 仅禁止下载/派生，新的构建须同时提供已核验的 `-ReuseModels` 输入。

## 分包与源码

共用工具 `build/tools/prepare_minimal_distribution.py` 支持 `prepare`、`verify`、`package`：

- `prepare` 从完整输入创建全新运行覆盖层，逐项记录保留、移出、来源和摘要，未知根文件拒绝丢弃。
- `verify` 同时核验实际运行树和外置完整材料，不将本地完整性 PASS 当成公开来源 PASS。
- `package` 产生真正的 `.tar.xz` 运行归档和独立对应源码归档，并保存本地打包记录；不接受 CLI 参数绕过公开门禁。

本体解压后直接出现 `Umi-OCR.exe`、`UmiOCR-data/`；插件解压后直接进入 `UmiOCR-data/plugins/<插件ID>/`，没有多余产品目录前缀。最简许可与 `SOURCE.txt` 在本体根/插件命名空间；不安装源码和审计树。运行所需 CA 证书、Qt/Chromium 资源、编解码器、模型与已有依赖许可不误删。

独立对应源码与运行包按实际版本/哈希对应，正式分发时放在同一交付位置清晰提供。完整原件、源码镜像与原始证据继续保留在构建工作区。[源码交付](../SOURCE-CODE.md)

## 审计、冻结和正式归档

完整输入仍走既有 `Audit-Package.ps1` / `verify_release_evidence.py` 来源、许可与运行门禁。`Finalize-Release.ps1 -DistributionRecord` 在这些门禁通过后核对最简运行树，公开批准输入还须绑定 `minimal_distribution_record_sha256`；最终归档按实际最简文件集合和字节校验，不是事后无记录删包。

正式源/许可仍有 BLOCK 时，不得据“运行包不含额外源码”忽略门禁。冻结后不刷新来源、重算快照或把新 PASS 写回旧源码。PaddleVL 的正式发行同样需要自己的源码与依赖许可核验，不能由主程序 PASS 代替。

- `Finalize-Release.ps1 -ReportRoot` 将结构审计与直接验证的新结果分别写入独立 `audit/`、`verification/` 子目录；不得覆盖已冻结/历史原件中的报告。
- `-ExistingArchive` 明确登记目标目录中的同名候选归档，保留原编码参数，但不绕过来源、许可、当次程序/文案批准或逐成员比对。仅成功后生成新的完整性回执，不改归档，也不覆盖既有回执。
- `prepare_minimal_distribution.py prepare --metadata-root` 仅供 PaddleVL 已独立核验的完整外置来源/许可根使用；版本、原始许可证及全部材料均须匹配，运行载荷仍来自实际完整组件输入。
- `prepare_webengine_sources.py --source-archive` 可从本项目锁定官方源码缓存重新只读收集法律文件，核对完整大小/SHA-256，不重复下载；不会按 `measurement_notice.ts` 等名称误收界面源码。
- 3.1.3 的有限验收范围独立于 3.1.2，保留截图/HDR/混屏 NOT_RUN，并明确未重跑 PDF 全矩阵、未完整网络下载大权重；一般发布意图不是当次程序和文案审查批准。

## 定向验收与本地更新

按影响面选择测试：新布局的分类/来源绑定、下载流式/取消/失败/冲突/路径安全、QML 按钮与配置回填、真实归档重装、实际程序启动、插件发现与代表性 OCR/文档链。纯分包的未变依赖和模型用逐文件哈希复核，并说明复用证据边界，不例行全仓回归。

截图捕获、HDR、混屏/多屏后续不再主动测试，保持 NOT_RUN，不要求人工补验。新增下载的网络 E2E 与本地已有模型推理分别记录；元数据可用不能算完整权重下载成功。

验收后从新归档组合更新固定安装 `release/Umi-OCR`，保留用户配置、日志、任务资源、`model/` 及本地私有 DLL；不覆盖运行中目录，不终止用户进程。发布前必须交审实际程序、文案、验收限制和清理预演；本地安装更新不等待公开发布批准，也不构成该批准。

## 清理与历史

只处理本项目本轮列明且已核对的目标，删除前检查占用、链接、原件归属和引用。保留模型、源码、依赖缓存和历史证据，不清理兄弟插件工程。release 顶层只保留固定安装和各组件最新/上一版本运行归档；独立源码与审计放构建目录。

[历史记录](HISTORY.md) · [组合许可](../LICENSES/COMBINED_DISTRIBUTION.md) · [插件接口](PLUGIN_API.md)
