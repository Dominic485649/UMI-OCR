"""仅用 mock 验证 GPU 覆盖、标量自检及安全诊断，不执行真实 CUDA。"""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/cuda_runtime_check.py"
if not HELPER.is_file():
    HELPER = ROOT / "win32_PaddleOCRVL_1_6/cuda_runtime_check.py"
spec = importlib.util.spec_from_file_location("tested_cuda_runtime_check", HELPER)
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


def support():
    return {"schema_version": 1, "paddle_version": "3.3.1", "cuda_version": "12.9", "providers": [
        {"path": path, "sha256": "0" * 64, "cubins": ["75", "80", "86", "89", "120"], "ptx": []}
        for path in ("vendor/paddle/base/libpaddle.pyd", "vendor/paddle/libs/phi.dll")
    ]}


def paddle(capability=(12, 0), actual=2.0):
    cuda = SimpleNamespace(device_count=Mock(return_value=1),
        get_device_capability=Mock(return_value=capability), get_device_name=Mock(return_value="NVIDIA 测试显卡"),
        synchronize=Mock())

    class Tensor:
        def __add__(self, other):
            if other != 1.0:
                raise AssertionError("自检表达式改变")
            return SimpleNamespace(numpy=lambda: [actual])

    return SimpleNamespace(__version__="3.3.1", version=SimpleNamespace(cuda=lambda: "12.9", cudnn=lambda: "9.9.0"),
        is_compiled_with_cuda=Mock(return_value=True), device=SimpleNamespace(cuda=cuda, set_device=Mock()),
        CUDAPlace=Mock(side_effect=lambda index: ("cuda", index)), to_tensor=Mock(return_value=Tensor()))


class RuntimeCheckTests(unittest.TestCase):
    def test_sm120_has_real_scalar_check_and_sync(self):
        engine = paddle()
        result = M.check_cuda(engine, "gpu:0", support())
        self.assertEqual(result["selfTest"], "PASSED")
        self.assertEqual(result["computeCapability"], "12.0")
        self.assertEqual(result["actual"], "2.0")
        engine.to_tensor.assert_called_once_with([1.0], dtype="float32", place=("cuda", 0))
        engine.device.cuda.synchronize.assert_called_once_with(0)

    def test_sm61_fails_before_device_selection_and_tensor(self):
        engine = paddle((6, 1))
        with self.assertRaises(M.CudaCheckError) as raised:
            M.check_cuda(engine, "gpu:0", support())
        self.assertEqual(raised.exception.error_type, "UNSUPPORTED_GPU_ARCHITECTURE")
        self.assertIn("6.1", str(raised.exception))
        engine.to_tensor.assert_not_called()
        engine.device.set_device.assert_not_called()
        self.assertEqual(len(raised.exception.details["unsupportedProviders"]), 2)

    def test_sm87_uses_compatible_sm80_not_exact_whitelist(self):
        self.assertEqual(M.check_cuda(paddle((8, 7)), "gpu:0", support())["selfTest"], "PASSED")

    def test_no_cross_major_cubin_compatibility(self):
        profile = support()
        for item in profile["providers"]:
            item["cubins"] = ["89"]
        with self.assertRaises(M.CudaCheckError) as raised:
            M.check_cuda(paddle(), "gpu:0", profile)
        self.assertEqual(raised.exception.error_type, "UNSUPPORTED_GPU_ARCHITECTURE")

    def test_generic_ptx_is_forward_compatible(self):
        profile = support()
        for item in profile["providers"]:
            item.update(cubins=["89"], ptx=["89"])
        self.assertEqual(M.check_cuda(paddle(), "gpu:0", profile)["selfTest"], "PASSED")

    def test_architecture_specific_ptx_is_not_claimed_as_generic(self):
        provider = {"cubins": [], "ptx": ["90a"]}
        self.assertIsNone(M.provider_supports(provider, 120))

    def test_all_core_providers_must_be_compatible(self):
        profile = support()
        profile["providers"][1]["cubins"] = ["89"]
        with self.assertRaises(M.CudaCheckError) as raised:
            M.check_cuda(paddle(), "gpu:0", profile)
        self.assertEqual(raised.exception.details["unsupportedProviders"], ["vendor/paddle/libs/phi.dll"])

    def test_no_device_or_invalid_device_never_allocates(self):
        for device, count, code in (("gpu:0", 0, "CUDA_DEVICE_UNAVAILABLE"), ("gpu:1", 1, "CUDA_DEVICE_UNAVAILABLE"), ("gpu:-1", 1, "INVALID_CUDA_DEVICE"), ("cpu", 1, "INVALID_CUDA_DEVICE")):
            engine = paddle()
            engine.device.cuda.device_count.return_value = count
            with self.subTest(device=device, count=count), self.assertRaises(M.CudaCheckError) as raised:
                M.check_cuda(engine, device, support())
            self.assertEqual(raised.exception.error_type, code)
            engine.to_tensor.assert_not_called()

    def test_cpu_build_is_explicit_failure(self):
        engine = paddle()
        engine.is_compiled_with_cuda.return_value = False
        with self.assertRaises(M.CudaCheckError) as raised:
            M.check_cuda(engine, "gpu:0", support())
        self.assertEqual(raised.exception.error_type, "CUDA_BUILD_REQUIRED")

    def test_wrong_result_and_nonfinite_remain_strict_and_json_safe(self):
        for value in (0.0, 1.0, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(M.CudaCheckError) as raised:
                M.check_cuda(paddle(actual=value), "gpu:0", support())
            self.assertEqual(raised.exception.error_type, "CUDA_SELF_TEST_RESULT_INVALID")
            self.assertEqual(raised.exception.details["selfTest"], "FAILED")
            json.dumps(raised.exception.details, allow_nan=False)

    def test_synchronization_failure_is_not_result_error(self):
        engine = paddle()
        engine.device.cuda.synchronize.side_effect = RuntimeError("no kernel image")
        with self.assertRaises(M.CudaCheckError) as raised:
            M.check_cuda(engine, "gpu:0", support())
        self.assertEqual(raised.exception.error_type, "CUDA_SELF_TEST_EXECUTION_FAILED")
        self.assertEqual(raised.exception.details["phase"], "synchronize")
        self.assertIn("no kernel image", str(raised.exception))

    def test_runtime_identity_mismatch_is_not_silently_accepted(self):
        engine = paddle()
        engine.version.cuda = lambda: "12.6"
        with self.assertRaises(M.CudaCheckError) as raised:
            M.check_cuda(engine, "gpu:0", support())
        self.assertEqual(raised.exception.error_type, "GPU_RUNTIME_RECORD_MISMATCH")
        engine.to_tensor.assert_not_called()

    def test_probe_only_does_not_claim_scalar_pass(self):
        engine = paddle()
        result = M.check_cuda(engine, "gpu:0", support(), run_tensor=False)
        self.assertEqual(result["selfTest"], "NOT_RUN")
        engine.to_tensor.assert_not_called()

    def test_helper_never_prints_to_protocol_stdout(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            M.check_cuda(paddle(), "gpu:0", support())
        self.assertEqual(output.getvalue(), "")

    def test_support_record_validation_and_budget(self):
        # 目录只含本测试创建的 JSON，未启动任何子进程或原生程序。
        temporary_root = ROOT / "build/tmp/cuda-runtime-check"
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="cuda-support-", dir=temporary_root) as directory:
            path = Path(directory) / "support.json"
            with self.assertRaises(M.CudaCheckError):
                M.load_support(path)
            path.write_text(json.dumps(support()), encoding="utf-8")
            self.assertEqual(M.load_support(path), support())
            broken = copy.deepcopy(support())
            broken["providers"][0]["sha256"] = "wrong"
            path.write_text(json.dumps(broken), encoding="utf-8")
            with self.assertRaises(M.CudaCheckError):
                M.load_support(path)
            path.write_bytes(b" " * (64 * 1024 + 1))
            with self.assertRaises(M.CudaCheckError):
                M.load_support(path)


if __name__ == "__main__":
    unittest.main()
