"""Known legacy id metadata must not disable the base payload exclusion gate."""

from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def main():
    powershell = shutil.which("pwsh")
    if not powershell:
        raise RuntimeError("PowerShell 7 is required for the actual package-audit regression")
    for relative in ("plugins_controller/manifest.py", "utils/ui_unlock.py", "other/ui_unlock.py"):
        for poisoned in (False, True):
            with tempfile.TemporaryDirectory(prefix="umi-base-audit-") as directory:
                root = Path(directory)
                manifest = root / "UmiOCR-data/py_src" / relative
                manifest.parent.mkdir(parents=True)
                source = 'KNOWN = {\n    "win32_PaddleOCRVL_1_6",\n}\n'
                if poisoned:
                    source += "import PaddleOCRVL\n"
                manifest.write_text(source, encoding="utf-8")
                (root / "empty.py").write_text("", encoding="utf-8")
                result = subprocess.run(
                    [powershell, "-NoProfile", "-File", str(ROOT / "build/windows/Audit-Package.ps1"),
                     "-PackageRoot", str(root), "-Kind", "base", "-LocalCandidate"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace",
                )
                # 微型夹具缺运行时，整体失败是预期；仅精确宿主声明可豁免文本规则。
                assert result.returncode != 0
                matched = "禁止的基础包源码内容" in result.stdout and "命中 PaddleOCRVL" in result.stdout
                assert matched == (poisoned or relative == "other/ui_unlock.py"), result.stdout
                assert "InvokeMethodOnNull" not in result.stdout, result.stdout
    cases = (
        ('source/docs/RELEASE_PaddleVL_DRAFT.md', False),
        ('source/docs/nested/PaddleOCR-VL.md', False),
        ('UmiOCR-data/PaddleVL.md', True),
        ('source/PaddleVL.md', True),
        ('source/docs/PaddleVL.py', True),
        ('source/docs/PaddleVL.gguf', True),
        ('source/docs/llama-server.exe', True),
        ('source/docs/PaddleVL/README.md', True),
    )
    for relative, forbidden in cases:
        with tempfile.TemporaryDirectory(prefix='umi-base-doc-audit-') as directory:
            root = Path(directory)
            document = root / relative
            document.parent.mkdir(parents=True)
            document.write_text('Independent plugin documentation\n', encoding='utf-8')
            result = subprocess.run(
                [powershell, '-NoProfile', '-File', str(ROOT / 'build/windows/Audit-Package.ps1'),
                 '-PackageRoot', str(root), '-Kind', 'base', '-LocalCandidate'],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8', errors='replace',
            )
            assert result.returncode != 0  # 微型夹具缺运行时，不把整体失败误记为包验收。
            assert ('禁止的发布内容:' in result.stdout) == forbidden, result.stdout
    print('Base audit boundaries passed: 6 legacy-id cases and 8 documentation/name cases.')


if __name__ == "__main__":
    main()
