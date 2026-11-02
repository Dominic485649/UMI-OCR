# 结构化文档 HTTP API

此接口使用插件声明的 `document` 能力，与旧 `/api/doc/*` 的分页文字 OCR 不同。主程序不内置推理模型，必须先安装、启用并配置提供该能力的插件。

## 后端与配置

- `GET /api/backends` 返回已启用的 OCR/document 后端列表，不代表已完成 GPU 健康检查。
- `GET /api/document/get_options?backendId=current` 返回结构化文档参数。
- `backendId` 为 `current` 时，在接纳任务时冻结当前 document 后端及有效配置。也可以显式指定已启用插件 ID。
- 请求选择不会改变 GUI 模型。实际模型资源在 GUI/HTTP/预热之间串行复用，不为每个请求启动重复 CUDA worker。
- 只提供 OCR 能力的插件不能冒充结构化文档后端。

## 上传与执行

`POST /api/document/upload` 使用 multipart/form-data：

- `file`：PDF 或支持的图片。
- `json`：以下 JSON 对象，可省略。

```json
{
  "backendId": "current",
  "options": {
    "maxOutputTokens": 4096
  },
  "pageRange": [1, 3],
  "taskTimeoutSeconds": 1800
}
```

`options` 只允许能力查询返回的局部参数，不接受程序路径、模型路径、端口、服务地址或任意导出路径。页范围从正整数开始，在推理前应用。任务时间预算是执行预算，不由进度事件无限续期；请求只能收紧插件允许的预算。

成功返回：

```json
{"code": 100, "data": "不透明任务ID", "jobId": "不透明任务ID"}
```

不上传空文件。当前单文件预算为 64 MiB，一次页范围不超过 500 页。结构化接口每个执行任务先预留约 193 MiB，结束后按实际自有文件结算；单资源不超过 16 MiB，任务结果资源预算为 128 MiB，本进程该接口总体临时空间预算为 512 MiB。旧 `/api/doc/*` 不计入这项结构化接口账本。排队或空间不足时明确拒绝，不无限积累。

## 状态、部分结果与取消

`POST /api/document/result`：

```json
{"jobId": "上传返回的任务ID", "includeResult": true}
```

响应包含 `state`、`stage`、`warnings`、`completedPages`、`result` 与已完成的 `partialPages`。

状态包括：

- `queued`：等待执行。
- `running`：正在初始化或解析。
- `succeeded`：完成，可能正常无内容。
- `partial`：仅部分页、区域或资源完成，必须检查警告。
- `failed`：失败且没有可用部分结果。
- `cancelled`：取消完成，已完成的部分结果仍可读取。

`code=100` 表示读取任务成功，不能仅凭它认定整份文档解析成功。必须检查状态和警告。

`POST /api/document/cancel` 接受相同的 `jobId`，只取消该任务，不终止其他 GUI/HTTP 任务。取消返回前后的状态以查询接口为准；后端退出与资源租约释放完成前，不删除仍可能在使用的输入。

## 下载与图片资源

`POST /api/document/download`：

```json
{"jobId": "上传返回的任务ID", "format": "zip"}
```

`format` 支持 `txt`、`md`、`json`、`zip`。结束后可下载完整或部分结果，正文不混入警告。仅完成部分页时，文本按原页号排序导出；JSON 保留部分标记和逐页结果。ZIP 内 Markdown 和 JSON 的资源地址均改为归档内的相对路径。

结果中的图片通过 `/api/document/assets/<jobId>/<assetId>` 返回。资源 ID 由宿主为当前任务生成，不接受客户端本地路径，不开放其他任务或模型目录。未知资源返回 404。

仅本进程登记、已经结束且无人使用的任务目录会按保留期回收。不会在服务器启动时清空整个 `temp_doc`，也不会清理用户模型、配置或未知历史数据。

## 旧接口兼容

`/api/ocr` 和旧 `/api/doc/*` 的既有响应结构保留。两者增加显式 `backendId` 选择入口；旧文档通过 multipart 表单的 `backendId` 字段指定后端，`json` 仍为既有扁平 options。

旧 `/api/doc/*` 仍是分页渲染/提图后执行文字 OCR，不返回这里的版面、表格、公式与结构化资源协议。旧 `ocr.preset` 只在 HTTP 兼容边界展开，不恢复 GUI 的识别预设。

本文是本轮接口契约，不代替实际验收记录。候选程序的 GPU、错误、取消、部分结果与资源测试须以同版本源码和产物的审计材料为准。
