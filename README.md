# Umi-OCR 3.0.3 合并修复与交付说明

主仓库：https://github.com/Dominic485649/UMI-OCR

**3.0.3** 整合 3.0.2 的批量文档动态队列、拖拽排序/移除、导入、文档右键重新 OCR、忽略区域、输出收尾和枚举热配置等设置修复，以及旧源码原地刷新工具停用和组合候选 CUDA 源码串包修复。

从组合候选生成 CUDA overlay 时，必须使用插件自己的对应源码、版本、快照和 provenance（来源记录），不再回退到宿主根目录；缺少明确插件来源的旧组合候选会被拒绝并要求重新装配，不自动猜源。本次不升级识别引擎、模型或依赖。

**日期冻结状态（2026-10-22，本轮 fresh 重建开始前）**：历史 R2 已完成基础/组合、真实热 GUI、Windows 托盘、HTTP/正常退出、GPU、归档重装及源码/模型核验，后来已交付程序和文案并获推送同意；但完整人工/HDR、原生 Explorer/鼠标、单件重新 OCR 全轮及混屏覆盖未完成。两个公开 `v3.0.3` 源码标签已存在，3.0.3 binary Release 尚未创建、上传或公开；下方保留此截点有效的 `v3.0.1` 二进制下载链接。

本轮计划修正正式门禁接线并在新目录 non-`LocalCandidate`、`-SkipArchive` prepare，此截点尚未构建，不继承 R2 的 PASS、哈希或审查同意。须先完成真实本地验收、固定实际 base/GPU overlay source/payload，再由用户审查本轮实际程序和两份文案；明确同意后才更新 main/tag，随后执行 fresh 正式门禁、受限 finalize 和正式归档重装/发布核验。允许替换标签不等于已同意新程序。

交付契约与后续证据归属见 [SOURCE-CODE.md](SOURCE-CODE.md)、[3.0.3 验收/冻结状态](docs/RELEASE_3.0.3_ACCEPTANCE.md)及[审查要求](docs/RELEASE_3.0.3_REVIEW.md)；两份文案为 [主程序草稿](docs/RELEASE_3.0.3_DRAFT.md)和 [CUDA 插件草稿](docs/RELEASE_CUDA_3.0.3_DRAFT.md)。[3.0.2 本地交付说明](docs/RELEASE_3.0.2_LOCAL.md)保留为历史，不回填新 PASS 修改冻结源码。

作者与来源：Dominic485649（本 fork 作者与维护者）；[hiroi-sora](https://github.com/hiroi-sora/Umi-OCR)（原 Umi-OCR 作者及原始版权来源）。

<p align="left">
    <span>
        <b>中文</b>
    </span>
    <span> • </span>
    <a href="README_en.md">
        English
    </a>
    <span> • </span>
    <a href="README_ja.md">
        日本語
    </a>
</p>

<p align="center">
  <a href="https://github.com/Dominic485649/UMI-OCR">
    <img width="200" height="128" src="https://tupian.li/images/2022/10/27/icon---256.png" alt="Umi-OCR">
  </a>
</p>

<h1 align="center">Umi-OCR 文字识别工具</h1>

<p align="center">
  <a href="https://github.com/Dominic485649/UMI-OCR">
    <img src="https://img.shields.io/github/v/release/Dominic485649/UMI-OCR?style=flat-square" alt="Umi-OCR">
  </a>
  <a href="#下载发行版">
    <img src="https://img.shields.io/github/downloads/Dominic485649/UMI-OCR/total?style=flat-square" alt="downloads">
  </a>
  <a href="https://github.com/Dominic485649/UMI-OCR">
    <img src="https://img.shields.io/github/stars/Dominic485649/UMI-OCR?style=flat-square" alt="stars">
  </a>
  <a href="https://github.com/Dominic485649/UMI-OCR/forks">
    <img src="https://img.shields.io/github/forks/Dominic485649/UMI-OCR?style=flat-square" alt="forks">
  </a>
  <a href="https://hosted.weblate.org/engage/umi-ocr/">
    <img src="https://hosted.weblate.org/widget/umi-ocr/svg-badge.svg" alt="翻译状态">
  </a>
</p>

<div align="center">
  <h3>
    <a href="#目录">
      使用说明
    </a>
    <span> • </span>
    <a href="#下载发行版">
      下载地址
    </a>
    <span> • </span>
    <a href="CHANGE_LOG.md">
      更新日志
    </a>
    <span> • </span>
    <a href="https://github.com/Dominic485649/UMI-OCR/issues">
      提交Bug
    </a>
  </h3>
</div>
<br>

<div align="center">
  <strong>开源、可批量的离线 OCR 软件</strong><br>
  <sub>Umi-OCR 3.0.3：面向 Windows 10/11 x64；交付状态见上方日期记录</sub>
</div><br>

- **公开版本**：基础程序与 CUDA 插件免费公开提供；第三方插件开发与接入开放。
- **方便**：解压即用，离线运行，无需网络。
- **高效**：默认使用离线 PP-OCRv6_medium 高精度流水线，统一识别多语言文字。
- **灵活**：支持命令行、HTTP接口等外部调用方式。
- **功能**：HDR截图OCR / 批量OCR / PDF识别 / 二维码 / 可选结构化文档解析

<p align="center"><img src="https://tupian.li/images/2023/11/19/65599097ab5f4.png" alt="1-标题-1.png" style="width: 80%;"></p>

![1-标题-2.png](https://tupian.li/images/2023/11/19/6559909fdeeba.png)

## 目录

- [截图识别](#截图OCR)
  - [排版解析](#文本后处理) - 识别不同排版，按正确顺序输出文字
- [批量识别](#批量OCR)
  - [忽略区域](#忽略区域) - 排除截图水印处的文字
- [二维码](#二维码) 支持扫码或生成二维码图片
- [文档识别](#文档识别) 从PDF扫描件中提取文本，或转为双层可搜索PDF
- [全局设置](#全局设置)
- [PP-OCRv6 设置说明](docs/SETTINGS_PP_OCRV6.md)
- [命令行调用](docs/README_CLI.md)
- [HTTP接口](docs/http/README.md)
- [构建 Windows CUDA 版](docs/BUILD_WINDOWS_CUDA.md)

## 使用源码

开发者请务必阅读 [构建项目](#构建项目) 。

### 本 fork 的许可证

原 Umi-OCR 的 MIT `LICENSE`、hiroi-sora 版权与署名完整保留。该 fork 新增或修改的代码按 [AGPL-3.0-or-later](COPYING) 发布；因发行包组合了 PyMuPDF，完整发行包也按 AGPL-3.0-or-later 发布。发行包包含对应源码、构建脚本、依赖锁和第三方声明。可以收费交付源码、构建产物、更新或支持，但不得限制接收者复制、修改或再分发其获得的 AGPL 覆盖内容。详见 [组合发行许可证说明](LICENSES/COMBINED_DISTRIBUTION.md)。

PDF 预览、PDF 页面读取、文档 OCR，以及单层和双层可搜索 PDF 输出均保留，并通过 PyMuPDF 的 `fitz` 接口实现。

## 下载发行版

**2026-10-22 本轮重建开始前的下载状态：** 已有 `v3.0.3` 源码标签，但没有 3.0.3 binary Release；以下保留 **3.0.1 Windows x64 正式 Release**（`v3.0.1`）的有效二进制链接，不表示新程序已经发布，也不替换历史 3.0.2 候选身份。基础程序与 CUDA 插件分别下载，CPU 与 PaddleOCR-VL 不包含在公开资产中。

- **基础程序**：[主仓库 v3.0.1 Release](https://github.com/Dominic485649/UMI-OCR/releases/tag/v3.0.1)。
- **CUDA 插件**：[插件仓库 v3.0.1 Release](https://github.com/Dominic485649/UMI-OCR_plugins/releases/tag/v3.0.1)。

配套文档：
- [3.0.1 主程序 Release 说明](docs/RELEASE_3.0.1_DRAFT.md)
- [CUDA 插件 Release 说明](docs/RELEASE_CUDA_3.0.1_DRAFT.md)
- [CUDA 插件说明（保留的 3.0.2 准备文档）](docs/README_CUDA_PLUGIN.md)

共用运行时为 Python 3.13.16、Qt 6.11.2。归档采用 `.tar.xz`，当前使用标准 LZMA2 默认压缩等级。完整解压基础程序，再将 CUDA 插件解压到主程序根目录；需要兼容 CUDA 12.6 的 NVIDIA 显卡与驱动，不需要系统 CUDA Toolkit。

CPU 与 CUDA 的识别效果相同，CPU 速度较慢；PaddleOCR-VL 精度高，速度接近 CPU。CPU 和 PaddleOCR-VL 插件单独收费提供，请联系 QQ 群【AWJ | Umi-OCR】：https://qm.qq.com/q/5XHoXCOU26 。收费用于覆盖开发、测试和维护成本，作者也需要生活并回收持续投入；建议先使用免费的 CUDA 版本，不要求购买收费插件。

## 开始使用

正式发行包提供可直接运行的目录。请先完整解压归档，不要在压缩包内运行启动器。

本软件无需安装，点击完整程序目录中的 `Umi-OCR.exe` 即可启动。

模型默认在首次使用时加载；用户也可选择主窗口显示后在后台立即或延迟预热。首次加载会建立 CUDA 上下文并把模型放到所选显卡，之后保持驻留并复用。托盘菜单可手动预热或清理模型；也可在全局设置中按系统内存占用或空闲时间自动清理。Python、OpenCV 和模型元数据仍会占用少量系统内存，这是正常现象。

遇到任何问题，请提 [Issue](https://github.com/Dominic485649/UMI-OCR/issues) ，我会尽可能帮助你。

## 界面语言

Umi-OCR 支持的界面多国语言。在第一次打开软件时，将会按照你的电脑的系统设置，自动切换语言。

如果需要手动切换语言，请参考下图，`全局设置`→`语言/Language` 。

<p align="center"><img src="https://tupian.li/images/2023/11/19/65599c3f9e600.png" alt="1-标题-1.png" style="width: 80%;"></p>

## 标签页

Umi-OCR v3 由一系列灵活好用的**标签页**组成。您可按照自己的喜好，打开需要的标签页。

标签栏左上角可以切换**窗口置顶**。右上角能够**锁定标签页**，以防止日常使用中误触关闭标签页。

### 截图OCR

<p align="center"><img src="https://tupian.li/images/2023/11/19/65599097aba8e.png" alt="2-截图-1.png" style="width: 80%;"></p>

**截图OCR**：打开这一页后，就可以用快捷键唤起截图，识别图中的文字。
- 左侧的图片预览栏，可直接用鼠标划选复制。
- 右侧的识别记录栏，可以编辑文字，允许划选多个记录复制。
- 也支持在别处复制图片，粘贴到Umi-OCR进行识别。
- Windows HDR 屏幕优先使用 WGC/D3D11 浮点捕获并映射为 sRGB；单屏初始化失败时只回退该屏的普通 SDR 截图。详见 [HDR 测试与校准](docs/HDR_TEST_WINDOWS.md)。
- 识别叠加层保留 OCR 的四点多边形和旋转方向，复杂排版不再压成轴对齐矩形；滚轮缩放以鼠标所在图像位置为锚点。

#### 文本后处理

<p align="center"><img src="https://tupian.li/images/2023/11/19/6559909f3e378.png" alt="2-截图-2.png" style="width: 80%;"></p>

关于 **OCR文本后处理 - 排版解析方案**： 可以整理OCR结果的排版和顺序，使文本更适合阅读和使用。预设方案：
- `多栏-按自然段换行`：适合大部分情景，自动识别多栏布局，按自然段规则进行换行。
- `多栏-总是换行`：每段语句都进行换行。
- `多栏-无换行`：强制将所有语句合并到同一行。
- `单栏-按自然段换行`/`总是换行`/`无换行`：与上述类似，不过 不区分多栏布局。
- `单栏-保留缩进`：适用于解析代码截图，保留行首缩进和行中空格。
- `不做处理`：OCR引擎的原始输出，默认每段语句都进行换行。

上述方案，均能自动处理横排和竖排（从右到左）的排版。（竖排文字还需要OCR引擎本身支持）

---

### 批量OCR

<p align="center"><img src="https://tupian.li/images/2023/11/19/655990a2511e0.png" alt="3-批量-1.png" style="width: 80%;"></p>

**批量OCR**：这一页用于批量导入本地图片进行识别。
- 支持格式：`jpg, jpe, jpeg, jfif, png, avif, webp, jxl, jxr, wdp, hdp, bmp, tif, tiff`。AVIF 固定使用 dav1d 解码，所有输入都会转换为 PP-OCR 可接受的连续 BGR 8-bit 图像。
- 保存识别结果的支持格式：`txt, jsonl, md, csv(Excel)`。
- 与截图OCR一样，支持`文本后处理`功能，整理OCR文本的排版和顺序。
- 没有数量上限，可一次性导入几百张图片进行任务。
- 支持任务完成后自动关机/待机。
- 如果要识别像素超大的长图或大图，请调整：**页面的设置→文字识别→限制图像边长→【调高数值】**。
- 拥有特殊功能 `忽略区域` 。

#### 忽略区域

<p align="center"><img src="https://tupian.li/images/2023/11/19/6559911d28be7.png" alt="3-批量-2.png" style="width: 80%;"></p>

关于 **OCR文本后处理 - 忽略区域**： 批量OCR中的一种特殊功能，适用于排除图片中的不想要的文字。
- 在批量识别页的右栏设置中可进入忽略区域编辑器。
- 如上方样例，图片顶部和右下角存在多个水印 / LOGO。如果批量识别这类图片，水印会对识别结果造成干扰。
- 按住右键，绘制多个矩形框。这些区域内的文字将在任务中被忽略。
- 请尽量将矩形框画得大一些，完全包裹住水印所有可能出现的位置。
- 注意，只有处于忽略区域框内部的整个文本块（而不是单个字符）会被忽略。如下图所示，黄色边框的深色矩形是一个忽略区域。那么只有`key_mouse`才会被忽略。`pubsub_connector.py`、`pubsub_service.py` 这两个文本块得以保留。
<p align="center"><img src="https://tupian.li/images/2024/05/30/66587bf03ae15.png" alt="忽略区域范围示例.png" style="width: 80%;"></p>

---

### 文档识别

<p align="center"><img src="https://github.com/hiroi-sora/Umi-OCR/assets/56373419/fc2266ee-b9b7-4079-8b10-6610e6da6cf5" alt="" style="width: 80%;"></p>

**文档识别**：
- 支持格式：`pdf, xps, epub, mobi, fb2, cbz`。
- 对扫描件进行OCR，或提取原有文本。可输出为 **双层可搜索PDF** 。
- 支持设定 **忽略区域** ，可用于排除页眉页脚的文字。
- 可设置任务完成后 **自动关机/休眠** 。

---

### 二维码

<p align="center"><img src="https://tupian.li/images/2023/11/19/655991268d6b1.png" alt="4-二维码-1.png" style="width: 80%;"></p>

**扫码**：
- 截图/粘贴/拖入本地图片，读取其中的二维码、条形码。
- 支持一图多码。
- 支持19种协议，如下：

`Aztec`,`Codabar`,`Code128`,`Code39`,`Code93`,`DataBar`,`DataBarExpanded`,`DataMatrix`,`EAN13`,`EAN8`,`ITF`,`LinearCodes`,`MatrixCodes`,`MaxiCode`,`MicroQRCode`,`PDF417`,`QRCode`,`UPCA`,`UPCE`

<p align="center"><img src="https://tupian.li/images/2023/11/19/6559911cda737.png" alt="4-二维码-2.png" style="width: 80%;"></p>

**生成码**：
- 输入文本，生成二维码图片。
- 支持19种协议和**纠错等级**等参数。

---

### 全局设置

<p align="center"><img src="https://tupian.li/images/2023/11/19/655991252e780.png" alt="5-全局设置-1.png" style="width: 80%;"></p>

**全局设置**：在这里可以调整软件的全局参数。常用功能如下：
- 一键添加快捷方式或设置开机自启。
- 更改界面**语言**。Umi支持繁中、英语、日语等语言。
- 切换界面**主题**。新增“跟随系统”，可分别指定系统浅色和深色时使用的主题；“中性深色”默认背景为 `rgb(24, 24, 24)`。
- 调整界面**文字的大小**和**字体**。
- 配置 PP-OCRv6 预设、辅助模型、长边限制、批量大小、阈值和 CUDA 设备。识别模型固定为 PP-OCRv6_medium，不提供无实际作用的识别语言包选项；界面语言切换不受影响。
- 高级设置默认折叠，仅保留确实生效的性能与 HDR 校准项；旧开发工具和渲染器选择已移除。
- Windows 版固定使用 Qt6 RHI/D3D11 硬件渲染；HDR SDR 白点和峰值亮度默认读取系统，只有实测映射不准确时才手动校准。
- 托盘图标始终显示：单击截图，双击打开主窗口；右键菜单可打开全局设置、预热/清理 OCR 模型、打开主窗口或退出 Umi-OCR。
- 模型后台可选启动后延迟 `0–60` 分钟预热或首次使用时加载；自动清理可关闭、在系统内存超过 90% 时每 6 分钟检查，或在空闲 `5–120` 分钟后执行。OCR 任务运行时不会清理。

所有 OCR 选项、默认值及质量/耗时/内存影响见 [PP-OCRv6 设置说明](docs/SETTINGS_PP_OCRV6.md)。

## 调用接口：

- [命令行手册](docs/README_CLI.md)
- [HTTP接口手册](docs/http/README.md)

---

## 关于项目结构

### 仓库：

- [主仓库](https://github.com/Dominic485649/UMI-OCR) 👈
- [公开 CUDA 插件仓库](https://github.com/Dominic485649/UMI-OCR_plugins)

### 工程结构：

`**` 后缀表示本仓库(`主仓库`)包含的内容。

```
Umi-OCR
├─ Umi-OCR.exe
├─ umi-ocr.sh
└─ UmiOCR-data
   ├─ main.py **
   ├─ version.py **
   ├─ qt_res **
   │  └─ 项目qt资源，包括图标和qml源码
   ├─ py_src **
   │  └─ 项目python源码
   ├─ plugins
   │  └─ 插件
   └─ i18n **
      └─ 翻译文件
```

本次 Windows 发行公开基础程序与 CUDA OCR 插件。第三方插件开发、接入和替换开放，不设商业准入限制，你也可以自行编写插件。本分支与旧 2.x 的 CPU/CUDA/VL 技术实现不兼容；其他插件是否兼容取决于公开接口和平台依赖，不承诺所有插件均可跨平台使用。

运行环境框架：

- [PyStand](https://github.com/skywind3000/PyStand) 定制版

## 构建项目

Windows 构建说明与脚本见：

- [Windows CUDA 构建文档](docs/BUILD_WINDOWS_CUDA.md)
- [Windows CUDA build guide (English)](docs/BUILD_WINDOWS_CUDA_en.md)

本次仅发行 Windows 版本；Linux 版作为后续方向考虑，不属于本次发布范围。

--- 

## 软件本地化翻译：

原始 Umi-OCR 使用 [Weblate](https://hosted.weblate.org/engage/umi-ocr/) 协作翻译，本分支保留这些贡献。该链接属于上游翻译项目，不代表本分支已建立独立的 Weblate 项目。本分支新增内容的翻译与反馈请提交到 [本仓库](https://github.com/Dominic485649/UMI-OCR/issues)。

感谢以下译者，为 Umi-OCR 贡献了本地化翻译工作：

| 译者                                                                                 | 贡献语言                  |
| ------------------------------------------------------------------------------------ | ------------------------- |
| [bob](https://hosted.weblate.org/user/q021)                                          | English, 繁體中文, 日本語 |
| [Qingzheng Gao](https://github.com/QZGao)                                            | English, 繁體中文         |
| [Weng, Chia-Ling](https://hosted.weblate.org/user/ChiaLingWeng)                      | English, 繁體中文         |
| [linzow](https://hosted.weblate.org/user/linzow)                                     | English, 繁體中文         |
| [Marcos i](https://hosted.weblate.org/user/ultramarkorj9)                            | English, Português        |
| [Eric Guo](https://hosted.weblate.org/user/qwedc001)                                 | English                   |
| [steven0081](https://hosted.weblate.org/user/steven0081)                             | English                   |
| [Brandon Cagle](https://hosted.weblate.org/user/random4t4x14)                        | English                   |
| [plum7x](https://hosted.weblate.org/user/plum7x)                                     | 繁體中文                  |
| [hugoalh](https://hosted.weblate.org/user/hugoalh)                                   | 繁體中文                  |
| Anarkiisto                             | 繁體中文                  |
| [ドコモ光](https://hosted.weblate.org/user/umren190402)                              | 日本語                    |
| [杨鹏](https://hosted.weblate.org/user/ypf)                                          | Português                 |
| Вячеслав Анатольевич Малышев                 | Русский                   |
| [Muhammadyusuf Kurbonov](https://hosted.weblate.org/user/muhammadyusuf.kurbonov2002) | Русский                   |
| [தமிழ்நேரம்](https://hosted.weblate.org/user/TamilNeram/)                                | தமிழ்                       |

如果有信息错误或人员缺漏，请在 [这个讨论](https://github.com/Dominic485649/UMI-OCR/issues) 中回复。

---

## 赞助

本 fork 由 [Dominic485649](https://github.com/Dominic485649) 开发和维护；原始 Umi-OCR 作者及版权来源为 [hiroi-sora](https://github.com/hiroi-sora/Umi-OCR)。

免费公开的基础程序与 CUDA 版本可直接使用。CPU 和 PaddleOCR-VL 插件另行收费，以分担开发、测试和维护投入；作者也需要收入支持持续工作。我们推荐优先使用免费 CUDA 版，而非要求用户购买收费插件。详情与联系入口见上方 QQ 群【AWJ | Umi-OCR】：https://qm.qq.com/q/5XHoXCOU26。

## [更新日志](CHANGE_LOG.md)

## 开发计划

<details>
<summary>已完成的工作</summary>

- 标签页框架。
- OCR API控制器。
- OCR 任务控制器。
- 主题管理器，支持切换浅色/深色主题主题。
- 实现 **批量OCR**。
- 实现 **截图OCR**。
- 快捷键机制。
- 系统托盘菜单。
- 文本块后处理（排版优化）。
- 引擎内存清理。
- 软件界面多国语言。
- 命令行模式。
- Excel（csv）输出格式。
- `Esc`中断截图操作
- 外置主题文件
- 字体切换
- 加载动画
- 忽略区域。
- 二维码识别。
- 批量识别页面的图片预览窗口。
- PDF识别。
- 调用本地图片浏览器打开图片。 [#335](https://github.com/hiroi-sora/Umi-OCR/issues/335)
- 重复上一次截图。 [#357](https://github.com/hiroi-sora/Umi-OCR/issues/357)
- HTTP/命令行接口添加二维码识别/生成功能。 (#423)
- 二维码接口的文档。
- Linux 平台移植。
- HTTP 文档识别接口。

</details>

<!-- ##### 正在进行的工作 -->

##### 远期计划

<details>
<summary>展开</summary>

这些是预想中的功能，在开发初期已预留好接口，将在远期慢慢实现。

但开发途中受限于实际情况，可能更改功能设计、新增及取消功能。

- [ ] 重构底层插件机制。
- [ ] 在线 OCR API 插件。
- [ ] 独立的数学公式识别插件。
- [ ] “数学公式”标签页，提供独立的数学公式识别/Latex渲染。
- [ ] 检查更新机制。
- [ ] 排版解析之外的文本后处理模块（如保留数字、半全角字符转换、文本纠错）。
- [ ] 关键接口函数添加事件触发方式。

- 图片翻译
- 离线翻译。
- 固定区域识别。
- 识别表格图片，输出为Excel。
- 历史记录系统。
- 兼容 MacOS / Ubuntu 等平台。

</details>
