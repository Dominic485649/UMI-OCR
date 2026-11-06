# CUDA 插件

CUDA 插件提供 PP-OCRv6_medium 离线图片与 PDF OCR，当前独立版本为 **3.0.5**。本轮只改变分包方式，不升级模型/依赖、不重新编译 worker，不把主程序 3.1.3 的版本号强行套到插件。

[插件 Releases](https://github.com/Dominic485649/UMI-OCR_plugins/releases) · [主程序 Releases](https://github.com/Dominic485649/UMI-OCR/releases)

## 安装

1. 先完整解压兼容的主程序。
2. 将 `Umi-OCR-Plugin_v3.0.5_Windows_x64_CUDA.tar.xz` 完整解压到同一主程序根目录。
3. 检查 `UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/umi-plugin.json` 与 `UmiOCR-CudaWorker.exe`，启动后在插件管理中启用 CUDA。

最简包只包含插件运行覆盖层与必要许可/源码指引，不内嵌源码树和审计材料。对应源码独立提供，见[源码交付](../SOURCE-CODE.md)。更新前正常退出，不覆盖运行中目录，保留配置、日志、任务资源和模型。

## 要求与能力

- Windows 10 1903+ / Windows 11 x64；兼容 CUDA 12.6 的 NVIDIA 显卡和驱动。
- 使用本体的 Python 3.13.16，插件私有推理闭包与模型随包提供，不需要系统 Python、pip 或 CUDA Toolkit。
- Host API 范围 `>=2.7,<3.0`，包含当前 2.9；兼容性不以本体与插件版本号相同判断。
- 原生 worker 在实际加载 Python/Paddle 的进程声明 UTF-8，不修改系统全局代码页或原版 Python EXE。
- 没有可用 CUDA 时明确失败，不暗中回退 CPU。
- 模型首次使用时加载，也可经设置/托盘预热或清理；[PP-OCRv6 设置](SETTINGS_PP_OCRV6.md)。

PaddleVL 是另一个独立插件，支持[模型下载/手动导入](MODEL_DOWNLOADS.md)与 HTTP 文档解析；这些按钮不替换 CUDA 自带的 PP-OCRv6 模型。

## 验证与许可

本轮分包按运行载荷逐文件不变、归档重装和联合运行核验，不把旧验收写成新结果。截图捕获、HDR、混屏/多屏继续 NOT_RUN。实际执行项以本轮记录为准。

原 Umi-OCR MIT 许可与署名保留，新增/修改部分遵循 AGPL-3.0-or-later；NVIDIA 和模型按各自条款使用。第三方插件开发/接入开放，不设置付费来源或作者身份门禁。

[Windows 构建](BUILD_WINDOWS_CUDA.md) · [插件 API](PLUGIN_API.md) · [历史记录](HISTORY.md)
