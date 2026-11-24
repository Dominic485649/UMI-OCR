import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from staging_smoke import configure_runtime


def run_model(model_dir, device_index, image):
    from paddle.inference import Config, create_predictor

    config = Config(
        str(model_dir / "inference.json"),
        str(model_dir / "inference.pdiparams"),
    )
    config.enable_use_gpu(1024, device_index)
    config.disable_glog_info()
    predictor = create_predictor(config)
    input_names = predictor.get_input_names()
    if len(input_names) != 1:
        raise RuntimeError(f"unexpected UVDoc inputs: {input_names}")
    predictor.get_input_handle(input_names[0]).copy_from_cpu(image)
    predictor.run()
    return [
        predictor.get_output_handle(name).copy_to_cpu()
        for name in predictor.get_output_names()
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_root", type=Path)
    parser.add_argument("original", type=Path)
    parser.add_argument("derived", type=Path)
    parser.add_argument("--device-index", type=int, default=0)
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    original_dir = args.original.resolve()
    derived_dir = args.derived.resolve()
    handles = configure_runtime(data_root)
    import numpy as np

    image = np.linspace(0.0, 1.0, 1 * 3 * 256 * 128, dtype=np.float32).reshape(
        1, 3, 256, 128
    )
    original = run_model(original_dir, args.device_index, image)
    derived = run_model(derived_dir, args.device_index, image)
    if len(original) != 1 or len(derived) != 2:
        raise RuntimeError(
            f"unexpected UVDoc output counts: original={len(original)}, derived={len(derived)}"
        )
    if not np.array_equal(original[0], derived[0]):
        raise RuntimeError(
            f"UVDoc image output changed; max_abs_error={np.max(np.abs(original[0] - derived[0]))}"
        )
    print(
        json.dumps(
            {
                "image_shape": list(derived[0].shape),
                "grid_shape": list(derived[1].shape),
                "image_output_pixel_identical": True,
            }
        )
    )
    del handles


if __name__ == "__main__":
    main()
