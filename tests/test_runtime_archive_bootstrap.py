"""只测运行容器声明和隔离导入，不启动Qt、网络或模型。"""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build/tmp/startup-small-files-20261028-r1/bootstrap-tests"
HOST = ROOT / "UmiOCR-data/runtime_archive_bootstrap.py"
CUDA = ROOT / "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/runtime_archive_bootstrap.py"
VL = ROOT.parent / "Umi-OCR-Plugin/win32_PaddleOCRVL_1_6/runtime_archive_bootstrap.py"


def load(path):
    spec = importlib.util.spec_from_file_location("archive_bootstrap_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture(root, kind, compression=zipfile.ZIP_STORED):
    name = "app.zip" if kind == "host" else "vendor.zip"
    member = "py_src/probe.py" if kind == "host" else "probe.py"
    logical = member if kind == "host" else "vendor/" + member
    payload = b"VALUE = 73\n"
    rows = []
    with zipfile.ZipFile(root / name, "w", compression=compression) as archive:
        if kind == "host":
            archive.writestr("py_src/", b"")
            rows.append({"logical_path": "py_src/", "member": "py_src/", "kind": "directory", "bytes": 0, "sha256": hashlib.sha256(b"").hexdigest()})
        archive.writestr(member, payload)
        rows.append({"logical_path": logical, "member": member, "kind": "file", "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
    data = (root / name).read_bytes()
    prefix = "" if kind == "host" else "vendor"
    selections = [{"logical_path": "py_src", "kind": "package"}] if kind == "host" else [{"logical_path": logical, "kind": "module"}]
    record = {"schema_version": 1, "format": "umi-runtime-stored-zip-v1", "state": "complete", "kind": kind,
              "archives": [{"path": name, "source_prefix": prefix, "selections": selections,
                            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "members": rows}]}
    (root / "runtime-archives.json").write_text(json.dumps(record), encoding="utf-8")
    return name, logical, record


class RuntimeArchiveBootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        WORK.mkdir(parents=True, exist_ok=True)
        if WORK.resolve() != WORK.absolute():
            raise ValueError("测试临时根不能使用链接")
        cls.host = load(HOST)
        cls.plugin = load(CUDA)

    def test_component_helpers_stay_identical(self):
        self.assertEqual(CUDA.read_bytes(), VL.read_bytes())

    def test_absent_archives_do_not_write_or_scan(self):
        with tempfile.TemporaryDirectory(dir=WORK) as temporary:
            root = Path(temporary)
            self.assertEqual(self.host.prepare_archives(root, kind="host"), [])
            self.assertEqual(self.plugin.prepare_archives(root), [])
            self.assertEqual(list(root.iterdir()), [])

    def test_valid_stored_archives_import_directly_without_extraction(self):
        for kind in ("host", "plugin"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=WORK) as temporary:
                root = Path(temporary)
                name, _, _ = fixture(root, kind)
                paths = self.host.prepare_archives(root, kind=kind) if kind == "host" else self.plugin.prepare_archives(root)
                self.assertEqual(paths, [str(root / name)])
                package = "py_src.probe" if kind == "host" else "probe"
                command = "import sys,importlib; sys.path.insert(0,sys.argv[1]); m=importlib.import_module(sys.argv[2]); assert m.VALUE==73; print(m.__file__)"
                result = subprocess.run([sys.executable, "-I", "-B", "-c", command, paths[0], package], capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(name, result.stdout)
                self.assertEqual({p.name for p in root.iterdir()}, {name, "runtime-archives.json"})

    def test_corrupt_missing_undeclared_and_shadowed_are_rejected(self):
        for kind in ("host", "plugin"):
            for failure in ("corrupt", "missing", "undeclared", "shadow"):
                with self.subTest(kind=kind, failure=failure), tempfile.TemporaryDirectory(dir=WORK) as temporary:
                    root = Path(temporary)
                    name, logical, _ = fixture(root, kind)
                    if failure == "corrupt":
                        with (root / name).open("r+b") as stream:
                            stream.seek(8)
                            stream.write(b"xx")
                    elif failure == "missing":
                        (root / name).unlink()
                    elif failure == "undeclared":
                        (root / "runtime-archives.json").unlink()
                    else:
                        loose = root / logical
                        loose.parent.mkdir(parents=True)
                        loose.write_text("VALUE = 2", encoding="utf-8")
                    with self.assertRaises((RuntimeError, FileNotFoundError)):
                        self.host.prepare_archives(root, kind=kind) if kind == "host" else self.plugin.prepare_archives(root)

    def test_schema_kind_and_completion_are_checked_at_runtime(self):
        for kind in ("host", "plugin"):
            for field, value in (("format", "unknown"), ("kind", "other"), ("state", "assembling")):
                with self.subTest(kind=kind, field=field), tempfile.TemporaryDirectory(dir=WORK) as temporary:
                    root = Path(temporary)
                    _, _, record = fixture(root, kind)
                    record[field] = value
                    (root / "runtime-archives.json").write_text(json.dumps(record), encoding="utf-8")
                    with self.assertRaises(RuntimeError):
                        self.host.prepare_archives(root, kind=kind) if kind == "host" else self.plugin.prepare_archives(root)

    def test_incomplete_and_legacy_markers_do_not_fall_back_to_loose(self):
        for kind in ("host", "plugin"):
            for name in ("archive-layout.json", ".runtime-archive-candidate.json", "runtime-archive-inputs.json"):
                with self.subTest(kind=kind, name=name), tempfile.TemporaryDirectory(dir=WORK) as temporary:
                    root = Path(temporary)
                    (root / name).write_text('{"state":"failed"}', encoding="utf-8")
                    with self.assertRaises(RuntimeError):
                        self.host.prepare_archives(root, kind=kind) if kind == "host" else self.plugin.prepare_archives(root)

    def test_compressed_members_are_rejected_even_with_matching_hash(self):
        for kind in ("host", "plugin"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=WORK) as temporary:
                root = Path(temporary)
                fixture(root, kind, zipfile.ZIP_DEFLATED)
                with self.assertRaises(RuntimeError):
                    self.host.prepare_archives(root, kind=kind) if kind == "host" else self.plugin.prepare_archives(root)

    def test_traversal_and_duplicate_fields_are_rejected(self):
        for kind in ("host", "plugin"):
            for failure in ("traversal", "duplicate", "bool-version"):
                with self.subTest(kind=kind, failure=failure), tempfile.TemporaryDirectory(dir=WORK) as temporary:
                    root = Path(temporary)
                    _, _, record = fixture(root, kind)
                    if failure == "traversal":
                        record["archives"][0]["members"][-1]["logical_path"] = "../outside.py"
                    elif failure == "bool-version":
                        record["schema_version"] = True
                    text = json.dumps(record)
                    if failure == "duplicate":
                        text = text.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1')
                    (root / "runtime-archives.json").write_text(text, encoding="utf-8")
                    with self.assertRaises(RuntimeError):
                        self.host.prepare_archives(root, kind=kind) if kind == "host" else self.plugin.prepare_archives(root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
