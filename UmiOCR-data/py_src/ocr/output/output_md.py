"""统一 Markdown 输出；TXT 仅是相同内容的兼容文件扩展名。"""
from .output import Output
from .tools import getDataText
from ...utils.image_formats import IMAGE_SUFFIXES

import hashlib
import os
from pathlib import Path
from urllib.parse import quote


def markdown_record(res, output_path):
    name = str(res["fileName"]).replace("[", "\\[").replace("]", "\\]")
    try:
        path = quote(os.path.relpath(res["path"], os.path.dirname(output_path)).replace("\\", "/"), safe="/:")
    except ValueError:  # Windows 跨盘符无法计算相对路径。
        path = Path(res["path"]).resolve().as_uri()
    content = f"\n---\n## [{name}]({path})\n\n"
    if Path(res["path"]).suffix.lower() in IMAGE_SUFFIXES:
        content += f"![{name}]({path})\n\n"
    if res["code"] == 100:
        content += str(res.get("markdown") or getDataText(res["data"]))
    elif res["code"] != 101:
        content += f'> [Error] OCR failed. Code: {res["code"]}, Msg: {res["data"]}\n'
    return content.rstrip() + "\n\n"


class OutputMD(Output):
    extension = ".md"

    def __init__(self, argd):
        self.dir = argd["outputDir"]
        self.fileName = argd["outputFileName"]
        self.outputPath = f"{self.dir}/{self.fileName}{self.extension}"
        self.ignoreBlank = argd["ignoreBlank"]
        with open(self.outputPath, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(f'> {argd["startDatetime"]}\n\n')
        self.recordArtifact(self.outputPath)

    def print(self, res):
        if res["code"] != 100 and self.ignoreBlank:
            return
        with open(self.outputPath, "a", encoding="utf-8", newline="\n") as stream:
            stream.write(markdown_record(res, self.outputPath))


class OutputMDIndividual(Output):
    extension = ".md"

    def __init__(self, argd):
        super().__init__(argd)
        self.outputSource = argd["outputDirType"] == "source"
        self.attemptPrefix = bool(argd.get("attemptPrefix"))
        self.startDatetime = argd["startDatetime"]

    def openOutputFile(self):
        pass

    def print(self, res):
        if res["code"] != 100 and self.ignoreBlank:
            return
        if self.attemptPrefix:
            source = os.path.normcase(os.path.abspath(res["path"]))
            identity = hashlib.sha256(source.encode("utf-8", "surrogatepass")).hexdigest()[:32]
            stem = Path(res["fileName"]).stem
            directory = os.path.dirname(os.path.abspath(res["path"])) if self.outputSource else self.dir
            path = os.path.join(directory, f"{self.fileName}.{stem}.{identity}{self.extension}")
        elif self.outputSource:
            path = str(Path(res["path"]).with_suffix(self.extension))
        else:
            path = os.path.join(self.dir, Path(res["fileName"]).stem + self.extension)
        with open(path, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(f"> {self.startDatetime}\n\n" + markdown_record(res, path))
        self.recordArtifact(path, sourcePath=res["path"])


class OutputMDTxt(OutputMD):
    extension = ".md.txt"


class OutputMDTxtIndividual(OutputMDIndividual):
    extension = ".md.txt"
