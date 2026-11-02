"""仅用标准库和 mock 验证设备发现边界，不调用真实 CUDA 驱动或模型。"""

from concurrent.futures import Future, ThreadPoolExecutor
import ctypes
import importlib.abc
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Event, Lock
import time
import types
import unittest
from unittest.mock import Mock, patch
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "UmiOCR-data"
TEMP_ROOT = ROOT / "build" / "tmp" / "settings-gpu-20261027-r1"
sys.path.insert(0, str(SOURCE))
from py_src.utils import cuda_device_probe as probe
from py_src.utils import _cuda_device_probe_worker as worker
from py_src.utils import doc_probe


PATHS = (SOURCE, SOURCE, Path(sys.executable).parent.parent, Path(sys.executable))


def device(ordinal=0, name="NVIDIA 同名设备", uuid_number=None):
    number = ordinal + 1 if uuid_number is None else uuid_number
    return {"value": f"gpu:{ordinal}", "ordinal": ordinal, "name": name,
            "uuid": f"GPU-00000000-0000-0000-0000-{number:012x}"}


def record(devices=None, state="ready"):
    return {"state": state, "devices": [device()] if devices is None else devices}


def encoded(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


class FakeProcess:
    def __init__(self, output, exit_code=0, wait_timeout=False):
        self.stdout = io.BytesIO(output)
        self.returncode = None
        self.exit_code = exit_code
        self.wait_timeout = wait_timeout
        self.kills = 0
        self.waits = []

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if self.returncode is None:
            if self.wait_timeout and timeout is not None:
                raise subprocess.TimeoutExpired("测试子进程", timeout)
            self.returncode = self.exit_code
        return self.returncode

    def kill(self):
        self.kills += 1
        self.returncode = -9


class ProbeCase(unittest.TestCase):
    def setUp(self):
        with probe._CACHE_LOCK:
            self.assertFalse(probe._INFLIGHT, "上次测试残留了在途发现")
            probe._CACHE.clear()
        self.runtime_patch = patch.object(probe, "_runtime_paths", return_value=PATHS)
        self.runtime_patch.start()
        self.addCleanup(self.runtime_patch.stop)
        self.translation_patch = patch.object(probe, "tr", side_effect=lambda text, **values: text.format(**values))
        self.translation_patch.start()
        self.addCleanup(self.translation_patch.stop)


class ProtocolTests(ProbeCase):
    def test_safe_command_and_inherited_environment(self):
        process = FakeProcess(encoded(record([device(0, uuid_number=7), device(1, uuid_number=3)])))
        with patch.dict(os.environ, {"CUDA_VISIBLE_DEVICES": "7,3", "CUDA_DEVICE_ORDER": "PCI_BUS_ID",
                                     "PYTHONPATH": r"Z:\不可信路径"}), patch.object(
                probe.subprocess, "Popen", return_value=process) as popen:
            result = probe.discover_cuda_devices()
        self.assertEqual(result["devices"], [device(0, uuid_number=7), device(1, uuid_number=3)])
        command = popen.call_args.args[0]
        options = popen.call_args.kwargs
        self.assertEqual(command[0], str(PATHS[-1]))
        self.assertEqual(command[1:7], ["-I", "-B", "-X", "utf8", "-u", "-c"])
        self.assertEqual(command[7], probe._WORKER_BOOTSTRAP)
        self.assertEqual(command[8:], [str(SOURCE)])
        self.assertFalse(options["shell"])
        self.assertEqual(options["cwd"], str(SOURCE))
        self.assertEqual(options["stdin"], subprocess.DEVNULL)
        self.assertEqual(options["stderr"], subprocess.DEVNULL)
        self.assertEqual(options["stdout"], subprocess.PIPE)
        self.assertEqual(options["env"]["CUDA_VISIBLE_DEVICES"], "7,3")
        self.assertEqual(options["env"]["CUDA_DEVICE_ORDER"], "PCI_BUS_ID")
        self.assertEqual(probe._PROBE_TIMEOUT_SECONDS, 10.0)
        self.assertTrue(process.stdout.closed)
        self.assertIsNotNone(process.poll())

    def test_driver_states_and_empty_devices(self):
        for state in ("no_devices", "driver_missing", "failed"):
            with self.subTest(state=state):
                process = FakeProcess(encoded(record([], state)))
                with patch.object(probe.subprocess, "Popen", return_value=process):
                    result = probe.discover_cuda_devices(force=True)
                self.assertEqual(result["state"], state)
                self.assertEqual(result["ok"], state == "no_devices")
                self.assertEqual(result["devices"], [])
                self.assertTrue(result["message"])
                self.assertEqual(set(result), {"ok", "state", "devices", "message"})

    def test_same_name_uuid_and_logical_order_are_preserved(self):
        devices = [device(0, uuid_number=9), device(1, uuid_number=2)]
        self.assertEqual(probe._parse_output(encoded(record(devices))), record(devices))
        all_devices = [device(index) for index in range(64)]
        self.assertEqual(probe._parse_output(encoded(record(all_devices)))["devices"], all_devices)

    def test_rejects_malformed_schema_and_strings(self):
        invalid = [None, [], True, {}, {"state": "ready", "devices": []},
                   record({}, "ready"), record([device()] * 65), record([device()], "no_devices"),
                   record([device()], "driver_missing"), record([], "timeout"),
                   {"state": True, "devices": []}, {**record(), "error": r"D:\私有目录"}]
        for field, value in (("ordinal", -1), ("ordinal", 1), ("ordinal", True), ("ordinal", 0.0),
                             ("value", "gpu:1"), ("value", 0), ("name", ""), ("name", "  "),
                             ("name", "x" * 256), ("name", "显" * 86), ("name", "NVIDIA\x00设备"),
                             ("name", "NVIDIA\n设备"), ("name", "NVIDIA\x85设备"), ("name", 42),
                             ("uuid", "GPU-invalid"), ("uuid", "x" * 2048), ("uuid", None)):
            invalid.append(record([{**device(), field: value}]))
        invalid += [record([{**device(), "extra": "不可信"}]), record([{"ordinal": 0}]),
                    record([device(0), device(0)]), record([device(0), device(2)]),
                    record([device(1), device(0)]), record([device(0), device(1, uuid_number=1)]),
                    record([device(0), {**device(1), "uuid": device(0)["uuid"].upper()}])]
        raw_invalid = [b"", b"not-json", b"\xff", b"{}\n{}", b'{"state":"failed","state":"ready","devices":[]}',
                       b'{"state":"ready","devices":[{"ordinal":0,"ordinal":0}]}',
                       b'{"state":"ready","devices":NaN}', b"[" * 2000 + b"]" * 2000]
        for value in invalid:
            raw_invalid.append(encoded(value))
        for raw in raw_invalid:
            with self.subTest(raw=raw[:120]):
                result = probe._parse_output(raw)
                self.assertEqual(result["state"], "failed")
                self.assertEqual(result["devices"], [])
                self.assertNotIn("私有目录", str(result))
        self.assertIn("过大", probe._parse_output(b"x" * (64 * 1024 + 1))["message_template"])

    def test_output_size_boundary(self):
        payload = encoded(record())
        bounded = payload.ljust(64 * 1024, b" ")
        self.assertEqual(probe._parse_output(bounded), record())
        self.assertEqual(probe._parse_output(bounded + b" ")["state"], "failed")

    def test_reader_thread_failure_reaps_owned_process(self):
        for target in ("constructor", "start"):
            process = FakeProcess(b"")
            thread_patch = (patch.object(probe, "Thread", side_effect=RuntimeError("读线程构造失败"))
                            if target == "constructor" else patch.object(probe.Thread, "start", side_effect=RuntimeError("读线程启动失败")))
            with self.subTest(target=target), thread_patch, patch.object(probe.subprocess, "Popen", return_value=process):
                result = probe.discover_cuda_devices(force=True)
            self.assertEqual(result["state"], "failed")
            self.assertEqual(process.kills, 1)
            self.assertIsNotNone(process.poll())
            self.assertTrue(process.stdout.closed)

    def test_exit_failure_does_not_accept_valid_output(self):
        process = FakeProcess(encoded(record()), exit_code=17)
        with patch.object(probe.subprocess, "Popen", return_value=process):
            result = probe.discover_cuda_devices()
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["devices"], [])
        self.assertIn("异常退出", result["message"])

    def test_timeout_reaps_only_created_process(self):
        owned = FakeProcess(encoded(record()), wait_timeout=True)
        unrelated = FakeProcess(b"")
        with patch.object(probe.subprocess, "Popen", return_value=owned):
            result = probe.discover_cuda_devices()
        self.assertEqual(result["state"], "timeout")
        self.assertEqual(owned.kills, 1)
        self.assertIsNotNone(owned.poll())
        self.assertTrue(owned.stdout.closed)
        self.assertIsNone(unrelated.poll())
        self.assertEqual(unrelated.kills, 0)

    def test_launch_and_read_errors_do_not_leak_paths(self):
        with patch.object(probe.subprocess, "Popen", side_effect=OSError(r"D:\私有目录\python.exe")):
            result = probe.discover_cuda_devices()
        self.assertEqual(result["state"], "failed")
        self.assertNotIn("私有目录", result["message"])
        process = FakeProcess(b"")
        process.stdout = Mock()
        process.stdout.read.side_effect = OSError(r"D:\私有目录")
        with patch.object(probe.subprocess, "Popen", return_value=process):
            result = probe.discover_cuda_devices(force=True)
        self.assertEqual(result["state"], "failed")
        self.assertNotIn("私有目录", result["message"])
        self.assertEqual(process.kills, 1)
        process.stdout.read.assert_called_once_with(64 * 1024 + 1)
        process.stdout.close.assert_called_once_with()


class RuntimeSelectionTests(unittest.TestCase):
    def test_reuses_doc_probe_runtime_resolver(self):
        self.assertIs(probe._runtime_paths, doc_probe._runtime_paths)

    def test_packaged_runtime_is_chosen_over_native_launcher(self):
        data = TEMP_ROOT / "候选应用"
        python = data / "runtime" / "python.exe"
        with patch.object(doc_probe, "__file__", str(data / "app.zip" / "py_src" / "utils" / "doc_probe.py")), patch.object(
                sys, "executable", str(data.parent / "Umi-OCR.exe")), patch.object(
                Path, "is_file", lambda value: value == python), patch.object(Path, "is_dir", return_value=False):
            paths = probe._runtime_paths()
        self.assertEqual(paths, (data / "app.zip", data, data, python))

    def test_native_launcher_without_portable_python_never_starts(self):
        with patch.object(sys, "executable", str(TEMP_ROOT / "Umi-OCR.exe")), patch.object(
                Path, "is_file", return_value=False), patch.object(probe.subprocess, "Popen") as popen:
            result = probe.discover_cuda_devices(force=True)
        self.assertEqual(result["state"], "failed")
        self.assertIn("无法安全启动", result["message"])
        popen.assert_not_called()

    def test_relative_path_python_is_not_searched_in_path(self):
        with patch.object(sys, "executable", "python.exe"), patch.object(Path, "is_file", return_value=False), patch.object(
                probe.subprocess, "Popen") as popen:
            result = probe.discover_cuda_devices(force=True)
        self.assertEqual(result["state"], "failed")
        popen.assert_not_called()

    def test_relative_existing_python_is_not_passed_to_popen(self):
        paths = (*PATHS[:-1], Path("python.exe"))
        with patch.object(probe, "_runtime_paths", return_value=paths), patch.object(Path, "is_file", return_value=True), patch.object(
                probe.subprocess, "Popen") as popen:
            result = probe.discover_cuda_devices(force=True)
        self.assertEqual(result["state"], "failed")
        popen.assert_not_called()

    def test_source_uses_current_portable_interpreter_not_old_app_zip(self):
        paths = probe._runtime_paths()
        self.assertEqual(paths[0], SOURCE)
        self.assertEqual(paths[-1], Path(sys.executable))
        self.assertNotEqual(paths[0], paths[2] / "app.zip")


class CacheTests(ProbeCase):
    def test_ttl_force_and_deep_copy(self):
        clock = [100.0]
        with patch.object(probe.time, "monotonic", side_effect=lambda: clock[0]), patch.object(
                probe, "_run_probe", side_effect=lambda *_: record()) as run:
            first = probe.discover_cuda_devices()
            first["devices"][0]["name"] = "被修改"
            first["devices"].append(device(1))
            clock[0] = 129.999
            self.assertEqual(probe.discover_cuda_devices()["devices"], [device()])
            self.assertEqual(run.call_count, 1)
            clock[0] = 130.0
            self.assertEqual(probe.discover_cuda_devices()["devices"], [device()])
            self.assertEqual(run.call_count, 2)
            probe.discover_cuda_devices(force=True)
            self.assertEqual(run.call_count, 3)
        self.assertEqual(probe._CACHE_TTL_SECONDS, 30.0)

    def test_environment_and_all_runtime_roots_are_cache_keys(self):
        with patch.dict(os.environ), patch.object(probe, "_run_probe", side_effect=lambda *_: record()) as run:
            os.environ.pop("CUDA_VISIBLE_DEVICES", None)
            os.environ.pop("CUDA_DEVICE_ORDER", None)
            probe.discover_cuda_devices()
            os.environ["CUDA_VISIBLE_DEVICES"] = ""
            probe.discover_cuda_devices()
            os.environ["CUDA_VISIBLE_DEVICES"] = "2,0"
            probe.discover_cuda_devices()
            os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
            probe.discover_cuda_devices()
            probe.discover_cuda_devices()
            self.assertEqual(run.call_count, 4)
            for index in range(4):
                paths = list(PATHS)
                paths[index] = TEMP_ROOT / f"运行根-{index}"
                with patch.object(probe, "_runtime_paths", return_value=tuple(paths)):
                    probe.discover_cuda_devices()
            self.assertEqual(run.call_count, 8)
            self.assertEqual(run.call_args.args[1]["CUDA_VISIBLE_DEVICES"], "2,0")
            self.assertEqual(run.call_args.args[1]["CUDA_DEVICE_ORDER"], "PCI_BUS_ID")

    def test_translations_are_not_cached(self):
        with patch.object(probe, "_run_probe", return_value=record()) as run:
            with patch.object(probe, "tr", return_value="当前语言一"):
                first = probe.discover_cuda_devices()
            with patch.object(probe, "tr", return_value="当前语言二"):
                second = probe.discover_cuda_devices()
        self.assertEqual(first["message"], "当前语言一")
        self.assertEqual(second["message"], "当前语言二")
        run.assert_called_once()

    def _assert_coalesced(self, failing=False):
        started, release, all_waiting = Event(), Event(), Event()
        count_lock = Lock()
        waiting = [0]

        class TrackingFuture(Future):
            def result(self, *args, **kwargs):
                with count_lock:
                    waiting[0] += 1
                    if waiting[0] == 7:
                        all_waiting.set()
                return super().result(*args, **kwargs)

        def slow_probe(*_):
            started.set()
            if not release.wait(5):
                raise AssertionError("并发测试未释放发现线程")
            if failing:
                raise OSError(r"D:\私有目录")
            return record()

        with patch.object(probe, "Future", TrackingFuture), patch.object(probe, "_run_probe", side_effect=slow_probe) as run:
            with ThreadPoolExecutor(max_workers=8) as pool:
                try:
                    tasks = [pool.submit(probe.discover_cuda_devices)]
                    self.assertTrue(started.wait(5), "发现线程没有启动")
                    tasks.extend(pool.submit(probe.discover_cuda_devices, bool(index % 2)) for index in range(7))
                    self.assertTrue(all_waiting.wait(5), "并发请求未合并到同一在途发现")
                finally:
                    release.set()
                results = [task.result(timeout=5) for task in tasks]
            run.assert_called_once()
            self.assertEqual(len({id(result["devices"]) for result in results}), 8)
            self.assertTrue(all(result["state"] == ("failed" if failing else "ready") for result in results))
            self.assertFalse(probe._INFLIGHT)
            probe.discover_cuda_devices()
            run.assert_called_once()
            results[0]["devices"].append(device(1))
            self.assertNotEqual(results[0]["devices"], results[1]["devices"])

    def test_concurrent_requests_and_force_are_coalesced(self):
        self._assert_coalesced()

    def test_concurrent_failure_releases_all_waiters(self):
        self._assert_coalesced(failing=True)


class RealProcessTests(ProbeCase):
    def test_deadline_reaps_worker_without_touching_another_owned_child(self):
        original_popen = subprocess.Popen
        sentinel = original_popen([str(PATHS[-1]), "-I", "-B", "-X", "utf8", "-c", "import time; time.sleep(60)"],
                                  cwd=str(TEMP_ROOT), stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        created = []

        def create(*args, **kwargs):
            process = original_popen(*args, **kwargs)
            created.append(process)
            return process

        scripts = ["import time; time.sleep(60)",
                   "import sys,time; sys.stdout.buffer.write(b'{}'); sys.stdout.flush(); sys.stdout.close(); time.sleep(60)"]
        try:
            with patch.object(probe.subprocess, "Popen", side_effect=create), patch.object(probe, "_PROBE_TIMEOUT_SECONDS", 0.15):
                for script in scripts:
                    started = time.monotonic()
                    with patch.object(probe, "_WORKER_BOOTSTRAP", script):
                        result = probe.discover_cuda_devices(force=True)
                    self.assertEqual(result["state"], "timeout")
                    self.assertLess(time.monotonic() - started, 5)
                    self.assertIsNone(sentinel.poll(), "发现误回收了另一测试子进程")
        finally:
            sentinel.kill()
            sentinel.wait()
        self.assertEqual(len(created), 2)
        self.assertTrue(all(process.poll() is not None and process.stdout.closed for process in created))

    def test_over_limit_output_is_bounded_and_stopped_early(self):
        original_popen = subprocess.Popen
        created = []

        def create(*args, **kwargs):
            process = original_popen(*args, **kwargs)
            created.append(process)
            return process

        started = time.monotonic()
        with patch.object(probe.subprocess, "Popen", side_effect=create), patch.object(
                probe, "_WORKER_BOOTSTRAP", "import sys,time; sys.stdout.buffer.write(b'x' * (8 * 1024 * 1024)); sys.stdout.flush(); time.sleep(60)"):
            result = probe.discover_cuda_devices()
        self.assertEqual(result["state"], "failed")
        self.assertIn("过大", result["message"])
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(len(created), 1)
        self.assertIsNotNone(created[0].poll())
        self.assertTrue(created[0].stdout.closed)


def fake_driver(devices=None, versioned=True, count=None, init_code=0):
    devices = [device()] if devices is None else devices
    handles = [500 - index * 17 for index in range(len(devices))]
    by_handle = dict(zip(handles, devices))
    driver = types.SimpleNamespace()
    driver.cuInit = Mock(return_value=init_code)

    def get_count(out):
        out._obj.value = len(devices) if count is None else count
        return 0

    def get_device(out, ordinal):
        out._obj.value = handles[ordinal]
        return 0

    def get_name(buffer, size, handle):
        buffer.value = by_handle[handle]["name"].encode("utf-8")
        return 0

    def get_uuid(out, handle):
        text = by_handle[handle]["uuid"][4:].replace("-", "")
        out._obj.bytes[:] = bytes.fromhex(text)
        return 0

    driver.cuDeviceGetCount = Mock(side_effect=get_count)
    driver.cuDeviceGet = Mock(side_effect=get_device)
    driver.cuDeviceGetName = Mock(side_effect=get_name)
    driver.cuDeviceGetUuid = Mock(side_effect=get_uuid)
    if versioned:
        driver.cuDeviceGetUuid_v2 = Mock(side_effect=get_uuid)
    return driver


class WorkerTests(unittest.TestCase):
    def test_only_driver_queries_and_versioned_uuid(self):
        expected = [device(0, uuid_number=8), device(1, uuid_number=2)]
        driver = fake_driver(expected)
        self.assertEqual(worker._query_devices(driver), expected)
        driver.cuInit.assert_called_once_with(0)
        self.assertEqual([call.args[1] for call in driver.cuDeviceGet.call_args_list], [0, 1])
        self.assertEqual([call.args[2] for call in driver.cuDeviceGetName.call_args_list], [500, 483])
        self.assertEqual(driver.cuDeviceGetUuid_v2.call_count, 2)
        driver.cuDeviceGetUuid.assert_not_called()
        self.assertEqual(ctypes.sizeof(worker._Uuid), 16)
        self.assertEqual(driver.cuInit.restype, ctypes.c_int)

    def test_old_uuid_symbol_is_supported(self):
        driver = fake_driver(versioned=False)
        self.assertEqual(worker._query_devices(driver), [device()])
        driver.cuDeviceGetUuid.assert_called_once()

    def test_uuid_query_error_does_not_fall_back_to_physical_identity(self):
        driver = fake_driver()
        driver.cuDeviceGetUuid_v2.side_effect = None
        driver.cuDeviceGetUuid_v2.return_value = 999
        with patch.object(worker, "_load_driver", return_value=driver):
            self.assertEqual(worker._probe(), record([], "failed"))
        driver.cuDeviceGetUuid.assert_not_called()

    def test_no_devices_at_initialization_or_count(self):
        for driver in (fake_driver(init_code=100), fake_driver([])):
            with patch.object(worker, "_load_driver", return_value=driver):
                self.assertEqual(worker._probe(), record([], "no_devices"))
            driver.cuDeviceGet.assert_not_called()
        driver = fake_driver()
        driver.cuDeviceGetCount.side_effect = None
        driver.cuDeviceGetCount.return_value = 100
        with patch.object(worker, "_load_driver", return_value=driver):
            self.assertEqual(worker._probe(), record([], "no_devices"))

    def test_missing_driver_and_query_failures_do_not_expose_details(self):
        for error, state in ((worker._DriverMissing(), "driver_missing"), (OSError(r"D:\私有目录"), "failed")):
            with patch.object(worker, "_load_driver", side_effect=error):
                self.assertEqual(worker._probe(), record([], state))
        for symbol in ("cuInit", "cuDeviceGetCount", "cuDeviceGet", "cuDeviceGetName", "cuDeviceGetUuid_v2"):
            driver = fake_driver()
            function = getattr(driver, symbol)
            function.side_effect = None
            function.return_value = 999
            with self.subTest(symbol=symbol), patch.object(worker, "_load_driver", return_value=driver):
                self.assertEqual(worker._probe(), record([], "failed"))
        for count in (-1, 65):
            with patch.object(worker, "_load_driver", return_value=fake_driver(count=count)):
                self.assertEqual(worker._probe(), record([], "failed"))

    def test_unterminated_and_invalid_utf8_names_fail(self):
        for raw in (b"x" * 256, b"\xff\x00"):
            driver = fake_driver()

            def get_name(buffer, size, handle):
                buffer.raw = raw.ljust(size, b"\x00")
                return 0

            driver.cuDeviceGetName.side_effect = get_name
            with patch.object(worker, "_load_driver", return_value=driver):
                self.assertEqual(worker._probe(), record([], "failed"))

    @unittest.skipUnless(os.name == "nt", "系统 DLL 安全路径仅适用于 Windows")
    def test_loads_only_system_directory_nvcuda(self):
        system_directory = r"C:\Windows\System32"

        def get_directory(buffer, size):
            buffer.value = system_directory
            return len(system_directory)

        kernel = types.SimpleNamespace(GetSystemDirectoryW=Mock(side_effect=get_directory))
        expected_driver = object()
        with patch.dict(os.environ, {"SystemRoot": r"Z:\恶意目录", "PATH": r"Z:\恶意目录"}), patch.object(
                worker.ctypes, "WinDLL", side_effect=[kernel, expected_driver]) as load:
            self.assertIs(worker._load_driver(), expected_driver)
        self.assertEqual(load.call_args_list[0].args, ("kernel32.dll",))
        self.assertEqual(load.call_args_list[1].args, (os.path.join(system_directory, "nvcuda.dll"),))
        self.assertTrue(all(call.kwargs == {"winmode": 0x00000800} for call in load.call_args_list))

    @unittest.skipUnless(os.name == "nt", "系统 DLL 安全路径仅适用于 Windows")
    def test_missing_system_driver_and_invalid_directory(self):
        def get_directory(buffer, size):
            buffer.value = r"C:\Windows\System32"
            return len(buffer.value)

        for code, state in ((126, "driver_missing"), (193, "failed")):
            error = OSError(r"D:\私有目录")
            error.winerror = code
            kernel = types.SimpleNamespace(GetSystemDirectoryW=Mock(side_effect=get_directory))
            with patch.object(worker.ctypes, "WinDLL", side_effect=[kernel, error]):
                self.assertEqual(worker._probe(), record([], state))
        for text, length in (("relative", 8), ("", 0), (r"C:\Windows", 32768)):
            def invalid_directory(buffer, size):
                buffer.value = text
                return length

            kernel = types.SimpleNamespace(GetSystemDirectoryW=Mock(side_effect=invalid_directory))
            with patch.object(worker.ctypes, "WinDLL", return_value=kernel) as load:
                self.assertEqual(worker._probe(), record([], "failed"))
                self.assertEqual(load.call_count, 1)


_BLOCK_IMPORTS = """
import importlib.abc
class RejectBackend(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'paddle', 'torch', 'PySide6', 'pynvml'} or fullname.startswith(('py_src.plugins_controller', 'py_src.mission')):
            raise AssertionError('禁止加载推理、Qt 或服务模块：' + fullname)
sys.meta_path.insert(0, RejectBackend())
"""


class IsolationTests(unittest.TestCase):
    def test_library_import_and_cached_discovery_are_backend_free(self):
        script = "import sys\n" + _BLOCK_IMPORTS + """
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
with patch('ctypes.WinDLL', side_effect=AssertionError('禁止调用真实驱动')), patch('subprocess.Popen', side_effect=AssertionError('导入时禁止启动进程')):
    from py_src.utils import cuda_device_probe, _cuda_device_probe_worker
    with patch.object(cuda_device_probe, '_run_probe', return_value={'state': 'no_devices', 'devices': []}):
        result = cuda_device_probe.discover_cuda_devices()
        assert result['ok'] and result['state'] == 'no_devices' and not result['devices']
assert not any(name.split('.')[0] in {'paddle', 'torch', 'PySide6', 'pynvml'} or name.startswith(('py_src.plugins_controller', 'py_src.mission')) for name in sys.modules)
"""
        completed = subprocess.run([str(PATHS[-1]), "-I", "-B", "-X", "utf8", "-c", script, str(SOURCE)],
                                   cwd=str(TEMP_ROOT), capture_output=True, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8", "replace"))

    def test_worker_bootstrap_source_and_zip_with_hostile_cwd(self):
        with tempfile.TemporaryDirectory(prefix="cuda-code-", dir=TEMP_ROOT) as temporary:
            root = Path(temporary)
            hostile = root / "不可信输入"
            hostile.mkdir()
            for name in ("json.py", "ctypes.py", "sitecustomize.py"):
                (hostile / name).write_text("raise AssertionError('不可信目录被导入')\n", encoding="utf-8")
            archive = root / "app.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("py_src/", b"")
                output.writestr("py_src/utils/", b"")
                for name in ("__init__.py", "_cuda_device_probe_worker.py"):
                    output.write(SOURCE / "py_src" / "utils" / name, "py_src/utils/" + name)
            prefix = "import sys,ctypes,types\n" + _BLOCK_IMPORTS + """
from unittest.mock import Mock
loaded = []
def system_directory(buffer, size):
    buffer.value = r'C:\\Windows\\System32'
    return len(buffer.value)
def fake_load(name, **kwargs):
    loaded.append(name)
    if name == 'kernel32.dll':
        return types.SimpleNamespace(GetSystemDirectoryW=Mock(side_effect=system_directory))
    raise FileNotFoundError('模拟缺少驱动')
ctypes.WinDLL = fake_load
"""
            suffix = """
assert len(loaded) == 2 and loaded[1] == r'C:\\Windows\\System32\\nvcuda.dll'
assert importlib.util.find_spec('py_src.utils._cuda_device_probe_worker').origin.startswith(code_root)
assert not any(name.split('.')[0] in {'paddle', 'torch', 'PySide6', 'pynvml'} or name.startswith(('py_src.plugins_controller', 'py_src.mission')) for name in sys.modules)
"""
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(hostile)
            for code_root in (SOURCE, archive):
                with self.subTest(code_root=code_root):
                    completed = subprocess.run(
                        [str(PATHS[-1]), "-I", "-B", "-X", "utf8", "-c", prefix + probe._WORKER_BOOTSTRAP + suffix, str(code_root)],
                        cwd=str(hostile), env=environment, capture_output=True, timeout=10)
                    self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8", "replace"))
                    self.assertEqual(json.loads(completed.stdout), record([], "driver_missing"))


class ConnectorTests(ProbeCase):
    def _connector(self, thread_run):
        qt_core = types.ModuleType("PySide6.QtCore")
        qt_core.QObject = object

        def slot(*signature, **kwargs):
            def decorate(function):
                function._slot_signature = signature
                return function
            return decorate

        qt_core.Slot = slot
        qt_core.Signal = lambda *signature: types.SimpleNamespace(emit=Mock(), signature=signature)
        qt = types.ModuleType("PySide6")
        qt.QtCore = qt_core
        thread_pool = types.ModuleType("py_src.utils.thread_pool")
        thread_pool.threadRun = thread_run
        module_patch = patch.dict(sys.modules, {"PySide6": qt, "PySide6.QtCore": qt_core,
                                                "py_src.utils.thread_pool": thread_pool})
        module_patch.start()
        self.addCleanup(module_patch.stop)

        class RejectServices(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname in {"py_src.plugins_controller.plugins_controller", "py_src.plugins_controller.services"} or fullname.startswith("py_src.mission"):
                    raise AssertionError("设备发现不得加载插件控制器或模型服务")

        import_patch = patch.object(sys, "meta_path", [RejectServices(), *sys.meta_path])
        import_patch.start()
        self.addCleanup(import_patch.stop)
        name = "py_src.plugins_controller.plugins_connector"
        spec = importlib.util.spec_from_file_location(name, SOURCE / "py_src/plugins_controller/plugins_connector.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.PluginsConnector()

    def test_independent_async_signal_preserves_request_id(self):
        jobs = []
        connector = self._connector(jobs.append)
        connector._pending = 4
        connector.requestOperation = Mock(side_effect=AssertionError("不得走插件操作接口"))
        result = {"ok": True, "state": "ready", "devices": [device()], "message": "测试"}
        with patch.object(probe, "discover_cuda_devices", return_value=result) as discover:
            connector.discoverCudaDevices("请求-旧", False)
            connector.discoverCudaDevices("请求-新", True)
            discover.assert_not_called()
            self.assertEqual(connector._pending, 4)
            for job in reversed(jobs):
                job()
            self.assertEqual([call.kwargs for call in discover.call_args_list], [{"force": True}, {"force": False}])
        self.assertEqual(connector.cudaDevicesDiscovered.signature, (str, "QVariant"))
        self.assertEqual(connector.discoverCudaDevices._slot_signature, (str, bool))
        self.assertEqual([call.args for call in connector.cudaDevicesDiscovered.emit.call_args_list],
                         [("请求-新", result), ("请求-旧", result)])
        connector.requestOperation.assert_not_called()
        connector.operationFinished.emit.assert_not_called()
        self.assertEqual(connector._pending, 4)
        self.assertNotIn("py_src.plugins_controller.services", sys.modules)
        self.assertNotIn("py_src.plugins_controller.plugins_controller", sys.modules)

    def test_background_failure_is_sanitized(self):
        jobs = []
        connector = self._connector(jobs.append)
        with patch.object(probe, "discover_cuda_devices", side_effect=RuntimeError(r"D:\私有目录")):
            connector.discoverCudaDevices("请求-失败", False)
            jobs.pop()()
        request_id, result = connector.cudaDevicesDiscovered.emit.call_args.args
        self.assertEqual(request_id, "请求-失败")
        self.assertEqual(result["state"], "failed")
        self.assertFalse(result["ok"])
        self.assertEqual(result["devices"], [])
        self.assertNotIn("私有目录", result["message"])
        self.assertEqual(connector._pending, 0)

    def test_scheduling_failure_still_emits_result(self):
        connector = self._connector(Mock(side_effect=RuntimeError(r"D:\私有目录")))
        connector.discoverCudaDevices("请求-排队失败", True)
        request_id, result = connector.cudaDevicesDiscovered.emit.call_args.args
        self.assertEqual(request_id, "请求-排队失败")
        self.assertEqual(result["state"], "failed")
        self.assertNotIn("私有目录", result["message"])

    def test_existing_controller_methods_remain_lazy_delegates(self):
        connector = self._connector(Mock())
        module = types.ModuleType("py_src.plugins_controller.plugins_controller")
        controller = module.PluginsController = Mock()
        with patch.dict(sys.modules, {module.__name__: module}):
            for name, args in (("init", ()), ("getPlugins", ()), ("setEnabled", ("插件", True)),
                               ("runHealthCheck", ("插件",)), ("hostInfo", ())):
                self.assertIs(getattr(connector, name)(*args), getattr(controller, name).return_value)
                getattr(controller, name).assert_called_once_with(*args)


if __name__ == "__main__":
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    unittest.main()
