[Translate to English](https://github-com.translate.goog/Dominic485649/UMI-OCR/blob/main/docs/http/README.md?_x_tr_sl=zh-CN&_x_tr_tl=en&_x_tr_hl=en&_x_tr_pto=wapp)

- [命令行手册](../README_CLI.md)
- HTTP接口手册

# HTTP接口手册

本文描述当前 3.1.x 的 HTTP 行为。公开版本、本地候选与插件版本见[主 README](../../README.md)；旧版本行为请按对应发行标签查看源码及当时文档，不使用当前说明替代历史验收。

#### 基础说明

主程序与 OCR 插件独立安装。图片 OCR 和普通文档 OCR 可选择当前后端或指定已注册的 OCR 插件；PaddleVL 的结构化解析使用独立的 document 能力，不能指定只有 OCR 能力的插件。CUDA 与 PaddleVL 均不提供 CPU 回退；二维码接口不依赖 OCR 推理插件。

图片 OCR 与二维码读取接受 Base64 图片，支持 JPEG、PNG、AVIF、WebP、JPEG XL、JPEG XR/WDP/HDP、BMP 和 TIFF，仍会校验实际解码内容和资源预算，不仅检查扩展名。

在“全局设置 → 服务”中开启 HTTP，缺省为 **开启、127.0.0.1:1224**；已有安装沿用保存的配置，端口占用时实际端口可能递增。普通 API **没有 API token、密码认证或 TLS**，并返回宽松 CORS 头；不要直接暴露到不可信网络。把主机改为 **任何可用地址（0.0.0.0）** 会扩大暴露面。

`/argv` 另有本机环回地址和浏览器 Origin 同源检查，非环回返回 `401`，不满足 Origin 检查返回 `403`；它不是独立认证机制，也不能据此宣称已防护 DNS rebinding 或所有浏览器攻击。UI 解锁不属于 HTTP 安全凭据。模型下载不改变 HTTP 启停、监听或鉴权配置。

##### 注意事项：

1. 退出软件时，当前正在处理的HTTP请求会被中断。
2. HTTP 连接由有限线程服务处理，共享连接许可上限为 16；socket I/O 超时为 30 秒，不等于模型任务总超时。重型任务仍受后端队列与共享执行许可限制，不要用并发请求绕过队列或显存预算。
3. 遇到 `ECONNREFUSED`、超时或 HTTP 错误时，先检查服务开关、实际监听端口、应用状态和日志。不要无条件重试文档上传等会创建新任务的请求，以免重复提交。

---

## 服务基础路由

| 方法 | 路径 | 响应 |
| --- | --- | --- |
| GET | `/`、`/umiocr` | 返回当前应用名称。 |
| OPTIONS | 任意路径 | CORS 预检响应 `204`; 不会执行对应路径的GET/POST操作。 |

当前 CORS 响应使用 `Access-Control-Allow-Origin: *`、`Access-Control-Allow-Headers: *` 和 `Access-Control-Allow-Methods: GET, POST, PUT, OPTIONS`。服务按声明的 `Content-Length` 对超过 **100 MiB（104,857,600 字节）** 的请求返回 `413`；Base64 编码后的体积计入该值。这不是对所有无长度、分块请求及解码后占用的统一验收保证，具体接口还可能有更小的上传、像素、页数和结果预算。

HTTP 的 `options` 使用相应能力 schema 默认值叠加本次请求值，不自动复制截图 OCR 页的自定义参数。`backendId=current` 会冻结当前配置用于本次任务；显式指定其他后端不会改 GUI 的全局选择。

## 目录

### 图片识别

1. [图片OCR：参数查询](api_ocr.md#/api/ocr/get_options)
2. [图片OCR：Base64 识别](api_ocr.md#/api/ocr)

### 文档识别

- [普通文档 OCR／PDF 处理](api_doc.md#/api/doc)：使用 OCR 能力的传统流程。
- [PaddleVL 结构化文档解析](api_document.md)：独立 document 任务、Markdown／JSON／资源导出，默认不要求显示文档任务 UI。

### 二维码识别

1. [二维码：Base64 识别](api_qrcode.md#/api/qrcode)
2. [二维码：从文本生成图片](api_qrcode.md#/api/qrcode/text)

### 命令行

- [命令行接口](argv.md#/argv)
