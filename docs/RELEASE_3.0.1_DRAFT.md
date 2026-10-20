# Umi-OCR v3.0.1：启动与 UTF-8 修复

> v3.0.1 正式发布说明。

v3.0.1 是针对 v3.0.0 的修复版本，重点解决可选插件未安装时的启动报错，以及编码受 Windows 系统代码页影响的问题。

## 修复内容

- 修复未安装结构化文档插件时弹出 `Global 处理配置项异常：document.api枚举列表为空。` 的问题。
- 修复基础包没有安装任何 OCR 后端时的同类空枚举报错。插件停用或移除后可以正确清理失效接口，重新启用后恢复实际可用选项，原有非法配置校验仍然保留。
- 启动器显式启用 UTF-8 模式，宿主标准输入输出、预配置读写及 CUDA worker 通信统一使用 UTF-8，避免仅设置环境变量在隔离模式下失效。
- 保持 CUDA 独立工作进程、按需加载和明确失败的行为，不增加静默 CPU 回退。本次不升级 Python、Qt、推理依赖或模型精度。

## 下载与安装

本次仍提供独立的主程序基础包和 CUDA OCR 插件：

| 组件 | 归档文件 |
| --- | --- |
| 主程序基础包 | `Umi-OCR_v3.0.1_Windows_x64.tar.xz` |
| CUDA OCR 插件 | `Umi-OCR-Plugin_GPU-OCR_v3.0.1_Windows_x64_CUDA12.6.tar.xz` |

- [主程序下载](https://github.com/Dominic485649/UMI-OCR/releases/tag/v3.0.1)
- [CUDA 插件下载](https://github.com/Dominic485649/UMI-OCR_plugins/releases/tag/v3.0.1)

请先完整解压基础包，再把 CUDA 插件完整解压到同一个主程序根目录，保留归档中的相对路径。建议在新目录中安装，并同时使用本版基础包与插件。只更新其中一个包不会包含另一组件的编码修复。

`.tar.xz` 包含外层 xz 和内层 tar。若工具先生成 `.tar` 文件，还需要继续解包，直到根目录出现 `Umi-OCR.exe`。不要仅复制启动器。

基础包自身不含 OCR 推理后端。公开 CUDA 插件使用 PP-OCRv6_medium；此次资产不包含 CPU 或 PaddleOCR-VL 插件。

## 运行要求与验证

- Windows 10/11 x64。CUDA OCR 需要兼容 CUDA 12.6 的 NVIDIA 显卡和驱动。
- Python 3.13.16、PySide6/Qt 6.11.2 保持不变。运行库随包提供，不需要另装 Python 或系统 CUDA Toolkit。
- CUDA 不可用时明确报错，不静默切换 CPU。

本轮已通过零后端启动、中文与 emoji 编码、真实 CUDA OCR、批量图片与可搜索 PDF、HTTP/命令行、插件刷新、界面热切换及 Windows 系统托盘验收。GPU 工作流记录绑定本轮适配器源码与运行时锁，不沿用旧版记录。

归档解压安装结果与 SHA-256 以随附校验记录为准。合成 HDR shader 与坐标测试通过，维护者确认实际 HDR 捕获成功。混合 HDR/SDR、多屏 DPI、负坐标及完整人工视觉/选区清单未在本轮全部验证，维护者在了解此覆盖限制后确认发布；不将这些未测场景标记为通过。详见 [本版验收范围与发布决定](https://github.com/Dominic485649/UMI-OCR/blob/v3.0.1/docs/RELEASE_3.0.1_ACCEPTANCE.md)。

## 来源与许可

本分支由 [Dominic485649](https://github.com/Dominic485649) 维护，源自 [hiroi-sora/Umi-OCR](https://github.com/hiroi-sora/Umi-OCR)，保留原作者、译者和贡献者署名。

原始 MIT 许可保留；本分支新增和修改部分遵循 AGPL-3.0-or-later。归档随附适用的对应源码、构建与依赖锁、第三方许可和来源材料。模型及 NVIDIA 运行库按各自适用条款分发，不主张其模型、名称或商标权利。
