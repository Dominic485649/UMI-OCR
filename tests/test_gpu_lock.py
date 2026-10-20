"""Updating E2E evidence must not change the lock that evidence refers to."""

import importlib.util
import json
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gpu_lock", ROOT / "build/tools/freeze_gpu_runtime.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

with tempfile.TemporaryDirectory() as directory:
    plugin = Path(directory)
    (plugin / "umi-plugin.json").write_text(json.dumps({"id": "custom", "version": "3.0.0"}), encoding="utf-8")
    (plugin / "native.dll").write_bytes(b"native fixture")
    (plugin / "api.py").write_text("# source", encoding="utf-8")
    module.generate(plugin)
    first = (plugin / "runtime.lock.json").read_bytes()
    (plugin / "gpu-e2e-evidence.json").write_text('{"tested":"new evidence"}', encoding="utf-8")
    cache = plugin / "__pycache__"
    cache.mkdir()
    (cache / "api.pyc").write_bytes(b"cache fixture")
    module.generate(plugin)
    assert (plugin / "runtime.lock.json").read_bytes() == first
print("GPU evidence-independent native lock regression passed.")
