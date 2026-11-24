# CUDA 插件

CUDA 插件提供 PP-OCRv6_medium 离线图片与 PDF OCR，当前修复候选独立版本为 **3.0.7**。本轮在 3.0.6 精简基线上更新 Paddle/NVIDIA 私有 GPU 闭包至 CUDA 12.9，保留原模型、OpenCV/ModelScope 子集和 Stored-ZIP；不要求与主程序同版。候选尚未公开发布，实际可下载版本以 Releases 为准。

[插件 Releases](https://github.com/Dominic485649/UMI-OCR_plugins/releases) · [主程序 Releases](https://github.com/Dominic485649/UMI-OCR/releases)

## 安装

1. 先完整解压兼容的主程序。
2. 将 `Umi-OCR-Plugin_v3.0.7_Windows_x64_CUDA.tar.xz` 完整解压到同一主程序根目录。
3. 检查 `UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/umi-plugin.json` 与 `UmiOCR-CudaWorker.exe`，启动后在插件管理中启用 CUDA。

最简包只包含插件运行覆盖层与必要许可/源码指引，不内嵌源码树和审计材料。对应源码独立提供，见[源码交付](../SOURCE-CODE.md)。更新前正常退出，不覆盖运行中目录，保留配置、日志、任务资源和模型。

## 要求与能力

- Windows 10 1903+ / Windows 11 x64；兼容 CUDA 12.9 的 NVIDIA GPU 和驱动。CUDA 12.9 GA 对应 Windows 驱动 576.02，VL 的 llama 驱动条件另外保留。
- 本轮 Paddle 两个核心库逐个确认含 sm75/80/86/89/120 cubin、无 PTX；不以“至少 7.5”推断所有更高算力可用。RTX 5060 的运行验收仍需实机；MX250（sm61）明确不支持，重装系统 CUDA 不能补出缺失架构。
- 使用本体的 Python 3.13.16，插件私有推理闭包与模型随包提供，不需要系统 Python、pip 或 CUDA Toolkit。
- Host API 范围 `>=2.7,<3.0`，包含当前 2.9；兼容性不以本体与插件版本号相同判断。
- 原生 worker 在实际加载 Python/Paddle 的进程声明 UTF-8，不修改系统全局代码页或原版 Python EXE。
- 没有可用 CUDA 时明确失败，不暗中回退 CPU。
- 模型首次使用时加载，也可经设置/托盘预热或清理；[PP-OCRv6 设置](SETTINGS_PP_OCRV6.md)。

PaddleVL 是另一个独立插件，支持[模型下载/手动导入](MODEL_DOWNLOADS.md)与 HTTP 文档解析；这些按钮不替换 CUDA 自带的 PP-OCRv6 模型。

## 验证与许可

新 GPU 闭包须独立完成基础算子、真实 OCR、包内启动及归档重装；本体未变部分注明复用的历史来源，不把旧验收写成新结果。截图捕获、HDR、混屏/多屏继续 NOT_RUN。实际完成项与未完成的 RTX50 实机范围以本轮记录及审阅草稿为准。

原 Umi-OCR MIT 许可与署名保留，新增/修改部分遵循 AGPL-3.0-or-later；NVIDIA 和模型按各自条款使用。第三方插件开发/接入开放，不设置付费来源或作者身份门禁。

[Windows 构建](BUILD_WINDOWS_CUDA.md) · [插件 API](PLUGIN_API.md) · [历史记录](HISTORY.md)
