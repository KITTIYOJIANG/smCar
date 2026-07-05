from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
DEFAULT_CONFIG = Path("roi_config.json")


@dataclass(frozen=True)
class Roi:
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class Sample:
    source: Path
    output: Path
    label: str


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_image(path: Path) -> np.ndarray | None:
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def write_image(path: Path, image: np.ndarray, quality: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        params = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
        encoded = cv2.imencode(".jpg", image, params)[1]
    elif suffix == ".png":
        encoded = cv2.imencode(".png", image)[1]
    else:
        encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])[1]
        path = path.with_suffix(".jpg")
    encoded.tofile(str(path))


def rotate_image(image: np.ndarray, degrees_clockwise: int) -> np.ndarray:
    normalized = degrees_clockwise % 360
    if normalized == 0:
        return image
    if normalized == 90:
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    if normalized == 180:
        return cv2.rotate(image, cv2.ROTATE_180)
    if normalized == 270:
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    raise ValueError("rotate_degrees_clockwise must be one of 0, 90, 180, 270")


def parse_roi(config: dict[str, Any], roi_name: str) -> Roi:
    rois = config.get("rois", {})
    if roi_name not in rois:
        available = ", ".join(sorted(rois))
        raise SystemExit(f"ROI '{roi_name}' not found. Available: {available}")
    raw = rois[roi_name]
    return Roi(x=int(raw["x"]), y=int(raw["y"]), w=int(raw["w"]), h=int(raw["h"]))


def crop_image(image: np.ndarray, roi: Roi) -> np.ndarray:
    height, width = image.shape[:2]
    x1 = max(0, roi.x)
    y1 = max(0, roi.y)
    x2 = min(width, roi.x + roi.w)
    y2 = min(height, roi.y + roi.h)
    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"ROI is outside image bounds: roi={roi} image={width}x{height}")
    return image[y1:y2, x1:x2]


def dataset_config(config: dict[str, Any], dataset: str) -> dict[str, Any]:
    datasets = config.get("datasets", {})
    if dataset not in datasets:
        available = ", ".join(sorted(datasets))
        raise SystemExit(f"dataset '{dataset}' not found. Available: {available}")
    return dict(datasets[dataset])


def clean_label_name(folder_name: str) -> str:
    if len(folder_name) > 2 and folder_name[:2].isdigit() and folder_name[2].isalpha():
        return folder_name[2:]
    return folder_name


def label_from_image_path(source: Path, image_path: Path) -> str:
    relative = image_path.relative_to(source)
    if len(relative.parts) <= 1:
        return "__root__"
    return clean_label_name(relative.parts[0])


def output_relative_path(source: Path, image_path: Path) -> Path:
    relative = image_path.relative_to(source)
    if len(relative.parts) <= 1:
        return relative
    return Path(*relative.parts[1:])


def collect_samples(
    source: Path,
    output: Path,
    include_labels: set[str],
    exclude_labels: set[str],
    max_per_label: int,
) -> list[Sample]:
    if not source.exists():
        raise SystemExit(f"source does not exist: {source}")

    samples: list[Sample] = []
    counts: dict[str, int] = {}
    for label_dir in sorted(path for path in source.iterdir() if path.is_dir()):
        label = clean_label_name(label_dir.name)
        if include_labels and label not in include_labels:
            continue
        if label in exclude_labels:
            continue

        for image_path in sorted(label_dir.rglob("*")):
            if not image_path.is_file() or image_path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            if max_per_label > 0 and counts.get(label, 0) >= max_per_label:
                continue
            rel = output_relative_path(source, image_path)
            out_path = output / label / rel
            samples.append(Sample(source=image_path, output=out_path, label=label))
            counts[label] = counts.get(label, 0) + 1
    return samples


def crop_samples(
    samples: list[Sample],
    roi: Roi,
    rotate_degrees: int,
    quality: int,
    overwrite: bool,
) -> tuple[int, int]:
    copied = 0
    skipped = 0
    for sample in samples:
        if sample.output.exists() and not overwrite:
            skipped += 1
            continue
        image = read_image(sample.source)
        if image is None:
            print(f"warning: unreadable {sample.source}")
            skipped += 1
            continue
        rotated = rotate_image(image, rotate_degrees)
        try:
            cropped = crop_image(rotated, roi)
        except ValueError as err:
            print(f"warning: {sample.source}: {err}")
            skipped += 1
            continue
        write_image(sample.output, cropped, quality)
        copied += 1
    return copied, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description="Crop a configured ROI into a clean training dataset.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--dataset", default="class", help="Dataset key from roi_config.json.")
    parser.add_argument("--source", type=Path, help="Override dataset source.")
    parser.add_argument("--output", type=Path, help="Override dataset output.")
    parser.add_argument("--roi", help="Override ROI key.")
    parser.add_argument("--max-per-label", type=int, default=0)
    parser.add_argument("--quality", type=int, default=92)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    config = read_json(args.config)
    dataset = dataset_config(config, args.dataset)
    roi_name = args.roi or str(dataset.get("roi", "class_roi"))
    roi = parse_roi(config, roi_name)
    rotate_degrees = int(config.get("rotate_degrees_clockwise", 0))

    source = (args.source or Path(dataset["source"])).resolve()
    output = (args.output or Path(dataset["output"])).resolve()
    include_labels = set(dataset.get("include_labels", []))
    exclude_labels = set(dataset.get("exclude_labels", []))

    samples = collect_samples(
        source=source,
        output=output,
        include_labels=include_labels,
        exclude_labels=exclude_labels,
        max_per_label=args.max_per_label,
    )
    if not samples:
        raise SystemExit(f"no images found for dataset '{args.dataset}'")

    copied, skipped = crop_samples(
        samples=samples,
        roi=roi,
        rotate_degrees=rotate_degrees,
        quality=args.quality,
        overwrite=args.overwrite,
    )
    labels = sorted({sample.label for sample in samples})
    print(f"dataset={args.dataset}")
    print(f"roi={roi_name} ({roi.x},{roi.y},{roi.w},{roi.h}) rotate={rotate_degrees}")
    print(f"labels={len(labels)} images={len(samples)}")
    print(f"cropped={copied} skipped={skipped}")
    print(f"output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
