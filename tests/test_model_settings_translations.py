"""Directed translation coverage tests. No GUI, GPU, network, or user settings.

Use --qt-data for QtCore-only compiled-QM verification. The plugin repository
is explicit, because neither release installations nor CPU plugins are inputs.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import csv
import importlib.util
import json
import logging
import os
from pathlib import Path
import re
import string
import sys
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
OPTIONS = None


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CHECKER = load_module("model_settings_i18n_checker", ROOT / "build/tools/model_settings_i18n.py")
LANGUAGES = CHECKER.LANGUAGES
TECHNICAL_IDENTITIES = {"Flash Attention", "f16", "q8_0", "NVIDIA CUDA 12.6", "PP-OCRv6_medium", "PaddleOCR-VL 1.6", "PaddleOCR-VL1.6", "OCR", "JSON", "JSONL", "Markdown", "Cyberpunk"}
PRESERVED_TERMS = ("[[x1,y1],[x2,y2]]", "fullPage", "imageOnly", "textOnly", "PP-OCRv6_medium", "PaddleOCR-VL 1.6", "PP-DocLayoutV3", "inference.json", "mmproj-*.gguf", "gpu:N", "gpu:0", "Turing sm75", "BT.2390", "DXGI", "llama-server", "f16", "q8_0")


def read_csv(path):
    header, rows = CHECKER.csv_rows(path)
    return header, {row["zh_CN"]: row for row in rows}


def sample_values(template):
    values = {}
    for _, field, spec, _ in string.Formatter().parse(template):
        if field is not None:
            if re.search(r"[eEfFgG%]$", spec):
                values[field] = 12.5
            elif re.search(r"[bcdoxXn]$", spec):
                values[field] = 12
            else:
                values[field] = "VALUE_" + field
    return values


class TranslationCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vl_root = OPTIONS.vl_root.resolve()
        cls.report = CHECKER.inventory(ROOT, cls.vl_root)
        cls.tables = {
            "cuda": ROOT / "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/i18n.csv",
            "vl": cls.vl_root / "i18n.csv",
            "host": ROOT / "UmiOCR-data/i18n/runtime.csv",
        }

    def test_all_active_ts_complete_and_placeholders_intact(self):
        for language, info in self.report["ts"].items():
            with self.subTest(language=language):
                self.assertEqual(info["unfinished"], 0)
                self.assertEqual(info["empty"], 0)
                self.assertEqual(info["problems"], 0, self.report["ts_problems"][language])

    def test_qml_context_source_coverage(self):
        for language, info in self.report["ts"].items():
            with self.subTest(language=language):
                self.assertEqual(info["qml_missing"], [])
        expected = {(m["context"], m["source"]) for m in CHECKER.ts_messages(ROOT / "dev-tools/i18n/release/en_US.ts")}
        for language in LANGUAGES:
            actual = {(m["context"], m["source"]) for m in CHECKER.ts_messages(ROOT / ("dev-tools/i18n/release/" + language + ".ts"))}
            self.assertEqual(expected, actual)

    def test_no_english_ts_fallbacks(self):
        for language, items in self.report["suspect_english"].items():
            for item in items:
                with self.subTest(language=language, source=item["source"]):
                    self.assertIn(item["translation"], TECHNICAL_IDENTITIES)

    def test_csv_columns_rows_and_languages(self):
        for name, path in self.tables.items():
            with self.subTest(table=name):
                self.assertTrue(path.is_file(), str(path))
                header, rows = CHECKER.csv_rows(path)
                self.assertEqual(tuple(header), CHECKER.CSV_LANGUAGES)
                self.assertEqual(len(rows), len({row["zh_CN"] for row in rows}), "duplicate source rows")
                self.assertTrue(rows)
                for row in rows:
                    source = row["zh_CN"]
                    self.assertNotIn(None, row, "malformed CSV column count")
                    for language in LANGUAGES:
                        self.assertTrue(row.get(language, "").strip(), (name, language, source))
                        self.assertEqual(CHECKER.placeholders(source), CHECKER.placeholders(row[language]), (name, language, source))
                        row[language].format(**sample_values(source))
                        if source not in TECHNICAL_IDENTITIES:
                            required_script = {"ru_RU": r"[А-Яа-яЁё]", "ta": r"[஀-௿]"}.get(language)
                            if required_script:
                                self.assertRegex(row[language], required_script, (name, language, source, "missing target-language script"))
                        prefix = re.match(r"^(\[(?:Error|Warning|Success)\]|[A-Z][A-Z_]+(?=[:：]))", source)
                        if prefix:
                            self.assertTrue(row[language].startswith(prefix.group()), (name, language, source))
                        for term in PRESERVED_TERMS:
                            if term in source:
                                self.assertIn(term, row[language], (name, language, source, term))
                    if source not in TECHNICAL_IDENTITIES:
                        self.assertFalse(all(row[language] == source for language in LANGUAGES), (name, source, "all-column source fallback"))
                        for language in ("ja_JP", "pt", "ru_RU", "ta", "zh_TW"):
                            self.assertNotEqual(row[language], row["en_US"], (name, source, language, "English fallback"))

    def test_plugin_python_and_manifest_coverage(self):
        for name, info in self.report["plugins"].items():
            with self.subTest(plugin=name):
                self.assertEqual(info["missing"], [])

    def test_theme_connector_new_runtime_templates(self):
        expected = {
            "同步 Windows 标题栏主题失败：{error}": (
                "Failed to synchronize the Windows title-bar theme: {error}",
                "Windows のタイトルバーのテーマを同期できませんでした：{error}",
                "Falha ao sincronizar o tema da barra de título do Windows: {error}",
                "Не удалось синхронизировать тему заголовка окна Windows: {error}",
                "Windows தலைப்புப் பட்டைக் கருப்பொருளை ஒத்திசைக்க முடியவில்லை: {error}",
                "同步 Windows 標題列佈景主題失敗：{error}",
            ),
            "读取主题文件失败。": (
                "Failed to read the theme file.",
                "テーマファイルを読み取れませんでした。",
                "Falha ao ler o arquivo do tema.",
                "Не удалось прочитать файл темы.",
                "கருப்பொருள் கோப்பைப் படிக்க முடியவில்லை.",
                "讀取佈景主題檔案失敗。",
            ),
        }
        templates = CHECKER.python_templates(ROOT / "UmiOCR-data/py_src/utils/theme_connector.py")
        _, rows = read_csv(self.tables["host"])
        active = types.ModuleType("plugin_i18n")
        shadow = types.ModuleType("py_src.imports.plugin_i18n")
        shadow.LangCode = "zh_CN"
        with mock.patch.dict(sys.modules, {"plugin_i18n": active, "py_src.imports.plugin_i18n": shadow}):
            host = load_module("translation_test_theme_delta_loader", ROOT / "UmiOCR-data/py_src/utils/runtime_i18n.py")
            for source, translations in expected.items():
                self.assertIn(source, templates)
                self.assertIn(source, rows)
                values = {"error": RuntimeError("THEME_SENTINEL {not_a_field}")} if "{error}" in source else {}
                for code, target in zip(LANGUAGES, translations):
                    active.LangCode = code
                    self.assertEqual(rows[source][code], target)
                    self.assertEqual(CHECKER.placeholders(source), CHECKER.placeholders(target))
                    result = host.tr(source, **values)
                    self.assertEqual(result, target.format(**values))
                    self.assertNotEqual(result, source.format(**values), (code, source, "source fallback cannot pass"))
            self.assertNotIn("PySide6.QtGui", sys.modules)
            self.assertNotIn("paddle", sys.modules)

    def test_mission_task_error_source_key_has_no_trailing_space(self):
        source = "[Error] No overloaded msnTask.\n【异常】未重载msnTask。"
        old_source = "[Error] No overloaded msnTask. \n【异常】未重载msnTask。"
        templates = CHECKER.python_templates(ROOT / "UmiOCR-data/py_src/mission/mission.py")
        self.assertIn(source, templates)
        self.assertNotIn(old_source, templates)
        _, rows = read_csv(self.tables["host"])
        self.assertIn(source, rows)
        self.assertNotIn(old_source, rows)
        expected = dict(zip(LANGUAGES, (
            "[Error] msnTask has not been overridden.",
            "[Error] msnTask がオーバーライドされていません。",
            "[Error] msnTask não foi sobrescrito.",
            "[Error] msnTask не переопределён.",
            "[Error] msnTask மேலெழுதப்படவில்லை.",
            "[Error] 未覆寫 msnTask。",
        )))
        active = types.ModuleType("plugin_i18n")
        with mock.patch.dict(sys.modules, {"plugin_i18n": active, "py_src.imports.plugin_i18n": None}):
            host = load_module("translation_test_mission_whitespace_key", ROOT / "UmiOCR-data/py_src/utils/runtime_i18n.py")
            for code in LANGUAGES:
                active.LangCode = code
                self.assertEqual(rows[source][code], expected[code], (code, "existing target translation changed"))
                self.assertEqual(host.tr(source), expected[code], (code, "source fallback is not translation coverage"))

    def test_host_python_template_coverage(self):
        _, rows = read_csv(self.tables["host"])
        templates = set()
        for path in (ROOT / "UmiOCR-data/py_src").rglob("*.py"):
            text = path.read_text(encoding="utf-8-sig")
            if "runtime_i18n import" in text:
                templates.update(CHECKER.python_templates(path))
        self.assertTrue(templates, "no host runtime_i18n call sites discovered")
        self.assertEqual(sorted(templates - rows.keys()), [])

    def test_cuda_device_probe_templates_have_six_translations(self):
        path = ROOT / "UmiOCR-data/py_src/utils/cuda_device_probe.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        templates = set()
        for statement in tree.body:
            if not isinstance(statement, ast.Assign):
                continue
            if not any(isinstance(target, ast.Name) and target.id == "_MESSAGES" for target in statement.targets):
                continue
            self.assertIsInstance(statement.value, ast.Dict)
            templates.update(
                value.value for value in statement.value.values
                if isinstance(value, ast.Constant) and isinstance(value.value, str)
            )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else ""
            if name != "_failure":
                continue
            templates.update(
                keyword.value.value for keyword in node.keywords
                if keyword.arg == "template"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            )
        self.assertEqual(len(templates), 9, "update this coverage when CUDA discovery templates change")
        _, rows = read_csv(self.tables["host"])
        self.assertEqual(sorted(templates - rows.keys()), [])
        for source in templates:
            with self.subTest(source=source):
                self.assertIn(source, rows)
                for language in LANGUAGES:
                    translation = rows[source].get(language, "")
                    self.assertTrue(translation.strip(), (language, source, "missing translation"))
                    self.assertEqual(CHECKER.placeholders(source), CHECKER.placeholders(translation), (language, source, "placeholder mismatch"))

    def test_interface_documentation_is_not_executed_as_translation(self):
        for path in (ROOT / "UmiOCR-data/py_src").rglob("*.py"):
            text = path.read_text(encoding="utf-8-sig")
            if "runtime_i18n import" not in text:
                continue
            tree = ast.parse(text, filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call) or not node.value.args:
                    continue
                call = node.value
                name = call.func.id if isinstance(call.func, ast.Name) else ""
                first = call.args[0]
                if name == "tr" and isinstance(first, ast.Constant) and isinstance(first.value, str):
                    self.assertFalse(first.value.startswith("\n") and "方法：POST" in first.value, (str(path), node.lineno, "interface documentation must remain non-executable; JSON braces are not format fields"))

    def test_placeholder_validator_rejects_real_regressions(self):
        pairs = (("%1 %2", "%1 %1"), ("%date %name %range", "%date %nome %range"), ("%Y %m %d %H %M %S %unix", "%Y %m %d %h %M %S %unix"), ("{field!r}", "{field}"), (r"\1\2<已隐藏>", r"\1<hidden>"))
        for original, broken in pairs:
            self.assertNotEqual(CHECKER.placeholders(original), CHECKER.placeholders(broken))
        self.assertEqual(CHECKER.placeholders("value {{x}} {name}"), CHECKER.placeholders("மதிப்பு {{x}} {name}"))

    def test_comment_extraction_and_fixed_language_label(self):
        source = '// qsTr("ignore")\ntext: qsTr("yes // quoted") /* qsTr("ignore2") */'
        clean = CHECKER.strip_qml_comments(source)
        self.assertNotIn('qsTr("ignore")', clean)
        self.assertNotIn('qsTr("ignore2")', clean)
        self.assertIn('qsTr("yes // quoted")', clean)
        qml = (ROOT / "UmiOCR-data/qt_res/qml/Configs/GlobalConfigs.qml").read_text(encoding="utf-8")
        self.assertIn('"title": "语言/language"', qml)
        self.assertNotIn('qsTr("语言/language")', qml)
        tree = ast.parse((ROOT / "UmiOCR-data/py_src/utils/i18n_configs.py").read_text(encoding="utf-8"))
        language_codes = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "LanguageCodes" for target in node.targets))
        self.assertEqual(set(language_codes.values()), {"简体中文", "繁體中文", "English", "日本語", "Português", "Русский", "தமிழ்"})

    def test_host_and_plugin_dynamic_language_without_qt(self):
        umi_log = types.ModuleType("umi_log")
        umi_log.logger = logging.getLogger("translation-test")
        with mock.patch.dict(sys.modules, {"umi_log": umi_log}):
            translator_api = load_module("translation_test_plugin_i18n", ROOT / "UmiOCR-data/py_src/imports/plugin_i18n.py")
        fake_host = types.ModuleType("py_src")
        fake_host.__path__ = []
        fake_imports = types.ModuleType("py_src.imports")
        fake_imports.__path__ = []
        package = types.ModuleType("translation_test_vl")
        package.__path__ = [str(self.vl_root)]
        modules = {"plugin_i18n": translator_api, "py_src": fake_host, "py_src.imports": fake_imports, "py_src.imports.plugin_i18n": translator_api, "translation_test_vl": package}
        with mock.patch.dict(sys.modules, modules):
            host = load_module("translation_test_runtime_i18n", ROOT / "UmiOCR-data/py_src/utils/runtime_i18n.py")
            cuda = load_module("translation_test_cuda_i18n", ROOT / "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/i18n_helpers.py")
            vl = load_module("translation_test_vl.checks", self.vl_root / "checks.py")
            runtime = load_module("translation_test_vl.runtime", self.vl_root / "runtime.py")
            for code in ("zh_CN", *LANGUAGES, "zh_CN", "ta", "en_US"):
                translator_api.LangCode = code
                for name, translator in (("host", host.tr), ("cuda", cuda.tr), ("vl", vl.tr)):
                    _, rows = read_csv(self.tables[name])
                    for original, row in rows.items():
                        with self.subTest(table=name, language=code, source=original):
                            values = sample_values(original)
                            expected = (original if code == "zh_CN" else row[code]).format(**values)
                            self.assertEqual(translator(original, **values), expected)
                text = r"C:\Users\PrivateIdentity\model.gguf /home/PrivateIdentity/file api_key=SECRET authorization:SECRET password=SECRET access_token=SECRET"
                redacted = runtime.RuntimeService._redactLog(text)
                self.assertNotIn("PrivateIdentity", redacted)
                self.assertNotIn("SECRET", redacted)
                self.assertIn("C:" + chr(92) + "Users" + chr(92), redacted)
                self.assertIn("/home/", redacted)
            self.assertNotIn("PySide6.QtGui", sys.modules)
            self.assertNotIn("paddle", sys.modules)

    def test_real_inline_manifest_display_fields_are_translated(self):
        umi_log = types.ModuleType("umi_log")
        umi_log.logger = logging.getLogger("translation-manifest-test")
        root_package = types.ModuleType("translation_test_manifest_host")
        root_package.__path__ = [str(ROOT / "UmiOCR-data/py_src")]
        package = types.ModuleType("translation_test_manifest_host.plugins_controller")
        package.__path__ = [str(ROOT / "UmiOCR-data/py_src/plugins_controller")]
        utilities = types.ModuleType("translation_test_manifest_host.utils")
        utilities.__path__ = [str(ROOT / "UmiOCR-data/py_src/utils")]
        with mock.patch.dict(sys.modules, {"umi_log": umi_log, "translation_test_manifest_host": root_package, "translation_test_manifest_host.plugins_controller": package, "translation_test_manifest_host.utils": utilities}):
            api = load_module("translation_manifest_language_api", ROOT / "UmiOCR-data/py_src/imports/plugin_i18n.py")
            load_module("translation_test_manifest_host.utils.runtime_i18n", ROOT / "UmiOCR-data/py_src/utils/runtime_i18n.py")
            load_module("translation_test_manifest_host.plugins_controller.host_api", ROOT / "UmiOCR-data/py_src/plugins_controller/host_api.py")
            manifest = load_module("translation_test_manifest_host.plugins_controller.manifest", ROOT / "UmiOCR-data/py_src/plugins_controller/manifest.py")
            raw = json.loads((self.vl_root / "umi-plugin.json").read_text(encoding="utf-8"))
            original = raw["services"][0]["config"]
            _, rows = read_csv(self.tables["vl"])
            for code in LANGUAGES:
                api.setLangCode(code)
                translated = manifest._translateConfig(original, api.Translator(str(self.vl_root / "umi-plugin.json"), "i18n.csv"))
                self.assertEqual(translated["title"], rows[original["title"]][code])
                self.assertEqual(translated["notice"]["toolTip"], rows[original["notice"]["toolTip"]][code])
                self.assertEqual(translated["notice"]["optionsList"][0][1], rows[original["notice"]["optionsList"][0][1]][code])
                self.assertEqual(translated["notice"]["optionsList"][0][0], "user-supplied")
                for field in ("mainModel", "mmprojModel"):
                    self.assertEqual(translated["service"][field]["nameFilters"], [rows[source][code] for source in original["service"][field]["nameFilters"]])
                self.assertEqual(translated["resources"]["timeoutSeconds"]["unit"], rows["秒"][code])
                self.assertEqual(translated["resources"]["contextLength"]["default"], 16384)
                self.assertEqual(translated["resources"]["contextLength"]["toolTip"], rows[original["resources"]["contextLength"]["toolTip"]][code])
                self.assertNotIn("gpuLayers", translated["resources"])

    def test_manifest_host_errors_do_not_use_plugin_csv_callback(self):
        umi_log = types.ModuleType("umi_log")
        umi_log.logger = logging.getLogger("translation-manifest-validation-test")
        root_package = types.ModuleType("translation_test_manifest_validation")
        root_package.__path__ = [str(ROOT / "UmiOCR-data/py_src")]
        package = types.ModuleType("translation_test_manifest_validation.plugins_controller")
        package.__path__ = [str(ROOT / "UmiOCR-data/py_src/plugins_controller")]
        utilities = types.ModuleType("translation_test_manifest_validation.utils")
        utilities.__path__ = [str(ROOT / "UmiOCR-data/py_src/utils")]
        with mock.patch.dict(sys.modules, {"umi_log": umi_log, "translation_test_manifest_validation": root_package, "translation_test_manifest_validation.plugins_controller": package, "translation_test_manifest_validation.utils": utilities}):
            api = load_module("translation_manifest_validation_language", ROOT / "UmiOCR-data/py_src/imports/plugin_i18n.py")
            sys.modules["plugin_i18n"] = api
            load_module("translation_test_manifest_validation.utils.runtime_i18n", ROOT / "UmiOCR-data/py_src/utils/runtime_i18n.py")
            load_module("translation_test_manifest_validation.plugins_controller.host_api", ROOT / "UmiOCR-data/py_src/plugins_controller/host_api.py")
            manifest = load_module("translation_test_manifest_validation.plugins_controller.manifest", ROOT / "UmiOCR-data/py_src/plugins_controller/manifest.py")
            _, rows = read_csv(self.tables["host"])
            for code in LANGUAGES:
                api.setLangCode(code)
                plugin_translator = api.Translator(str(self.vl_root / "umi-plugin.json"), "i18n.csv")
                raw = {"schema_version": 999}
                with mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(raw))):
                    parsed, error = manifest.loadManifest("translation_dummy", str(self.vl_root), plugin_translator)
                self.assertIsNone(parsed)
                self.assertEqual(error, rows["不支持的 schema_version：{schema}（宿主支持：{supported}）。"][code].format(schema=999, supported="1"))
                raw = {"schema_version": 1, "id": "translation_dummy", "version": ""}
                with mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(raw))):
                    parsed, error = manifest.loadManifest("translation_dummy", str(self.vl_root), plugin_translator)
                self.assertIsNone(parsed)
                self.assertEqual(error, rows["清单缺少 version 。"][code])

    def test_plain_host_language_wins_over_shadow_namespace(self):
        umi_log = types.ModuleType("umi_log")
        umi_log.logger = logging.getLogger("translation-namespace-test")
        with mock.patch.dict(sys.modules, {"umi_log": umi_log}):
            active = load_module("translation_active_language_api", ROOT / "UmiOCR-data/py_src/imports/plugin_i18n.py")
            shadow = load_module("translation_shadow_language_api", ROOT / "UmiOCR-data/py_src/imports/plugin_i18n.py")
        shadow.LangCode = ""
        fake_host = types.ModuleType("py_src")
        fake_host.__path__ = []
        fake_imports = types.ModuleType("py_src.imports")
        fake_imports.__path__ = []
        package = types.ModuleType("translation_test_namespace_vl")
        package.__path__ = [str(self.vl_root)]
        with mock.patch.dict(sys.modules, {"plugin_i18n": active, "py_src": fake_host, "py_src.imports": fake_imports, "py_src.imports.plugin_i18n": shadow, "translation_test_namespace_vl": package}):
            host = load_module("translation_namespace_host_i18n", ROOT / "UmiOCR-data/py_src/utils/runtime_i18n.py")
            cuda = load_module("translation_namespace_cuda_i18n", ROOT / "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/i18n_helpers.py")
            vl = load_module("translation_test_namespace_vl.checks", self.vl_root / "checks.py")
            api_module = load_module("translation_test_namespace_vl.api", self.vl_root / "api.py")
            for code in LANGUAGES:
                active.setLangCode(code)
                self.assertEqual(api_module._WorkerClient._environment()["UMI_PLUGIN_LANGUAGE"], code)
                self.assertEqual(host.language(), code)
                self.assertEqual(cuda.language(), code)
                for name, translator in (("cuda", cuda.tr), ("vl", vl.tr)):
                    _, rows = read_csv(self.tables[name])
                    source = "CUDA 设备" if name == "cuda" else "主 GGUF"
                    self.assertEqual(translator(source), rows[source][code], (name, code, "shadow LangCode must not override host"))

    def test_vl_redaction_for_all_languages(self):
        package = types.ModuleType("translation_test_redaction_vl")
        package.__path__ = [str(self.vl_root)]
        with mock.patch.dict(sys.modules, {"plugin_i18n": None, "py_src.imports.plugin_i18n": None, "translation_test_redaction_vl": package}):
            load_module("translation_test_redaction_vl.checks", self.vl_root / "checks.py")
            runtime = load_module("translation_test_redaction_vl.runtime", self.vl_root / "runtime.py")
            text = r"C:\Users\PrivateIdentity\model.gguf /home/PrivateIdentity/file api_key=SECRET authorization:SECRET password=SECRET access_token=SECRET"
            for code in ("zh_CN", *LANGUAGES):
                with mock.patch.dict(os.environ, {"UMI_PLUGIN_LANGUAGE": code}):
                    result = runtime.RuntimeService._redactLog(text)
                    self.assertNotIn("PrivateIdentity", result, code)
                    self.assertNotIn("SECRET", result, code)
                    self.assertIn("C:" + chr(92) + "Users" + chr(92), result)
                    self.assertIn("/home/", result)

    def test_zipimport_catalogue_path_and_missing_file_safety(self):
        host = load_module("translation_test_zip_runtime_i18n", ROOT / "UmiOCR-data/py_src/utils/runtime_i18n.py")
        data = ROOT / "build/tmp/model-settings-20261026-020955-i18n/nonexistent-package"
        source_file = data / "py_src/utils/runtime_i18n.py"
        zipped_file = data / "app.zip/py_src/utils/runtime_i18n.py"
        expected = data / "i18n/runtime.csv"
        self.assertEqual(host._catalogue_path(source_file), expected.resolve())
        self.assertEqual(host._catalogue_path(zipped_file), expected.resolve())
        api = types.ModuleType("plugin_i18n")
        api.LangCode = "ta"
        with mock.patch.object(host, "_CATALOGUE_PATH", expected), mock.patch.dict(sys.modules, {"plugin_i18n": api, "py_src.imports.plugin_i18n": None}):
            host._catalogue.cache_clear()
            self.assertEqual(host.tr("缺少 {name}", name="catalogue"), "缺少 catalogue")
        host._catalogue.cache_clear()

    def test_worker_language_environment_without_host_import(self):
        package = types.ModuleType("translation_test_worker_vl")
        package.__path__ = [str(self.vl_root)]
        with mock.patch.dict(sys.modules, {"plugin_i18n": None, "py_src.imports.plugin_i18n": None, "translation_test_worker_vl": package}):
            cuda = load_module("translation_test_worker_cuda_i18n", ROOT / "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/i18n_helpers.py")
            vl = load_module("translation_test_worker_vl.checks", self.vl_root / "checks.py")
            for code in ("zh_CN", *LANGUAGES, "ta", "en_US"):
                with mock.patch.dict(os.environ, {"UMI_PLUGIN_LANGUAGE": code}):
                    for name, translator in (("cuda", cuda.tr), ("vl", vl.tr)):
                        _, rows = read_csv(self.tables[name])
                        for original, row in rows.items():
                            values = sample_values(original)
                            expected = (original if code == "zh_CN" else row[code]).format(**values)
                            self.assertEqual(translator(original, **values), expected, (name, code, original))

    @unittest.skipUnless(os.name == "nt", "Qt runtime is Windows-only")
    def test_compiled_qm_every_active_message_qtcore_only(self):
        if OPTIONS.qt_data is None:
            self.skipTest("--qt-data not provided; compiled QM not verified")
        site_packages = OPTIONS.qt_data.resolve() / "site-packages"
        sys.path.insert(0, str(site_packages))
        handle = os.add_dll_directory(str(site_packages / "PySide6"))
        try:
            from PySide6.QtCore import QCoreApplication, QTranslator, qVersion
            self.assertEqual(qVersion(), "6.11.2")
            app = QCoreApplication.instance() or QCoreApplication([])
            self.assertIsNotNone(app)
            for language in LANGUAGES:
                translator = QTranslator()
                path = ROOT / "UmiOCR-data/i18n" / (language + ".qm")
                self.assertTrue(translator.load(str(path)), str(path))
                messages = CHECKER.ts_messages(ROOT / "dev-tools/i18n/release" / (language + ".ts"))
                for message in messages:
                    with self.subTest(language=language, context=message["context"], source=message["source"]):
                        self.assertEqual(translator.translate(message["context"], message["source"]), message["translation"])
            self.assertNotIn("PySide6.QtGui", sys.modules)
            self.assertNotIn("paddle", sys.modules)
        finally:
            handle.close()
            sys.path.remove(str(site_packages))


def input_hashes(vl_root):
    import hashlib
    paths = set()
    for code in LANGUAGES:
        paths.add(ROOT / "dev-tools/i18n/release" / (code + ".ts"))
        paths.add(ROOT / "UmiOCR-data/i18n" / (code + ".qm"))
    paths.update((ROOT / "UmiOCR-data/qt_res/qml").rglob("*.qml"))
    for directory in (ROOT / "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA", vl_root):
        paths.update(directory.glob("*.py"))
        paths.update(directory.glob("*.json"))
        paths.add(directory / "i18n.csv")
    paths.update((ROOT / "UmiOCR-data/i18n/runtime.csv", ROOT / "UmiOCR-data/py_src/utils/runtime_i18n.py", ROOT / "UmiOCR-data/py_src/utils/i18n_configs.py", ROOT / "UmiOCR-data/py_src/imports/plugin_i18n.py", ROOT / "UmiOCR-data/py_src/plugins_controller/manifest.py", ROOT / "UmiOCR-data/py_src/plugins_controller/host_api.py", Path(__file__), ROOT / "build/tools/model_settings_i18n.py"))
    for path in (ROOT / "UmiOCR-data/py_src").rglob("*.py"):
        if "runtime_i18n import" in path.read_text(encoding="utf-8-sig"):
            paths.add(path)
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None for path in sorted(paths)}


def main():
    global OPTIONS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vl-root", required=True, type=Path)
    parser.add_argument("--qt-data", type=Path)
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--tests", nargs="+", help="Optional explicit subset; the default runs every test")
    OPTIONS = parser.parse_args()
    suite = unittest.TestSuite(TranslationCoverage(name) for name in OPTIONS.tests) if OPTIONS.tests else unittest.defaultTestLoader.loadTestsFromTestCase(TranslationCoverage)
    before = input_hashes(OPTIONS.vl_root.resolve())
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    after = input_hashes(OPTIONS.vl_root.resolve())
    changed = sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path))
    if OPTIONS.audit:
        report = {"inputHashes": before, "inputChangedDuringRun": changed, "requestedTests": OPTIONS.tests, "testsRun": result.testsRun, "failures": [(str(case), text) for case, text in result.failures], "errors": [(str(case), text) for case, text in result.errors], "skipped": [(str(case), reason) for case, reason in result.skipped], "passed": result.wasSuccessful() and not changed, "qtData": str(OPTIONS.qt_data) if OPTIONS.qt_data else None, "qtGuiImported": "PySide6.QtGui" in sys.modules, "paddleImported": "paddle" in sys.modules, "guiHotSwitch": "not run"}
        OPTIONS.audit.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if changed:
        print("Translation inputs changed during verification: " + ", ".join(changed), file=sys.stderr)
    raise SystemExit(0 if result.wasSuccessful() and not changed else 1)


if __name__ == "__main__":
    main()
