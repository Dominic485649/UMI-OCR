"""Remove optional model code from a locked PaddleOCR/PaddleX installation."""

import ast
import shutil
import sys
from pathlib import Path


MARKERS = (
    "Paddle" + "OCR" + "-" + "VL",
    "Paddle" + "OCR" + "VL",
    "PP" + "-Doc" + "Layout" + "V3",
    "llama" + "." + "cpp",
    "gg" + "uf",
    "mm" + "proj",
)
TEXT_SUFFIXES = {".py", ".json", ".yaml", ".yml", ".toml", ".ini", ".txt", ".md"}


def contains_marker(value):
    text = str(value).lower()
    return any(marker.lower() in text for marker in MARKERS)


def contains_path_marker(value):
    text = str(value).lower()
    compact = "".join(char for char in text if char.isalnum())
    return contains_marker(text) or any(
        "".join(char for char in marker.lower() if char.isalnum()) in compact
        for marker in MARKERS
    )


def remove_path(path, root):
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise RuntimeError(f"Refusing to remove outside site-packages: {resolved}")
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


class SourceStripper(ast.NodeTransformer):
    def __init__(self):
        super().__init__()
        self.api_exports = set()

    def marked(self, node):
        return contains_path_marker(ast.unparse(node))

    def visit_Import(self, node):
        node.names = [
            alias
            for alias in node.names
            if not contains_path_marker(f"{alias.name} {alias.asname or ''}")
        ]
        return node if node.names else None

    def visit_ImportFrom(self, node):
        if (node.module or "").startswith("_api_client"):
            self.api_exports.update(alias.asname or alias.name for alias in node.names)
            return None
        node.names = [
            alias
            for alias in node.names
            if not contains_path_marker(f"{node.module or ''} {alias.name} {alias.asname or ''}")
        ]
        return node if node.names else None

    def visit_Dict(self, node):
        kept = []
        for key, value in zip(node.keys, node.values):
            if key is None:
                if self.marked(value):
                    continue
                kept.append((None, self.visit(value)))
                continue
            if self.marked(key) or self.marked(value):
                continue
            new_key = self.visit(key)
            new_value = self.visit(value)
            if new_key is not None and new_value is not None:
                kept.append((new_key, new_value))
        node.keys = [key for key, _value in kept]
        node.values = [value for _key, value in kept]
        return node

    def visit_List(self, node):
        node.elts = [
            self.visit(item)
            for item in node.elts
            if not self.marked(item)
            and not (
                isinstance(item, ast.Constant)
                and isinstance(item.value, str)
                and item.value in self.api_exports
            )
        ]
        return node

    visit_Tuple = visit_List
    visit_Set = visit_List

    def visit_Assign(self, node):
        node = self.generic_visit(node)
        return None if self.marked(node) else node

    def visit_AnnAssign(self, node):
        node = self.generic_visit(node)
        return None if self.marked(node) else node

    def visit_Expr(self, node):
        return None if self.marked(node) else self.generic_visit(node)

    def visit_FunctionDef(self, node):
        if contains_path_marker(node.name):
            return None
        node = self.generic_visit(node)
        if self.marked(node):
            return None
        if not node.body:
            node.body = [ast.Pass()]
        return node

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        if contains_path_marker(node.name):
            return None
        node = self.generic_visit(node)
        if self.marked(node):
            return None
        if not node.body:
            node.body = [ast.Pass()]
        return node

    def visit_If(self, node):
        if self.marked(node.test):
            return None
        node = self.generic_visit(node)
        if self.marked(node):
            return None
        if not node.body:
            node.body = [ast.Pass()]
        return node


def strip_python(path):
    source = path.read_text(encoding="utf-8")
    api_root_init = (
        path.name == "__init__.py"
        and path.parent.name == "paddleocr"
        and "_api_client" in source
    )
    if not contains_path_marker(source) and not api_root_init:
        return False
    tree = ast.parse(source, filename=str(path))
    tree = SourceStripper().visit(tree)
    ast.fix_missing_locations(tree)
    rewritten = ast.unparse(tree) + "\n"
    if contains_path_marker(rewritten):
        raise RuntimeError(f"Could not remove optional model code from {path}")
    path.write_text(rewritten, encoding="utf-8", newline="\n")
    return True


def text_files(root):
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            yield path


def main(site_packages):
    root = Path(site_packages).resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    removed = 0
    rewritten = 0
    api_client = root / "paddleocr" / "_api_client"
    if api_client.is_dir():
        remove_path(api_client, root)
        removed += 1
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.exists() and contains_path_marker(path.name):
            remove_path(path, root)
            removed += 1
    for path in text_files(root):
        if path.suffix.lower() == ".py":
            rewritten += int(strip_python(path))
        elif contains_path_marker(path.read_text(encoding="utf-8", errors="ignore")):
            remove_path(path, root)
            removed += 1
    leftovers = []
    for path in root.rglob("*"):
        if contains_path_marker(path.name):
            leftovers.append(str(path))
        elif path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            if contains_path_marker(path.read_text(encoding="utf-8", errors="ignore")):
                leftovers.append(str(path))
    if leftovers:
        raise RuntimeError("Optional model residue remains:\n" + "\n".join(leftovers))
    print(f"Stripped optional model residue: removed={removed}, rewritten={rewritten}.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: strip_optional_models_3_7.py <site-packages>")
    main(sys.argv[1])
