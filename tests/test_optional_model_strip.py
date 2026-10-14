import ast
import importlib.util
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    tool_path = ROOT / "build" / "tools" / "strip_optional_models_3_7.py"
    spec = importlib.util.spec_from_file_location("optional_model_strip", tool_path)
    tool = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = tool
    spec.loader.exec_module(tool)
    marker = "Paddle" + "OCR" + "VL"
    enum_name = "_".join(("PADDLE", "OCR", "VL"))

    with tempfile.TemporaryDirectory() as temp_dir:
        site_packages = Path(temp_dir)
        package = site_packages / "paddleocr"
        package.mkdir()
        optional_dir = package / "_".join(("paddleocr", "vl"))
        optional_dir.mkdir()
        (optional_dir / "model.py").write_text("marker = 'optional'\n", encoding="utf-8")
        api_client = package / "_api_client"
        api_client.mkdir()
        (api_client / "client.py").write_text("class Client:\n    pass\n", encoding="utf-8")
        (package / "__init__.py").write_text(
            "from ._api_client.client import Client\n"
            "__all__ = ['Client', 'Keep']\n",
            encoding="utf-8",
        )
        source = package / "models.py"
        source.write_text(
            "class _ModelManager:\n"
            f"    model_names = ['keep', '{marker}']\n"
            "\n"
            "    def available(self):\n"
            "        return self.model_names\n",
            encoding="utf-8",
        )
        (package / "api.py").write_text(
            "class Model:\n"
            f"    {enum_name} = 'optional'\n"
            "    KEEP = 'keep'\n"
            "\n"
            f"DOCUMENT_MODELS = {{Model.{enum_name}, Model.KEEP}}\n"
            "\n"
            f"def validate(value: {marker}):\n"
            "    return value\n",
            encoding="utf-8",
        )
        tool.main(site_packages)
        stripped = source.read_text(encoding="utf-8")
        assert "class _ModelManager" in stripped
        assert marker not in stripped
        ast.parse(stripped, filename=str(source))
        api_source = (package / "api.py").read_text(encoding="utf-8")
        assert "class Model" in api_source
        assert "Model.KEEP" in api_source
        assert enum_name not in api_source
        assert marker not in api_source
        assert not optional_dir.exists()
        assert not api_client.exists()
        init_source = (package / "__init__.py").read_text(encoding="utf-8")
        assert "Client" not in init_source and "Keep" in init_source

    print("Optional model stripper regression passed.")


if __name__ == "__main__":
    main()
