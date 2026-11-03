"""宿主级可选 UI 能力。只影响界面，不参与模型、任务或 HTTP 鉴权。"""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
import sys
import threading

DLL_NAME = "Umi-OCR-UIUnlock.dll"
DLL_ABI = 1
DOCUMENT_UI_FEATURE = "structured_document_ui"
_DOCUMENT_UI_PLUGIN_ID = (
    "win32_PaddleOCRVL_1_6"
)
_DOCUMENT_UI_FLAG = 1
_MAX_DLL_BYTES = 1024 * 1024
# 私有实现不在仓库内；公开宿主仅保留已核验产物的信任绑定和 C ABI。
_TRUSTED_DLL_SHA256 = frozenset({
    "7485dd3a492a283e5c46b05df9e9de7059752f166aaf8668bcfa15c5641d892e",
})
_state = None
_state_lock = threading.Lock()
_native_modules = []  # 模块持有至进程退出，不留下已卸载 DLL 的函数指针。


@dataclass(frozen=True)
class UiUnlockState:
    enabled: bool
    reason: str
    sha256: str = ""


def _program_root(module_file):
    path = Path(module_file).absolute()
    for parent in path.parents:
        if parent.name.casefold() == "app.zip":
            return parent.parent.parent
    return path.parents[3]


def _plain_file(path):
    for candidate in (path, *path.parents):
        info = candidate.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("UI 解锁路径包含链接或重解析点")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= _MAX_DLL_BYTES:
        raise ValueError("UI 解锁文件类型、硬链接或大小无效")


def _query_locked(path):
    import ctypes
    from ctypes import wintypes
    import msvcrt

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    close.restype = wintypes.BOOL
    final_name = kernel.GetFinalPathNameByHandleW
    final_name.argtypes = (wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD)
    final_name.restype = wintypes.DWORD
    # GENERIC_READ / FILE_SHARE_READ：校验和加载期间拒绝文件被写入或替换。
    handle = create(str(path), 0x80000000, 0x1, None, 3, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        count = final_name(handle, buffer, len(buffer), 0)
        if not count or count >= len(buffer):
            raise ValueError("无法核对 UI 解锁文件的句柄路径")
        actual = buffer.value.removeprefix("\\\\?\\")
        if os.path.normcase(os.path.abspath(actual)) != os.path.normcase(str(path)):
            raise ValueError("UI 解锁文件句柄落在预期路径之外")
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        handle = None  # 所有权移交给文件对象。
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if info.st_nlink != 1 or not 0 < info.st_size <= _MAX_DLL_BYTES:
                raise ValueError("UI 解锁文件在打开时已改变")
            digest = hashlib.sha256()
            total = 0
            for chunk in iter(lambda: stream.read(65536), b""):
                total += len(chunk)
                if total > _MAX_DLL_BYTES:
                    raise ValueError("UI 解锁文件超过预算")
                digest.update(chunk)
            checksum = digest.hexdigest()
            if checksum not in _TRUSTED_DLL_SHA256:
                return UiUnlockState(False, "untrusted-content", checksum)
            # 绝对路径；依赖仅从 DLL 所在目录和 System32 搜索，不依赖 CWD/PATH。
            module = ctypes.WinDLL(str(path), winmode=0x100 | 0x800)
            query = module.UmiUiUnlock_Query
            query.argtypes = (ctypes.c_uint32,)
            query.restype = ctypes.c_uint32
            capabilities = query(DLL_ABI)
            _native_modules.append(module)
            if not capabilities & _DOCUMENT_UI_FLAG:
                return UiUnlockState(False, "capability-unavailable", checksum)
            return UiUnlockState(True, "unlocked", checksum)
    finally:
        if handle is not None:
            close(handle)


def probe_ui_unlock(program_root):
    """校验指定程序根中的可选 DLL；调用方只读取能力，不从环境变量接受解锁。"""
    if sys.platform != "win32":
        return UiUnlockState(False, "unsupported-platform")
    path = Path(program_root).absolute() / DLL_NAME
    if str(path).startswith(("\\\\", "//")):
        return UiUnlockState(False, "invalid")
    try:
        _plain_file(path)
        return _query_locked(path)
    except FileNotFoundError:
        return UiUnlockState(False, "missing")
    except (OSError, ValueError, AttributeError, TypeError):
        return UiUnlockState(False, "invalid")


def get_ui_unlock_state():
    global _state
    with _state_lock:
        if _state is None:
            _state = probe_ui_unlock(_program_root(__file__))
            if not _state.enabled and _state.reason not in {"missing", "unsupported-platform"}:
                from umi_log import logger
                logger.warning("UI 解锁 DLL 未通过校验，相关界面保持关闭；HTTP 能力不受影响。")
        return _state


def required_page_feature(plugin_id, page_key):
    if plugin_id == _DOCUMENT_UI_PLUGIN_ID and page_key == "StructuredDocument":
        return DOCUMENT_UI_FEATURE
    return ""


def is_ui_feature_enabled(feature):
    if not feature:
        return True
    return feature == DOCUMENT_UI_FEATURE and get_ui_unlock_state().enabled


def ui_feature_snapshot():
    state = get_ui_unlock_state()
    return {"documentUi": state.enabled, "unlockState": state.reason, "unlockAbi": DLL_ABI,
            "documentUiBackends": [_DOCUMENT_UI_PLUGIN_ID]}
