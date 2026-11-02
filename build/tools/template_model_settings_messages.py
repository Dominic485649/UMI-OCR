"""本轮宿主/CUDA 文案结构化迁移，复用已审查的 AST 模板构造器。"""
import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re

FILES = [
    "py_src/mission/backend_runtime.py", "py_src/mission/managed_mission.py", "py_src/mission/mission.py",
    "py_src/mission/mission_ocr.py", "py_src/mission/mission_document.py", "py_src/mission/mission_doc.py",
    "py_src/plugins_controller/services.py", "py_src/plugins_controller/plugins_connector.py",
    "py_src/plugins_controller/plugins_controller.py", "py_src/plugins_controller/capabilities.py",
    "py_src/plugins_controller/manifest.py",
    "py_src/server/backend_router.py", "py_src/server/request_validation.py", "py_src/server/request_budgets.py",
    "py_src/server/structured_document_server.py", "py_src/server/ocr_server.py",
    "py_src/server/doc_server.py", "py_src/server/web_server.py",
    "plugins/win32_PaddleOCRv6_CUDA/api.py", "plugins/win32_PaddleOCRv6_CUDA/worker.py",
    "plugins/win32_PaddleOCRv6_CUDA/health.py",
]
HAN = re.compile(r"[㐀-鿿]")


def migrate(path, engine):
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docs.add(id(first.value))
    lines = text.encode().splitlines(keepends=True)
    offsets, total = [], 0
    for line in lines:
        offsets.append(total)
        total += len(line)
    changes, templates, restored_comments = [], [], []
    # 代码中的独立字符串说明不是运行文案；修复早期迁移误包裹的说明，
    # 避免 JSON 示例里的花括号被当成 .format 占位符执行。
    for node in ast.walk(tree):
        if not isinstance(node, ast.Expr):
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            docs.add(id(value))
        elif (engine.is_translation(value) and not value.keywords and len(value.args) == 1
              and isinstance(value.args[0], ast.Constant) and isinstance(value.args[0].value, str)):
            docs.add(id(value))
            start = offsets[value.lineno - 1] + value.col_offset
            end = offsets[value.end_lineno - 1] + value.end_col_offset
            changes.append((start, end, ast.unparse(value.args[0]).encode()))
            restored_comments.append(value.args[0].value)
    def is_string(node):
        if isinstance(node, ast.Constant):
            return isinstance(node.value, str)
        if isinstance(node, ast.JoinedStr):
            return True
        return (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add)
                and not isinstance(node.left, (ast.List, ast.Tuple, ast.Dict, ast.Set))
                and not isinstance(node.right, (ast.List, ast.Tuple, ast.Dict, ast.Set))
                and (is_string(node.left) or is_string(node.right)))
    def visit(node, parent=None):
        if id(node) in docs or engine.is_translation(node):
            return
        if isinstance(node, ast.FunctionDef) and node.name in {"tr", "_error_type"}:
            return
        candidate = is_string(node)
        if candidate and engine.has_han(node):
            if isinstance(parent, ast.Compare):
                return
            replacement, template = engine.translated(node)
            if HAN.search(template):
                start = offsets[node.lineno - 1] + node.col_offset
                end = offsets[node.end_lineno - 1] + node.end_col_offset
                changes.append((start, end, ast.unparse(replacement).encode()))
                templates.append(template)
                return
        for child in ast.iter_child_nodes(node):
            visit(child, node)
    visit(tree)
    before = hashlib.sha256(text.encode()).hexdigest()
    raw = text.encode()
    for start, end, value in sorted(changes, reverse=True):
        raw = raw[:start] + value + raw[end:]
    updated = raw.decode()
    parsed = ast.parse(updated)
    imported = any(isinstance(node, ast.ImportFrom) and any(alias.name == "tr" for alias in node.names)
                   for node in parsed.body)
    if changes and not imported:
        if path.name == "worker.py":
            anchor = "sys.path.insert(0, str(PLUGIN_DIR))"
            if anchor not in updated:
                raise ValueError("无法定位独立 worker 的模块路径初始化。")
            updated = updated.replace(anchor, anchor + "\nfrom i18n_helpers import tr", 1)
        else:
            insertion = 0
            for node in parsed.body:
                if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                        and isinstance(node.value.value, str)) or (isinstance(node, ast.ImportFrom) and node.module == "__future__"):
                    insertion = node.end_lineno
                else:
                    break
            chunks = updated.splitlines(keepends=True)
            statement = "from .i18n_helpers import tr\n" if "plugins" in path.parts else "from ..utils.runtime_i18n import tr\n"
            chunks.insert(insertion, statement)
            updated = "".join(chunks)
    ast.parse(updated)
    if changes:
        path.write_text(updated, encoding="utf-8", newline="\n")
    return {"file": str(path), "expressions": len(changes), "templates": templates,
            "restoredComments": restored_comments,
            "beforeSha256": before, "afterSha256": hashlib.sha256(updated.encode()).hexdigest()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--engine", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--exclude", action="append", default=[])
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError("迁移报告已存在，拒绝覆盖历史证据。")
    spec = importlib.util.spec_from_file_location("reviewed_message_template_engine", args.engine)
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    report = [migrate(args.data_root / relative, engine) for relative in FILES if relative not in args.exclude]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({"engineSha256": hashlib.sha256(args.engine.read_bytes()).hexdigest(),
                                     "files": report}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"files": len(report), "expressions": sum(item["expressions"] for item in report)}, ensure_ascii=False))
