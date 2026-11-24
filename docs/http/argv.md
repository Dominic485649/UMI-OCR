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

- [命令行接口](#/argv)

<a id="/argv"></a>

---

## 命令行 接口

此接口用于命令行参数的跨进程传输，一般由程序内部自动调用。开发者也可手动调用。

由于此接口允许访问本机图片、关闭软件和调用界面函数，只接受本机 IPv4 或 IPv6 环回地址连接。浏览器请求还必须与本服务同源，外部网页和 `Origin: null` 请求返回 HTTP `403`。普通命令行客户端不发送 `Origin`，继续使用本机调用。

URL：`/argv`

例：`http://127.0.0.1:1224/argv`

### 请求

方法：`POST`

参数：`json` `list`

传入一个 **字符串列表** ，列表中记录命令行参数。

- 如：命令行调用 `Umi-OCR.exe --path "D:/xxx.png"`
- 等价于向argv接口发送： `["--path", "D:/xxx.png"]`
- 非环回地址返回 HTTP `401`；不同源的浏览器请求返回 HTTP `403`；JSON 不是字符串列表时返回 HTTP `400`。

具体命令行规则请见 [README_CLI.md](../README_CLI.md) 。

### 调用接口 示例代码

<details>
<summary>JavaScript 示例：（点击展开）</summary>

```javascript
// 此示例只可在与 Umi-OCR HTTP 服务同源的页面中执行。
// 外部网站或 file:// 页面无法通过浏览器调用这个命令接口。
const url = new URL("/argv", location.origin);
// 等价于命令行指令 Umi-OCR --screenshot
const data = ["--screenshot"];
fetch(url, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(data)
    })
    .then(response => response.text()) // 返回值是字符串
    .then(data => {
        console.log("screenshot text:\n", data)
    })
    .catch(error => {
        console.error(error);
    });
```

</details>