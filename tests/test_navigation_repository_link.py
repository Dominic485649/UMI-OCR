"""首页仓库链接的定向回归：来源、六语目录与实际QM，不启动程序或模型。"""
import argparse
import json
import os
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
QT_DATA = None
TRANSLATIONS = {
    "en_US": "Repository link",
    "ja_JP": "リポジトリへのリンク",
    "pt": "Link do repositório",
    "ru_RU": "Ссылка на репозиторий",
    "ta": "களஞ்சிய இணைப்பு",
    "zh_TW": "儲存庫連結",
}


class NavigationRepositoryLink(unittest.TestCase):
    def test_home_label_keeps_actual_repository_target(self):
        source = (ROOT / "UmiOCR-data/qt_res/qml/TabPages/Navigation/Navigation.qml").read_text("utf-8-sig")
        self.assertIn('[`+qsTr("仓库链接")+`](${UmiAbout.url.home})', source)
        self.assertNotIn('qsTr("官方网站")', source)
        about = json.loads((ROOT / "UmiOCR-data/about.json").read_text("utf-8-sig"))
        self.assertEqual(about["url"]["home"], "https://github.com/Dominic485649/UMI-OCR")

    def test_supported_catalogs_have_navigation_context_translation(self):
        for code, expected in TRANSLATIONS.items():
            with self.subTest(language=code):
                root = ET.parse(ROOT / "dev-tools/i18n/release" / (code + ".ts")).getroot()
                contexts = {context.findtext("name"): context for context in root.findall("context")}
                messages = {message.findtext("source"): message for message in contexts["Navigation"].findall("message")}
                self.assertNotIn("官方网站", messages)
                translated = messages["仓库链接"].find("translation")
                self.assertNotIn(translated.get("type"), ("unfinished", "obsolete", "vanished"))
                self.assertEqual(translated.text, expected)
                self.assertTrue(any(message.findtext("source") == "官方网站" for message in contexts["About"].findall("message")),
                    "本次首页改名不应顺带修改关于页")

    def test_compiled_qm_has_new_navigation_key(self):
        if QT_DATA is None:
            self.skipTest("通过--qt-data显式提供独立QtCore依赖，才验证实际QM")
        self.assertTrue(sys.flags.dont_write_bytecode and sys.flags.isolated)
        sys.path[:0] = [str(QT_DATA / "site-packages"), str(QT_DATA / "dependencies.zip")]
        handle = os.add_dll_directory(str(QT_DATA / "site-packages/PySide6"))
        try:
            from PySide6.QtCore import QCoreApplication, QTranslator
            application = QCoreApplication.instance() or QCoreApplication([])
            self.assertEqual(QCoreApplication.translate("Navigation", "仓库链接"), "仓库链接")
            for code, expected in TRANSLATIONS.items():
                with self.subTest(language=code):
                    translator = QTranslator()
                    self.assertTrue(translator.load(str(ROOT / "UmiOCR-data/i18n" / (code + ".qm"))))
                    self.assertTrue(application.installTranslator(translator))
                    try:
                        self.assertEqual(QCoreApplication.translate("Navigation", "仓库链接"), expected)
                        self.assertTrue(translator.translate("About", "官方网站"))
                        self.assertFalse(translator.translate("Navigation", "官方网站"))
                    finally:
                        application.removeTranslator(translator)
            self.assertFalse(any(name.split(".")[0] in {"paddle", "paddlex", "torch"} for name in sys.modules))
        finally:
            handle.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qt-data", type=Path)
    args, remaining = parser.parse_known_args()
    QT_DATA = args.qt_data
    unittest.main(argv=[sys.argv[0], *remaining])
