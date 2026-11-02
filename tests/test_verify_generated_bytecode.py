"""源码绑定的自有运行缓存核验，不启动产品或模型。"""
import argparse
import hashlib
import io
import json
import marshal
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build/tools"))
import runtime_archive_layout as layout
import verify_generated_bytecode as verifier

WORK = ROOT / "build/tmp/startup-small-files-20261028-r1/generated-bytecode-fixtures"


class GeneratedBytecodeTests(unittest.TestCase):
    def setUp(self):
        WORK.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="fixture-", dir=WORK)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "package/value.py"
        self.source.parent.mkdir()
        self.data = b"VALUE = 42\ndef value():\n    return VALUE\n"
        self.source.write_bytes(self.data)
        self.expected = {"package/value.py": hashlib.sha256(self.data).hexdigest()}
        self.cache = self.source.parent / "__pycache__" / ("value." + sys.implementation.cache_tag + ".pyc")
        self.cache.parent.mkdir()
        self.write_cache()

    def write_cache(self, code=None, *, flags=0):
        code = code or compile(self.data, str(self.source), "exec", dont_inherit=True, optimize=0)
        header = (verifier.importlib.util.MAGIC_NUMBER + struct.pack("<I", flags)
                  + (struct.pack("<II", int(self.source.stat().st_mtime) & 0xffffffff, len(self.data))
                     if not flags else verifier.importlib.util.source_hash(self.data)))
        self.cache.write_bytes(header + marshal.dumps(code))

    def check(self):
        return verifier.verify_generated_cache(self.root, self.cache.relative_to(self.root).as_posix(), self.expected)

    def test_real_timestamp_cache_matches_all_nested_source_code(self):
        result = self.check()
        self.assertTrue(result["sourceCodeMatches"])
        self.assertEqual(result["codeObjectsVerified"], 2)
        self.assertFalse(result["executed"])

    def test_checked_and_unchecked_hash_headers_bind_source(self):
        for flags in (1, 3):
            self.write_cache(flags=flags)
            self.assertEqual(self.check()["flags"], flags)

    def test_unknown_or_changed_source_is_refused(self):
        for expected in ({}, {"package/value.py": "0" * 64}):
            self.expected = expected
            with self.assertRaises(ValueError):
                self.check()

    def test_changed_code_is_refused_even_with_valid_source_header(self):
        self.write_cache(compile(b"VALUE = 0\n", str(self.source), "exec", dont_inherit=True, optimize=0))
        with self.assertRaises(ValueError):
            self.check()

    def test_wrong_filename_and_foreign_paths_are_refused(self):
        self.write_cache(compile(self.data, str(self.root / "outside.py"), "exec", dont_inherit=True, optimize=0))
        with self.assertRaises(ValueError):
            self.check()
        with self.assertRaises(layout.LayoutError):
            verifier.verify_generated_cache(self.root, "../outside.pyc", self.expected)

    def test_corrupt_header_flags_and_trailing_data_are_refused(self):
        original = self.cache.read_bytes()
        for data in (b"BAD!" + original[4:], original[:4] + struct.pack("<I", 2) + original[8:],
                     original[:8] + b"\x00" * 8 + original[16:], original + b"extra"):
            self.cache.write_bytes(data)
            with self.assertRaises(ValueError):
                self.check()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = layout.plain_path(args.output)
    output.relative_to(ROOT / "build/audit")
    output.mkdir()
    tools = [Path(__file__), Path(verifier.__file__)]
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in tools}
    log = io.StringIO()
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(GeneratedBytecodeTests))
    after = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in tools}
    record = {"status": "PASS" if result.wasSuccessful() and before == after else "FAIL",
              "testsRun": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
              "skipped": len(result.skipped), "sourceBefore": before, "sourceAfter": after,
              "pythonExecutable": sys.executable, "pythonVersion": sys.version, "scope": "微型合成缓存，不运行产品或模型"}
    (output / "raw.log").write_text(log.getvalue(), encoding="utf-8")
    (output / "result.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(log.getvalue())
    print(json.dumps(record, ensure_ascii=False))
    raise SystemExit(0 if record["status"] == "PASS" else 1)
