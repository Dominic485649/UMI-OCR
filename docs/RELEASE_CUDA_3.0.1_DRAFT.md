# Umi-OCR CUDA OCR 插件 v3.0.1：UTF-8 通信修复

> v3.0.1 正式发布说明。

本版为 [Umi-OCR v3.0.1 主程序](https://github.com/Dominic485649/UMI-OCR/releases/tag/v3.0.1) 提供 PP-OCRv6_medium 离线 OCR，重点修复独立工作进程的编码边界。

## 本次修复

- 启动 CUDA worker 时显式启用 UTF-8 模式，并设置独立的 UTF-8 子进程环境，避免系统代码页或继承的 GBK 配置影响通信。
- worker 入口统一标准输入输出编码，保留标准错误日志与 JSON 通信的分离，中文和非 BMP 字符不再依赖本机默认编码。
- 保持独立进程、按需加载和工作进程复用方式。推理依赖、CUDA 12.6 运行库和模型精度不变，不增加 CPU fallback。

## 安装与运行

归档文件：`Umi-OCR-Plugin_GPU-OCR_v3.0.1_Windows_x64_CUDA12.6.tar.xz`

先完整解压本版主程序基础包，再将本插件的 `.tar.xz` 完整解压到同一个主程序根目录，保留 `UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/` 的相对路径。建议同时更新主程序与插件，以包含两侧的编码修复。

如果解压工具先输出 `.tar`，请继续解开内层归档。插件许可证及对应源码记录位于 `LICENSES/plugins/win32_PaddleOCRv6_CUDA/`，不会覆盖主程序的同名记录，请完整保留。

- 支持 Windows 10/11 x64，需要兼容 CUDA 12.6 的 NVIDIA 显卡和驱动。
- 与主程序共用随附的 Python 3.13.16，不需要另装 Python 或系统 CUDA Toolkit。
- CUDA、模型或必要依赖不可用时明确报错，不静默回退 CPU。
- 此次公开资产不包含 CPU 或 PaddleOCR-VL 插件。

## 验证、来源与许可

本轮已通过工作进程 UTF-8 协议、真实 CUDA OCR/PDF、模型释放、无效 GPU、HTTP/命令行与 CUDA-only 界面热切换回归。新 GPU 工作流记录绑定本轮适配器源码、运行时锁和测试脚本。

归档解压安装结果与 SHA-256 以随附校验记录为准。对应源码在本仓库 `v3.0.1` 标签公开，归档另附源码镜像、源码 ZIP 和来源记录。

维护者确认实际 HDR 捕获成功，并在了解本轮尚未覆盖的混合屏及完整人工验收场景后确认发布。该确认不是未测场景的测试通过记录，详见 [本版验收范围与发布决定](https://github.com/Dominic485649/UMI-OCR_plugins/blob/v3.0.1/docs/RELEASE_3.0.1_ACCEPTANCE.md)。

维护者为 [Dominic485649](https://github.com/Dominic485649)。主程序源自 [hiroi-sora/Umi-OCR](https://github.com/hiroi-sora/Umi-OCR)，保留原作者版权与贡献署名。

归档随附适用的对应源码、构建与依赖锁、第三方许可和来源材料。模型、NVIDIA 运行库和其他组件遵守各自适用条款，不宣称其权利已被转让或另获商标授权。
