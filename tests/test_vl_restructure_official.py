"""用锁定的官方 PaddleX 格式化／跨页重组代码复现双图，不加载模型。"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data", type=Path)
    parser.add_argument("--plugin-source", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    data, source, work = args.data.resolve(), args.plugin_source.resolve(), args.work.resolve()
    if work.exists(): raise FileExistsError(work)
    work.mkdir()
    os.chdir(work)
    os.environ.update(PADDLE_PDX_CACHE_HOME=str(work / "paddlex-cache"), PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK="True")
    runtime_plugin = data / "plugins/win32_PaddleOCRVL_1_6"
    spec = importlib.util.spec_from_file_location("runtime_bootstrap_for_test", runtime_plugin / "runtime_archive_bootstrap.py")
    bootstrap = importlib.util.module_from_spec(spec); spec.loader.exec_module(bootstrap)
    archive_paths = bootstrap.prepare_archives(runtime_plugin)
    vendor = runtime_plugin / "vendor"
    sys.path[:0] = [*archive_paths, str(vendor), str(data / "site-packages"), str(data / "dependencies.zip"), str(source.parent)]
    handles = [os.add_dll_directory(str(data / "site-packages/PySide6"))]
    for parent in [vendor / "paddle/base", *(vendor / "nvidia").glob("*")]:
        directory = parent / "bin" if (parent / "bin").is_dir() else parent
        if directory.is_dir(): handles.append(os.add_dll_directory(str(directory)))
    from PIL import Image
    from paddlex.inference.pipelines.paddleocr_vl.result import PaddleOCRVLBlock, PaddleOCRVLResult
    from paddlex.inference.pipelines.paddleocr_vl.pipeline import _PaddleOCRVLPipeline
    from win32_PaddleOCRVL_1_6 import worker
    worker._config = {"tempRoot": str(work)}
    worker._progress = lambda *_args, **_kwargs: None
    records = []
    for formatted in (True, False):
        results = []
        for number in (1, 2):
            image = Image.new("RGB", (60, 40), (number * 30, 80, 100))
            block = PaddleOCRVLBlock(label="image", bbox=[10, 20, 70, 60], content="图片中的识别文字")
            block.image = {"path": "imgs/img_in_image_box_10_20_70_60.png", "img": image}
            page = PaddleOCRVLResult({"input_path": str(work / f"page-{number}.png"), "page_index": number - 1, "page_count": 1,
                "width": 100, "height": 80, "parsing_res_list": [block], "layout_det_res": {"boxes": []}, "imgs_in_doc": [],
                "model_settings": {"format_block_content": formatted, "use_layout_detection": True, "use_doc_preprocessor": False,
                    "use_ocr_for_image_block": True, "use_seal_recognition": True, "use_chart_recognition": True}})
            engine = types.SimpleNamespace(predict=lambda *args, _page=page, **kw: [ _page ],
                restructure_pages=lambda pages, **options: _PaddleOCRVLPipeline.restructure_pages(None, pages, **options))
            worker._engine = engine
            result = worker._document_page(work / f"page-{number}.png", {}, number)
            results.append(result)
            image.close()
        worker._restructure_completed(results, {})
        combined = worker._combine_document(work / "原始文档.pdf", results, [], 2)
        counts = [page["markdown"].count("<img ") for page in combined["data"]["pages"]]
        expected = [2, 2] if formatted else [1, 1]
        assert counts == expected, {"formatted": formatted, "counts": counts, "markdown": combined["markdown"]}
        if not formatted:
            assert len(combined["data"]["assets"]) == 2, "不同页合法复用的图片不能被全局去重"
            assert combined["markdown"].count("图片中的识别文字") == 2
            assert combined["markdown"].count('src="file:///') == 2, "重组改变扩展名后仍须关联真实导出资源"
            assert not combined["partial"], combined["warnings"]
        records.append({"formatBlockContent": formatted, "imagesPerPage": counts, "markdown": combined["markdown"]})
    (work / "result.json").write_text(json.dumps({"passed": True, "modelInference": "NOT_RUN", "officialFormatterAndRestructure": True, "cases": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": True, "oldImagesPerPage": records[0]["imagesPerPage"], "fixedImagesPerPage": records[1]["imagesPerPage"]}, ensure_ascii=False))
    del handles


if __name__ == "__main__":
    main()
