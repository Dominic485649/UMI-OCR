from .output_txt import OutputTxt
from .output_txt_plain import OutputTxtPlain
from .output_txt_individual import OutputTxtIndividual
from .output_md import OutputMD, OutputMDIndividual
from .output_jsonl import OutputJsonl
from .output_csv import OutputCsv
from .output_pdf_layered import OutputPdfLayered
from .output_pdf_one_layer import OutputPdfOneLayer

"""识别结果输出器。初始化传入参数字典：
    outputArgd = {
        "outputDir": "",  # 输出路径
        "outputDirType": "",  # 输出目录类型，"source" 为原文件目录，"specify"为指定目录
        "outputFileName": "",  # 输出文件名（前缀）
        "startDatetime": "",  # 开始日期字符串（标准格式）
        "ignoreBlank": True/False,  # 忽略空白文件
    }
"""
Output = {
    # 纯文本输出器
    "txt": OutputTxt,
    "txtPlain": OutputTxtPlain,
    "txtIndividual": OutputTxtIndividual,
    "md": OutputMD,
    "mdIndividual": OutputMDIndividual,
    "jsonl": OutputJsonl,
    "csv": OutputCsv,
    # PDF输出器，需要额外的参数 "originPath" 原始文件路径
    "pdfLayered": OutputPdfLayered,
    "pdfOneLayer": OutputPdfOneLayer,
}


def output_factories(formats, *, compatibility=False, registry=None):
    """UI 迁移旧 TXT 选项；HTTP 显式兼容请求仍可取得 .md.txt。"""
    aliases = {"txtPlain": "txt"} if compatibility else {
        "txt": "md", "txtPlain": "md", "txtIndividual": "mdIndividual"}
    registry = Output if registry is None else registry
    selected, seen = [], set()
    for key in formats:
        key = aliases.get(key, key)
        if key not in seen:
            selected.append((key, registry[key]))
            seen.add(key)
    return selected


def ui_output_factories(options, *, registry=None):
    prefix = "mission.filesType."
    return output_factories((key[len(prefix):] for key, enabled in options.items()
                             if key.startswith(prefix) and enabled), registry=registry)
