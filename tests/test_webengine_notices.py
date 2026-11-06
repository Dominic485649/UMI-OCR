"""Qt 声明收集的正反例；不下载源码，不执行归档内容。"""
import hashlib
import importlib.util
import io
from pathlib import Path, PurePosixPath
import tarfile
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("webengine_notices_fixture", ROOT / "build/tools/prepare_webengine_sources.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
WORK = ROOT / "build/tmp/release-313-public-20261106-r1/notice-fixtures"


class WebEngineNoticeTests(unittest.TestCase):
    def setUp(self):
        WORK.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=WORK)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def archive(self, members):
        target = self.root / "source.tar.xz"
        with tarfile.open(target, "w:xz") as archive:
            for name, content in members:
                item = tarfile.TarInfo(name)
                item.size = len(content)
                archive.addfile(item, io.BytesIO(content))
        return target

    def test_actual_legal_names_and_attribution_metadata_are_kept(self):
        for name in ("LICENSE", "LICENCE-MIT", "COPYING.LGPL", "COPYRIGHT", "NOTICE.txt",
                     "LICENSE.chromium", "LICENSE.html", "third_party_licenses.txt", "THIRD-PARTY-NOTICES.md",
                     "PATENTS", "AUTHORS", "font.license", "qt_attribution.json", "APPLE_LICENSE",
                     "Apache-LICENSE-2.0.txt", "LicenseRef-KhronosFreeUse.txt", "CopyrightNotice.txt",
                     "MODULE_LICENSE_MPL_GPL_LGPL", "ThirdPartyNoticeText.txt", "thirdpartynotices.txt",
                     "workerpool.min.js.LICENSE.txt", "fastutil_licence", "UNLICENSE"):
            with self.subTest(name=name):
                self.assertTrue(m.is_notice_file(PurePosixPath("third_party/library/" + name)))

    def test_source_assets_and_notice_substrings_are_not_legal_files(self):
        for name in ("measurement_notice.ts", "measurement_notice.html", "NOTICE.ts", "notice.html",
                     "license_checker.py", "LICENSE.sha1", "LICENSE.png", "NOTICE.patch", "COPYING.js",
                     "licenseCheck.cpp", "licensecheck.pl.vanilla", "licenseRule.json",
                     "readme.rs-third-party-license-review.md", "licenses.xml", "privacy_notice.json", "stylesheet.css"):
            with self.subTest(name=name):
                self.assertFalse(m.is_notice_file(PurePosixPath("chrome/browser/resources/" + name)))

    def test_kept_members_retain_exact_original_bytes_and_hashes(self):
        content = b"Copyright original\r\nBSD licence original\r\n"
        source = self.archive([("library/LICENSE", content), ("library/qt_attribution.json", b"{}"),
                               ("ui/measurement_notice.ts", b"export class MeasurementNotice {}")])
        target = self.root / "notices.zip"
        records, size = m.collect_notices(source, target, minimum_files=2)
        self.assertEqual(size, len(content) + 2)
        with zipfile.ZipFile(target) as archive:
            self.assertEqual(set(archive.namelist()), {"library/LICENSE", "library/qt_attribution.json"})
            self.assertEqual(archive.read("library/LICENSE"), content)
        self.assertEqual(records[0]["sha256"], hashlib.sha256(content).hexdigest())
        with self.assertRaises(FileExistsError):
            m.collect_notices(source, target, minimum_files=2)

    def test_locked_legal_wrappers_are_not_dropped_only_because_of_source_extensions(self):
        self.assertEqual(len(m.LEGAL_WRAPPERS), 9)
        for name in m.LEGAL_WRAPPERS:
            self.assertTrue(m.is_notice_file(PurePosixPath(name)), name)
        name = next(iter(m.LEGAL_WRAPPERS))
        source = self.archive([(name, b"substituted executable source, not original legal text")])
        with self.assertRaisesRegex(ValueError, "锁定原件"):
            m.collect_notices(source, self.root / "notices.zip", minimum_files=1)

    def test_duplicate_legal_members_are_rejected(self):
        source = self.archive([("library/LICENSE", b"one"), ("library/LICENSE", b"two")])
        with self.assertRaisesRegex(ValueError, "重复"):
            m.collect_notices(source, self.root / "notices.zip", minimum_files=1)

    def test_invalid_member_paths_are_rejected(self):
        for index, name in enumerate(("../LICENSE", "/LICENSE", "C:/LICENSE", "library\\LICENSE")):
            folder = self.root / str(index)
            folder.mkdir()
            source = folder / "source.tar.xz"
            with tarfile.open(source, "w:xz") as archive:
                item = tarfile.TarInfo(name)
                item.size = 3
                archive.addfile(item, io.BytesIO(b"bad"))
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "非法"):
                m.collect_notices(source, folder / "notices.zip", minimum_files=1)

    def test_oversized_or_incomplete_legal_materials_fail_closed(self):
        source = self.archive([("library/LICENSE", b"x" * (2 * 1024 * 1024 + 1))])
        with self.assertRaisesRegex(ValueError, "单项许可"):
            m.collect_notices(source, self.root / "oversized.zip", minimum_files=1)
        with self.assertRaisesRegex(ValueError, "不完整"):
            m.collect_notices(self.archive([("library/LICENSE", b"licence")]), self.root / "incomplete.zip", minimum_files=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
