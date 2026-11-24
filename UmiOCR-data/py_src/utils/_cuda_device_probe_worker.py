"""只查询系统 NVIDIA Driver API 的短生命周期 worker，不创建 CUDA 上下文。"""

import ctypes
import json
import os
import sys


_MAX_DEVICES = 64
_NAME_BUFFER_BYTES = 256
_LOAD_LIBRARY_SEARCH_SYSTEM32 = 0x00000800
_CUDA_ERROR_NO_DEVICE = 100


class _DriverMissing(Exception):
    pass


class _DriverError(Exception):
    pass


class _Uuid(ctypes.Structure):
    _fields_ = [("bytes", ctypes.c_ubyte * 16)]


def _load_driver():
    if os.name != "nt":
        raise _DriverError("不支持的平台")
    # 不信任 PATH、当前目录或可改写的 SystemRoot 环境变量。
    kernel32 = ctypes.WinDLL("kernel32.dll", winmode=_LOAD_LIBRARY_SEARCH_SYSTEM32)
    get_system_directory = kernel32.GetSystemDirectoryW
    get_system_directory.argtypes = [ctypes.POINTER(ctypes.c_wchar), ctypes.c_uint]
    get_system_directory.restype = ctypes.c_uint
    buffer = ctypes.create_unicode_buffer(32768)
    length = get_system_directory(buffer, len(buffer))
    if not 0 < length < len(buffer) or not os.path.isabs(buffer.value):
        raise _DriverError("系统目录无效")
    driver_path = os.path.join(buffer.value, "nvcuda.dll")
    try:
        return ctypes.WinDLL(driver_path, winmode=_LOAD_LIBRARY_SEARCH_SYSTEM32)
    except OSError as exc:
        if isinstance(exc, FileNotFoundError) or getattr(exc, "winerror", None) == 126:
            raise _DriverMissing() from None
        raise


def _bind(driver, name, argtypes):
    function = getattr(driver, name)
    function.argtypes = argtypes
    function.restype = ctypes.c_int
    return function


def _check(code):
    if code != 0:
        raise _DriverError("驱动查询失败")


def _query_devices(driver):
    initialize = _bind(driver, "cuInit", [ctypes.c_uint])
    result = initialize(0)
    if result == _CUDA_ERROR_NO_DEVICE:
        return []
    _check(result)
    count = ctypes.c_int()
    get_count = _bind(driver, "cuDeviceGetCount", [ctypes.POINTER(ctypes.c_int)])
    result = get_count(ctypes.byref(count))
    if result == _CUDA_ERROR_NO_DEVICE:
        return []
    _check(result)
    if not 0 <= count.value <= _MAX_DEVICES:
        raise _DriverError("设备数量超出上限")
    if not count.value:
        return []
    get_device = _bind(driver, "cuDeviceGet", [ctypes.POINTER(ctypes.c_int), ctypes.c_int])
    get_name = _bind(driver, "cuDeviceGetName", [ctypes.POINTER(ctypes.c_char), ctypes.c_int, ctypes.c_int])
    # v2 可区分 MIG 计算实例；旧驱动只缺此符号时使用原版 UUID 接口。
    uuid_symbol = "cuDeviceGetUuid_v2" if hasattr(driver, "cuDeviceGetUuid_v2") else "cuDeviceGetUuid"
    get_uuid = _bind(driver, uuid_symbol, [ctypes.POINTER(_Uuid), ctypes.c_int])
    devices = []
    for ordinal in range(count.value):
        device = ctypes.c_int()
        _check(get_device(ctypes.byref(device), ordinal))
        name_buffer = ctypes.create_string_buffer(_NAME_BUFFER_BYTES)
        _check(get_name(name_buffer, len(name_buffer), device.value))
        if b"\x00" not in name_buffer.raw:
            raise _DriverError("设备名称未终止")
        name = name_buffer.value.decode("utf-8")
        uuid = _Uuid()
        _check(get_uuid(ctypes.byref(uuid), device.value))
        hex_uuid = bytes(uuid.bytes).hex()
        uuid_text = "GPU-" + "-".join((hex_uuid[:8], hex_uuid[8:12], hex_uuid[12:16], hex_uuid[16:20], hex_uuid[20:]))
        # 保留驱动在继承环境下给出的逻辑顺序，不映射或猜测物理卡号。
        devices.append({"value": f"gpu:{ordinal}", "ordinal": ordinal, "name": name, "uuid": uuid_text})
    return devices


def _probe():
    try:
        devices = _query_devices(_load_driver())
        return {"state": "ready" if devices else "no_devices", "devices": devices}
    except _DriverMissing:
        return {"state": "driver_missing", "devices": []}
    except Exception:
        # 不输出异常、DLL 路径、环境或驱动原始诊断。
        return {"state": "failed", "devices": []}


def main():
    response = json.dumps(_probe(), ensure_ascii=False, separators=(",", ":"))
    sys.stdout.buffer.write(response.encode("utf-8"))
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
