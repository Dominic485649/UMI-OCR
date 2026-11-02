import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("gpu_startup_recorder", ROOT / "build/tools/record_gpu_startup.py")
recorder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recorder)


class StartupRecordTests(unittest.TestCase):
    def setUp(self):
        self.data = ROOT / "build/artifacts/fixture/UmiOCR-data"
        self.startup = {
            "pid": 123, "native_code_page": 65001, "python_utf8_mode": True,
            "stdin_encoding": "utf-8", "stdout_encoding": "utf-8",
            "python_dll": str(self.data / "runtime/python313.dll"),
            "python_version": "3.13.16", "model_names": list(recorder.MODEL_NAMES), "device": "gpu:0",
        }

    def validate(self):
        recorder.validate_startup(self.startup, 123, self.data, "gpu:0")

    def test_current_worker_startup_is_accepted(self):
        self.validate()

    def test_startup_information_is_required(self):
        with self.assertRaises(ValueError):
            recorder.validate_startup(None, 123, self.data, "gpu:0")

    def test_wrong_process_cannot_supply_evidence(self):
        self.startup["pid"] = 124
        with self.assertRaises(ValueError):
            self.validate()

    def test_boolean_pid_is_not_an_integer_process_id(self):
        self.startup["pid"] = True
        with self.assertRaises(ValueError):
            self.validate()

    def test_native_legacy_code_page_is_rejected(self):
        self.startup["native_code_page"] = 936
        with self.assertRaises(ValueError):
            self.validate()

    def test_python_utf8_alone_does_not_prove_native_utf8(self):
        self.startup.pop("native_code_page")
        with self.assertRaises(ValueError):
            self.validate()

    def test_python_utf8_mode_must_be_real_boolean(self):
        self.startup["python_utf8_mode"] = 1
        with self.assertRaises(ValueError):
            self.validate()

    def test_stream_encodings_must_both_be_utf8(self):
        for name in ("stdin_encoding", "stdout_encoding"):
            with self.subTest(stream=name):
                original = self.startup[name]
                self.startup[name] = "cp936"
                with self.assertRaises(ValueError):
                    self.validate()
                self.startup[name] = original

    def test_python_dll_must_come_from_current_host(self):
        self.startup["python_dll"] = str(ROOT / "another-runtime/python313.dll")
        with self.assertRaises(ValueError):
            self.validate()

    def test_windows_python_dll_name_is_case_insensitive(self):
        if __import__("os").name != "nt":
            self.skipTest("Windows路径语义")
        self.startup["python_dll"] = str(self.data / "runtime/Python313.DLL")
        self.validate()

    def test_all_five_models_are_required(self):
        self.startup["model_names"].remove("UVDoc")
        with self.assertRaises(ValueError):
            self.validate()

    def test_device_must_match_requested_gpu(self):
        self.startup["device"] = "cpu"
        with self.assertRaises(ValueError):
            self.validate()

    def test_interpreter_version_must_match_runtime_family(self):
        self.startup["python_version"] = "3.12.0"
        with self.assertRaises(ValueError):
            self.validate()

    def test_tree_binding_is_stable_and_byte_sensitive(self):
        first = recorder.tree_binding({"b": "2" * 64, "a": "1" * 64})
        self.assertEqual(first, recorder.tree_binding({"a": "1" * 64, "b": "2" * 64}))
        self.assertNotEqual(first, recorder.tree_binding({"a": "3" * 64, "b": "2" * 64}))

    def test_paths_cannot_escape_the_project(self):
        with self.assertRaises(ValueError):
            recorder.plain(ROOT / ".." / "external.json")

    def test_network_paths_are_rejected(self):
        with self.assertRaises(ValueError):
            recorder.plain(Path("//server/share/startup.json"))

    def test_import_does_not_load_an_inference_backend(self):
        import sys
        self.assertFalse({name.split(".", 1)[0] for name in sys.modules} & recorder.PROPRIETARY_MODULES)


if __name__ == "__main__":
    unittest.main()
