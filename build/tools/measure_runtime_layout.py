"""只读统计运行目录和顶层依赖包，不把文件数或ZIP合并当作启动性能。"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import time


def reject_links(path):
    path = Path(path).absolute()
    for node in (path, *path.parents):
        info = node.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("统计拒绝链接或junction：" + str(node))
    return path


def new_counter():
    return {"files": 0, "smallFiles64KiB": 0, "pythonFiles": 0,
            "logicalBytes": 0, "allocatedBytes": 0, "allocationUnavailable": 0}


def allocation_reader():
    if os.name != "nt":
        return lambda path, info: getattr(info, "st_blocks", 0) * 512 if hasattr(info, "st_blocks") else None
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                       ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    create.restype = ctypes.c_void_p
    query = kernel.GetFileInformationByHandleEx
    query.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    query.restype = ctypes.c_int
    close = kernel.CloseHandle
    close.argtypes = [ctypes.c_void_p]
    close.restype = ctypes.c_int

    class FileStandardInfo(ctypes.Structure):
        _fields_ = [("AllocationSize", ctypes.c_longlong), ("EndOfFile", ctypes.c_longlong),
                    ("NumberOfLinks", ctypes.c_uint32), ("DeletePending", ctypes.c_ubyte),
                    ("Directory", ctypes.c_ubyte)]

    def allocated(path, info):
        handle = create(str(path), 0x80, 7, None, 3, 0, None)
        if handle == ctypes.c_void_p(-1).value:
            return None
        try:
            details = FileStandardInfo()
            if not query(handle, 1, ctypes.byref(details), ctypes.sizeof(details)):
                return None
            return details.AllocationSize
        finally:
            close(handle)

    return allocated


def measure(root, packages=False):
    root = reject_links(root)
    if not root.is_dir():
        raise ValueError("统计根必须为目录")
    counters, total = {}, new_counter()
    allocated = allocation_reader()
    started = time.perf_counter()
    pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                    raise ValueError("统计拒绝链接或junction：" + str(path))
                if stat.S_ISDIR(info.st_mode):
                    pending.append(path)
                    continue
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError("统计拒绝非普通文件：" + str(path))
                parts = path.relative_to(root).parts
                if packages:
                    area = parts[0]
                elif parts[0] == "UmiOCR-data" and len(parts) > 2:
                    area = "/".join(parts[:4] if parts[1] == "plugins" and len(parts) > 3 else parts[:2])
                    if parts[1] == "plugins":
                        area = "/".join(parts[:3])
                else:
                    area = parts[0] if len(parts) > 1 else "<root-files>"
                disk_size = allocated(path, info)
                for counter in (total, counters.setdefault(area, new_counter())):
                    counter["files"] += 1
                    counter["smallFiles64KiB"] += int(info.st_size <= 65536)
                    counter["pythonFiles"] += int(path.suffix.lower() == ".py")
                    counter["logicalBytes"] += info.st_size
                    counter["allocatedBytes"] += disk_size or 0
                    counter["allocationUnavailable"] += int(disk_size is None)
    return {"root": str(root), "observedAtUtc": datetime.now(timezone.utc).isoformat(),
            "elapsedSeconds": time.perf_counter() - started, "total": total,
            "areas": dict(sorted(counters.items())),
            "boundary": "只读文件元数据；不读配置内容、不递归进入链接，不测启动或识别性能。分配空间为当前文件系统查询结果。"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--packages", action="store_true")
    args = parser.parse_args()
    reject_links(args.output.parent)
    if args.output.exists():
        raise FileExistsError("拒绝覆盖旧布局统计：" + str(args.output))
    result = measure(args.root, args.packages)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"root": result["root"], "total": result["total"], "report": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
