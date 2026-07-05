r"""Prepare OpenART SmartCar image datasets.

This script handles two dataset styles:

1. Character classification:
   raw_Images/SpongeBob/*.jpg -> datasets/character/SpongeBob/*.jpg

2. Grid/tile classification:
   raw screen images -> perspective-warped map tiles for manual labeling.

Run from software/vision:
    python tools\prepare_openart_dataset.py preview-character
    python tools\prepare_openart_dataset.py crop-character
    python tools\prepare_openart_dataset.py preview-grid
    python tools\prepare_openart_dataset.py slice-grid
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageFile


ImageFile.LOAD_TRUNCATED_IMAGES = True


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}
VISION_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = VISION_ROOT / "openmv" / "configs" / "openart_dataset_config.json"


def resolve_config_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return VISION_ROOT / path


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def image_files(raw_root: Path) -> list[Path]:
    return sorted(
        p for p in raw_root.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_image(path: Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        try:
            pil_img = Image.open(path).convert("RGB")
            img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        except Exception as err:
            raise RuntimeError(f"failed to read image: {path}") from err
    return img


def write_image(path: Path, img: np.ndarray) -> None:
    ensure_dir(path.parent)
    ok, encoded = cv2.imencode(path.suffix, img)
    if not ok:
        raise RuntimeError(f"failed to encode image: {path}")
    encoded.tofile(str(path))


def safe_stem(path: Path, raw_root: Path) -> str:
    rel = path.relative_to(raw_root)
    parts = list(rel.parts)
    parts[-1] = Path(parts[-1]).stem
    return "__".join(parts)


def clean_label_name(folder_name: str) -> str:
    if len(folder_name) > 2 and folder_name[:2].isdigit() and folder_name[2].isalpha():
        return folder_name[2:]
    return folder_name


def label_from_path(path: Path, raw_root: Path) -> str:
    rel = path.relative_to(raw_root)
    if len(rel.parts) <= 1:
        return "__root__"
    return clean_label_name(rel.parts[0])


def draw_label(img: np.ndarray, text: str, x: int, y: int) -> None:
    cv2.rectangle(img, (x, y - 20), (x + 360, y + 6), (0, 0, 0), -1)
    cv2.putText(img, text, (x + 4, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)


def contact_sheet(images: list[np.ndarray], cols: int = 4) -> np.ndarray:
    if not images:
        raise RuntimeError("no images to preview")
    h, w = images[0].shape[:2]
    rows = (len(images) + cols - 1) // cols
    sheet = np.zeros((rows * h, cols * w, 3), dtype=np.uint8)
    for i, img in enumerate(images):
        y = (i // cols) * h
        x = (i % cols) * w
        sheet[y : y + h, x : x + w] = img
    return sheet


def character_preview(config: dict, limit: int) -> Path:
    raw_root = resolve_config_path(config["raw_root"])
    preview_dir = resolve_config_path(config["preview_dir"])
    x, y, w, h = config["character"]["roi"]
    previews: list[np.ndarray] = []

    for path in image_files(raw_root)[:limit]:
        img = read_image(path)
        cv2.rectangle(img, (x, y), (x + w, y + h), (0, 0, 255), 3)
        draw_label(img, str(path.relative_to(raw_root)), 8, 24)
        small = cv2.resize(img, (320, 240), interpolation=cv2.INTER_AREA)
        previews.append(small)

    out = preview_dir / "character_roi_preview.jpg"
    write_image(out, contact_sheet(previews))
    return out


def crop_character(config: dict) -> tuple[Path, int]:
    raw_root = resolve_config_path(config["raw_root"])
    output_root = resolve_config_path(config["character"]["output_root"])
    output_size = int(config["character"]["output_size"])
    x, y, w, h = config["character"]["roi"]
    manifest_path = output_root / "manifest.csv"
    count = 0

    ensure_dir(output_root)
    with manifest_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["path", "label", "source", "x", "y", "w", "h"])

        for path in image_files(raw_root):
            label = label_from_path(path, raw_root)
            img = read_image(path)
            crop = img[y : y + h, x : x + w]
            if crop.size == 0:
                raise RuntimeError(f"empty crop for {path}; check character roi")
            crop = cv2.resize(crop, (output_size, output_size), interpolation=cv2.INTER_AREA)
            out = output_root / label / f"{safe_stem(path, raw_root)}.jpg"
            write_image(out, crop)
            writer.writerow([str(out), label, str(path), x, y, w, h])
            count += 1

    return output_root, count


def warp_grid(img: np.ndarray, quad: list[list[float]], rows: int, cols: int, tile_size: int) -> np.ndarray:
    src = np.array(quad, dtype=np.float32)
    width = cols * tile_size
    height = rows * tile_size
    dst = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(img, matrix, (width, height))


def draw_grid_overlay(img: np.ndarray, quad: list[list[float]], rows: int, cols: int) -> np.ndarray:
    overlay = img.copy()
    pts = np.array(quad, dtype=np.int32)
    cv2.polylines(overlay, [pts], True, (0, 0, 255), 3)

    src = np.array(quad, dtype=np.float32)
    unit = 100.0
    dst = np.array(
        [[0, 0], [cols * unit, 0], [cols * unit, rows * unit], [0, rows * unit]],
        dtype=np.float32,
    )
    inv = cv2.getPerspectiveTransform(dst, src)

    def project(point: tuple[float, float]) -> tuple[int, int]:
        p = np.array([[[point[0], point[1]]]], dtype=np.float32)
        q = cv2.perspectiveTransform(p, inv)[0][0]
        return int(round(q[0])), int(round(q[1]))

    for c in range(1, cols):
        p1 = project((c * unit, 0))
        p2 = project((c * unit, rows * unit))
        cv2.line(overlay, p1, p2, (0, 255, 255), 1)
    for r in range(1, rows):
        p1 = project((0, r * unit))
        p2 = project((cols * unit, r * unit))
        cv2.line(overlay, p1, p2, (0, 255, 255), 1)
    return overlay


def grid_preview(config: dict, limit: int) -> Path:
    raw_root = resolve_config_path(config["raw_root"])
    preview_dir = resolve_config_path(config["preview_dir"])
    grid = config["grid"]
    rows = int(grid["rows"])
    cols = int(grid["cols"])
    tile_size = int(grid["tile_size"])
    quad = grid["quad"]
    previews: list[np.ndarray] = []

    for path in image_files(raw_root)[:limit]:
        img = read_image(path)
        overlay = draw_grid_overlay(img, quad, rows, cols)
        draw_label(overlay, str(path.relative_to(raw_root)), 8, 24)
        warped = warp_grid(img, quad, rows, cols, tile_size)
        warped_small = cv2.resize(warped, (320, 240), interpolation=cv2.INTER_AREA)
        overlay_small = cv2.resize(overlay, (320, 240), interpolation=cv2.INTER_AREA)
        previews.append(np.hstack([overlay_small, warped_small]))

    out = preview_dir / "grid_roi_preview.jpg"
    write_image(out, contact_sheet(previews, cols=2))
    return out


def slice_grid(config: dict) -> tuple[Path, int]:
    raw_root = resolve_config_path(config["raw_root"])
    grid = config["grid"]
    rows = int(grid["rows"])
    cols = int(grid["cols"])
    tile_size = int(grid["tile_size"])
    quad = grid["quad"]
    output_root = resolve_config_path(grid["output_root"])
    manifest_path = output_root / "manifest.csv"
    count = 0

    ensure_dir(output_root)
    with manifest_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["path", "source", "row", "col", "label"])

        for path in image_files(raw_root):
            img = read_image(path)
            warped = warp_grid(img, quad, rows, cols, tile_size)
            source_name = safe_stem(path, raw_root)
            source_dir = output_root / source_name
            for r in range(rows):
                for c in range(cols):
                    tile = warped[
                        r * tile_size : (r + 1) * tile_size,
                        c * tile_size : (c + 1) * tile_size,
                    ]
                    out = source_dir / f"r{r:02d}_c{c:02d}.jpg"
                    write_image(out, tile)
                    writer.writerow([str(out), str(path), r, c, ""])
                    count += 1

    return output_root, count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=["preview-character", "crop-character", "preview-grid", "slice-grid"],
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--limit", type=int, default=12, help="number of images in preview modes")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)

    if args.command == "preview-character":
        out = character_preview(config, args.limit)
        print(f"wrote {out}")
    elif args.command == "crop-character":
        out, count = crop_character(config)
        print(f"wrote {count} crops under {out}")
    elif args.command == "preview-grid":
        out = grid_preview(config, args.limit)
        print(f"wrote {out}")
    elif args.command == "slice-grid":
        out, count = slice_grid(config)
        print(f"wrote {count} tiles under {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
