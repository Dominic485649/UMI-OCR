"""Translation inventory/check tool for the approved model-settings change.

No GUI, inference, network, configuration changes, or release installation writes.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import csv
import hashlib
from html import escape
import json
import io
from pathlib import Path
import re
import string
import subprocess
import xml.etree.ElementTree as ET

LANGUAGES = ("en_US", "ja_JP", "pt", "ru_RU", "ta", "zh_TW")
CSV_LANGUAGES = ("zh_CN", *LANGUAGES)
INACTIVE = {"obsolete", "vanished"}


def placeholders(text):
    qt = Counter(re.findall(r"%(?:L?\d+|unix\b|date\b|name\b|range\b|[YmdHMS]|n\b)", text))
    qt.update(re.findall(r"\\[1-9]", text))
    brace = Counter()
    try:
        for _, field, spec, conversion in string.Formatter().parse(text):
            if field is not None:
                brace[(field, spec, conversion)] += 1
    except ValueError:
        brace[("INVALID_BRACES", "", None)] += 1
    return qt, brace


def ts_messages(path):
    root = ET.parse(path).getroot()
    result = []
    for context in root.findall("context"):
        for node in context.findall("message"):
            translation = node.find("translation")
            kind = translation.get("type", "") if translation is not None else "unfinished"
            if kind in INACTIVE:
                continue
            source = node.findtext("source", "")
            translated = "".join(translation.itertext()) if translation is not None else ""
            result.append({"context": context.findtext("name"), "source": source,
                           "translation": translated, "type": kind})
    return result


def python_templates(path):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    result = set()
    translation_names = {"tr"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            translation_names.update(alias.asname or alias.name for alias in node.names if alias.name == "tr")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
        implicit_error = path.name in {"asset_paths.py", "worker.py"} and name in {"RuntimeError", "ValueError", "TimeoutError", "OSError"}
        if (name in translation_names | {"BudgetError", "_progress"} or implicit_error) and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            result.add(node.args[0].value)
        if name == "option":
            for index in (0, 2):
                if len(node.args) > index and isinstance(node.args[index], ast.Constant) and isinstance(node.args[index].value, str):
                    result.add(node.args[index].value)
    return result


def manifest_templates(node):
    result = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key in {"title", "toolTip", "description", "intro", "unit"} and isinstance(value, str):
                result.add(value)
            elif key == "optionsList" and isinstance(value, list):
                for option in value:
                    if isinstance(option, list) and len(option) > 1 and isinstance(option[1], str):
                        result.add(option[1])
                    elif isinstance(option, str):
                        result.add(option)
            elif key == "nameFilters" and isinstance(value, list):
                result.update(x for x in value if isinstance(x, str))
            else:
                result.update(manifest_templates(value))
    elif isinstance(node, list):
        for value in node:
            result.update(manifest_templates(value))
    return result


def strip_qml_comments(text):
    """Remove JS/QML comments while preserving quoted string contents."""
    output = []
    index = 0
    quote = None
    while index < len(text):
        char = text[index]
        if quote:
            output.append(char)
            if char == "\\" and index + 1 < len(text):
                index += 1
                output.append(text[index])
            elif char == quote:
                quote = None
        elif char in ("'", '"', "`"):
            quote = char
            output.append(char)
        elif text[index:index + 2] == "//":
            end = text.find("\n", index)
            index = len(text) if end < 0 else end
            output.append("\n")
            continue
        elif text[index:index + 2] == "/*":
            end = text.find("*/", index + 2)
            index = len(text) if end < 0 else end + 2
            output.append(" ")
            continue
        else:
            output.append(char)
        index += 1
    return "".join(output)


def qml_templates(directory):
    result = set()
    literal = r'''(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')'''
    pattern = re.compile(r"\bqsTr\s*\(\s*(" + literal + r"(?:\s*\+\s*" + literal + r")*)")
    for path in directory.rglob("*.qml"):
        text = strip_qml_comments(path.read_text(encoding="utf-8-sig"))
        for match in pattern.finditer(text):
            source = "".join(ast.literal_eval(token.group()) for token in re.finditer(literal, match.group(1)))
            result.add((path.stem, source))
    return result


def csv_rows(path):
    if not path.is_file():
        return [], []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or []), list(reader)


def host_templates(root, excluded=()):
    result = set()
    files = {}
    for path in (root / "UmiOCR-data/py_src").rglob("*.py"):
        if path.name in excluded:
            continue
        source = path.read_text(encoding="utf-8-sig")
        if "runtime_i18n import" not in source:
            continue
        templates = python_templates(path)
        if templates:
            files[str(path.relative_to(root))] = sorted(templates)
            result.update(templates)
    return result, files


def inventory(root, vl_root, excluded_host=()):
    tables = {}
    missing = {}
    for language in LANGUAGES:
        messages = ts_messages(root / "dev-tools/i18n/release" / (language + ".ts"))
        problems = []
        for item in messages:
            reasons = []
            if not item["translation"].strip():
                reasons.append("empty")
            if item["type"] == "unfinished":
                reasons.append("unfinished")
            if placeholders(item["source"]) != placeholders(item["translation"]):
                reasons.append("placeholders")
            if reasons:
                problems.append({**item, "reasons": reasons})
        tables[language] = {"active": len(messages), "problems": len(problems),
                            "empty": sum("empty" in p["reasons"] for p in problems),
                            "unfinished": sum("unfinished" in p["reasons"] for p in problems)}
        missing[language] = problems
    plugins = {}
    paths = {"cuda": root / "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA", "vl": vl_root}
    for name, directory in paths.items():
        templates = set()
        for path in directory.glob("*.py"):
            templates.update(python_templates(path))
        manifest = directory / "umi-plugin.json"
        if manifest.is_file():
            templates.update(manifest_templates(json.loads(manifest.read_text(encoding="utf-8"))))
        header, rows = csv_rows(directory / "i18n.csv")
        known = {row["zh_CN"] for row in rows}
        plugins[name] = {"header": header, "rows": len(rows), "templates": sorted(templates),
                         "missing": sorted(templates - known)}
    qml = qml_templates(root / "UmiOCR-data/qt_res/qml")
    english = {(m["context"], m["source"]): m["translation"] for m in ts_messages(root / "dev-tools/i18n/release/en_US.ts")}
    untranslated = {}
    for language in LANGUAGES:
        messages = ts_messages(root / "dev-tools/i18n/release" / (language + ".ts"))
        known = {(m["context"], m["source"]) for m in messages}
        tables[language]["qml_missing"] = [{"context": c, "source": s} for c, s in sorted(qml - known)]
        if language != "en_US":
            untranslated[language] = [m for m in messages if m["translation"] == english.get((m["context"], m["source"])) and re.search(r"[A-Za-z]{3}", m["translation"]) and re.search(r"[㐀-鿿]", m["source"])]
    templates, host_files = host_templates(root, excluded_host)
    header, rows = csv_rows(root / "UmiOCR-data/i18n/runtime.csv")
    host = {"header": header, "rows": len(rows), "templates": sorted(templates), "missing": sorted(templates - {row["zh_CN"] for row in rows}), "files": host_files}
    return {"ts": tables, "ts_problems": missing, "suspect_english": untranslated, "plugins": plugins, "host": host}


def load_catalogue(directory):
    result = {}
    if directory is None:
        return result
    for path in sorted(directory.glob("catalogue-*.json")):
        for source, values in json.loads(path.read_text(encoding="utf-8")).items():
            if len(values) != len(LANGUAGES) or any(not isinstance(v, str) or not v.strip() for v in values):
                raise ValueError(f"Invalid translation row in {path}: {source}")
            if source in result and result[source] != values:
                raise ValueError(f"Conflicting translations for {source}")
            for language, text in zip(LANGUAGES, values):
                if placeholders(source) != placeholders(text):
                    raise ValueError(f"Placeholder mismatch ({language}): {source}")
            result[source] = values
    return result


def apply_ts(root, catalogue, directory):
    overrides = json.loads((directory / "ts-overrides.json").read_text(encoding="utf-8"))
    baseline = json.loads((directory / "inventory-before.json").read_text(encoding="utf-8"))
    changes = {}
    for language_index, language in enumerate(LANGUAGES):
        path = root / "dev-tools/i18n/release" / (language + ".ts")
        text = path.read_text(encoding="utf-8")
        finished = {m["source"]: m["translation"] for m in ts_messages(path) if not m["type"] and m["translation"].strip() and placeholders(m["source"]) == placeholders(m["translation"])}
        # These pre-existing unfinished translations were reviewed individually.
        # The explicit overrides repair the English placeholders/Portuguese
        # fallbacks and the Japanese document-vs-image mistranslation.
        reviewed = {(m["context"], m["source"]): m["translation"] for m in baseline["ts_problems"][language] if m["translation"].strip() and m["type"] == "unfinished" and "placeholders" not in m["reasons"]}
        count = 0
        def replace_context(context_match):
            context_text = context_match.group()
            context = ET.fromstring(context_text).findtext("name")
            def replace_message(message_match):
                nonlocal count
                message_text = message_match.group()
                message = ET.fromstring(message_text)
                source = message.findtext("source", "")
                translation = message.find("translation")
                kind = translation.get("type", "") if translation is not None else "unfinished"
                if kind in INACTIVE:
                    return message_text
                value = overrides.get(language, {}).get(source)
                if value is None:
                    value = reviewed.get((context, source))
                if value is None and (kind == "unfinished" or translation is None or not "".join(translation.itertext()).strip()):
                    value = finished.get(source)
                    if value is None and source in catalogue:
                        value = catalogue[source][language_index]
                    if value is None:
                        value = reviewed.get((context, source))
                if value is None:
                    return message_text
                if placeholders(source) != placeholders(value):
                    raise ValueError(f"Invalid TS placeholders: {language}: {source}")
                replacement = "<translation>" + escape(value, quote=False) + "</translation>"
                updated = re.sub(r"<translation\b[^>]*(?:/>|>.*?</translation>)", lambda _: replacement, message_text, flags=re.S)
                if updated != message_text:
                    count += 1
                return updated
            return re.sub(r"<message\b[^>]*>.*?</message>", replace_message, context_text, flags=re.S)
        text = re.sub(r"<context>.*?</context>", replace_context, text, flags=re.S)
        path.write_text(text, encoding="utf-8", newline="\n")
        changes[language] = count
    return changes


def apply_csv(root, vl_root, catalogue, report):
    changes = {}
    tables = {"cuda": root / "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/i18n.csv", "vl": vl_root / "i18n.csv"}
    if report["host"]["templates"]:
        tables["host"] = root / "UmiOCR-data/i18n/runtime.csv"
    for name, path in tables.items():
        _, existing_rows = csv_rows(path)
        existing = {row["zh_CN"]: row for row in existing_rows}
        templates = report["host"]["templates"] if name == "host" else report["plugins"][name]["templates"]
        sources = list(existing) + sorted(set(templates) - set(existing))
        rows = []
        missing = []
        for source in sources:
            row = {"zh_CN": source}
            for index, language in enumerate(LANGUAGES):
                value = existing.get(source, {}).get(language)
                if not value and source in catalogue:
                    value = catalogue[source][index]
                if not value:
                    missing.append((source, language))
                elif placeholders(source) != placeholders(value):
                    raise ValueError(f"CSV placeholders ({name}, {language}): {source}")
                row[language] = value
            rows.append(row)
        if missing:
            changes[name] = {"written": False, "missing": missing}
            continue
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=CSV_LANGUAGES, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        content = stream.getvalue().encode("utf-8")
        changed = not path.is_file() or path.read_bytes() != content
        if changed:
            path.write_bytes(content)
        changes[name] = {"written": True, "changed": changed, "rows": len(rows), "sha256": hashlib.sha256(content).hexdigest()}
    return changes


def gaps(report, catalogue):
    qml_sources = sorted({item["source"] for item in report["ts_problems"]["en_US"] if item["source"] not in catalogue})
    return {"qml_needed": qml_sources,
            "qml_regex_missing": report["ts"]["en_US"]["qml_missing"],
            "suspect_english": report["suspect_english"],
            "plugin_needed": {name: [source for source in values["templates"] if source not in catalogue] for name, values in report["plugins"].items()},
            "host_needed": [source for source in report["host"]["templates"] if source not in catalogue]}


def append_host_templates(root, source_catalogue, expected_sha256):
    """Append a small frozen delta without touching/revalidating other tables."""
    path = root / "UmiOCR-data/i18n/runtime.csv"
    before = path.read_bytes()
    before_sha256 = hashlib.sha256(before).hexdigest()
    if before_sha256 != expected_sha256:
        raise ValueError("Host catalogue changed since the supplied baseline")
    mapping = json.loads(source_catalogue.read_text(encoding="utf-8"))
    header, existing_rows = csv_rows(path)
    if tuple(header) != CSV_LANGUAGES or not before.endswith(b"\n"):
        raise ValueError("Unexpected host catalogue header or final newline")
    existing = {row["zh_CN"] for row in existing_rows}
    rows = []
    for source, values in mapping.items():
        if source in existing:
            raise ValueError("Refusing to overwrite an existing source: " + source)
        if len(values) != len(LANGUAGES):
            raise ValueError("Incomplete language delta: " + source)
        row = {"zh_CN": source}
        for language, value in zip(LANGUAGES, values):
            if not value.strip() or placeholders(source) != placeholders(value):
                raise ValueError("Invalid delta translation: " + language + ": " + source)
            row[language] = value
        rows.append(row)
    stream = io.StringIO(newline="")
    csv.DictWriter(stream, fieldnames=CSV_LANGUAGES, lineterminator="\n").writerows(rows)
    suffix = stream.getvalue().encode("utf-8")
    with path.open("ab") as output:
        output.write(suffix)
    after = path.read_bytes()
    if after != before + suffix:
        raise ValueError("Host catalogue prefix changed while appending")
    return {"path": str(path), "beforeSha256": before_sha256, "beforeSize": len(before), "afterSha256": hashlib.sha256(after).hexdigest(), "afterSize": len(after), "originalRows": len(existing_rows), "addedRows": len(rows), "currentRows": len(existing_rows) + len(rows), "oldBytesUnchanged": True, "sources": list(mapping), "scope": "Only the requested new host templates were validated and appended. No QM or plugin CSV was opened or modified."}


def seed_from_ts(root, source_report, catalogue):
    frozen = json.loads(source_report.read_text(encoding="utf-8"))
    sources = {source for item in frozen["files"] for source in item["templates"]} - set(catalogue)
    translations = {}
    for code in LANGUAGES:
        lookup = {}
        for message in ts_messages(root / "dev-tools/i18n/release" / (code + ".ts")):
            if not message["type"] and message["translation"].strip() and placeholders(message["source"]) == placeholders(message["translation"]):
                lookup.setdefault(message["source"], message["translation"])
        translations[code] = lookup
    return {source: [translations[code][source] for code in LANGUAGES] for source in sorted(sources) if all(source in translations[code] for code in LANGUAGES)}


def preservation(root, vl_root, directory):
    overrides = json.loads((directory / "ts-overrides.json").read_text(encoding="utf-8"))
    result = {"ts": {}, "vl": {}, "unexpectedChanges": []}
    for code in LANGUAGES:
        relative = "dev-tools/i18n/release/" + code + ".ts"
        baseline = subprocess.run(["git", "-C", str(root), "show", "HEAD:" + relative], capture_output=True, check=True).stdout
        old = {(m["context"], m["source"]): m for m in ts_messages(io.BytesIO(baseline))}
        current = {(m["context"], m["source"]): m for m in ts_messages(root / relative)}
        changed = []
        preserved = 0
        for key in old.keys() & current.keys():
            if old[key]["translation"] == current[key]["translation"]:
                preserved += 1
            else:
                source = key[1]
                allowed = source in overrides.get(code, {}) and current[key]["translation"] == overrides[code][source]
                item = {"context": key[0], "source": source, "approvedRepair": allowed}
                changed.append(item)
                if not allowed:
                    result["unexpectedChanges"].append({"language": code, **item})
        result["ts"][code] = {"baselineSha256": hashlib.sha256(baseline).hexdigest(), "commonActive": len(old.keys() & current.keys()), "preservedTranslations": preserved, "repairs": changed}
    baseline = subprocess.run(["git", "-C", str(vl_root.parent), "show", "HEAD:" + vl_root.name + "/i18n.csv"], capture_output=True, check=True).stdout.decode("utf-8-sig")
    old_rows = list(csv.DictReader(io.StringIO(baseline)))
    _, current_rows = csv_rows(vl_root / "i18n.csv")
    current = {row["zh_CN"]: row for row in current_rows}
    preserved = 0
    for row in old_rows:
        if current.get(row["zh_CN"], {}).get("en_US") == row["en_US"]:
            preserved += 1
        else:
            result["unexpectedChanges"].append({"component": "vl", "source": row["zh_CN"]})
    result["vl"] = {"originalRows": len(old_rows), "preservedEnglishTranslations": preserved}
    result["passed"] = not result["unexpectedChanges"]
    return result


def evidence(root, vl_root, report):
    files = []
    paths = [root / "dev-tools/i18n/release" / (code + ".ts") for code in LANGUAGES]
    paths += [root / "UmiOCR-data/i18n" / (code + ".qm") for code in LANGUAGES]
    paths += [root / "UmiOCR-data/i18n/runtime.csv", root / "UmiOCR-data/py_src/utils/runtime_i18n.py", root / "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/i18n.csv", vl_root / "i18n.csv", root / "tests/test_model_settings_translations.py", root / "build/tools/model_settings_i18n.py", root / "build/tools/model_settings_qt_tools.py", root / "build/tools/model_settings_compile_i18n.py"]
    for path in paths:
        files.append({"path": str(path), "exists": path.is_file(), "size": path.stat().st_size if path.is_file() else None, "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None})
    inputs = []
    for directory in (root / "UmiOCR-data/qt_res/qml", root / "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA", vl_root):
        for pattern in (("*.qml",) if directory.name == "qml" else ("*.py", "*.json")):
            iterator = directory.rglob(pattern) if directory.name == "qml" else directory.glob(pattern)
            for path in sorted(iterator):
                inputs.append({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    host_inputs = set(report["host"]["files"])
    host_inputs.update(("UmiOCR-data/py_src/utils/i18n_configs.py", "UmiOCR-data/py_src/imports/plugin_i18n.py", "UmiOCR-data/py_src/plugins_controller/manifest.py", "UmiOCR-data/py_src/plugins_controller/host_api.py"))
    for relative in sorted(host_inputs):
        path = root / relative
        inputs.append({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    summary = {"languages": ["zh_CN", *LANGUAGES], "tsActivePerLanguage": {code: info["active"] for code, info in report["ts"].items()}, "tsProblemsPerLanguage": {code: info["problems"] for code, info in report["ts"].items()}, "qmlMissingPerLanguage": {code: len(info["qml_missing"]) for code, info in report["ts"].items()}, "plugins": {name: {"rows": info["rows"], "templates": len(info["templates"]), "missing": len(info["missing"])} for name, info in report["plugins"].items()}, "host": {"rows": report["host"]["rows"], "templates": len(report["host"]["templates"]), "missing": len(report["host"]["missing"])}, "guiHotSwitch": "not run", "gpuInference": "not run", "releaseInstallationModified": False, "committed": False, "pushed": False, "cleanup": {"deleted": [], "retained": ["Locked Qt 6.11.2 CLI tool subset for reproducible extraction/compilation", "Translation source mappings and audit history"], "scope": "Only this task's owned catalogues, tests, tools and audit/tmp directories were written"}}
    return {"summary": summary, "files": files, "translationInputs": inputs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inventory", "gaps", "apply-ts", "apply-csv", "evidence", "preservation", "seed-ts", "append-host"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--vl-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--catalogue-dir", type=Path)
    parser.add_argument("--exclude-host", nargs="*", default=(), help="Explicit temporarily unfrozen host filenames; omitted for final coverage")
    parser.add_argument("--source-report", type=Path)
    parser.add_argument("--expected-host-sha256")
    args = parser.parse_args()
    if args.command == "append-host":
        payload = append_host_templates(args.root.resolve(), args.source_report, args.expected_host_sha256)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False))
        return
    if args.command == "seed-ts":
        if args.output.exists():
            raise SystemExit("Refusing to replace an existing translation seed")
        payload = seed_from_ts(args.root.resolve(), args.source_report, load_catalogue(args.catalogue_dir))
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"reusedCompleteTsSources": len(payload)}, ensure_ascii=False))
        return
    if args.command == "preservation":
        report = preservation(args.root.resolve(), args.vl_root.resolve(), args.catalogue_dir)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"passed": report["passed"], "unexpectedChanges": len(report["unexpectedChanges"]), "vl": report["vl"]}, ensure_ascii=False))
        raise SystemExit(0 if report["passed"] else 1)
    catalogue = load_catalogue(args.catalogue_dir)
    changes = apply_ts(args.root.resolve(), catalogue, args.catalogue_dir) if args.command == "apply-ts" else None
    report = inventory(args.root.resolve(), args.vl_root.resolve(), args.exclude_host)
    if args.command == "apply-csv":
        changes = apply_csv(args.root.resolve(), args.vl_root.resolve(), catalogue, report)
        report = inventory(args.root.resolve(), args.vl_root.resolve(), args.exclude_host)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = evidence(args.root.resolve(), args.vl_root.resolve(), report) if args.command == "evidence" else gaps(report, catalogue) if args.command == "gaps" else {**report, "applied": changes} if changes is not None else report
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ts": {k: {**{field: value for field, value in item.items() if field != "qml_missing"}, "qml_missing": len(item["qml_missing"])} for k, item in report["ts"].items()}, "plugins": {k: {"rows": v["rows"], "templates": len(v["templates"]), "missing": len(v["missing"])} for k, v in report["plugins"].items()}, "host": {"rows": report["host"]["rows"], "templates": len(report["host"]["templates"]), "missing": len(report["host"]["missing"])}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
