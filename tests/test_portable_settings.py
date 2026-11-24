import argparse
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build" / "tools"))
from staging_smoke import configure_runtime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_root", type=Path)
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    handles = configure_runtime(data_root)

    from PySide6.QtCore import QCoreApplication
    from PySide6.QtQml import QJSEngine
    from py_src.utils.portable_settings import PortableSettings

    app = QCoreApplication.instance() or QCoreApplication([])
    engine = QJSEngine()
    with tempfile.TemporaryDirectory() as temp:
        path = str(Path(temp) / ".settings")
        settings = PortableSettings(path)
        payload = engine.evaluate("({name: 'Umi-OCR', values: [1, 2, 3]})")
        settings.setValue("Test", "payload", payload)
        settings.sync()

        restored = PortableSettings(path).value("Test", "payload", None)
        assert restored == {"name": "Umi-OCR", "values": [1, 2, 3]}
        assert settings.contains("Test", "payload")
        settings.remove("Test", "payload")
        assert not settings.contains("Test", "payload")

    del engine, app, handles
    print("Portable .settings QVariant round-trip passed.")


if __name__ == "__main__":
    main()
