"""轻量参数描述；模型与预设展示由统一宿主入口管理。"""
import os
from .i18n_helpers import tr


def default_preprocess_threads(cpu_count=None):
    count = max(1, int(cpu_count if cpu_count is not None else (os.cpu_count() or 1)))
    return count if count < 6 else count - 4


DEFAULT_OPTIONS = {
    "detModel": "PP-OCRv6_medium", "recModel": "PP-OCRv6_medium",
    "docOrientation": True, "undistort": "auto", "textlineOrientation": "on",
    "longSide": 4000, "recBatchSize": 6, "scoreThreshold": 0.45,
}


def option(title, default, tooltip="", **extra):
    value = {"title": tr(title), "default": default, **extra}
    if tooltip:
        value["toolTip"] = tr(tooltip)
    return value


switch_options = [["off", tr("关闭")], ["auto", tr("按任务自动")], ["on", tr("启用")]]
model_options = [["PP-OCRv6_medium", "PP-OCRv6_medium"]]

globalOptions = {
    "title": "PP-OCRv6_medium", "modelName": "PP-OCRv6_medium", "type": "group",
    "hardware": option("推理加速", "cuda126",
        "仅支持 NVIDIA GPU。CUDA 不可用时明确失败，不会切换 CPU 推理。",
        optionsList=[["cuda126", "NVIDIA CUDA 12.6"]]),
    "device": option("CUDA 设备", "gpu:0", "使用 gpu:N 选择显卡，默认 gpu:0。",
        deviceProvider="nvidia-cuda"),
    "preprocessThreads": option("预处理线程", default_preprocess_threads(),
        "仅控制图像预处理，不代表 CPU 推理。增加线程也会增加 CPU 与内存占用。",
        min=1, max=max(64, os.cpu_count() or 1), isInt=True, advanced=True),
}

localOptions = {
    "title": tr("模型参数"), "modelName": "PP-OCRv6_medium", "type": "group",
    # 机器参数保留，单一模型不重复绘制无意义的下拉框。
    "detModel": {"default": "PP-OCRv6_medium", "optionsList": model_options},
    "recModel": {"default": "PP-OCRv6_medium", "optionsList": model_options},
    "docOrientation": option("文档方向分类", True, "校正横放、倒置的文档，会增加少量计算。"),
    "undistort": option("文档去扭曲", "auto",
        "按任务自动时，截图关闭，批量图片和文档启用。", optionsList=switch_options),
    "textlineOrientation": option("文本行方向分类", "on",
        "校正单独旋转的文字行，关闭可减少计算。", optionsList=switch_options),
    "longSide": option("长边限制", 4000,
        "控制检测分辨率。超出单次预算的图片会分块处理，而不是静默缩小整图。",
        min=640, max=8000, isInt=True, unit="px", advanced=True),
    "recBatchSize": option("识别批量大小", 6,
        "增加批量可提高多行识别速度，也会增加显存占用。",
        min=1, max=64, isInt=True, advanced=True),
    "scoreThreshold": option("置信度阈值", 0.45,
        "提高阈值可减少误识别，但可能遗漏低对比文字。",
        min=0.0, max=1.0, isInt=False, advanced=True),
    "taskType": {"type": "text", "default": "screenshot", "save": False},
}

CONFIG = {"global_options": globalOptions, "local_options": localOptions}
