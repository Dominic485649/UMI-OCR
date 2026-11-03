"""正式回归入口的 loose/Stored 对应源码选择，不执行候选程序或测试样本代码。"""
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "build/windows/Test-Release.ps1"
TEXT = SCRIPT.read_text("utf-8-sig")
SELECTOR = TEXT.split("# UTF-8 的源码专用检查", 1)[1].split('$Python = Join-Path', 1)[0]


class ReleaseSuiteSources(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="umi-suite-source-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.stage = self.root / "安装候选"
        self.data = self.stage / "UmiOCR-data"
        self.data.mkdir(parents=True)
        self.driver = self.root / "selector.ps1"
        self.driver.write_text('param([string]$StagingRoot,[string]$DataRoot,[string]$SourceRoot="")\n'
            '$ErrorActionPreference="Stop"\n# UTF-8 的源码专用检查' + SELECTOR
            + '\n[Console]::Write($SourceRoot)\n', encoding="utf-8")

    @staticmethod
    def source_files(root):
        (root / "py_src/utils").mkdir(parents=True)
        (root / "main.py").write_text("# SYNTHETIC SOURCE - NEVER EXECUTED\n", encoding="utf-8")
        (root / "py_src/utils/pre_configs.py").write_text("# SYNTHETIC SOURCE - NEVER EXECUTED\n", encoding="utf-8")

    def run_selector(self, source=None):
        command = ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(self.driver),
                   "-StagingRoot", str(self.stage), "-DataRoot", str(self.data)]
        if source is not None:
            command.extend(["-SourceRoot", str(source)])
        return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=30)

    def test_loose_layout_keeps_actual_data_root(self):
        self.source_files(self.data)
        result = self.run_selector()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(result.stdout).resolve(), self.data.resolve())

    def test_stored_layout_uses_packaged_corresponding_source(self):
        source = self.stage / "source/UmiOCR-data"
        self.source_files(source)
        result = self.run_selector()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(result.stdout).resolve(), source.resolve())

    def test_explicit_source_root_is_forwarded_without_changing_data_root(self):
        self.source_files(self.data)
        source = self.root / "明确指定的对应源码"
        self.source_files(source)
        result = self.run_selector(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(result.stdout).resolve(), source.resolve())

    def test_missing_corresponding_source_is_not_silently_skipped(self):
        self.assertNotEqual(self.run_selector().returncode, 0)
        source = self.stage / "source/UmiOCR-data"
        source.mkdir(parents=True)
        (source / "main.py").write_text("# fixture\n", encoding="utf-8")
        self.assertNotEqual(self.run_selector().returncode, 0)

    def test_utf8_launcher_and_source_checks_both_remain_in_suite(self):
        line = next(line for line in TEXT.splitlines() if line.startswith('Invoke-PortablePython "tests\\test_utf8_runtime.py"'))
        self.assertIn('$DataRoot, (Join-Path $StagingRoot "Umi-OCR.exe")', line)
        self.assertIn('"--source-root", $SourceRoot', line)
        self.assertIn('[string]$SourceRoot = ""', TEXT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
