# Umi-OCR CUDA 插件 v3.0.4 启动修复候选

CUDA 插件仓库为 [Dominic485649/UMI-OCR_plugins](https://github.com/Dominic485649/UMI-OCR_plugins)。本仓库提供 CUDA 源码与必要构建、测试、依赖锁和许可材料。

**当前准备状态（2026-10-24）**：本轮只准备 CUDA 插件 `3.0.4`，配套已发布的主程序 `3.0.3`，不要求两个产品版本相同，不重编或改写本体。3.0.4 的候选、启动验收与文案仍须按当次实际记录交审；这里不声称已验收、已创建标签或已发布，正式发行门禁仍保持原规则与 BLOCK。见 [3.0.4 CUDA 文案](RELEASE_CUDA_3.0.4_DRAFT.md)及[本轮审查范围](RELEASE_CUDA_3.0.4_REVIEW.md)。

本插件为 Umi-OCR 提供基于 PaddlePaddle GPU 的 PP-OCRv6_medium 离线文字识别。维护者为 [Dominic485649](https://github.com/Dominic485649)，主程序基于 [hiroi-sora 的 Umi-OCR](https://github.com/hiroi-sora/Umi-OCR)。原始作者与第三方贡献署名保留。

## 下载与安装

| 当前已公开的内容 | 下载位置 |
| --- | --- |
| Umi-OCR 3.0.3 主程序基础包 | [主仓库 v3.0.3 Release](https://github.com/Dominic485649/UMI-OCR/releases/tag/v3.0.3) |
| CUDA 3.0.3 插件 | [插件仓库 v3.0.3 Release](https://github.com/Dominic485649/UMI-OCR_plugins/releases/tag/v3.0.3) |

上述链接是现有公开版本，不代表新插件 3.0.4 已经公开。公开资产仅包含基础包和 CUDA 插件，不提供 CPU 或 PaddleOCR-VL 下载资产。

1. 将主程序基础包完整解压到新的目录。
2. 将兼容该本体 Host API 的 CUDA 插件 `.tar.xz` 完整解压到同一主程序根目录，保留归档相对路径；不要覆盖正在运行的安装。
3. 确认 `UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/umi-plugin.json` 和插件自己的 `UmiOCR-CudaWorker.exe` 存在。新入口随 3.0.4 候选源码构建，不从旧 Python EXE 改写获得。
4. 启动 `Umi-OCR.exe`。主程序产品版本仍为 3.0.3，插件页面显示其独立版本；兼容性按 Host API 范围而非两个产品版本相等判断。

`.tar.xz` 是外层 xz 和内层 tar。某些工具需要分别解压，不要只得到一个 `.tar` 文件就结束。插件许可与对应源码保存在 `LICENSES/plugins/win32_PaddleOCRv6_CUDA/`，安装时不要丢弃；这个独立目录避免覆盖主程序同名材料。

## 运行要求与执行边界

- 新 worker 入口要求 Windows 10 1903+ / Windows 11 x64，并需兼容 CUDA 12.6 的 NVIDIA 显卡与驱动；不能满足原生 UTF-8 进程条件时明确拒绝启动。
- Python 3.13.16 使用主程序随附的原始 runtime DLL，不需要额外安装系统 Python。
- PaddleOCR、PaddleX、PaddlePaddle GPU 与 CUDA/cuDNN 依赖及模型保持既有锁定输入，本轮不升级、不下载或更换。
- 不需要安装系统 CUDA Toolkit，但这不等于不需要显卡驱动。
- 源码构建的 `UmiOCR-CudaWorker.exe` 在实际加载 Python/Paddle 的同一进程声明 `activeCodePage=UTF-8`；仅设置 Python 标准流编码不足以修复传统代码页下的原生模型路径读取。
- 不修改 Windows 全局代码页、不修补原版 Python EXE、不搬迁模型；主程序不直接加载 Paddle/NVIDIA 推理栈，进程间仍使用 JSON-lines。
- 不提供 CPU fallback，缺少 CUDA 或初始化失败时明确报错。
- 默认在首次识别时加载模型，可以通过主程序设置和托盘操作预热或释放。

本次不发行 Linux 版本，后续会考虑 Linux 兼容。

## 版本与验收范围

插件产品版本为 `3.0.4`，本体产品版本保留 `3.0.3`。Host API 仍为 `2.8`，插件兼容范围保持 `>=2.7,<3.0`；产品版本和 Host API 不是同一字段。

本轮实际回归仅覆盖主程序/worker 就绪、CUDA 自检、模型初始化与正常退出；不会执行图片、批量或 PDF OCR 工作流，也不将历史 E2E PASS 冒充新版本实测。启动记录不是完整 OCR 验收或公开发行授权，最终结果、未测项目及门禁状态以本轮审计和用户审查为准。

其他插件依据公开接口、平台、Python ABI 与依赖约束判定兼容性，不设置作者身份或付费来源门禁。第三方插件开发、接入和替换保持开放；也可以自行开发兼容的 OCR 或文档插件，不必购买作者提供的其他实现。

## CPU、CUDA 与 PaddleOCR-VL

CPU 与 CUDA 的识别效果一致，CPU 的速度明显较慢。有兼容 NVIDIA 显卡时推荐 CUDA，日常截图、批量图片和 PDF 识别的速度与交互体验提升很大。

PaddleOCR-VL 精度高，速度与 CPU 接近，适合更看重精度或结构化文档处理的需求。CPU 与 PaddleOCR-VL 是单独的付费选项，不包含在此次公开发行中。

开发、测试、维护和支持都有成本，我也要吃饭，希望通过可选交付回收一部分投入。这不是要求大家必须购买，也不会限制第三方兼容插件。收费不会取消接收者依法享有的开源许可权利。

联系作者：QQ 群 [【AWJ | Umi-OCR】](https://qm.qq.com/q/5XHoXCOU26)。

## 源码、构建与许可

插件适配器、原生 worker 入口的 C++/CMake/manifest/资源、构建入口、依赖锁、补丁、启动测试与第三方声明须随对应源码材料提供。公开构建不应依赖本地未发布的 CPU/VL 项目，不能通过搬运整个收费插件项目来补齐 CUDA 交付。

原始 Umi-OCR MIT 声明与 hiroi-sora 版权保留。本分支新增和修改部分按 AGPL-3.0-or-later 提供。CUDA/cuDNN 和模型不因进程隔离而自动变成 AGPL 覆盖或免除其适用条款，具体以随包许可与来源声明为准，不新增模型、名称或商标授权主张。

- [当前 Windows CUDA 构建说明](BUILD_WINDOWS_CUDA.md)
- [插件接口](PLUGIN_API.md)
- [组合发行许可说明](../LICENSES/COMBINED_DISTRIBUTION.md)
- [主程序已公开的 3.0.3 Release](https://github.com/Dominic485649/UMI-OCR/releases/tag/v3.0.3)
