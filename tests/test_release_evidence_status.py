import importlib.util
import json
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def main():
    path = ROOT / "build" / "tools" / "verify_release_evidence.py"
    spec = importlib.util.spec_from_file_location("release_evidence", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def allowed(conditions):
        # These unit cases isolate component statuses; publication additionally
        # requires separately verified source and current-payload gates.
        return module.public_release_allowed({
            "source_delivery": {"status": "PASS", "verified": True},
            "current_source_e2e": {"status": "PASS", "verified": True, "publication_authorized": True},
            **conditions,
        })

    assert allowed({"included": {"status": "PASS"}})
    assert allowed({"absent": {"status": "NOT_INCLUDED"}})
    assert not allowed({"cudnn": {"status": "PASS_WITH_REQUIREMENTS"}})
    assert not allowed({"model": {"status": "BLOCK"}})
    staging = ROOT / "staging"
    package = staging / "UmiOCR-data"
    assert module.runtime_lock_target(staging, package, package / "native-dlls.lock.json", "UmiOCR-data/runtime/python313.dll") == staging / "UmiOCR-data/runtime/python313.dll"
    assert module.runtime_lock_target(staging, package, package / "runtime.lock.json", "vendor/paddle/base/paddle.pyd") == package / "vendor/paddle/base/paddle.pyd"
    assert module.runtime_lock_target(staging, package, package / "runtime.lock.json", "../escape.dll") is None
    assert tuple(module.CPU_MODELS) == (
        "PP-LCNet_x1_0_doc_ori",
        "UVDoc",
        "PP-LCNet_x1_0_textline_ori",
        "PP-OCRv6_medium_det",
        "PP-OCRv6_medium_rec",
    )
    with tempfile.TemporaryDirectory() as temporary:
        vendor = Path(temporary)
        marker = vendor / "shapely-2.1.2.dist-info" / "DELVEWHEEL"
        marker.parent.mkdir()
        marker.write_text("Arguments: ['D:\\\\a\\\\_temp\\\\geos-3.13.1\\\\bin']", encoding="utf-8")
        assert module.cpu_geos_version(vendor) == "3.13.1"
    with tempfile.TemporaryDirectory() as temporary:
        staging = Path(temporary)
        vendor = staging / "vendor"
        info = vendor / "colorama-0.4.6.dist-info"
        info.mkdir(parents=True)
        (info / "METADATA").write_text(
            "Name: colorama\nVersion: 0.4.6\nHome-page: https://github.com/tartley/colorama\n"
            "Classifier: License :: OSI Approved :: BSD License\n",
            encoding="utf-8",
        )
        rows, _, _ = module.package_rows(vendor, staging)
        assert rows[0]["upstream_revision"] == "0.4.6"
        assert rows[0]["evidence_snapshot"]["artifact_path"].endswith("colorama-0.4.6.dist-info/METADATA")
        assert module.CPU_BINARY_LICENSES["colorama"] == "BSD-3-Clause"
        assert callable(module.verify_cpu_pdfium_bundle)
    with tempfile.TemporaryDirectory() as temporary:
        staging = Path(temporary)
        plugin = staging / "UmiOCR-data" / "plugins" / "win32_PaddleOCRv6_CUDA"
        plugin.mkdir(parents=True)
        runtime_lock = plugin / "runtime.lock.json"
        runtime_lock.write_text('{"nativeBinaryCount": 1}', encoding="utf-8")
        models = {
            "models": [
                {"model_name": "PP-LCNet_x1_0_doc_ori_infer"},
                {"model_name": "UVDoc_grid_infer"},
                {"model_name": "PP-LCNet_x1_0_textline_ori_infer"},
                {"model_name": "PP-OCRv6_medium_det_infer"},
                {"model_name": "PP-OCRv6_medium_rec_infer"},
            ]
        }
        record = {
            "test_type": "real_gpu_ocr_workflows_e2e",
            "status": "PASS",
            "device": "gpu:0",
            "architecture": {
                "type": "separate-worker-stdio-ipc",
                "host_loaded_proprietary_modules": [],
                "ipc_payload": "JSON-lines path/base64 -> JSON OCR result",
            },
            "plugin_runtime_lock_sha256": module.sha256(runtime_lock),
            "model_initialization": [
                "PP-LCNet_x1_0_doc_ori",
                "UVDoc",
                "PP-LCNet_x1_0_textline_ori",
                "PP-OCRv6_medium_det",
                "PP-OCRv6_medium_rec",
            ],
            "ffmpeg_backend_dll_count": 0,
            "cusolvermg_dll_count": 0,
            "exercised_paths": ["batch OCR", "document PDF OCR", "CUDA-only failure paths"],
        }
        evidence = plugin / "gpu-e2e-evidence.json"
        source = staging / "source" / "UmiOCR-data" / "plugins" / plugin.name / evidence.name
        source.parent.mkdir(parents=True)
        evidence.write_text(json.dumps(record), encoding="utf-8")
        source.write_text(json.dumps(record), encoding="utf-8")
        assert module.verify_gpu_e2e(staging, plugin, models)["status"] == "PASS"
        source.unlink()
        (staging / "SOURCE-CODE.md").write_text(
            "# local candidate\n"
            "- Local Git commit: 9deac935099d742d627ecaf15af7f2b2f7b708a1\n"
            "- Local tag: v2.8.0\n"
            "- Upstream repository (reference only): https://github.com/Dominic485649/Umi-OCR\n"
            "- Public source URL: **PENDING**\n",
            encoding="utf-8",
        )
        assert module.verify_gpu_e2e(staging, plugin, models, ROOT)["status"] == "PASS"
        record["device"] = "cpu"
        evidence.write_text(json.dumps(record), encoding="utf-8")
        assert module.verify_gpu_e2e(staging, plugin, models, ROOT)["status"] == "BLOCK"
        # New release evidence must bind adapter source, not just the native
        # runtime lock.  A changed Python adapter invalidates old inference.
        manifest = plugin / "umi-plugin.json"
        manifest.write_text('{"version":"3.0.0"}', encoding="utf-8")
        adapter = plugin / "api.py"
        adapter.write_text("# tested adapter\n", encoding="utf-8")
        record["device"] = "gpu:0"
        evidence.write_text(json.dumps(record), encoding="utf-8")
        assert module.verify_gpu_e2e(staging, plugin, models, ROOT)["status"] == "BLOCK"
        record["plugin_source_sha256"] = {"api.py": module.sha256(adapter)}
        record["workflow_test"] = {"SHA256": module.sha256(ROOT / "tests/test_ocr_workflows.py")}
        evidence.write_text(json.dumps(record), encoding="utf-8")
        assert module.verify_gpu_e2e(staging, plugin, models, ROOT)["status"] == "PASS"
        adapter.write_text("# changed after the test\n", encoding="utf-8")
        assert module.verify_gpu_e2e(staging, plugin, models, ROOT)["status"] == "BLOCK"
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        repo = base / "repo"
        staging = base / "public-staging"
        sibling = base / "Umi-OCR-Plugin" / "win32_PaddleOCRv6_CPU"
        sibling.mkdir(parents=True)
        (repo / "UmiOCR-data/plugins/win32_PaddleOCRVL_1_6").mkdir(parents=True)
        (staging / "UmiOCR-data/plugins").mkdir(parents=True)
        result = module.verify_cpu_and_document(repo, artifact_staging=staging)
        assert result["cpu_ocr"]["status"] == "NOT_INCLUDED"
        assert result["document_models"]["status"] == "NOT_INCLUDED"
        # A development source tree must not influence actual archive scope.
        assert allowed({"cpu": result["cpu_ocr"], "document": result["document_models"]})
        (staging / "UmiOCR-data/plugins/win32_PaddleOCRVL_1_6").mkdir()
        result = module.verify_cpu_and_document(repo, artifact_staging=staging)
        assert result["document_models"]["status"] == "BLOCK"
        (staging / "UmiOCR-data/plugins" / module.CPU_PLUGIN_ID).mkdir()
        audited = {"cpu_ocr": {"status": "BLOCK", "blockers": ["forced failure"]},
                   "runtime": {}, "models": {}, "opencv": {}, "ffmpeg": {},
                   "mpl": {}, "copyleft": {}, "e2e": {}, "source": {}}
        with patch.object(module, "verify_cpu_artifact", return_value=audited) as verify_cpu:
            result = module.verify_cpu_and_document(repo, artifact_staging=staging)
            verify_cpu.assert_called_once_with(staging, repo, [])
        assert result["cpu_ocr"]["status"] == "BLOCK"
        assert not allowed({"cpu": result["cpu_ocr"]})
    print("Release evidence status gate regression passed.")


if __name__ == "__main__":
    main()
