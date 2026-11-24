import argparse
import shutil
import sys
from importlib.metadata import version
from pathlib import Path


PREDICTOR_OLD = """        batch_preds = self.runner(x=x)
        batch_warp_preds = self.postprocessors[\"DocTrPostProcess\"](batch_preds)

        return {
            \"input_path\": batch_data.input_paths,
            \"page_index\": batch_data.page_indexes,
            \"input_img\": batch_raw_imgs,
            \"doctr_img\": batch_warp_preds,
        }
"""

PREDICTOR_NEW = """        batch_preds = self.runner(x=x)
        if len(batch_preds) == 2:
            batch_image_preds, batch_grids = batch_preds
            batch_preds = [batch_image_preds]
        else:
            batch_grids = [None] * len(batch_raw_imgs)
        batch_warp_preds = self.postprocessors[\"DocTrPostProcess\"](batch_preds)

        return {
            \"input_path\": batch_data.input_paths,
            \"page_index\": batch_data.page_indexes,
            \"input_img\": batch_raw_imgs,
            \"doctr_img\": batch_warp_preds,
            \"grid\": batch_grids,
        }
"""

PIPELINE_OLD = """                output_imgs = [
                    item[\"doctr_img\"][:, :, ::-1]
                    for item in self.doc_unwarping_model(rot_imgs)
                ]
            else:
                output_imgs = rot_imgs

            for input_path, page_index, image_array, angle, rot_img, output_img in zip(
                batch_data.input_paths,
                batch_data.page_indexes,
                image_arrays,
                angles,
                rot_imgs,
                output_imgs,
            ):
"""

PIPELINE_NEW = """                unwarping_results = list(self.doc_unwarping_model(rot_imgs))
                output_imgs = [item[\"doctr_img\"][:, :, ::-1] for item in unwarping_results]
                grids = [item.get(\"grid\") for item in unwarping_results]
            else:
                output_imgs = rot_imgs
                grids = [None] * len(rot_imgs)

            for input_path, page_index, image_array, angle, rot_img, output_img, grid in zip(
                batch_data.input_paths,
                batch_data.page_indexes,
                image_arrays,
                angles,
                rot_imgs,
                output_imgs,
                grids,
            ):
"""

RESULT_OLD = '                    "output_img": output_img,\n'
RESULT_NEW = '                    "output_img": output_img,\n                    "grid": grid,\n'

AISTUDIO_IMPORTS = """from aistudio_sdk.errors import NotExistError
from aistudio_sdk.snapshot_download import snapshot_download as aistudio_download
"""

AISTUDIO_OPTIONAL = """try:
    from aistudio_sdk.errors import NotExistError
    from aistudio_sdk.snapshot_download import snapshot_download as aistudio_download
except ModuleNotFoundError:
    class NotExistError(Exception):
        pass

    def aistudio_download(*args, **kwargs):
        raise RuntimeError("AI Studio model downloads are not included in this offline build.")
"""


def replace_once(path, old, new):
    text = path.read_text(encoding="utf-8")
    if new and new in text:
        return
    if not new and old not in text:
        return
    if text.count(old) != 1:
        raise RuntimeError(f"PaddleX patch target changed: {path}")
    path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")


def apply(site_packages):
    sys.path.insert(0, str(Path(site_packages).resolve()))
    if version("paddlex") != "3.7.2":
        raise RuntimeError("This compatibility patch is locked to PaddleX 3.7.2.")
    root = Path(site_packages).resolve() / "paddlex" / "inference"
    predictor = root / "models" / "image_unwarping" / "predictor.py"
    pipeline = root / "pipelines" / "doc_preprocessor" / "pipeline.py"
    replace_once(predictor, PREDICTOR_OLD, PREDICTOR_NEW)
    replace_once(pipeline, PIPELINE_OLD, PIPELINE_NEW)
    replace_once(pipeline, RESULT_OLD, RESULT_NEW)

    engines_init = root / "models" / "engines" / "__init__.py"
    runners_init = root / "models" / "runners" / "__init__.py"
    replace_once(engines_init, "    onnxruntime,\n", "")
    replace_once(
        runners_init,
        "from .onnxruntime_runner import ONNXRuntimeRunner, ONNXRuntimeRunnerConfig\n",
        "",
    )
    replace_once(runners_init, '    "ONNXRuntimeRunner",\n', "")
    replace_once(runners_init, '    "ONNXRuntimeRunnerConfig",\n', "")
    for path in (
        root / "models" / "engines" / "onnxruntime.py",
        root / "models" / "runners" / "onnxruntime_runner.py",
    ):
        path.unlink(missing_ok=True)

    official_models = root / "utils" / "official_models.py"
    replace_once(official_models, AISTUDIO_IMPORTS, AISTUDIO_OPTIONAL)
    package_root = Path(site_packages).resolve()
    for path in (package_root / "aistudio_sdk", *package_root.glob("aistudio_sdk-*.dist-info")):
        if path.is_dir():
            shutil.rmtree(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("site_packages")
    args = parser.parse_args()
    apply(args.site_packages)


if __name__ == "__main__":
    main()
