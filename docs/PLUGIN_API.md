# Umi-OCR 插件 API 规范（契约 v2）

本文档描述 Umi-OCR 2.8 起的插件契约。**任何人都可以按本规范实现兼容插件**，
不需要获得授权，也不需要修改本体源码。

- 宿主 API 版本：`2.8`
- 清单 schema 版本：`1`
- 清单文件名：`umi-plugin.json`
- 实现位置：[`py_src/plugins_controller/`](https://github.com/Dominic485649/UMI-OCR/tree/v3.0.0/UmiOCR-data/py_src/plugins_controller/)
- 回归测试：[`tests/test_plugin_contract.py`](https://github.com/Dominic485649/UMI-OCR/blob/v3.0.0/tests/test_plugin_contract.py)

---

## 1. 设计原则

### 1.1 发现阶段不导入插件代码

宿主扫描插件目录时**只读 `umi-plugin.json`**。这意味着：

- 依赖损坏、平台不符、宿主版本不匹配的插件仍然会被**列出**并说明原因，
  而不是让宿主在启动时崩溃或静默消失。
- 重量级后端（CUDA、PaddlePaddle、外部服务客户端）在真正被使用前
  不会被导入，不占用启动时间、内存和显存。

唯一的例外是旧版 `PluginInfo` 插件：它的元数据写在 Python 里，必须导入才能读到。
这是兼容旧生态的已知代价，规范中明确标注。

### 1.2 能力是契约单位

插件通过 `capabilities` 声明自己提供什么能力。宿主为每种能力类型准备
**独立的**注册表、任务管理器、配置界面和错误路径。

把一种能力硬接到另一种能力的接口上（例如让文档解析后端假装成 OCR 引擎）
是被明确禁止的：两者的输入、输出、生命周期和失败模式都不同，
硬接会让错误提示、任务调度和资源释放全部失真。

### 1.3 插件自带运行时，用户不需要 pip install

插件可以携带私有的 `vendor/` 目录（Python 包）和原生 DLL 目录。
宿主在激活插件时挂载它们。**用户只需要把插件归档解压到 Umi-OCR 本体目录。**

`vendor` 默认**追加**到 `sys.path` 末尾，基础环境优先，避免插件覆盖宿主依赖。

---

## 2. 目录结构

```
Umi-OCR/
├── Umi-OCR.exe
└── UmiOCR-data/
    └── plugins/
        ├── .plugins_state              ← 宿主维护的启用/禁用状态，勿手工编辑
        └── <你的插件 id>/
            ├── umi-plugin.json         ← 必需
            ├── __init__.py             ← 必需（使其成为可导入的 Python 包）
            ├── api.py                  ← 能力实现（惰性导入）
            ├── config.py               ← 可选，动态配置
            ├── health.py               ← 可选，健康检查
            ├── i18n.csv                ← 可选，插件私有翻译
            ├── YourPage.qml            ← 可选，插件页
            └── vendor/                 ← 可选，插件私有 Python 包
```

**插件目录名必须与清单里的 `id` 完全一致。** 目录名同时也是 Python 包名，
因此必须是合法的 Python 标识符，且不能与已有模块重名。
建议加平台/后端前缀，例如 `win32_PaddleOCRv6_CUDA`。

---

## 3. 清单 `umi-plugin.json`

### 3.1 完整示例

```json
{
  "schema_version": 1,
  "id": "win32_MyOcr",
  "name": "My OCR Engine",
  "version": "1.0.0",
  "host_api": ">=2.8,<3.0",
  "platform": ["win32"],
  "arch": ["x86_64"],
  "vendor": "Your Name",
  "license": "MIT",
  "homepage": "https://example.com/my-ocr",
  "description": "示例 OCR 后端。",
  "conflicts": ["win32_OtherOcr"],
  "i18n": "i18n.csv",
  "services": [
    {
      "id": "shared-model",
      "entry": "runtime:getService",
      "config": { "title": "模型服务", "type": "group" }
    }
  ],
  "capabilities": [
    {
      "type": "ocr",
      "entry": "api:Api",
      "config": {
        "global_options": { "title": "My OCR", "type": "group" },
        "local_options": { "title": "识别设置", "type": "group" }
      },
      "meta": { "serviceRefs": ["shared-model"] }
    }
  ],
  "pages": [
    {
      "key": "MyPage",
      "qml": "MyPage.qml",
      "controller": "page:MyPage",
      "title": "我的页面",
      "intro": "# 我的页面\n\n说明文字。"
    }
  ],
  "health": "health:check",
  "runtime": {
    "vendor_dirs": ["vendor"],
    "dll_dirs": ["vendor/mylib/bin", "vendor/nvidia/*/bin"],
    "priority": "append"
  }
}
```

### 3.2 字段

| 字段 | 必需 | 说明 |
| --- | --- | --- |
| `schema_version` | 是 | 目前只支持 `1` 。 |
| `id` | 是 | 必须与插件目录名一致。 |
| `name` | 否 | 界面显示名，默认取 `id` 。会走插件 i18n 翻译。 |
| `version` | 是 | 插件自身版本，如 `1.2.0` 。 |
| `host_api` | 否 | 支持的宿主 API 范围，默认 `*` 。语法见 §3.3。 |
| `platform` | 否 | `win32` / `linux` / `darwin` / `*` 。空或缺省 = 不限制。 |
| `arch` | 否 | `x86_64` / `arm64` / `x86` / `*` 。空或缺省 = 不限制。 |
| `vendor` `license` `homepage` `description` | 否 | 展示用元数据。`description` 会走 i18n。 |
| `conflicts` | 否 | 与之互斥的插件 id 列表。见 §3.5。 |
| `i18n` | 否 | 插件私有翻译 CSV 文件名。见 §7。 |
| `services` | 否 | 2.8 起的插件级共享服务列表。见 §4.4。 |
| `capabilities` | 是 | 至少一项。见 §4。 |
| `pages` | 否 | 插件标签页。见 §6。 |
| `health` | 否 | 健康检查入口。见 §5。 |
| `runtime` | 否 | 私有运行时挂载。见 §8。 |

### 3.3 版本范围语法

逗号分隔的比较式，**全部满足**才算通过：

| 写法 | 含义 |
| --- | --- |
| `*` 或省略 | 任意宿主版本 |
| `>=2.8,<3.0` | 2.8 及以上、3.0 以下（**当前推荐写法**） |
| `2.7` | 精确等于 2.7（旧契约插件） |
| `>=2.7` | 2.7 及以上 |

支持的运算符：`>=` `<=` `==` `!=` `>` `<`。
版本号按 `主.次.补丁` 三段比较，缺失段补 `0`，非数字后缀忽略（`2.7.0-beta1` → `2.7.0`）。
**语法非法的范围一律判为不兼容**——宁可拒绝，也不放进来一个坏插件。

宿主兼容规则：主版本号变化 = 破坏性变更；次版本号递增 = 只增加能力，旧插件继续可用。

### 3.4 入口引用格式

`"<相对模块>:<属性>"`，模块路径相对于插件包：

| 写法 | 解析结果 |
| --- | --- |
| `":Api"` | `<插件id>` 包根的 `Api` |
| `"api:Api"` | `<插件id>.api` 的 `Api` |
| `"backends.gpu:Engine"` | `<插件id>.backends.gpu` 的 `Engine` |

缺少 `:` 或属性名为空都会被拒绝并说明原因。

### 3.5 互斥

`conflicts` 是**双向**生效的：只要 A 声明了 B、或 B 声明了 A，两者就不能同时启用。

典型场景：CPU OCR 插件与 GPU OCR 插件各自 vendor 了不兼容的 PaddlePaddle 构建，
同时挂载会导致 DLL 冲突。

裁决规则：在所有通过校验的插件中按 **id 字典序**排序，先到者保留，
后到者标记为 `conflict` 状态并提示用户禁用其一。这个规则是确定性的、可复现的。

---

## 4. 能力

### 4.1 宿主内置的能力类型

| 类型 | 用途 | 注册表 | 任务管理器 | QML 管理器 |
| --- | --- | --- | --- | --- |
| `ocr` | 图片 → 文本框 | [`py_src/ocr/api`](https://github.com/Dominic485649/UMI-OCR/blob/v3.0.0/UmiOCR-data/py_src/ocr/api/__init__.py) | `MissionOCR` | `OcrManager.qml` |
| `document` | 文档 → 结构化块 + Markdown | [`py_src/document/api`](https://github.com/Dominic485649/UMI-OCR/blob/v3.0.0/UmiOCR-data/py_src/document/api/__init__.py) | `MissionDocument` | `DocumentManager.qml` |

声明宿主不认识的能力类型，插件会被标记为 `incompatible` 并列出宿主支持的类型。

### 4.2 能力声明

```json
{
  "type": "ocr",
  "entry": "api:Api",
  "config": { }
}
```

- `type`：能力类型。
- `entry`：**惰性解析**的实现入口。必须是可调用对象，接受一个参数
  （合并后的配置字典 `argd`），返回后端实例。
- `config`：配置声明，两种写法见 §4.3。

### 4.3 配置：内联 vs 入口

**内联对象（推荐）** —— 配置直接写在清单里，发现阶段**一行 Python 都不导入**：

```json
"config": {
  "global_options": { "title": "My OCR", "type": "group" },
  "local_options": { "title": "识别设置", "type": "group" }
}
```

也可以只写一个裸字典，宿主会把它当作 `local_options`：

```json
"config": { "title": "识别设置", "type": "group" }
```

**入口字符串** —— 配置由 Python 提供，适合默认值需要按机器计算的场景
（例如线程数取决于 CPU 核心数）：

```json
"config": "config:CONFIG"
```

```python
# config.py —— 必须保持轻量：只描述配置，不导入后端
import os

CONFIG = {
    "global_options": {...},
    "local_options": {
        "threads": {"title": "线程", "default": os.cpu_count(), "isInt": True},
    },
}
```

> **代价**：`import <插件id>.config` 会连带执行 `<插件id>/__init__.py`。
> 这是 Python 的固有行为，无法规避。因此配置模块和包根都必须轻量。
> 真正的后端实现始终放在 `entry` 指向的模块里，它不会在发现阶段被导入。

### 4.4 共享服务（宿主 API 2.8）

当多个 capability 需要复用同一模型服务、端口或进程时，在清单顶层声明
`services`，并在 capability 的 `meta.serviceRefs` 里引用它：

```json
"services": [{
  "id": "shared-model",
  "entry": "runtime:getService",
  "config": {"title": "模型服务", "type": "group"}
}],
"capabilities": [{
  "type": "ocr",
  "entry": "ocr_api:Api",
  "meta": {"serviceRefs": ["shared-model"]}
}]
```

- `id` 在单个插件内必须唯一；`entry` 是惰性解析的服务工厂或实例。
- 每个 `serviceRefs` 必须引用本插件已声明的服务，否则清单会被拒绝。
- 服务配置只在全局设置出现一次；宿主把已去前缀的服务配置合并给引用它的
  capability。
- 服务实例可实现 `configure`、`prestart`、`ensure_ready`、`acquire`、
  `health`、`maintain`、`release`、`stop_owned` / `shutdown_owned`，并应通过
  `get_status` 暴露 `stopped/starting/ready/busy/sleeping/failed` 等状态。
  共享模型服务应让 `acquire`/`release` 串行化请求，并在有活动租约时拒绝会
  引起重启的配置改变或停止操作。宿主退出及插件重新扫描时只调用
  `shutdown_owned`，因此外部进程的所有权必须由服务自身严格区分。

旧插件不声明 `services` 时保持原有行为。

### 4.5 配置项字典格式

配置项复用 Umi-OCR 现有的 `Configs` 格式：

```json
{
  "title": "分组标题",
  "type": "group",
  "someOption": {
    "title": "选项名",
    "default": "a",
    "optionsList": [["a", "甲"], ["b", "乙"]],
    "toolTip": "悬停提示",
    "advanced": false
  },
  "aNumber": {
    "title": "数值", "default": 8, "min": 1, "max": 64, "isInt": true, "unit": "px"
  }
}
```

- `global_options` 出现在【全局设置】里，全局共享。
- `local_options` 出现在【每个标签页】的设置里，可按页覆盖。
- 传给 `entry` 的 `argd` 里，键已经**去掉了 `<类型>.<插件id>.` 前缀**。

### 4.6 `ocr` 能力的后端契约

```python
class Api:
    def __init__(self, globalArgd: dict): ...

    def start(self, argd: dict) -> str:
        """返回 "" 正常；"[Error] ..." 终止本任务队列。"""

    def runPath(self, imgPath: str) -> dict: ...
    def runBytes(self, imageBytes: bytes) -> dict: ...
    def runBase64(self, imageBase64: str) -> dict: ...
    # 均返回 {"code": 100, "data": [{
    #   "box": [[x,y]*4], "polygon": [[x,y], ...],
    #   "text": str, "score": float | None
    # }]}
    # 或 {"code": 101, "data": ""}（无文字） /
    # {"code": 9xx, "data": "[Error] ...", "errorType": "..."}

    def warmup(self, argd: dict) -> str: ...
    def get_status(self) -> dict:
        """{"state": "unloaded|warming|loaded|unavailable",
            "idleSeconds": float, "error": str}"""
    def release(self) -> str: ...
    def stop(self) -> None: ...
```

`box` 始终保留四点兼容形状；有更精确区域时用可选 `polygon` 传递。`score`
只能是可校准的数值；VLM Spotting 等后端无法可靠提供置信度时必须返回 `None`，
宿主的平均分与显示/导出会保留为空。

### 4.7 `document` 能力的后端契约

```python
class Api:
    def __init__(self, argd: dict): ...

    def start(self, argd: dict) -> str: ...

    def parseDoc(self, msn: dict) -> dict:
        """msn 至少含 {"path": 文档路径}，可含 "pageRange"。
        {"code": 100, "text": str, "markdown": str,
         "data": {"pages": [...], "blocks": [...], "assets": [...]},
         "warnings": [...], "metadata": {...}}
        {"code": 101, "data": ""}                       无可提取内容
        {"code": 9xx, "data": "[Error] 可操作的中文提示",
         "errorType": "..."}                                失败
        """

    def health(self, argd: dict) -> dict:
        """{"ok": bool, "message": str, "details": dict}"""

    def get_status(self) -> dict: ...
    def release(self) -> str: ...
    def stop(self) -> None: ...
```

`block` 至少保留官方布局的 ID、分组和顺序：

```python
{"id": int | str, "globalId": int | None,
 "groupId": int | str | None, "globalGroupId": int | None,
 "order": int | None, "category": str, "categoryName": str,
 "bbox": [[x, y]] * 4, "polygon": [[x, y], ...], "content": str,
 "table": {"html": str | None, "cells": object | None} | None,
 "formula": {"latex": str | None} | None}
```

失败结果的可选 `errorType` 是稳定、面向软件处理的分类（例如
`INVALID_CONFIGURATION`、`LLAMA_CPP_INCOMPATIBLE`、`MODEL_NOT_READY`、
`PIPELINE_DEPENDENCY_MISSING`、`GPU_INITIALIZATION_FAILED`、
`REQUEST_TIMEOUT`、`INVALID_MODEL_OUTPUT`）。共享模型服务还应区分
`SERVER_PROGRAM_MISSING`、`MODEL_FILE_MISSING`、`MMPROJ_FILE_MISSING`、
`LAYOUT_MODEL_MISSING`、`PORT_CONFLICT`、`SERVER_START_FAILED`、
`SERVER_EXITED`、`SERVER_START_TIMEOUT` 与 `SERVICE_BUSY`。它不能替代给用户看的可操作
中文 `data` 信息。

---

## 5. 健康检查

```json
"health": "health:check"
```

```python
# health.py
def check() -> dict:
    return {"ok": True, "message": "CUDA 可用，模型完整。", "details": {...}}
```

- **只有健康检查返回 `ok=True` 时，界面才允许把该后端显示为"可用"。**
  仅仅"被发现"不等于可用。
- 检查失败时 `message` 必须给出**可操作的下一步**，不能只报错误码。
  参考实现：[`win32_PaddleOCRv6_CUDA/health.py`](../UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/health.py)
- 检查是**按需**执行的，不在启动路径上，因此可以放心导入后端做真实探测。
- 未声明 `health` 的插件按"加载成功"处理，并在 `details.declared = false` 中如实标注。

---

## 6. 插件页

```json
"pages": [
  {
    "key": "MyPage",
    "qml": "MyPage.qml",
    "controller": "page:MyPage",
    "title": "我的页面",
    "intro": "# 我的页面\n\n说明。"
  }
]
```

- `key` 在全局唯一，不能与内置页（`ScreenshotOCR` `BatchOCR` `BatchDOC` `QRCode`
  `Navigation` `GlobalConfigsPage` `About`）重名。
- `qml` 是相对插件目录的路径，**文件必须存在**，否则清单校验失败。
- `controller` 可选。声明后，页面会拥有一个 Python 控制器，构造签名与内置页一致：

```python
# page.py
class MyPage:
    def __init__(self, ctrlKey, connector):
        self.ctrlKey = ctrlKey
        self.connector = connector
```

> **契约 v1 的缺陷**：`tag_pages_connector.PageClass` 是硬编码的四个内置页，
> 插件页即使声明了 `needController` 也拿不到控制器（`addPage` 返回空串，
> 页面创建直接失败）。v2 通过
> [`page_registry`](https://github.com/Dominic485649/UMI-OCR/blob/v3.0.0/UmiOCR-data/py_src/tag_pages/page_registry.py)
> 补上了这条路径，控制器同样是惰性解析的。

---

## 7. 国际化

插件的用户可见字符串走现有的
[`plugin_i18n.Translator`](https://github.com/Dominic485649/UMI-OCR/blob/v3.0.0/UmiOCR-data/py_src/imports/plugin_i18n.py) 流程：
一个 UTF-8 CSV，首行是语言代码表头，首列是原文。

```csv
zh_CN,en_US,ja_JP
My OCR Engine,My OCR Engine,私のOCRエンジン
识别设置,Recognition settings,認識設定
```

在清单里声明 `"i18n": "i18n.csv"` 后，宿主会自动翻译：

- 顶层 `name`、`description`
- 每个 `page` 的 `title`、`intro`
- **内联 `config`** 中的 `title`、`toolTip`、`unit`，以及 `optionsList` 的显示文本

入口式（Python）配置需要插件自己调用 `Translator` 翻译。

---

## 8. 私有运行时

```json
"runtime": {
  "vendor_dirs": ["vendor"],
  "dll_dirs": ["vendor/mylib/bin", "vendor/nvidia/*/bin"],
  "priority": "append"
}
```

| 字段 | 说明 |
| --- | --- |
| `vendor_dirs` | 相对插件目录的 Python 包搜索路径。目录**必须存在**，否则激活失败。 |
| `dll_dirs` | Windows 原生 DLL 搜索目录，支持 `*` 通配。通过 `os.add_dll_directory` 注册。 |
| `python_archives` | 可选 Stored ZIP 路径，直接导入；归档必须位于插件目录内。 |
| `resource_archives` | 可选 RCC 路径，直接注册 QML/图像资源，无需解压。 |
| `worker_archives` | 独立工作进程自行加载的私有 ZIP；宿主不挂载这些推理依赖。 |
| `priority` | `append`（默认，基础环境优先）或 `prepend`（插件覆盖宿主依赖）。 |

**默认用 `append`。** 只有当插件确实需要覆盖宿主自带的某个包时才用 `prepend`，
并在插件文档里说明原因——它会影响整个进程。

随包 CPU、CUDA、VL 的 `vendor_dirs` 和 `dll_dirs` 均为空，私有依赖只由各自工作进程加载，可以同时启用。旧式宿主内插件可用 `conflicts` 声明冲突（§3.5）。

---

## 9. 插件状态

| 状态 | 含义 | 用户可做什么 |
| --- | --- | --- |
| `ready` | 校验通过、已启用、能力已注册 | 正常使用 |
| `disabled` | 用户主动禁用 | 在插件管理中重新启用，即时更新 |
| `incompatible` | 宿主 API / 平台 / 架构 / 能力类型不匹配 | 升级 Umi-OCR 或换匹配的插件版本 |
| `conflict` | 与另一个已启用插件互斥 | 禁用其中一个后刷新；随包插件互不冲突 |
| `invalid` | 清单缺失或非法 | 重新解压插件归档 |
| `error` | 导入或注册阶段失败 | 看 `message`，通常是依赖不完整 |
| `unhealthy` | 健康检查未通过 | 按 `message` 给出的指引修复 |

每条记录都带 `message` 说明原因。**没有"静默消失"这个状态**——
这正是契约 v1 里 `group="document"` 插件遇到的问题。

### 安装 / 卸载

- **安装**：把插件归档解压到 Umi-OCR 本体目录。归档的第一层必须是
  `UmiOCR-data/plugins/<插件id>/`，不能再包一层产品目录，也不能要求用户
  `pip install`。在插件管理中刷新发现、启用和健康检查状态。
- **禁用**：插件管理中关闭；活动任务结束后终止对应独立工作进程，释放其内存与显存。宿主无需重启。第三方插件若把原生库装入宿主，其卸载限制由插件声明。
- **卸载**：删除 `UmiOCR-data/plugins/<插件id>/` 整个目录后刷新插件状态。
  插件的私有配置项会随之从设置界面消失，已保存的值保留在 `.settings` 中不影响使用。

### 发布归档最低内容

发布前必须解压到一个空目录并通过 `Audit-Package.ps1 -Kind plugin`。归档必须有：

- 顶层 `COPYING`、`LICENSE`、`NOTICE.md`；
- 安装载荷 `UmiOCR-data/plugins/<插件id>/`，包括清单、实际声明的 QML、私有
  `vendor/`/DLL 目录、`runtime.lock.json`，以及有私有运行时的依赖锁；
- `source/` 对应源码镜像，至少含插件清单、构建脚本和依赖锁。

`document` 插件可在**源码与文案**中说明用户自备的服务端和模型路径，但归档内
不得携带 GGUF、mmproj、llama.cpp 可执行文件或未确认可再分发的版面/模型权重。
“可被发现”不等于“可用”：必须以健康检查通过为准。

---

## 10. 旧版插件兼容

只有 `__init__.py` 里的 `PluginInfo`、没有 `umi-plugin.json` 的插件仍然可用：

```python
PluginInfo = {
    "group": "ocr",
    "global_options": {...},
    "local_options": {...},
    "api_class": Api,
    "page": {"key": "...", "qml": "...", "needController": False, ...},
}
```

宿主会把它适配成一份等价清单：

| PluginInfo | 适配结果 |
| --- | --- |
| `group` | 单个 capability 的 `type` |
| `api_class` | 已求值的能力入口（不再惰性） |
| `global_options` / `local_options` | 能力配置 |
| `page` | 单个 page |
| —— | `version = "0.0.0"`，`host_api = "*"`，平台/架构不限制 |

适配出的记录标记 `legacy = true`，界面会显示为旧版插件。

**已知限制**：

1. 旧版插件**必须被导入**才能读到 `PluginInfo`，因此享受不到"发现阶段零导入"。
2. 旧版 `page.needController = true` 但没有控制器入口时，v1 会静默失败；
   v2 明确降级为无控制器页并写日志。
3. 没有版本、平台、架构、依赖闭包和健康检查信息，宿主无法为其做兼容性判断。

**建议新插件一律使用 `umi-plugin.json`。**

---

## 11. 兼容矩阵

| 宿主版本 | 清单 schema | `host_api` 取值 | 旧版 `PluginInfo` | `document` 能力 | 插件页控制器 | 共享服务 |
| --- | --- | --- | --- | --- | --- | --- |
| ≤ 2.6 | 不支持 | —— | 支持（唯一方式） | **不支持** | **不支持** | **不支持** |
| 2.7 | 1 | `2.7` | 支持（适配层） | 支持 | 支持 | **不支持** |
| 2.8 | 1 | `>=2.8,<3.0` | 支持（适配层） | 支持 | 支持 | 支持 |

在 2.6 及更早的宿主上，带 `umi-plugin.json` 的插件如果同时保留了
`PluginInfo`，仍会按旧路径加载；否则会被旧宿主忽略。
内置的 `win32_PaddleOCRv6_CUDA` 就同时保留了两者。

---

## 12. 最小可用示例

```
plugins/win32_MyOcr/
├── umi-plugin.json
├── __init__.py      （空文件即可）
└── api.py
```

`umi-plugin.json`：

```json
{
  "schema_version": 1,
  "id": "win32_MyOcr",
  "name": "My OCR",
  "version": "1.0.0",
  "host_api": ">=2.8,<3.0",
  "platform": ["win32"],
  "arch": ["x86_64"],
  "capabilities": [
    {
      "type": "ocr",
      "entry": "api:Api",
      "config": {
        "global_options": {"title": "My OCR", "type": "group"},
        "local_options": {"title": "识别设置", "type": "group"}
      }
    }
  ]
}
```

`api.py`：

```python
class Api:
    def __init__(self, globalArgd):
        self.argd = globalArgd

    def start(self, argd):
        return ""

    def runPath(self, imgPath):
        return {"code": 100, "data": [
            {"box": [[0, 0], [10, 0], [10, 10], [0, 10]], "text": "hello", "score": 1.0}
        ]}

    def runBytes(self, imageBytes):
        return {"code": 101, "data": ""}

    def runBase64(self, imageBase64):
        return {"code": 101, "data": ""}

    def warmup(self, argd):
        return "[Success]"

    def get_status(self):
        return {"state": "loaded", "idleSeconds": 0, "error": ""}

    def release(self):
        return "[Success]"

    def stop(self):
        pass
```

解压到 `UmiOCR-data/plugins/` 后刷新插件状态，就能在【全局设置 → 文字识别 → 当前接口】里选到它。

---

## 13. 许可证提示

Umi-OCR 本体的 Windows 组合发行版是 AGPL-3.0-or-later（详见
[`LICENSES/COMBINED_DISTRIBUTION.md`](../LICENSES/COMBINED_DISTRIBUTION.md)）。

插件以**独立归档**分发、通过本规范定义的接口与宿主交互。
不同的分发与链接方式对应不同的许可证义务，**请自行评估你的插件应当采用什么许可证**。
本文档不构成法律意见，也不代表 Umi-OCR 项目对任何第三方插件的授权。

插件如需携带模型权重或第三方二进制，**必须自行确认其再分发许可**，
并在插件的 `NOTICE` / `LICENSES` 中逐项列明来源、许可证与用途。
