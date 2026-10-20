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
from ..mission.mission_doc import DocSuf
from ..mission.mission_ocr import ImageSuf
from .doc_probe import PROBE_BATCH_SIZE, probe_documents
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
    """枚举支持的文件，并为无法导入的路径保留可见诊断。"""
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
        except (TypeError, ValueError, OSError) as exc:
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
# doc: 返回隔离进程读取的文档信息字典列表
def asynFindFiles(
    paths: List,  # 初始路径列表
    sufType: str,  # 后缀类型，FileSuf的key
    isRecurrence: bool,  # 若为True，则递归搜索
    completeKey: str,  # 全部完成后的事件key。传入合法路径列表和错误信息列表。
    updateKey: str,  # UI刷新进度的事件key。填""则不刷新。向事件传入 (已完成的路径数量, 最近一条路径)
    updateTime: float,  # UI刷新进度的间距
):
    filePaths = []
    issues = []
    pending = []
    lastTime = 0

    def addIssue(kind, path, message):
        issues.append({"kind": kind, "path": path, "message": message})
        logger.warning(message)

    def updateEvent(fp):
        nonlocal lastTime
        now = time.monotonic()
        if updateKey and now - lastTime > updateTime:
            PubSubService.publish(updateKey, len(filePaths), fp)
            lastTime = now

    def flushDocuments():
        if not pending:
            return
        batch = pending.copy()
        pending.clear()
        try:
            # 每次最多缓存固定数量的路径；扫描线程不调用 fitz，也不先读完整个目录树。
            infos = list(probe_documents(batch))
            if len(infos) != len(batch):
                raise ValueError("文档读取结果数量不匹配")
        except Exception as exc:
            message = f"文档读取异常（{type(exc).__name__}）。"
            infos = [{"error": message, "error_kind": "workererror"} for _ in batch]
        for fp, info in zip(batch, infos):
            if "error" in info:
                addIssue(
                    info.get("error_kind", "unreadable"),
                    fp,
                    f'读入文档失败：{fp}（{info["error"]}）',
                )
            else:
                filePaths.append(info)
            updateEvent(fp)

    def addFile(fp):
        fp = fp.replace("\\", "/")
        if sufType == "doc":
            pending.append(fp)
            if len(pending) >= PROBE_BATCH_SIZE:
                flushDocuments()
        else:
            filePaths.append(fp)
            updateEvent(fp)

    try:
        if isinstance(paths, QJSValue):
            paths = paths.toVariant()
        if not isinstance(paths, list):
            addIssue("invalid", "", "不合法的路径列表。")
            return
        sufs = FileSuf.get(sufType, "") if isinstance(sufType, str) else ""
        if not sufs:
            addIssue("invalid", "", "不合法的后缀类型。")
            return
        if updateKey:
            updateTime = max(0.0, float(updateTime))
        issues.extend(_scanFiles(paths, sufs, isRecurrence, addFile))
    except Exception as exc:
        addIssue("scanerror", "", f"文件扫描异常（{type(exc).__name__}）：{exc}")
    finally:
        # 正常、空结果、参数错误或扫描异常，都只能从这里发送一次双参数终态。
        # 已枚举到的文档即使在后续扫描异常时也要结算，不能遗失导入票据。
        try:
            flushDocuments()
        except Exception as exc:
            addIssue("scanerror", "", f"文档导入汇总异常（{type(exc).__name__}）：{exc}")
        finally:
            PubSubService.publish(completeKey, filePaths, issues)
