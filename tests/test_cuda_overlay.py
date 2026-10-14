"""Installing CUDA must preserve host notices and source provenance."""

import importlib.util
from pathlib import Path
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("overlay", ROOT / "build/tools/prepare_cuda_overlay.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    gpu = root / "gpu"
    plugin = gpu / "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA"
    plugin.mkdir(parents=True)
    (plugin / "api.py").write_text("# CUDA", encoding="utf-8")
    (gpu / "LICENSES").mkdir()
    (gpu / "LICENSES/THIRD_PARTY_NOTICES.md").write_text("GPU notices", encoding="utf-8")
    (gpu / "source-snapshot.json").write_text('{"GPU":"source"}', encoding="utf-8")
    overlay = root / "overlay"
    module.prepare(gpu, overlay)
    host = root / "host"
    (host / "LICENSES").mkdir(parents=True)
    (host / "LICENSES/THIRD_PARTY_NOTICES.md").write_text("host notices", encoding="utf-8")
    (host / "source-snapshot.json").write_text('{"host":"source"}', encoding="utf-8")
    shutil.copytree(overlay, host, dirs_exist_ok=True)
    assert (host / "LICENSES/THIRD_PARTY_NOTICES.md").read_text() == "host notices"
    assert (host / "source-snapshot.json").read_text() == '{"host":"source"}'
    assert (host / "LICENSES/plugins/win32_PaddleOCRv6_CUDA/LICENSES/THIRD_PARTY_NOTICES.md").read_text() == "GPU notices"
    assert (host / "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/api.py").is_file()
print("CUDA overlay host-source and license-preservation regression passed.")
