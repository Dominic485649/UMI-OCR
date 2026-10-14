"""Regression checks for the public-product privacy gate."""

import importlib.util
from pathlib import Path
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("public_payload", ROOT / "build/tools/verify_public_payload.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def main():
    for name in (".claude/session.json", ".CoDeX/settings.json", "docs/ClAuDe.Md", "nested/AGENTS.md"):
        assert module.forbidden(name), name
    assert not module.forbidden("docs/README.md")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "README.md").write_text("public", encoding="utf-8")
        assert module.verify(root)["status"] == "PASS"
        with zipfile.ZipFile(root / "source-snapshot.zip", "w") as archive:
            archive.writestr("nested/.CLAUDE/private.json", "private")
        result = module.verify(root)
        assert result["status"] == "BLOCK"
        assert result["violations"] == ["source-snapshot.zip!nested/.CLAUDE/private.json"]
        (root / "source-snapshot.zip").unlink()
        plugin = root / "UmiOCR-data/plugins/win32_PaddleOCRv6_CPU"
        plugin.mkdir(parents=True)
        assert module.verify(root)["status"] == "BLOCK"
    print("Public payload privacy gate regression passed.")


if __name__ == "__main__":
    main()
