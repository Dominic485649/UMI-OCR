"""Regression checks for the public-product privacy gate."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("public_payload", ROOT / "build/tools/verify_public_payload.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def main():
    for name in (".claude/session.json", ".CoDeX/settings.json", "CLAUDE.md", "docs/ClAuDe.Md", "nested/AGENTS.md"):
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
    sys.path.insert(0, str(ROOT / "build/tools"))
    from export_cuda_source import selected_sources

    exported = {path.as_posix() for path in selected_sources(ROOT)}
    required_documents = {
        "docs/RELEASE_3.0.2_DRAFT.md",
        "docs/RELEASE_CUDA_3.0.2_DRAFT.md",
        "docs/RELEASE_3.0.2_REVIEW.md",
        "docs/RELEASE_3.0.3_DRAFT.md",
        "docs/RELEASE_CUDA_3.0.3_DRAFT.md",
        "docs/RELEASE_3.0.3_ACCEPTANCE.md",
        "docs/RELEASE_3.0.3_REVIEW.md",
    }
    assert required_documents <= exported, sorted(required_documents - exported)
    assert "CLAUDE.md" not in exported
    assert "cleanup-old-artifacts.ps1" not in exported
    assert all((ROOT / name).is_file() for name in required_documents)
    print("Public payload privacy and CUDA release-document export regressions passed.")


class UpstreamSourcePrivacyTests(unittest.TestCase):
    def verify_fixture(self, relative, checksum, extra=()):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / relative
            archive.parent.mkdir(parents=True)
            archive.write_bytes(b"synthetic upstream archive fixture")
            members = sorted(module.QT_UPSTREAM_ASSISTANT_FILES) + list(extra)
            with patch.object(module, "inspect_archive", return_value=members), patch.object(module, "digest", return_value=checksum):
                return module.verify(root)

    def test_only_exact_locked_official_source_members_are_preserved(self):
        for prefix in ("third_party/", "source/third_party/"):
            result = self.verify_fixture(prefix + module.QT_SOURCE_NAME, module.QT_SOURCE_SHA256)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["violations"], [])
            self.assertEqual(set(result["checked_archives"][0]["preserved_upstream_assistant_files"]), module.QT_UPSTREAM_ASSISTANT_FILES)

    def test_modified_archive_does_not_inherit_upstream_exception(self):
        result = self.verify_fixture("source/third_party/" + module.QT_SOURCE_NAME, "0" * 64)
        self.assertEqual(result["status"], "BLOCK")
        self.assertEqual(len(result["violations"]), 5)

    def test_same_hash_at_another_path_does_not_inherit_exception(self):
        result = self.verify_fixture("other/" + module.QT_SOURCE_NAME, module.QT_SOURCE_SHA256)
        self.assertEqual(result["status"], "BLOCK")

    def test_extra_private_members_still_block(self):
        result = self.verify_fixture("source/third_party/" + module.QT_SOURCE_NAME, module.QT_SOURCE_SHA256, ("nested/.claude/private.json",))
        self.assertEqual(result["status"], "BLOCK")
        self.assertEqual(result["violations"], ["source/third_party/" + module.QT_SOURCE_NAME + "!nested/.claude/private.json"])


if __name__ == "__main__":
    main()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(UpstreamSourcePrivacyTests))
    raise SystemExit(0 if result.wasSuccessful() else 1)
