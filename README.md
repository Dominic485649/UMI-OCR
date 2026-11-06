# Umi-OCR

[中文](README.md) · [English](README_en.md) · [日本語](README_ja.md)

面向 Windows 10/11 x64 的离线 OCR 工具。支持图片与 PDF 批量识别、截图 OCR、二维码、Markdown 结果、命令行和 HTTP 接口。

本 fork 由 [Dominic485649](https://github.com/Dominic485649) 维护，基于 [hiroi-sora/Umi-OCR](https://github.com/hiroi-sora/Umi-OCR)。保留原始版权、署名和[翻译贡献](docs/ACKNOWLEDGEMENTS.md)。

## 下载发行版

主程序与插件分别下载、独立版本。实际公开版本、附件和摘要以 Release 页面为准：

| 组件 | 下载入口 | 用途 |
| --- | --- | --- |
| 主程序 | [主程序 Releases](https://github.com/Dominic485649/UMI-OCR/releases) | 界面、任务、图片/PDF 处理，不内置 OCR 推理插件 |
| CUDA 插件 | [插件 Releases](https://github.com/Dominic485649/UMI-OCR_plugins/releases) | PP-OCRv6_medium 图片与 PDF OCR，包含配套推理模型 |
| PaddleVL 插件 | [插件 Releases](https://github.com/Dominic485649/UMI-OCR_plugins/releases) | PaddleOCR-VL 1.6 图片 OCR、结构化文档 HTTP 接口，模型按需获取 |

当前公开基线为主程序 **3.1.2**、CUDA **3.0.5**、PaddleVL **3.1.2**。本地 **3.1.3 候选**新增最简运行包和 PaddleVL 模型下载，尚不代表已公开发布，见[本轮说明](docs/RELEASE_3.1.3_DRAFT.md)。

主程序 Host API 为 **2.9**；CUDA 声明 `>=2.7,<3.0`，PaddleVL 声明 `>=2.9,<3.0`。兼容性不以产品版本号相同判断。运行环境为 Python 3.13.16、Qt 6.11.2；不需要安装系统 Python 或 CUDA Toolkit，但需要兼容 CUDA 12.6 的 NVIDIA 显卡与驱动。

## 安装与更新

1. 将主程序 `.tar.xz` **完整解压**到可写目录，不在压缩包内运行。
2. 将所需插件 `.tar.xz` 解压到**同一主程序根目录**，保留归档内的相对路径。
3. 启动 `Umi-OCR.exe`，在“全局设置 → 插件管理”中启用并选择模型。

```text
用户选择的安装目录/
├── Umi-OCR.exe
└── UmiOCR-data/
    └── plugins/
        ├── win32_PaddleOCRv6_CUDA/
        └── win32_PaddleOCRVL_1_6/
            └── model/                 按钮下载的模型
```

更新前正常退出软件，不覆盖运行中的目录。保留原配置、日志、任务资源和用户模型，不用新包的默认/测试配置覆盖它们。最简运行包不再额外附送顶层开发源码树、源码 ZIP 或内部审计报告；运行依赖、HTTPS 证书和必要许可仍保留。PaddleVL 原生闭包的完整性校验仍要求保留其原始来源材料，见[具体边界](SOURCE-CODE.md)。完整对应源码另行获取，普通使用不需要下载源码包。

旧版超大归档若以 `.tar.xz.001` 等分卷提供，须下载全部分卷及该 Release 配套的恢复工具，校验恢复后再解压；不要把单卷当成插件安装。[旧分卷恢复说明](build/windows/Restore-ReleaseArchive.ps1)

## PaddleVL 模型下载

在“插件管理 → PaddleOCR-VL 1.6”的**主 GGUF、视觉投影 GGUF、版面模型目录**行，文件选择按钮左侧提供“下载”。点击确认后通过官方 HTTPS 直链后台下载，显示进度，可取消。

- 主 GGUF 与视觉投影使用固定版本的 PaddlePaddle 官方模型，不自动选择量化版；合计约 **1.69 GiB**。
- PP-DocLayoutV3 约 **126 MiB**，仅完整文档解析需要。
- 目标固定为**当前用户实际安装的对应插件根目录 `model/`**，不是开发仓库、系统缓存或 `D:\AI\models`。
- 完整下载并通过大小、SHA-256 和内容校验后才回填模型路径；同名不匹配文件不覆盖。失败或只读目录会明确报错，不静默换目录。
- 原有手动导入继续可用，外部模型不搬迁、不修改。软件启动时不自动下载，模型与依赖就绪后仍可离线运行。

详见[模型获取说明](docs/MODEL_DOWNLOADS.md)。PaddleVL 文档解析默认通过 [HTTP](docs/http/api_document.md) 使用，默认界面不展示文档任务页；模型下载不改变 HTTP 的启用、监听或鉴权配置。

## 常用功能

- **图片 OCR**：粘贴、拖入或批量导入 JPEG、PNG、WebP、AVIF、JXL、JXR/WDP/HDP、BMP、TIFF；支持忽略区域、排版后处理和四点多边形预览。
- **文档 OCR**：处理 PDF 等文档，提取原有文字或执行 OCR，输出可搜索 PDF。
- **结果**：默认 Markdown，支持结构化 JSON、CSV 和适用的 PDF 输出；旧 TXT 设置兼容迁移。
- **模型设置**：统一选择后端、CUDA 设备、预热和自动清理；任务运行时的模型切换安全延后生效。
- **界面**：多语言、浅/深色与跟随系统、字体缩放、标签页、快捷键和托盘。
- **外部调用**：[命令行](docs/README_CLI.md)、[HTTP API](docs/http/README.md)。

[使用指南](docs/USER_GUIDE.md) · [PP-OCRv6 设置](docs/SETTINGS_PP_OCRV6.md) · [文档目录](docs/README.md)

## 开发与许可证

- [Windows 构建](docs/BUILD_WINDOWS_CUDA.md) · [插件 API](docs/PLUGIN_API.md)
- [独立源码交付](SOURCE-CODE.md) · [组合发行许可](LICENSES/COMBINED_DISTRIBUTION.md)

原 Umi-OCR 保留 MIT [LICENSE](LICENSE)；本 fork 新增/修改部分及包含 PyMuPDF 的组合发行遵循 [AGPL-3.0-or-later](COPYING)。收费交付或支持不限制接收者的开源许可权利；模型、NVIDIA 与其他第三方组件按各自条款使用，不新增模型或商标授权主张。

问题反馈：[Issues](https://github.com/Dominic485649/UMI-OCR/issues)。额外交付与支持可联系 QQ 群 [【AWJ | Umi-OCR】](https://qm.qq.com/q/5XHoXCOU26)。第三方插件开发和接入开放。

## 验证边界与历史

每次候选的实际验收以当轮记录为准。截图捕获、HDR、混屏/多屏继续 **NOT_RUN**；其它验证不能代替这些场景，也不要求补做截图测试。当前目标仅为 Windows x64。

[更新日志](CHANGE_LOG.md) · [历史发布与验收记录](docs/HISTORY.md)
