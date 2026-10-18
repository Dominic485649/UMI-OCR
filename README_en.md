# Umi-OCR 3.0.1

Main repository: https://github.com/Dominic485649/UMI-OCR

Stable version: 3.0.1; Release tag: `v3.0.1`. This release publicly provides the base application and CUDA plugin.

Authors and provenance: Dominic485649 (author and maintainer of this fork); [hiroi-sora](https://github.com/hiroi-sora/Umi-OCR) (original Umi-OCR author and original copyright source).

<p align="left">
    <a href="README.md">
        中文
    </a>
    <span> • </span>
    <span>
        <b>English</b>
    </span>
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

<h1 align="center">Umi-OCR</h1>

<p align="center">
  <a href="https://github.com/Dominic485649/UMI-OCR/releases">
    <img src="https://img.shields.io/github/v/release/Dominic485649/UMI-OCR?style=flat-square" alt="Umi-OCR">
  </a>
  <a href="#download-releases">
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
    <a href="#usage">
      Usage
    </a>
    <span> • </span>
    <a href="#download-releases">
      Download Releases
    </a>
    <span> • </span>
    <a href="CHANGE_LOG.md">
      Changelog
    </a>
    <span> • </span>
    <a href="https://github.com/Dominic485649/UMI-OCR/issues">
      Issue a problem
    </a>
  </h3>
</div>
<br>

<div align="center">
  <strong>Open-source, Batch Offline OCR Software</strong><br>
  <sub>Umi-OCR 3.0.1: this release targets Windows 10/11 x64</sub>
</div><br>

- **Public editions**: The base application and CUDA plugin are provided publicly at no charge; third-party plugin development and integration are open.
- **Convenient**: Unzip and use, run offline, no need for network.
- **Efficient**: Uses the offline PP-OCRv6_medium high-accuracy pipeline by default.
- **Flexible**: Supports customizable interface, and supports multiple calling methods such as command-line and HTTP API.

<p align="center"><img src="https://tupian.li/images/2024/03/27/66040ec301b55.png" alt="1-标题-1.png" style="width: 80%;"></p>

![1-标题-2.png](https://tupian.li/images/2023/11/19/6559909fdeeba.png)

## Using the Source Code:

Developers should read [Building the Project](#Build-the-Project) before proceeding.

### License of This Fork

The original Umi-OCR MIT `LICENSE`, hiroi-sora copyright, and attribution are retained unchanged. Files added or modified by this fork are licensed under [AGPL-3.0-or-later](COPYING), and the complete distribution is AGPL-3.0-or-later because it combines PyMuPDF. Release archives include corresponding source, build scripts, dependency locks, and third-party notices. Charging for source delivery, build artifacts, updates, or support is permitted, but recipients' rights to copy, modify, and redistribute AGPL-covered material cannot be restricted. See the [combined-distribution licensing note](LICENSES/COMBINED_DISTRIBUTION.md).

PDF preview, PDF page reading, document OCR, and single-layer and layered searchable-PDF output remain available through PyMuPDF's `fitz` interface.

## Download Releases:

This is the **3.0.1 Windows x64 stable Release**, tagged `v3.0.1`. Download the base application and CUDA plugin separately. CPU and PaddleOCR-VL plugins are not public assets in this release.

- **Base application**: [Main repository v3.0.1 Release](https://github.com/Dominic485649/UMI-OCR/releases/tag/v3.0.1).
- **CUDA plugin**: [Plugin repository v3.0.1 Release](https://github.com/Dominic485649/UMI-OCR_plugins/releases/tag/v3.0.1).

The host and CUDA worker share Python 3.13.16; Qt stays at 6.11.2. Archives use `.tar.xz` with standard LZMA2 at the tool's default compression level. Fully extract the base first, then extract the CUDA plugin into the application root. A CUDA 12.6-compatible NVIDIA GPU and driver are required; a system CUDA Toolkit is not required.

CPU and CUDA provide the same recognition results, with CPU running more slowly. PaddleOCR-VL offers high accuracy at a speed close to CPU. CPU and PaddleOCR-VL plugins are offered separately for a fee; contact the QQ group 【AWJ | Umi-OCR】: https://qm.qq.com/q/5XHoXCOU26 . Fees help cover development, testing, and maintenance; the author also needs income to recover this ongoing investment. We recommend trying the free CUDA edition first; purchasing a paid plugin is not required.

## Getting Started

The release is a portable, directly runnable directory. Fully extract the archive before running the launcher.

Models load on first use by default. Explicit background warmup policies are preserved. Workers are reused for subsequent tasks and can be released when idle; active tasks finish before configuration changes apply.

If you encounter any problems, please submit an [Issue](https://github.com/Dominic485649/UMI-OCR/issues) and I will do my best to assist you.

## Interface Language

Umi-OCR supports multiple languages for its interface. When you open the software for the first time, it will automatically switch to the language based on your computer's system settings.

If you need to manually switch languages, please refer to the following figure, `全局设置`→`语言/Language` .

<p align="center"><img src="https://tupian.li/images/2023/11/19/65599c3f9e600.png" alt="1-标题-1.png" style="width: 80%;"></p>

## Tabbed Interface

Umi-OCR v3 is composed of a series of flexible and easy-to-use **tabbed interfaces**. You can open the required tabbed interface according to your preferences.

The top left corner of the tab bar can be used to switch **window always on top**. The top right corner can be used to **lock the tabbed interface** to prevent accidental closure during daily use.

### Screenshot OCR

<p align="center"><img src="https://tupian.li/images/2024/03/27/66040ecb4dfb4.png" alt="2-截图-1.png" style="width: 80%;"></p>

**Screenshot OCR**: After opening this page, you can use a keyboard shortcut to capture a screenshot and recognize the text in the image.

- The left-side image preview panel allows you to select and copy text with your mouse.
- The right-side recognition record panel allows you to edit text and select and copy multiple records.
- It also supports copying images from elsewhere and pasting them into Umi-OCR for recognition.
- HDR monitors use a WGC/D3D11 floating-point capture path and deterministic sRGB tone mapping. A failed monitor falls back to the normal SDR capture path without disabling screenshot OCR.
- OCR overlays preserve all four polygon points and text rotation instead of flattening complex layouts to rectangles. Wheel zoom stays anchored to the image point under the pointer.

#### Paragraph Merge

<p align="center"><img src="https://tupian.li/images/2024/03/27/66040ecc62ac9.png" alt="2-截图-2.png" style="width: 80%;"></p>

About **OCR Text Post-Processing - Paragraph Merge**: This feature can organize the layout and order of OCR results to make the text more suitable for reading and use. The preset schemes are:

- **Single line**: Merge text on the same line, suitable for most scenarios.
- **Multiple lines - natural paragraphs**: Intelligently recognize and merge text belonging to the same paragraph, suitable for most scenarios, as shown in the figure above.
- **Multiple lines - code block**: Try to restore the original indentation and spacing of the text. Suitable for recognizing code snippets or scenes that require retaining spaces.
- **Vertical layout**: Suitable for vertical layout. Needs to be used in conjunction with a model library that also supports vertical layout recognition.

---

### Batch OCR

<p align="center"><img src="https://tupian.li/images/2024/03/27/66040ecdc5197.png" alt="3-批量-1.png" style="width: 80%;"></p>

**Batch OCR**: This page supports batch importing local images for recognition.

- Input formats: `jpg, jpe, jpeg, jfif, png, avif, webp, jxl, jxr, wdp, hdp, bmp, tif, tiff`. AVIF decoding is pinned to dav1d, and all inputs are normalized to contiguous BGR 8-bit pixels before OCR.
- The recognized content can be saved in various formats such as txt/jsonl/md/csv(Excel).
- Supports `text post-processing` technology, which can recognize text belonging to the same natural paragraph and merge it. It also supports multiple processing schemes such as code blocks and vertical text.
- There is no limit on the number of images that can be imported for processing at one time, and the software can automatically shut down or sleep after completing the task.

#### Ignore Regions

<p align="center"><img src="https://tupian.li/images/2024/03/27/66040ecbc0021.png" alt="3-批量-2.png" style="width: 80%;"></p>

About **OCR Text Post-Processing - Ignore Regions**: This is a special function in batch OCR that is used to exclude unwanted text in images.

- The ignore region editor can be accessed in the right column of the batch recognition page settings.
- As shown in the example above, there are multiple watermarks/LOGOs at the top and bottom right corner of the image. If these images are recognized in batches, the watermarks will interfere with the recognition results.
- Hold down the right mouse button to draw multiple rectangular boxes. The text inside these areas will be ignored during the task.
- Please try to draw the rectangular boxes larger, completely wrapping all possible positions of the watermark.

---

### Batch Documents OCR

<p align="center"><img src="https://tupian.li/images/2024/03/27/66040ecc8bfd4.png" alt="" style="width: 80%;"></p>

---

### QR Code

<p align="center"><img src="https://tupian.li/images/2024/03/27/66040ed01f5b2.png" alt="4-二维码-1.png" style="width: 80%;"></p>

**Scan Code**:

- You can capture screenshots, paste, or drag local images to read QR codes and barcodes.
- Supports multiple codes in one image.
- Supports 19 protocols, as follows:

`Aztec`,`Codabar`,`Code128`,`Code39`,`Code93`,`DataBar`,`DataBarExpanded`,`DataMatrix`,`EAN13`,`EAN8`,`ITF`,`LinearCodes`,`MatrixCodes`,`MaxiCode`,`MicroQRCode`,`PDF417`,`QRCode`,`UPCA`,`UPCE`,

<p align="center"><img src="https://tupian.li/images/2024/03/27/66040ed001437.png" alt="4-二维码-2.png" style="width: 80%;"></p>

**Generate Code**:

- Enter text to generate a QR code image.
- Supports 19 protocols and parameters such as **error correction level**.

---

### Global Settings

<p align="center"><img src="https://tupian.li/images/2024/03/27/66040ed16f4e0.png" alt="5-全局设置-1.png" style="width: 80%;"></p>

**Global Settings**: Here you can adjust the global parameters of the software. Common features include:

- One-click to add shortcuts or set auto-startup.
- Change the interface **language**. Umi supports traditional Chinese, English, Japanese, and other languages.
- Switch interface **themes**. Follow-system mode can map Windows light and dark modes to separate themes; Neutral Dark uses an `rgb(24, 24, 24)` base.
- Adjust the **font size** and **font** of the interface text.
- Configure the PP-OCRv6 preset, auxiliary stages, image limit, recognition batch size, threshold, and CUDA device. The recognition model is fixed to PP-OCRv6_medium; there is no ineffective recognition-language-pack option. Interface language switching remains available.
- Advanced settings start collapsed and contain only effective performance or HDR calibration controls; the old developer tools and renderer selector are removed.
- The Windows build always uses Qt6 RHI/D3D11 hardware rendering. HDR SDR-white and peak-luminance values use system detection by default and should only be overridden for measured calibration issues.
- The tray icon remains visible: single-click captures a screenshot, double-click opens the main window, and the context menu opens global settings, warms/releases the OCR model, opens the window, or exits Umi-OCR.
- Model loading can be delayed by `0–60` minutes or deferred to first use. Cleanup can be disabled, checked every six minutes when system memory exceeds 90%, or run after `5–120` idle minutes. It never runs during an OCR task.

See the [PP-OCRv6 settings guide](docs/SETTINGS_PP_OCRV6.md).

---

## API Usage:

- [Command-line manual](docs/README_CLI.md)
- [HTTP API manual](docs/http/README.md)

## About Project Structure

### Repositories:

- [Main Repository](https://github.com/Dominic485649/UMI-OCR) 👈
- [Public CUDA plugin repository](https://github.com/Dominic485649/UMI-OCR_plugins)
Third-party plugin development, integration, and replacement are open with no commercial gatekeeping; you can also write your own plugin. This branch is technically incompatible with the old 2.x CPU/CUDA/VL implementations. Compatibility of other plugins depends on the public interfaces and platform dependencies, and is not guaranteed for every plugin or platform.

## Build the Project

Windows build instructions and scripts:

- [Windows CUDA build guide](docs/BUILD_WINDOWS_CUDA_en.md)
- [中文构建文档](docs/BUILD_WINDOWS_CUDA.md)

Linux support is being considered for the future and is not included in this release.

---

## Software Localization:

The original Umi-OCR uses [Weblate](https://hosted.weblate.org/engage/umi-ocr/) for collaborative translation, and this fork retains those contributions. That link belongs to the upstream translation project, not a separate Weblate project for this fork. Please submit translations and feedback for this fork's new content to [this repository](https://github.com/Dominic485649/UMI-OCR/issues).

We extend our gratitude to the following translators for contributing to the localization of Umi-OCR:

| Translator                                                                           | Contributed Languages     |
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

If you find any errors in the information or missing contributors, please reply in [this discussion](https://github.com/Dominic485649/UMI-OCR/issues).

---

## [CHANGE LOG](CHANGE_LOG.md)
