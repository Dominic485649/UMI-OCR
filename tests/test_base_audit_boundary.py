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
    for poisoned in (False, True):
        with tempfile.TemporaryDirectory(prefix="umi-base-audit-") as directory:
            root = Path(directory)
            manifest = root / "UmiOCR-data/py_src/plugins_controller/manifest.py"
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
            # Fixtures intentionally lack the required runtime.  Audit failure
            # is expected, but the source-token check must remain independent.
            assert result.returncode != 0
            matched = "禁止的基础包源码内容" in result.stdout and "命中 PaddleOCRVL" in result.stdout
            assert matched == poisoned, result.stdout
            assert "InvokeMethodOnNull" not in result.stdout, result.stdout
    print("Base audit legacy-id versus implementation boundary regression passed.")


if __name__ == "__main__":
    main()
