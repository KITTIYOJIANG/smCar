from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from crop_roi import (
    IMAGE_EXTENSIONS,
    Roi,
    clean_label_name,
    crop_image,
    parse_roi,
    read_image,
    rotate_image,
    write_image,
)


DEFAULT_CONFIG = Path("roi_config.json")
DEFAULT_OUTPUT = Path("openmv") / "openmvImages" / "character_object_roi"
DEFAULT_PREVIEW = Path("reports") / "character_debug" / "object_roi_preview.jpg"
DEFAULT_MANIFEST = Path("reports") / "character_debug" / "object_roi_manifest.csv"


@dataclass(frozen=True)
class Detection:
    rect: tuple[int, int, int, int]
    score: float
    reason: str


@dataclass(frozen=True)
class Sample:
    path: Path
    label: str
    scene: str
    rel_under_label: Path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dataset_config(config: dict[str, Any], dataset: str) -> dict[str, Any]:
    datasets = config.get("datasets", {})
    if dataset not in datasets:
        available = ", ".join(sorted(datasets))
        raise SystemExit(f"dataset '{dataset}' not found. Available: {available}")
    return dict(datasets[dataset])


def collect_samples(source: Path) -> list[Sample]:
    samples: list[Sample] = []
    for label_dir in sorted(path for path in source.iterdir() if path.is_dir()):
        label = clean_label_name(label_dir.name)
        for path in sorted(label_dir.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            rel = path.relative_to(label_dir)
            scene = rel.parts[0] if len(rel.parts) > 1 else "unsorted"
            samples.append(
                Sample(
                    path=path,
                    label=label,
                    scene=scene,
                    rel_under_label=rel,
                )
            )
    return samples


def auto_or_config_crop(image: np.ndarray, roi: Roi) -> tuple[np.ndarray, tuple[int, int]]:
    height, width = image.shape[:2]
    if width >= height and roi.x + roi.w <= width and roi.y + roi.h <= height:
        return crop_image(image, roi), (roi.x, roi.y)
    return image, (0, 0)


def square_rect(
    x: int,
    y: int,
    w: int,
    h: int,
    img_w: int,
    img_h: int,
    margin: float,
) -> tuple[int, int, int, int]:
    cx = x + w / 2.0
    cy = y + h / 2.0
    side = int(round(max(w, h) * (1.0 + margin)))
    side = max(24, min(side, max(img_w, img_h)))
    x1 = int(round(cx - side / 2.0))
    y1 = int(round(cy - side / 2.0))
    x1 = max(0, min(img_w - side, x1))
    y1 = max(0, min(img_h - side, y1))
    side = min(side, img_w - x1, img_h - y1)
    return x1, y1, side, side


def candidate_mask(crop: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    hue = hsv[:, :, 0]

    colorful = (saturation > 45) & (value > 35)
    very_dark = gray < 55
    edges = cv2.Canny(gray, 50, 140)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1) > 0

    # The upper blue sky often dominates the view. Keep colorful details, but
    # suppress large pure-blue sky regions unless they also contain edges.
    blue_sky = (hue >= 85) & (hue <= 125) & (saturation > 70) & (value > 80) & (~edges)
    mask = (colorful | very_dark | edges) & (~blue_sky)

    mask = mask.astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8), iterations=2)
    return mask


def detect_object(crop: np.ndarray) -> Detection:
    img_h, img_w = crop.shape[:2]
    mask = candidate_mask(crop)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best: Detection | None = None
    center_x = img_w / 2.0
    center_y = img_h / 2.0

    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = float(cv2.contourArea(contour))
        rect_area = float(w * h)
        if w < 12 or h < 12:
            continue
        if rect_area < img_w * img_h * 0.006:
            continue
        if w > img_w * 0.96 and h > img_h * 0.75:
            continue
        if y < 4 and h > img_h * 0.5:
            continue

        fill = area / max(1.0, rect_area)
        cx = x + w / 2.0
        cy = y + h / 2.0
        distance = ((cx - center_x) ** 2 + (cy - center_y) ** 2) ** 0.5
        center_bias = 1.0 - min(0.85, distance / max(1.0, (img_w**2 + img_h**2) ** 0.5))
        lower_bias = 1.15 if cy > img_h * 0.35 else 0.75
        aspect = max(w / max(1, h), h / max(1, w))
        aspect_penalty = 1.0 / max(1.0, aspect / 2.6)
        score = rect_area * (0.55 + fill) * center_bias * lower_bias * aspect_penalty

        detection = Detection(rect=(x, y, w, h), score=float(score), reason="mask_component")
        if best is None or detection.score > best.score:
            best = detection

    if best is not None:
        return best

    # Conservative fallback: center square of the configured crop.
    side = int(min(img_w, img_h) * 0.78)
    x = max(0, (img_w - side) // 2)
    y = max(0, (img_h - side) // 2)
    return Detection(rect=(x, y, side, side), score=0.0, reason="center_fallback")


def draw_detection(crop: np.ndarray, detection: Detection, label: str) -> np.ndarray:
    canvas = crop.copy()
    x, y, w, h = detection.rect
    color = (0, 255, 0) if detection.reason != "center_fallback" else (0, 0, 255)
    cv2.rectangle(canvas, (x, y), (x + w, y + h), color, 2)
    cv2.putText(canvas, label[:32], (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
    cv2.putText(canvas, label[:32], (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    return canvas


def resize_tile(image: np.ndarray, width: int, height: int) -> np.ndarray:
    return cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)


def write_preview(tiles: list[np.ndarray], output: Path, columns: int) -> None:
    if not tiles:
        return
    columns = max(1, min(columns, len(tiles)))
    blank = np.full_like(tiles[0], 245)
    padded = list(tiles)
    while len(padded) % columns:
        padded.append(blank.copy())
    rows = [cv2.hconcat(padded[index : index + columns]) for index in range(0, len(padded), columns)]
    sheet = cv2.vconcat(rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imencode(".jpg", sheet, [int(cv2.IMWRITE_JPEG_QUALITY), 92])[1].tofile(str(output))


def output_path(output_root: Path, sample: Sample) -> Path:
    return output_root / sample.label / sample.rel_under_label.with_suffix(".jpg")


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract a tighter character-card ROI from right-eye raw images.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--dataset", default="class")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--preview", type=Path, default=DEFAULT_PREVIEW)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--roi", default="class_roi")
    parser.add_argument("--size", type=int, default=160)
    parser.add_argument("--margin", type=float, default=0.28)
    parser.add_argument("--max-preview", type=int, default=120)
    parser.add_argument("--columns", type=int, default=6)
    parser.add_argument("--quality", type=int, default=92)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    config = read_json(args.config)
    dataset = dataset_config(config, args.dataset)
    source = (args.source or Path(dataset["source"])).resolve()
    output_root = args.output.resolve()
    roi = parse_roi(config, args.roi)
    rotate_degrees = int(config.get("rotate_degrees_clockwise", 0))

    samples = collect_samples(source)
    if not samples:
        raise SystemExit(f"no images found under {source}")

    rows: list[list[str | int | float]] = []
    preview_tiles: list[np.ndarray] = []
    written = 0
    skipped = 0
    fallbacks = 0

    for sample in samples:
        image = read_image(sample.path)
        if image is None:
            skipped += 1
            continue
        rotated = rotate_image(image, rotate_degrees)
        crop, offset = auto_or_config_crop(rotated, roi)
        detection = detect_object(crop)
        if detection.reason == "center_fallback":
            fallbacks += 1

        x, y, w, h = detection.rect
        square = square_rect(x, y, w, h, crop.shape[1], crop.shape[0], args.margin)
        sx, sy, ss, _ = square
        object_crop = crop[sy : sy + ss, sx : sx + ss]
        object_crop = cv2.resize(object_crop, (args.size, args.size), interpolation=cv2.INTER_AREA)

        dst = output_path(output_root, sample)
        if not dst.exists() or args.overwrite:
            write_image(dst, object_crop, args.quality)
            written += 1
        else:
            skipped += 1

        rows.append(
            [
                str(sample.path),
                sample.label,
                sample.scene,
                str(dst),
                offset[0] + x,
                offset[1] + y,
                w,
                h,
                detection.score,
                detection.reason,
            ]
        )

        if len(preview_tiles) < args.max_preview:
            detected_view = draw_detection(crop, Detection(square, detection.score, detection.reason), sample.label)
            tile = np.hstack(
                [
                    resize_tile(detected_view, args.size, args.size),
                    resize_tile(object_crop, args.size, args.size),
                ]
            )
            preview_tiles.append(tile)

    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    with args.manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["source", "label", "scene", "output", "x", "y", "w", "h", "score", "reason"])
        writer.writerows(rows)

    write_preview(preview_tiles, args.preview.resolve(), args.columns)
    print(f"source={source}")
    print(f"samples={len(samples)} written={written} skipped={skipped} fallbacks={fallbacks}")
    print(f"output={output_root}")
    print(f"manifest={args.manifest.resolve()}")
    print(f"preview={args.preview.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
