import os


def default_preprocess_threads(cpu_count=None):
    count = max(1, int(cpu_count if cpu_count is not None else (os.cpu_count() or 1)))
    return count if count < 6 else count - 4


PRESETS = {
    "speed": {
        "detModel": "PP-OCRv6_medium",
        "recModel": "PP-OCRv6_medium",
        "docOrientation": False,
        "undistort": "off",
        "textlineOrientation": "off",
        "longSide": 1600,
        "recBatchSize": 16,
        "scoreThreshold": 0.60,
    },
    "balanced": {
        "detModel": "PP-OCRv6_medium",
        "recModel": "PP-OCRv6_medium",
        "docOrientation": True,
        "undistort": "auto",
        "textlineOrientation": "on",
        "longSide": 2560,
        "recBatchSize": 12,
        "scoreThreshold": 0.50,
    },
    "accuracy": {
        "detModel": "PP-OCRv6_medium",
        "recModel": "PP-OCRv6_medium",
        "docOrientation": True,
        "undistort": "auto",
        "textlineOrientation": "on",
        "longSide": 4000,
        "recBatchSize": 6,
        "scoreThreshold": 0.45,
    },
}


def _managed(title, default, tooltip, **extra):
    return {
        "title": title,
        "default": default,
        "toolTip": tooltip,
        "presetManaged": True,
        **extra,
    }


model_options = [
    ["PP-OCRv6_medium", "PP-OCRv6_medium（默认，高精度）"],
]

switch_options = [
    ["off", "关闭"],
    ["auto", "按任务自动"],
    ["on", "启用"],
]

globalOptions = {
    "title": "PP-OCRv6 CUDA",
    "type": "group",
    "hardware": {
        "title": "推理加速",
        "default": "cuda126",
        "optionsList": [["cuda126", "NVIDIA CUDA 12.6（必需）"]],
        "toolTip": "仅支持 NVIDIA GPU。CUDA 不可用时 OCR 会明确失败，不会切换 CPU、oneDNN、ONNX 或 DirectML。",
    },
    "device": {
        "title": "CUDA 设备",
        "default": "gpu:0",
        "toolTip": "默认 gpu:0。可填写 gpu:N 选择显卡；模型和中间张量会占用该卡显存，不提供 CPU 推理。",
    },
    "preprocessThreads": {
        "title": "预处理线程",
        "default": default_preprocess_threads(),
        "min": 1,
        "max": max(64, os.cpu_count() or 1),
        "isInt": True,
        "toolTip": "默认：逻辑核心少于 6 时使用全部核心，否则使用逻辑核心数减 4。仅控制 OpenCV/Python 图像预处理，不代表 CPU 推理；增加线程可降低预处理耗时，也会增加 CPU 与内存占用。",
        "advanced": True,
    },
}

localOptions = {
    "title": "高精度 PP-OCRv6",
    "type": "group",
    "preset": {
        "title": "识别预设",
        "default": "accuracy",
        "optionsList": [
            ["speed", "速度优先"],
            ["balanced", "均衡"],
            ["accuracy", "高精度（默认）"],
            ["custom", "自定义"],
        ],
        "presetValues": PRESETS,
        "toolTip": "仅在主动选择预设时覆盖下列参数；手动修改任一受管参数后立即显示为“自定义”。",
    },
    "detModel": _managed(
        "文字检测模型",
        "PP-OCRv6_medium",
        "仅安装 PP-OCRv6_medium。定位图片中的文字区域；提高小字、密集排版和复杂背景质量，但增加耗时、显存和内存。",
        optionsList=model_options,
    ),
    "recModel": _managed(
        "文字识别模型",
        "PP-OCRv6_medium",
        "仅安装 PP-OCRv6_medium。将文字区域转换为字符；提高准确率和统一多语言表现，但增加耗时、显存和内存。",
        optionsList=model_options,
    ),
    "docOrientation": _managed(
        "文档方向分类",
        True,
        "默认启用。自动旋转横放、倒置文档，提高方向错误时的质量；会增加少量耗时和显存。",
    ),
    "undistort": _managed(
        "文档去扭曲",
        "auto",
        "默认按任务自动：截图关闭，批量图片和渲染文档启用。校正弯曲、透视或褶皱，提高拍照书页质量，但增加耗时、显存和内存。",
        optionsList=switch_options,
    ),
    "textlineOrientation": _managed(
        "文本行方向分类",
        "on",
        "高精度默认启用。校正单独旋转的文字行，提高海报、标签和复杂排版质量；关闭可降低耗时和显存。",
        optionsList=switch_options,
    ),
    "longSide": _managed(
        "长边限制",
        4000,
        "高精度默认 4000 像素。提高数值可改善大图小字质量，但会增加耗时、显存和内存；降低数值可提速。",
        min=640,
        max=8000,
        isInt=True,
        unit="px",
        advanced=True,
    ),
    "recBatchSize": _managed(
        "识别批量大小",
        6,
        "高精度默认 6。提高批量可降低大量文本行的耗时，但会增加显存和内存；显存不足时应降低。",
        min=1,
        max=64,
        isInt=True,
        advanced=True,
    ),
    "scoreThreshold": _managed(
        "置信度阈值",
        0.45,
        "高精度默认 0.45。提高阈值可减少误识别并略降后处理耗时，但可能漏掉低对比文字；降低会保留更多候选。",
        min=0.0,
        max=1.0,
        isInt=False,
        advanced=True,
    ),
    "taskType": {
        "type": "text",
        "default": "screenshot",
        "save": False,
    },
}

# 插件契约 v2 的配置入口。宿主在发现阶段读取它来构建设置界面，
# 因此本模块必须保持轻量：只描述配置，不导入 paddle 等后端。
CONFIG = {
    "global_options": globalOptions,
    "local_options": localOptions,
}
