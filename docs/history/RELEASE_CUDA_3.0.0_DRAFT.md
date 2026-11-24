# Umi-OCR CUDA OCR 插件 v3.0.0

> 正式 Release，仓库为 `Dominic485649/UMI-OCR_plugins`，标签为 `v3.0.0`，不设置 prerelease。

此版本为 [Umi-OCR v3.0.0 主程序](https://github.com/Dominic485649/UMI-OCR/releases/tag/v3.0.0) 提供 PP-OCRv6_medium 离线 OCR。公开发行只包含 CUDA 插件，不包含 CPU 与 PaddleOCR-VL 插件。

## 安装

先下载并完整解压主程序基础包，再把此 Release 的 CUDA 插件 `.tar.xz` 完整解压到主程序根目录，保留 `UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/` 路径。若软件已经运行，刷新插件列表再选择对应引擎。

`.tar.xz` 包含两层。若工具先输出 `.tar`，还需要解开内层归档。不要将整个归档仅放入插件目录而不解压。插件许可与对应源码保留在 `LICENSES/plugins/win32_PaddleOCRv6_CUDA/`，不会覆盖本体同名记录，请完整保留。

## 运行与兼容

- 本次支持 Windows 10/11 x64，需要兼容 CUDA 12.6 的 NVIDIA 显卡和驱动。
- 主程序和 CUDA worker 共用主程序随附的 Python 3.13.16，不额外安装系统 Python。
- 插件随附锁定的推理依赖和 CUDA/cuDNN 运行库，不需要系统 CUDA Toolkit。
- Paddle/NVIDIA 推理位于独立 worker 进程，不直接加载到界面宿主中。
- 不提供 CPU fallback。缺少 CUDA、模型或必要依赖时明确报告失败。
- 产品版本与 Host API 分开，第三方插件按公开接口与实际运行环境判断兼容性。
- 本分支旧版 CPU、CUDA、PaddleOCR-VL 插件不作为本版支持对象，请使用匹配的新实现。

默认首次识别时加载模型，之后复用工作进程。主程序支持预热与释放模型，设置变更的具体行为见同版使用文档。

CPU 与 CUDA 的识别效果一致，CPU 速度明显较慢，因此推荐公开提供的 CUDA 版本。PaddleOCR-VL 精度高，速度与 CPU 接近。CPU/VL 为单独的付费选项，用于回收开发与维护成本，联系 QQ 群 [【AWJ | Umi-OCR】](https://qm.qq.com/q/5XHoXCOU26)。

插件接口保持开放，你也可以自行开发和接入兼容实现，不设置付费身份或作者来源门禁。收费交付不取消接收者依法享有的开源许可权利。

本次不提供 Linux 发行包，后续考虑兼容 Linux。

## 来源与校验

维护者为 [Dominic485649](https://github.com/Dominic485649)。主程序源自 [hiroi-sora/Umi-OCR](https://github.com/hiroi-sora/Umi-OCR)，保留原作者版权与贡献署名。

插件随附适用的对应源码、构建与依赖锁、第三方许可和来源材料。NVIDIA 运行库、模型及第三方组件遵守各自适用条款，不宣称其权利已被转让给本项目。

归档使用 `.tar.xz`，当前工具链采用标准 LZMA2 默认压缩等级。最终资产名称、文件大小及 SHA-256 以此次重新构建、审计和验收后的清单为准。

- [主程序同版下载](https://github.com/Dominic485649/UMI-OCR/releases/tag/v3.0.0)
- [插件仓库](https://github.com/Dominic485649/UMI-OCR_plugins)
- [安装与运行说明](README_CUDA_PLUGIN.md)

本轮已通过真实 CUDA 批量图片、可搜索 PDF、无效 GPU、模型释放、HTTP OCR/二维码/文档链路和 CUDA-only 界面热切换验收。版本支持范围和限制见主仓库审查报告。
