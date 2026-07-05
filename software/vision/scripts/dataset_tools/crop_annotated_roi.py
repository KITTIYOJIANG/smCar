from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from crop_roi import Roi, crop_image, read_image, rotate_image, write_image


DEFAULT_CONFIG = Path("roi_config.json")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dataset_config(config: dict[str, Any], dataset: str) -> dict[str, Any]:
    datasets = config.get("datasets", {})
    if dataset not in datasets:
        available = ", ".join(sorted(datasets))
        raise SystemExit(f"dataset '{dataset}' not found. Available: {available}")
    return dict(datasets[dataset])


def destination_path(output: Path, label: str, source: Path) -> Path:
    return output / label / source.name


def main() -> int:
    parser = argparse.ArgumentParser(description="Crop training images from a per-image ROI annotation CSV.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--dataset", default="class")
    parser.add_argument("--annotations", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--quality", type=int, default=92)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    config = read_json(args.config)
    dataset = dataset_config(config, args.dataset)
    annotations = args.annotations or (Path("reports") / f"roi_annotations_{args.dataset}.csv")
    output = (args.output or Path(dataset["output"])).resolve()

    if not annotations.exists():
        raise SystemExit(f"annotations file does not exist: {annotations}")

    cropped = 0
    skipped = 0
    with annotations.open("r", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("status") != "labeled":
                skipped += 1
                continue
            source = Path(row["path"])
            if not source.is_absolute():
                source = Path.cwd() / source
            image = read_image(source)
            if image is None:
                print(f"warning: unreadable {source}")
                skipped += 1
                continue

            rotate_degrees = int(row.get("rotate_degrees") or config.get("rotate_degrees_clockwise", 0))
            image = rotate_image(image, rotate_degrees)
            roi = Roi(x=int(row["x"]), y=int(row["y"]), w=int(row["w"]), h=int(row["h"]))
            try:
                cropped_image = crop_image(image, roi)
            except ValueError as err:
                print(f"warning: {source}: {err}")
                skipped += 1
                continue

            dst = destination_path(output, row["label"], source)
            if dst.exists() and not args.overwrite:
                skipped += 1
                continue
            write_image(dst, cropped_image, args.quality)
            cropped += 1

    print(f"annotations={annotations.resolve()}")
    print(f"cropped={cropped} skipped={skipped}")
    print(f"output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
