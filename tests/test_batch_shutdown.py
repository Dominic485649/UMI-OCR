"""验证真实应用退出钩子的顺序，不启动 Qt、推理或外部进程。"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path
import sys
import types
from unittest.mock import patch
import zipfile

REPO = Path(__file__).resolve().parents[1]


def shutdown_code(data_root):
    if data_root is None:
        path = REPO / "UmiOCR-data/py_src/run.py"
        source = path.read_text("utf-8")
        origin = str(path)
    else:
        root = data_root.resolve()
        archive = root / "app.zip"
        if archive.is_file():
            with zipfile.ZipFile(archive) as bundle:
                source = bundle.read("py_src/run.py").decode("utf-8-sig")
            origin = str(archive) + "/py_src/run.py"
        else:
            path = root / "py_src/run.py"
            source = path.read_text("utf-8")
            origin = str(path)
    tree = ast.parse(source, filename=origin)
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "shutdownBackends"]
    assert len(functions) == 1, origin
    module = ast.Module(body=[functions[0]], type_ignores=[])
    ast.fix_missing_locations(module)
    return compile(module, origin, "exec"), origin


def exercise(code, present=True, result=True, fail=False):
    events = []
    errors = []
    modules = {}
    for name in ("py_src", "py_src.mission", "py_src.plugins_controller"):
        module = types.ModuleType(name)
        module.__path__ = []
        modules[name] = module
    for suffix, label, symbol in (("mission_ocr", "ocr", "MissionOCR"),
                                  ("mission_document", "document", "MissionDocument")):
        module = types.ModuleType("py_src.mission." + suffix)
        setattr(module, symbol, types.SimpleNamespace(shutdown=lambda value=label: events.append(value)))
        modules[module.__name__] = module
    services = types.ModuleType("py_src.plugins_controller.services")
    services.PluginServices = types.SimpleNamespace(shutdownAll=lambda: events.append("services"))
    modules[services.__name__] = services

    def finish(timeout):
        events.append("batch")
        assert timeout == 30000
        if fail:
            raise RuntimeError("受控的批量收尾异常")
        return result

    if present:
        modules["py_src.tag_pages.batch_runtime"] = types.SimpleNamespace(shutdownBatchIO=finish)
    logger = types.SimpleNamespace(error=lambda *args, **kwargs: errors.append(args))
    with patch.dict(sys.modules, modules):
        if not present:
            sys.modules.pop("py_src.tag_pages.batch_runtime", None)
        namespace = {"__package__": "py_src", "logger": logger}
        exec(code, namespace)
        namespace["shutdownBackends"]()
        if not present:
            assert "py_src.tag_pages.batch_runtime" not in sys.modules
    return events, errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_root", nargs="?", type=Path, help="指定新包时从该包真实 app.zip 读取，不借仓库实现")
    args = parser.parse_args()
    code, origin = shutdown_code(args.data_root)
    order, errors = exercise(code)
    assert order == ["batch", "ocr", "document", "services"] and not errors, (order, errors)
    order, errors = exercise(code, present=False)
    assert order == ["ocr", "document", "services"] and not errors, (order, errors)
    order, errors = exercise(code, result=False)
    assert order == ["batch", "ocr", "document", "services"] and len(errors) == 1, (order, errors)
    order, errors = exercise(code, fail=True)
    assert order == ["batch", "ocr", "document", "services"] and len(errors) == 1, (order, errors)
    print(f"批量退出钩子回归通过：4组，实际代码来源={origin}")


if __name__ == "__main__":
    main()
