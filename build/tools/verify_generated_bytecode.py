"""核验本轮自有运行生成的缓存；不执行缓存，不允许按后缀忽略未知文件。"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import marshal
from pathlib import Path
import struct
import sys
import types


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_generated_cache(root, relative, expected):
    """仅接受已有独立载荷清单中源码对应的当前解释器缓存。"""
    import runtime_archive_layout as layout

    root = layout.plain_path(root)
    relative = layout.canonical_relative(relative)
    path = layout.plain_path(root / relative)
    suffix = "." + sys.implementation.cache_tag + ".pyc"
    require(path.parent.name == "__pycache__" and path.name.endswith(suffix), "不是本次解释器的普通未优化缓存")
    source = layout.plain_path(path.parent.parent / (path.name[:-len(suffix)] + ".py"))
    source_relative = source.relative_to(root).as_posix()
    require(source_relative in expected, "缓存没有独立归档清单中的对应源码")
    require(path.stat().st_size <= 4 * 1024**2 and source.stat().st_size <= 4 * 1024**2, "缓存或源码超出本次有限核验范围")
    data, source_bytes = path.read_bytes(), source.read_bytes()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    require(source_sha == expected[source_relative], "对应源码与独立归档载荷不一致")
    require(len(data) >= 16 and data[:4] == importlib.util.MAGIC_NUMBER, "缓存版本或头部无效")
    flags = struct.unpack("<I", data[4:8])[0]
    if flags == 0:
        mtime, size = struct.unpack("<II", data[8:16])
        require(mtime == int(source.stat().st_mtime) & 0xffffffff and size == len(source_bytes) & 0xffffffff,
                "缓存时间戳或源码长度不匹配")
    else:
        require(flags in (1, 3) and data[8:16] == importlib.util.source_hash(source_bytes), "缓存标志或源码哈希不匹配")
    stream = io.BytesIO(data[16:])
    code = marshal.load(stream)
    require(isinstance(code, types.CodeType) and not stream.read(1), "缓存不是单个完整代码对象")
    require(Path(code.co_filename).is_absolute() and layout.plain_path(code.co_filename) == source,
            "缓存代码文件名不属于对应源码")
    # 仅在内存编译已核验原源码用于比较，不写入新的字节码或执行代码。
    compiled = compile(source_bytes, code.co_filename, "exec", dont_inherit=True, optimize=0)
    pending, seen = [(code, compiled)], 0
    fields = ("co_argcount", "co_posonlyargcount", "co_kwonlyargcount", "co_nlocals", "co_stacksize", "co_flags",
              "co_code", "co_consts", "co_names", "co_varnames", "co_filename", "co_name", "co_qualname",
              "co_firstlineno", "co_linetable", "co_exceptiontable", "co_freevars", "co_cellvars")
    while pending:
        actual, wanted = pending.pop()
        seen += 1
        require(seen <= 20000, "缓存代码对象超过有限预算")
        require(all(getattr(actual, field) == getattr(wanted, field) for field in fields), "缓存代码与原始源码不一致")
        pending.extend((left, right) for left, right in zip(actual.co_consts, wanted.co_consts)
                       if isinstance(left, types.CodeType) and isinstance(right, types.CodeType))
    return {"path": relative, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
            "source": source_relative, "sourceSha256": source_sha, "flags": flags,
            "codeObjectsVerified": seen, "sourceCodeMatches": True, "executed": False}
