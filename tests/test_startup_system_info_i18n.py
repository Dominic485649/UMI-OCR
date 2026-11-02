"""Directed About diagnostics translation tests; QtCore only, no user settings."""

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import types
import unittest
from unittest import mock
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = ("en_US", "ja_JP", "pt", "ru_RU", "ta", "zh_TW")
SOURCES = ("正在后台采集系统信息…", "系统信息采集失败：%1", "系统信息采集已取消")
TARGETS = {
    "en_US": ("Collecting system information in the background…", "Failed to collect system information: %1", "System information collection cancelled"),
    "ja_JP": ("システム情報をバックグラウンドで収集中…", "システム情報を収集できませんでした：%1", "システム情報の収集をキャンセルしました"),
    "pt": ("Coletando informações do sistema em segundo plano…", "Falha ao coletar informações do sistema: %1", "Coleta de informações do sistema cancelada"),
    "ru_RU": ("Сбор информации о системе в фоновом режиме…", "Не удалось собрать информацию о системе: %1", "Сбор информации о системе отменён"),
    "ta": ("பின்னணியில் கணினித் தகவல்கள் சேகரிக்கப்படுகின்றன…", "கணினித் தகவல்களைச் சேகரிக்க முடியவில்லை: %1", "கணினித் தகவல் சேகரிப்பு ரத்து செய்யப்பட்டது"),
    "zh_TW": ("正在背景收集系統資訊…", "系統資訊收集失敗：%1", "系統資訊收集已取消"),
}
OPTIONS = None


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def messages(path):
    result = []
    for context in ET.parse(path).getroot().findall("context"):
        for message in context.findall("message"):
            translation = message.find("translation")
            kind = translation.get("type", "") if translation is not None else "unfinished"
            if kind not in {"obsolete", "vanished"}:
                result.append((context.findtext("name"), message.findtext("source", ""),
                               "".join(translation.itertext()) if translation is not None else "", kind))
    return result


class AboutSystemInfoTranslations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        packages = OPTIONS.qt_data.resolve() / "site-packages"
        sys.path.insert(0, str(packages))
        cls.dll_handle = os.add_dll_directory(str(packages / "PySide6"))
        from PySide6.QtCore import QCoreApplication, QTranslator, qInstallMessageHandler, qVersion
        cls.qt = types.SimpleNamespace(QCoreApplication=QCoreApplication, QTranslator=QTranslator,
                                      qInstallMessageHandler=qInstallMessageHandler, qVersion=qVersion)
        cls.app = QCoreApplication.instance() or QCoreApplication([])
        cls.catalogues = {code: messages(ROOT / "dev-tools/i18n/release" / (code + ".ts")) for code in LANGUAGES}
        cls.baseline = json.loads(OPTIONS.baseline.read_text("utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.dll_handle.close()
        sys.path.remove(str(OPTIONS.qt_data.resolve() / "site-packages"))

    def test_three_about_qstr_keys_and_failed_placeholder_are_unchanged(self):
        source = (ROOT / "UmiOCR-data/qt_res/qml/TabPages/About/About.qml").read_text("utf-8")
        keys = Counter(re.findall(r'qsTr\("([^"\n]+)"\)', source))
        for key in SOURCES:
            self.assertEqual(keys[key], 1)
        self.assertIn('qsTr("系统信息采集失败：%1").arg(UmiSystemInfo.error)', source)
        self.assertNotIn("zh_CN", TARGETS)
        self.assertEqual(SOURCES[1].count("%1"), 1)

    def test_six_catalogues_have_exact_finished_targets_in_about_context(self):
        for code, targets in TARGETS.items():
            for source, target in zip(SOURCES, targets):
                with self.subTest(code=code, source=source):
                    matching = [row for row in self.catalogues[code] if row[1] == source]
                    self.assertEqual(matching, [("About", source, target, "")])
                    self.assertEqual(Counter(re.findall(r"%\d+", source)), Counter(re.findall(r"%\d+", target)))
                    self.assertNotEqual(source, target)
                    if code != "en_US":
                        self.assertNotEqual(target, TARGETS["en_US"][SOURCES.index(source)])
        for code, pattern in (("ru_RU", r"[А-Яа-яЁё]"), ("ta", r"[஀-௿]")):
            for target in TARGETS[code]:
                self.assertRegex(target, pattern)

    def test_only_three_new_messages_added_and_other_ts_bytes_preserved(self):
        for item in self.baseline["catalogues"]:
            path = Path(item["ts"]["path"])
            text = path.read_bytes().decode("utf-8")
            removed = []
            def strip_delta(match):
                node = ET.fromstring(match.group())
                if node.findtext("source") in SOURCES:
                    removed.append(node.findtext("source"))
                    return ""
                return match.group()
            previous = re.sub(r"(?ms)^    <message>\r?\n.*?^    </message>\r?\n", strip_delta, text)
            self.assertEqual(Counter(removed), Counter(SOURCES))
            self.assertEqual(hashlib.sha256(previous.encode("utf-8")).hexdigest(), item["ts"]["sha256"])
            self.assertEqual(len(self.catalogues[item["code"]]), item["activeMessages"] + 3)

    def test_compiled_qm_preserves_every_active_message_in_affected_catalogues(self):
        self.assertEqual(self.qt.qVersion(), "6.11.2")
        for code in LANGUAGES:
            translator = self.qt.QTranslator()
            path = ROOT / "UmiOCR-data/i18n" / (code + ".qm")
            self.assertTrue(translator.load(str(path)), str(path))
            for context, source, target, kind in self.catalogues[code]:
                with self.subTest(code=code, context=context, source=source):
                    self.assertEqual(kind, "")
                    self.assertEqual(translator.translate(context, source), target)
        self.assertNotIn("PySide6.QtGui", sys.modules)
        self.assertNotIn("PySide6.QtWidgets", sys.modules)

    def test_real_i18n_setlanguage_switches_all_seven_languages_without_user_config(self):
        package = types.ModuleType("about_i18n_fixture")
        package.__path__ = []
        pre = types.ModuleType("about_i18n_fixture.pre_configs")
        settings, plugin_codes, retranslations = [], [], []
        pre.setValue = lambda key, value: settings.append((key, value))
        package.pre_configs = pre
        plugin = types.ModuleType("plugin_i18n")
        plugin.setLangCode = plugin_codes.append
        with mock.patch.dict(sys.modules, {"about_i18n_fixture": package,
            "about_i18n_fixture.pre_configs": pre, "plugin_i18n": plugin, "umi_log": mock.Mock()}):
            path = ROOT / "UmiOCR-data/py_src/utils/i18n_configs.py"
            spec = importlib.util.spec_from_file_location("about_i18n_fixture.i18n_configs", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        manager = module.I18n
        manager.qtApp, manager.translator, manager.langCode = self.app, self.qt.QTranslator(), ""
        manager.langDict = {"zh_CN": ["简体中文", ""]}
        manager.langDict.update({code: [code, str(ROOT / "UmiOCR-data/i18n" / (code + ".qm"))] for code in LANGUAGES})
        def retranslate():
            retranslations.append((manager.langCode, tuple(self.qt.QCoreApplication.translate("About", key) for key in SOURCES)))
        self.app.qmlEngine = types.SimpleNamespace(retranslate=retranslate)
        cycle = ("zh_CN", *LANGUAGES, *reversed(("zh_CN", *LANGUAGES)))
        sentinel = "ERR_SENTINEL Ω {path} %2"
        try:
            for code in cycle:
                self.assertTrue(manager.setLanguage(code), code)
                expected = SOURCES if code == "zh_CN" else TARGETS[code]
                actual = tuple(self.qt.QCoreApplication.translate("About", key) for key in SOURCES)
                self.assertEqual(actual, expected, code)
                self.assertEqual(retranslations[-1], (code, expected))
                self.assertEqual(actual[1].replace("%1", sentinel), expected[1].replace("%1", sentinel))
                self.assertIn(sentinel, actual[1].replace("%1", sentinel))
            self.assertEqual(plugin_codes, list(cycle))
            self.assertEqual(settings, [("i18n", code) for code in cycle])
            self.assertEqual(len(retranslations), len(cycle))
        finally:
            self.app.removeTranslator(manager.translator)
            self.app.translators = []
            del self.app.qmlEngine


def main():
    global OPTIONS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qt-data", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    OPTIONS = parser.parse_args()
    paths = [Path(__file__), ROOT / "UmiOCR-data/qt_res/qml/TabPages/About/About.qml",
             ROOT / "UmiOCR-data/py_src/utils/i18n_configs.py"]
    paths += [ROOT / "dev-tools/i18n/release" / (code + ".ts") for code in LANGUAGES]
    paths += [ROOT / "UmiOCR-data/i18n" / (code + ".qm") for code in LANGUAGES]
    before = {str(path): digest(path) for path in paths}
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(AboutSystemInfoTranslations))
    after = {str(path): digest(path) for path in paths}
    report = {"status": "PASS" if result.wasSuccessful() and not result.skipped and before == after else "FAIL",
        "pythonExecutable": sys.executable, "pythonVersion": sys.version,
        "isolated": sys.flags.isolated, "dontWriteBytecode": sys.flags.dont_write_bytecode,
        "utf8Mode": sys.flags.utf8_mode, "qtVersion": AboutSystemInfoTranslations.qt.qVersion(),
        "testsRun": result.testsRun, "failures": [(str(test), text) for test, text in result.failures],
        "errors": [(str(test), text) for test, text in result.errors], "skipped": [(str(test), reason) for test, reason in result.skipped],
        "sourceSha256": after, "sourcesUnchangedDuringTests": before == after,
        "languageCount": 7, "compiledCatalogueCount": 6,
        "activeMessagesPerCatalogue": {code: len(rows) for code, rows in AboutSystemInfoTranslations.catalogues.items()},
        "hotSwitch": "real I18n.setLanguage/QTranslator installation/removal, in-memory config/plugin stubs and retranslate callback spy; not live QML/GUI",
        "qtGuiImported": "PySide6.QtGui" in sys.modules, "qtWidgetsImported": "PySide6.QtWidgets" in sys.modules,
        "guiOrExeStarted": False, "scope": "three About status keys; byte-preservation delta and every active message in six newly compiled catalogues"}
    OPTIONS.audit.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({key: report[key] for key in ("status", "testsRun", "languageCount", "compiledCatalogueCount", "sourcesUnchangedDuringTests")}, ensure_ascii=False))
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
