"""只补充本轮缺少的 QML／CSV 翻译；不重写既有译文，不触碰 CUDA 插件。"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import re
from html import escape
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

from model_settings_i18n import LANGUAGES, CSV_LANGUAGES, inventory, placeholders, qml_templates, ts_messages

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vl", type=Path, required=True)
    parser.add_argument("--mapping", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = inventory(ROOT, args.vl)
    targets = sorted(qml_templates(ROOT / "UmiOCR-data/qt_res/qml") | qml_templates(args.vl))
    existing = {language: ts_messages(ROOT / "dev-tools/i18n/release" / (language + ".ts")) for language in LANGUAGES}
    missing_qml = [(context, source) for context, source in targets if any(not any(item["context"] == context and item["source"] == source for item in existing[language]) for language in LANGUAGES)]
    needed = sorted({source for _, source in missing_qml} | set(report["plugins"]["vl"]["missing"]) | set(report["host"]["missing"]))
    mapping = json.loads(args.mapping.read_text("utf-8")) if args.mapping else {}
    derived = []
    for source in needed:
        if source in mapping: continue
        values = []
        for language in LANGUAGES:
            value = next((item["translation"] for item in existing[language] if item["source"] == source and item["translation"]), None)
            if not value:
                candidate = source.replace(".md", ".txt")
                value = next((item["translation"].replace(".txt", ".md") for item in existing[language] if item["source"] == candidate and candidate != source and item["translation"]), None)
            if value: values.append(value)
        if len(values) == len(LANGUAGES): mapping[source] = values; derived.append(source)
    unresolved = [source for source in needed if source not in mapping]
    if unresolved or not args.mapping:
        args.report.write_text(json.dumps({"needed": needed, "derived": derived, "unresolved": unresolved, "qml": missing_qml, "vl": report["plugins"]["vl"]["missing"], "host": report["host"]["missing"]}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"needed": len(needed), "derived": len(derived), "unresolved": unresolved}, ensure_ascii=False))
        return
    for source in needed:
        values = mapping[source]
        if len(values) != len(LANGUAGES) or any(not value.strip() or placeholders(source) != placeholders(value) for value in values):
            raise ValueError("翻译或占位符不匹配：" + source)
    changed = []
    for index, language in enumerate(LANGUAGES):
        path = ROOT / "dev-tools/i18n/release" / (language + ".ts")
        before = path.read_text("utf-8")
        known = {(item["context"], item["source"]) for item in existing[language]}
        text, count = before, 0
        for context, source in missing_qml:
            if (context, source) in known: continue
            message = "\n    <message><source>" + escape(source, quote=False) + "</source><translation>" + escape(mapping[source][index], quote=False) + "</translation></message>\n"
            pattern = r"(<context>\s*<name>" + re.escape(context) + r"</name>.*?)(</context>)"
            if re.search(pattern, text, flags=re.S):
                text = re.sub(pattern, lambda match: match[1] + message + match[2], text, count=1, flags=re.S)
            else:
                text = text.replace("</TS>", "<context><name>" + escape(context) + "</name>" + message + "</context>\n</TS>")
            count += 1
        # XML 数字实体保留翻译键中的行尾空格，避免把有效文本变成补丁尾随空白。
        text = re.sub(r"<message><source>.*?</message>", lambda match: re.sub(r"([ \t]+)\n", lambda item: "&#32;" * len(item[1]) + "\n", match[0]), text, flags=re.S)
        text = re.sub(r"(?m)^[ \t]+$", "", text)
        if text != before: path.write_text(text, encoding="utf-8", newline="\n")
        changed.append({"path": str(path), "added": count, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    for path, sources in ((args.vl / "i18n.csv", report["plugins"]["vl"]["missing"]), (ROOT / "UmiOCR-data/i18n/runtime.csv", report["host"]["missing"])):
        before = path.read_bytes()
        with path.open(encoding="utf-8-sig", newline="") as stream:
            if tuple(next(csv.reader(stream))) != CSV_LANGUAGES: raise ValueError("未知 CSV 列")
        suffix = io.StringIO(newline="")
        writer = csv.writer(suffix, lineterminator="\n")
        for source in sources: writer.writerow([source, *mapping[source]])
        with path.open("ab") as stream: stream.write(suffix.getvalue().encode("utf-8"))
        assert path.read_bytes().startswith(before)
        changed.append({"path": str(path), "added": len(sources), "oldBytesUnchanged": True, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    args.report.write_text(json.dumps({"status": "PASS", "files": changed, "derived": derived, "cudaModified": False}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "PASS", "addedQmlMessages": len(missing_qml), "addedCsvRows": len(report["host"]["missing"]) + len(report["plugins"]["vl"]["missing"])}, ensure_ascii=False))


if __name__ == "__main__": main()
