# ============================================
# =============== 文件查找/加载 ===============
# ============================================
# 从指定路径中，查找符合的文件

import re
import os
import time
from PySide6.QtQml import QJSValue
from typing import List

from ..event_bus.pubsub_service import PubSubService  # 发布事件
from ..mission.mission_doc import MissionDOC, DocSuf
from ..mission.mission_ocr import ImageSuf
from umi_log import logger


FileSuf = {  # 合法文件后缀
    "image": ImageSuf,
    "doc": DocSuf,
}


def _displayPath(path):
    try:
        return os.path.abspath(os.fspath(path)).replace("\\", "/")
    except (TypeError, ValueError, OSError):
        return str(path)


def _scanFiles(paths, sufs, isRecurrence, addFile):
    """Find matching files and return diagnostics for paths that could not import."""
    issues = []

    def addIssue(kind, path, message):
        issue = {"kind": kind, "path": _displayPath(path), "message": message}
        issues.append(issue)
        logger.warning(message)

    def isMatching(path):
        return os.path.splitext(path)[-1].lower() in sufs

    for path in paths:
        displayPath = _displayPath(path)
        try:
            if os.path.isfile(path):
                if isMatching(path):
                    addFile(os.path.abspath(path))
                else:
                    addIssue("unsupported", path, f"不支持的文件类型：{displayPath}")
                continue
            if not os.path.isdir(path):
                if os.path.lexists(path):
                    addIssue("invalid", path, f"不是可导入的文件或文件夹：{displayPath}")
                else:
                    addIssue("missing", path, f"路径不存在：{displayPath}")
                continue
        except OSError as exc:
            addIssue("unreadable", path, f"无法访问路径：{displayPath}（{exc}）")
            continue

        found = 0
        issueCount = len(issues)

        def addMatchedFile(filePath):
            nonlocal found
            addFile(filePath)
            found += 1

        if isRecurrence:
            def onWalkError(exc):
                errorPath = exc.filename or path
                addIssue(
                    "unreadable",
                    errorPath,
                    f"无法访问文件夹：{_displayPath(errorPath)}（{exc}）",
                )

            for root, _dirs, files in os.walk(path, onerror=onWalkError):
                for file in files:
                    if isMatching(file):
                        addMatchedFile(os.path.abspath(os.path.join(root, file)))
        else:
            try:
                with os.scandir(path) as entries:
                    for entry in entries:
                        try:
                            if entry.is_file() and isMatching(entry.name):
                                addMatchedFile(os.path.abspath(entry.path))
                        except OSError as exc:
                            addIssue(
                                "unreadable",
                                entry.path,
                                f"无法访问文件：{_displayPath(entry.path)}（{exc}）",
                            )
            except OSError as exc:
                addIssue("unreadable", path, f"无法访问文件夹：{displayPath}（{exc}）")

        if found == 0 and len(issues) == issueCount:
            addIssue("empty", path, f"文件夹中没有支持的文件：{displayPath}")

    return issues


# 同步从路径中搜索后缀符合要求的文件，返回路径列表。
def findFiles(
    paths: List,  # 初始路径列表
    sufType: str,  # 后缀类型，FileSuf的key
    isRecurrence: bool,  # 若为True，则递归搜索
):
    if isinstance(paths, QJSValue):
        paths = paths.toVariant()
    if not isinstance(paths, list):
        logger.error(f"不合法的路径列表：{paths}, {type(paths)}")
        return []
    sufs = FileSuf.get(sufType, "")
    if not sufs:
        logger.error(f"不合法的后缀类型：{sufs}")
        return []

    filePaths = []
    _scanFiles(paths, sufs, isRecurrence, filePaths.append)
    for i, p in enumerate(filePaths):  # 规范化正斜杠
        filePaths[i] = p.replace("\\", "/")
    return filePaths


# 异步从路径中搜索后缀符合要求的文件，并定时刷新UI。
# image: 返回路径列表
# doc: 返回 MissionDOC.getDocInfo 的信息字典列表
def asynFindFiles(
    paths: List,  # 初始路径列表
    sufType: str,  # 后缀类型，FileSuf的key
    isRecurrence: bool,  # 若为True，则递归搜索
    completeKey: str,  # 全部完成后的事件key。传入合法路径列表和错误信息列表。
    updateKey: str,  # UI刷新进度的事件key。填""则不刷新。向事件传入 (已完成的路径数量, 最近一条路径)
    updateTime: float,  # UI刷新进度的间距
):
    if isinstance(paths, QJSValue):
        paths = paths.toVariant()
    if not isinstance(paths, list):
        logger.error(f"不合法的路径列表：{paths}, {type(paths)}")
        PubSubService.publish(completeKey, [])
        return
    sufs = FileSuf.get(sufType, "")
    if not sufs:
        logger.error(f"不合法的后缀类型：{sufs}")
        PubSubService.publish(completeKey, [])
        return

    if not updateKey:  # 如果没有刷新事件，则刷新间隔为无穷大
        updateTime = float("inf")
    filePaths = []
    issues = []
    lastTime = 0  # 上一次update事件的时间

    def updateEvent(fp):
        nonlocal lastTime
        now = time.time()
        if now - lastTime > updateTime:
            PubSubService.publish(updateKey, len(filePaths), fp)
            lastTime = now

    def addFile(fp):
        fp = fp.replace("\\", "/")  # 规范化正斜杠
        if sufType == "doc":  # 文档读取信息
            info = MissionDOC.getDocInfo(fp)
            if "error" in info:
                logger.warning(f'读入文档失败：{fp}, {info["error"]}')
                issues.append(
                    {
                        "kind": "unreadable",
                        "path": fp,
                        "message": f'读入文档失败：{fp}（{info["error"]}）',
                    }
                )
            else:
                filePaths.append(info)
        else:
            filePaths.append(fp)
        updateEvent(fp)

    issues.extend(_scanFiles(paths, sufs, isRecurrence, addFile))

    PubSubService.publish(completeKey, filePaths, issues)
