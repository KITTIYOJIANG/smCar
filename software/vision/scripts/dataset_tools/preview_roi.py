from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from crop_roi import IMAGE_EXTENSIONS, Roi, clean_label_name, crop_image, parse_roi, read_image, rotate_image


DEFAULT_CONFIG = Path("roi_config.json")
DEFAULT_OUTPUT = Path("reports") / "roi_preview.jpg"
ROI_COLORS = {
    "screen_roi": (0, 0, 255),
    "map_roi": (255, 128, 0),
    "first_view_roi": (0, 255, 255),
    "class_roi": (0, 255, 0),
    "digit_roi": (255, 0, 255),
}


@dataclass(frozen=True)
class PreviewSample:
    path: Path
    label: str


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dataset_config(config: dict[str, Any], dataset: str) -> dict[str, Any]:
    datasets = config.get("datasets", {})
    if dataset not in datasets:
        available = ", ".join(sorted(datasets))
        raise SystemExit(f"dataset '{dataset}' not found. Available: {available}")
    return dict(datasets[dataset])


def collect_samples(source: Path, include_labels: set[str], exclude_labels: set[str]) -> list[PreviewSample]:
    if not source.exists():
        raise SystemExit(f"source does not exist: {source}")

    samples: list[PreviewSample] = []
    for label_dir in sorted(path for path in source.iterdir() if path.is_dir()):
        label = clean_label_name(label_dir.name)
        if include_labels and label not in include_labels:
            continue
        if label in exclude_labels:
            continue
        for path in sorted(label_dir.rglob("*")):
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
                samples.append(PreviewSample(path=path, label=label))
    return samples


def draw_rois(image: np.ndarray, rois: dict[str, Roi]) -> np.ndarray:
    canvas = image.copy()
    for name, roi in rois.items():
        color = ROI_COLORS.get(name, (255, 255, 255))
        cv2.rectangle(canvas, (roi.x, roi.y), (roi.x + roi.w, roi.y + roi.h), color, 2)
        cv2.putText(canvas, name, (roi.x + 4, max(16, roi.y + 18)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
    return canvas


def resize_with_header(image: np.ndarray, label: str, width: int, height: int) -> np.ndarray:
    resized = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
    header_h = 26
    tile = np.full((height + header_h, width, 3), 245, dtype=np.uint8)
    tile[header_h:, :] = resized
    cv2.putText(tile, label[:32], (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (20, 20, 20), 1, cv2.LINE_AA)
    return tile


def write_contact_sheet(tiles: list[np.ndarray], output: Path, columns: int) -> None:
    if not tiles:
        raise SystemExit("no preview tiles generated")
    columns = max(1, min(columns, len(tiles)))
    blank = np.full_like(tiles[0], 245)
    padded = list(tiles)
    while len(padded) % columns:
        padded.append(blank.copy())
    rows = [cv2.hconcat(padded[index : index + columns]) for index in range(0, len(padded), columns)]
    sheet = cv2.vconcat(rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imencode(".jpg", sheet, [int(cv2.IMWRITE_JPEG_QUALITY), 92])[1].tofile(str(output))


def selected_rois(config: dict[str, Any], names: list[str]) -> dict[str, Roi]:
    roi_names = names or list(config.get("rois", {}).keys())
    return {name: parse_roi(config, name) for name in roi_names}


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a visual ROI preview contact sheet.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--dataset", default="class")
    parser.add_argument("--source", type=Path, help="Override dataset source.")
    parser.add_argument("--roi", action="append", default=[], help="ROI key to draw/crop. Repeatable.")
    parser.add_argument("--mode", choices=["boxed", "crop"], default="boxed")
    parser.add_argument("--count", type=int, default=24)
    parser.add_argument("--seed", type=int, default=20260626)
    parser.add_argument("--columns", type=int, default=4)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    config = read_json(args.config)
    dataset = dataset_config(config, args.dataset)
    source = (args.source or Path(dataset["source"])).resolve()
    include_labels = set(dataset.get("include_labels", []))
    exclude_labels = set(dataset.get("exclude_labels", []))
    rotate_degrees = int(config.get("rotate_degrees_clockwise", 0))
    rois = selected_rois(config, args.roi)

    samples = collect_samples(source, include_labels, exclude_labels)
    if not samples:
        raise SystemExit(f"no images found for dataset '{args.dataset}'")
    rng = random.Random(args.seed)
    rng.shuffle(samples)

    tiles: list[np.ndarray] = []
    crop_roi_name = args.roi[0] if args.roi else str(dataset.get("roi", "class_roi"))
    crop_roi = parse_roi(config, crop_roi_name)
    for sample in samples[: args.count]:
        image = read_image(sample.path)
        if image is None:
            continue
        image = rotate_image(image, rotate_degrees)
        if args.mode == "boxed":
            view = draw_rois(image, rois)
        else:
            view = crop_image(image, crop_roi)
        tiles.append(resize_with_header(view, f"{sample.label}: {sample.path.name}", 220, 165))

    write_contact_sheet(tiles, args.output.resolve(), args.columns)
    print(f"dataset={args.dataset} mode={args.mode} count={len(tiles)}")
    print(f"rotate={rotate_degrees}")
    print(f"output={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
