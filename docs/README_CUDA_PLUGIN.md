# Umi-OCR CUDA 插件 v3.0.1

CUDA 插件仓库为 [Dominic485649/UMI-OCR_plugins](https://github.com/Dominic485649/UMI-OCR_plugins)。本仓库提供已审查的 CUDA 源码与必要构建、测试、依赖锁和许可材料。

本插件为 Umi-OCR 提供基于 PaddlePaddle GPU 的 PP-OCRv6_medium 离线文字识别。维护者为 [Dominic485649](https://github.com/Dominic485649)，主程序基于 [hiroi-sora 的 Umi-OCR](https://github.com/hiroi-sora/Umi-OCR)。原始作者与第三方贡献署名保留。

## 下载与安装

| 内容 | 下载位置 |
| --- | --- |
| Umi-OCR 主程序基础包 | [主仓库 v3.0.1 Release](https://github.com/Dominic485649/UMI-OCR/releases/tag/v3.0.1) |
| CUDA 插件 | [插件仓库 v3.0.1 Release](https://github.com/Dominic485649/UMI-OCR_plugins/releases/tag/v3.0.1) |

本次公开提供 CUDA 插件，不提供 CPU 或 PaddleOCR-VL 下载资产。

1. 将主程序基础包完整解压到新的目录。
2. 将 CUDA 插件 `.tar.xz` 完整解压到该主程序根目录，保留归档相对路径。
3. 确认 `UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/umi-plugin.json` 存在。
4. 启动 `Umi-OCR.exe`。如果程序已经运行，刷新插件列表，再选择对应 OCR 引擎。

`.tar.xz` 是外层 xz 和内层 tar。某些工具需要分别解压，不要只得到一个 `.tar` 文件就结束。插件许可与对应源码保存在 `LICENSES/plugins/win32_PaddleOCRv6_CUDA/`，安装时不要丢弃；这个独立目录避免覆盖主程序同名材料。

## 运行要求与执行边界

- Windows 10/11 x64，以及兼容 CUDA 12.6 的 NVIDIA 显卡与驱动。
- Python 3.13.16 使用主程序随附的同一份解释器，不需要额外安装系统 Python。
- PaddleOCR、PaddleX、PaddlePaddle GPU 与 CUDA/cuDNN 依赖由锁定的插件运行时提供。
- 不需要安装系统 CUDA Toolkit，但这不等于不需要显卡驱动。
- 推理运行在独立 worker 进程，通过 JSON-lines 传递图片路径、图像字节和 OCR 结果。主程序不直接加载 Paddle/NVIDIA 推理栈。
- 不提供 CPU fallback，缺少 CUDA 或初始化失败时明确报错。
- 默认在首次识别时加载模型，可以通过主程序设置和托盘操作预热或释放。

本次不发行 Linux 版本，后续会考虑 Linux 兼容。

## 版本与兼容

插件产品版本为 `3.0.1`，与主程序正式发布标签 `v3.0.1` 对应。产品版本和 Host API 版本不是同一字段，宿主接口保留现有兼容路径。

本分支的旧版 CPU、CUDA 与 PaddleOCR-VL 插件不作为本版支持对象，请使用匹配的新实现。其他插件依据公开接口、平台、Python ABI 与依赖约束判定兼容性，不设置作者身份或付费来源门禁。

第三方插件开发、接入和替换保持开放。你也可以自行开发兼容的 OCR 或文档插件，不必购买作者提供的其他实现。

## CPU、CUDA 与 PaddleOCR-VL

CPU 与 CUDA 的识别效果一致，CPU 的速度明显较慢。有兼容 NVIDIA 显卡时推荐 CUDA，日常截图、批量图片和 PDF 识别的速度与交互体验提升很大。

PaddleOCR-VL 精度高，速度与 CPU 接近，适合更看重精度或结构化文档处理的需求。CPU 与 PaddleOCR-VL 是单独的付费选项，不包含在此次公开发行中。

开发、测试、维护和支持都有成本，我也要吃饭，希望通过可选交付回收一部分投入。这不是要求大家必须购买，也不会限制第三方兼容插件。收费不会取消接收者依法享有的开源许可权利。

联系作者：QQ 群 [【AWJ | Umi-OCR】](https://qm.qq.com/q/5XHoXCOU26)。

## 源码、构建与许可

插件源码、构建入口、依赖锁、补丁、测试与第三方声明随公开仓库提供。公开构建不应依赖本地未发布的 CPU/VL 项目，不能通过搬运整个收费插件项目来补齐 CUDA 交付。

原始 Umi-OCR MIT 声明与 hiroi-sora 版权保留。本分支新增和修改部分按 AGPL-3.0-or-later 提供。CUDA/cuDNN 和模型不因进程隔离而自动变成 AGPL 覆盖或免除其适用条款，具体以随包许可与来源声明为准。

- [主程序 README](https://github.com/Dominic485649/UMI-OCR/blob/v3.0.1/README.md)
- [Windows CUDA 构建说明](https://github.com/Dominic485649/UMI-OCR_plugins/blob/v3.0.1/docs/BUILD_WINDOWS_CUDA.md)
- [插件接口](https://github.com/Dominic485649/UMI-OCR_plugins/blob/v3.0.1/docs/PLUGIN_API.md)
- [组合发行许可说明](https://github.com/Dominic485649/UMI-OCR_plugins/blob/v3.0.1/LICENSES/COMBINED_DISTRIBUTION.md)
- [主程序 Release](https://github.com/Dominic485649/UMI-OCR/releases/tag/v3.0.1)
