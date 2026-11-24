import argparse
import copy
import json
import shutil
from pathlib import Path


def derive(source, destination):
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if source == destination:
        raise ValueError("Source and destination UVDoc directories must differ.")
    destination.mkdir(parents=True, exist_ok=True)
    with (source / "inference.json").open("r", encoding="utf-8") as stream:
        model = json.load(stream)
    operations = model["program"]["regions"][0]["blocks"][0]["ops"]
    grid_sample = next(op for op in operations if op.get("#") == "1.grid_sample")
    original_fetch = next(
        op
        for op in operations
        if op.get("#") == "1.fetch" and op["I"][0]["%"] == grid_sample["O"][0]["%"]
    )
    grid_id = grid_sample["I"][1]["%"]
    grid_type = next(
        output["TT"]
        for op in operations
        for output in op.get("O", [])
        if isinstance(output, dict) and output.get("%") == grid_id
    )
    if any(op.get("#") == "1.fetch" and op["I"][0]["%"] == grid_id for op in operations):
        raise ValueError("UVDoc model already exposes its sampling grid.")
    max_id = max(
        value["%"]
        for op in operations
        for value in op.get("O", [])
        if isinstance(value, dict) and isinstance(value.get("%"), int)
    )
    grid_fetch = copy.deepcopy(original_fetch)
    grid_fetch["A"][0]["AT"]["D"] = "fetch_name_1"
    grid_fetch["A"][1]["AT"]["D"] = 1
    grid_fetch["I"] = [{"%": grid_id}]
    grid_fetch["O"][0]["%"] = max_id + 1
    grid_fetch["O"][0]["TT"] = copy.deepcopy(grid_type)
    operations.insert(operations.index(original_fetch) + 1, grid_fetch)
    with (destination / "inference.json").open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(model, stream, ensure_ascii=True, separators=(",", ":"))
    for name in ("inference.pdiparams", "inference.yml"):
        shutil.copy2(source / name, destination / name)


def main():
    parser = argparse.ArgumentParser(
        description="Expose UVDoc's read-only sampling grid as a second PIR fetch."
    )
    parser.add_argument("source")
    parser.add_argument("destination")
    args = parser.parse_args()
    derive(args.source, args.destination)


if __name__ == "__main__":
    main()
