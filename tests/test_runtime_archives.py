import importlib, sys, tempfile, zipimport
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"build/tools"))
from merge_runtime import merge_modules
with tempfile.TemporaryDirectory() as temp:
    root=Path(temp)/"vendor";package=root/"archive_test";package.mkdir(parents=True)
    (package/"__init__.py").write_text('"""Original package docstring."""\nfrom __future__ import annotations\n',encoding="utf-8")
    (package/"value.py").write_text("VALUE = 42\n",encoding="utf-8")
    (package/"disk.py").write_text("from pathlib import Path\nVALUE = Path(__file__).parent.name\n",encoding="utf-8")
    (package/"native.pyd").write_bytes(b"original native bytes")
    archive=root.parent/"vendor.zip";report=merge_modules(root,archive)
    assert report["merged_files"]==1 and (package/"disk.py").is_file()
    assert (package/"native.pyd").read_bytes()==b"original native bytes"
    sys.path.insert(0,str(root));sys.path.append(str(archive))
    loaded=importlib.import_module("archive_test")
    with patch("builtins.compile",side_effect=AssertionError("ZIP bytecode must not be recompiled")):
        module=importlib.import_module("archive_test.value")
    assert module.VALUE==42 and "vendor.zip" in module.__file__
    assert importlib.import_module("archive_test.disk").VALUE=="archive_test"
print("ZIP bytecode, mixed native/package imports, __file__ resources and original hashes passed.")
