[Translate to English](https://github-com.translate.goog/Dominic485649/UMI-OCR/blob/main/docs/http/README.md?_x_tr_sl=zh-CN&_x_tr_tl=en&_x_tr_hl=en&_x_tr_pto=wapp)

- [命令行手册](../README_CLI.md)
- HTTP接口手册

# HTTP接口手册

（本文档仅适用于 Umi-OCR 最新版本。旧版本请查看 [Github备份分支](https://github.com/Dominic485649/UMI-OCR/branches) 中对应版本的文档。）

#### 基础说明

Umi-OCR 3.0.0 面向 Windows 10/11 x64，基础包可独立运行；PP-OCRv6 CUDA 插件单独安装，并与基础包共用 Python 3.13 运行时。插件使用 NVIDIA CUDA 12.6 与 PP-OCRv6_medium，CUDA 不可用时 OCR 请求明确失败，不会切换到 CPU、oneDNN、ONNX 或 DirectML；二维码接口不依赖 CUDA，仍可使用。图片 OCR 与二维码接口接受 Base64 形式的 JPEG、PNG、AVIF（dav1d）、WebP、JPEG XL、JPEG XR/WDP/HDP、BMP 和 TIFF。插件相关协助：[QQ 联系群](https://qm.qq.com/q/5XHoXCOU26)。

![Umi-OCR-全局页-服务.png](https://tupian.li/images/2023/10/25/653907e9bac06.png)

如上图，必须允许HTTP服务才能使用HTTP接口（默认开启）。如果需要允许被局域网访问，请将主机切换到**任何可用地址**。

在全局设置页中勾选**高级**才会显示。普通 OCR、二维码和文档 HTTP 服务不提供身份认证，响应允许任意网页来源读取；切换到“任何可用地址”会向局域网开放接口，只应在可信网络中使用。`/argv` 只接受本机环回连接，浏览器调用还必须与本服务同源，外部网页调用命令返回 HTTP `403`。

##### 注意事项：

1. 退出软件时，当前正在处理的HTTP请求会被中断。
2. WSGI 服务同步处理HTTP请求，慢速OCR或文档任务会阻塞后续请求；OCR任务本身也由现有队列调度，不要用并发请求绕过队列。
3. 遇到 `ECONNREFUSED`、超时或 HTTP 错误时，先检查服务开关、实际监听端口、应用状态和日志。不要无条件重试文档上传等会创建新任务的请求，以免重复提交。

---

## 服务基础路由

| 方法 | 路径 | 响应 |
| --- | --- | --- |
| GET | `/`、`/umiocr` | 返回当前应用名称。 |
| OPTIONS | 任意路径 | CORS 预检响应 `204`; 不会执行对应路径的GET/POST操作。 |

当前CORS响应使用 `Access-Control-Allow-Origin: *`、`Access-Control-Allow-Headers: *` 和 `Access-Control-Allow-Methods: GET, POST, PUT, OPTIONS`。单个HTTP请求体上限为100 MB；超限请求返回HTTP `413`。对于Base64图像，编码后的请求体计入此上限。

## 目录

### 图片识别

1. [图片OCR：参数查询](api_ocr.md#/api/ocr/get_options)
2. [图片OCR：Base64 识别](api_ocr.md#/api/ocr)

### 文档识别（PDF识别）

- [文档识别流程](api_doc.md#/api/doc)

### 二维码识别

1. [二维码：Base64 识别](api_qrcode.md#/api/qrcode)
2. [二维码：从文本生成图片](api_qrcode.md#/api/qrcode/text)

### 命令行

- [命令行接口](argv.md#/argv)
