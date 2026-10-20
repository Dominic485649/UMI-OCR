# Umi-OCR v3.0.0

> 正式 Release 发布文案，标签为 `v3.0.0`，不设置 prerelease。

Umi-OCR v3.0.0 是基于 [hiroi-sora/Umi-OCR](https://github.com/hiroi-sora/Umi-OCR) 继续开发的版本，由 [Dominic485649](https://github.com/Dominic485649) 维护本分支，保留原作者、译者和第三方贡献署名。

## 本次公开提供什么

- **主程序基础包**：在 [Dominic485649/UMI-OCR](https://github.com/Dominic485649/UMI-OCR/releases/tag/v3.0.0) 下载。
- **CUDA OCR 插件**：在 [Dominic485649/UMI-OCR_plugins](https://github.com/Dominic485649/UMI-OCR_plugins/releases/tag/v3.0.0) 下载。
- **CPU 与 PaddleOCR-VL 插件**：不包含在此次公开资产中，作为单独的付费选项联系作者。

基础包提供界面、插件宿主、截图、任务管理、图片与 PDF 处理、二维码和 HTTP/命令行调用。安装 CUDA 插件后使用 PP-OCRv6_medium 离线文字识别。基础包自身不包含 OCR 推理后端。

## 本次版本内容

- 主程序和 CUDA 推理进程共用 Python 3.13.16，保留 PySide6/Qt 6.11.2 与已经锁定的推理依赖，不迁移 Python。
- CUDA 推理位于独立 worker 进程中，宿主不直接加载 Paddle/NVIDIA 推理栈。进程隔离不等于独立安装另一份 Python。
- 设置在现有任务队列全部完成后应用；暂停的队列仍视为未完成，须先恢复或取消，再等待队列结束后切换。切换时点按整个队列是否完成判断，不按当前单张图片是否结束判断。
- 插件启用状态与列表、界面语言和 HTTP 服务配置支持刷新。
- 截图、批量图片与 PDF OCR 保留。Windows HDR 捕获、文本多边形、图片缩放、模型预热与空闲释放沿用当前实现。
- 修复任务队列收尾时新请求可能滞留的问题；后端或回调异常会结束错误队列，并允许后续任务继续。
- 修复共享模型服务被并发初始化多次的问题，健康检查与启动操作复用同一个惰性实例。
- 修正 HTTP 跨域预检，校验请求类型与文档上传/下载路径；本机命令接口拒绝外部网页来源调用。
- 应用版本与插件宿主接口版本分开。第三方插件按公开接口、平台和依赖条件判断兼容性，不设置收费身份或作者来源门禁。
- 关于、项目反馈、下载与插件入口明确区分本分支、CUDA 插件仓库和原始项目。
- 发行归档使用 `.tar.xz`。当前工具链采用标准 LZMA2 默认压缩等级，不将其描述为 Fast LZMA2。

本轮已验证基础界面与真实 Windows 托盘、CUDA OCR、批量图片、可搜索 PDF、HTTP/命令行、二维码及文档上传/下载/清理链路。详细边界见 [审查报告](RELEASE_3.0.0_REVIEW.md)，资产大小和 SHA-256 以 Release 附件清单为准。

## 运行与安装

- 本次面向 Windows 10/11 x64。
- 使用 CUDA OCR 需要兼容 CUDA 12.6 的 NVIDIA 显卡和驱动。
- CUDA 运行库由插件提供，不需要额外安装系统 CUDA Toolkit。
- CUDA 不可用时明确返回错误，不静默回退到 CPU。
- 本次不提供 Linux 发行包，后续会考虑兼容 Linux。

先完整解压主程序的 `.tar.xz`，再将 CUDA 插件归档解压到主程序根目录，保留插件归档中的相对路径。安装后应存在：

```text
Umi-OCR.exe
UmiOCR-data/
  runtime/python.exe
  plugins/win32_PaddleOCRv6_CUDA/umi-plugin.json
```

`.tar.xz` 包含外层 xz 压缩和内层 tar 归档。若解压工具先输出 `.tar`，还需要将它完整解包。不要只解压外层或仅复制启动器。

首次启动时模型默认按需加载。需要时可以手动预热。离线识别不需要在线 OCR 服务，显卡驱动仍需由用户正确安装。

## 升级与插件兼容

建议解压到新的目录，不将新文件逐个覆盖到旧运行环境中。迁移设置前先备份；旧插件设置或页面不代表对应后端已经安装。

本分支的旧版 CPU、CUDA 和 PaddleOCR-VL 插件不作为本版支持对象，请使用匹配的新实现。其他第三方插件继续依据公开接口和实际运行环境判断兼容性。产品主版本变化不代表把所有插件的接口主版本一起改为相同数字。

插件接口开放。你可以自行开发、接入或替换兼容插件，也可以选择其他实现；CPU/VL 的收费安排不会成为第三方插件的使用门禁。

## 为什么推荐 CUDA，为什么有付费选项

CPU 和 CUDA 版本的识别效果一致，但 CPU 速度明显较慢。有兼容的 NVIDIA 显卡时，我推荐使用公开提供的 CUDA 插件，速度、吞吐和交互体验的提升很大。

PaddleOCR-VL 精度高，速度与 CPU 接近，适合更看重精度或结构化文档处理的需求。它不属于此次公开下载内容。

CPU 和 PaddleOCR-VL 作为单独的付费选项，是为了回收一部分开发、测试、维护和支持成本。我也要吃饭，希望这些投入可以持续。不是要求大家必须购买，免费的 CUDA 方案仍是推荐选择。

有需要请加入 QQ 群 [【AWJ | Umi-OCR】](https://qm.qq.com/q/5XHoXCOU26) 联系作者。收费交付不取消接收者依法享有的开源许可权利。

## 许可证、来源与校验

原始 Umi-OCR 的 MIT 许可与 hiroi-sora 版权保留。本分支新增和修改部分按 AGPL-3.0-or-later 提供；组合发行许可、第三方运行库和模型的适用条款以随包声明为准，不宣称拥有第三方模型、名称或商标权利。

最终资产随附适用的对应源码、构建与依赖来源信息，以及 SHA-256 校验文件。发布检查覆盖基础包与 CUDA 插件的完整性、解压安装和源码闭包，并排除未发布 CPU/VL 产品、用户配置、个人文档、缓存及助手配置与会话。

- [主程序 README](../README.md)
- [CUDA 插件说明](README_CUDA_PLUGIN.md)
- [HTTP 接口](http/README.md)
- [命令行调用](README_CLI.md)
- [插件接口与兼容说明](PLUGIN_API.md)
- [组合发行许可证说明](../LICENSES/COMBINED_DISTRIBUTION.md)
