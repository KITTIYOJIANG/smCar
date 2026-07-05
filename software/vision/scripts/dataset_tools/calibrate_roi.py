from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from crop_roi import crop_image, parse_roi, read_image, rotate_image


DEFAULT_CONFIG = Path("roi_config.json")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def draw_existing_roi(image: np.ndarray, config: dict[str, Any], roi_name: str) -> np.ndarray:
    preview = image.copy()
    try:
        roi = parse_roi(config, roi_name)
    except SystemExit:
        return preview
    cv2.rectangle(preview, (roi.x, roi.y), (roi.x + roi.w, roi.y + roi.h), (0, 0, 255), 2)
    cv2.putText(
        preview,
        f"current {roi_name}: x={roi.x} y={roi.y} w={roi.w} h={roi.h}",
        (8, 22),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 0, 255),
        2,
        cv2.LINE_AA,
    )
    return preview


def main() -> int:
    parser = argparse.ArgumentParser(description="Interactively drag an ROI and write it into roi_config.json.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--roi", default="class_roi")
    parser.add_argument("--no-write", action="store_true", help="Only print the selected ROI.")
    args = parser.parse_args()

    config = read_json(args.config)
    image = read_image(args.image)
    if image is None:
        raise SystemExit(f"cannot read image: {args.image}")

    rotate_degrees = int(config.get("rotate_degrees_clockwise", 0))
    image = rotate_image(image, rotate_degrees)
    preview = draw_existing_roi(image, config, args.roi)

    print("Drag the ROI from top-left to bottom-right.")
    print("Press Enter or Space to accept. Press c to cancel.")
    selected = cv2.selectROI(f"select {args.roi}", preview, showCrosshair=True, fromCenter=False)
    cv2.destroyAllWindows()

    x, y, w, h = (int(value) for value in selected)
    if w <= 0 or h <= 0:
        raise SystemExit("selection cancelled")

    _ = crop_image(image, parse_roi({"rois": {args.roi: {"x": x, "y": y, "w": w, "h": h}}}, args.roi))
    print(f'{args.roi}: {{"x": {x}, "y": {y}, "w": {w}, "h": {h}}}')

    if not args.no_write:
        config.setdefault("rois", {})[args.roi] = {"x": x, "y": y, "w": w, "h": h}
        write_json(args.config, config)
        print(f"updated={args.config.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
