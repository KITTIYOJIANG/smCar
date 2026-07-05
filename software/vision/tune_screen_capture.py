from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


def parse_roi(value: str | None, image_shape: tuple[int, int, int]) -> tuple[int, int, int, int]:
    height, width = image_shape[:2]
    if not value:
        return 0, 0, width, height
    parts = [int(part.strip()) for part in value.split(",")]
    if len(parts) != 4:
        raise ValueError("ROI must be x,y,w,h")
    x, y, w, h = parts
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
        raise ValueError(f"ROI {value!r} is outside image size {width}x{height}")
    return x, y, w, h


def metrics(bgr: np.ndarray) -> dict[str, float]:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    mean_luma = float(gray.mean())
    overexposed = float((gray >= 245).mean() * 100.0)
    underexposed = float((gray <= 10).mean() * 100.0)
    saturation = float(hsv[:, :, 1].mean())
    return {
        "sharpness_laplacian": lap_var,
        "mean_luma": mean_luma,
        "overexposed_percent": overexposed,
        "underexposed_percent": underexposed,
        "mean_saturation": saturation,
    }


def enhance_for_debug(bgr: np.ndarray, gamma: float, clahe_clip: float, sharp: float) -> np.ndarray:
    # Gamma below 1 darkens LCD highlights and makes grid colors less washed out.
    table = np.array([((i / 255.0) ** (1.0 / gamma)) * 255 for i in range(256)]).astype("uint8")
    corrected = cv2.LUT(bgr, table)

    lab = cv2.cvtColor(corrected, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=clahe_clip, tileGridSize=(8, 8))
    l_channel = clahe.apply(l_channel)
    balanced = cv2.cvtColor(cv2.merge((l_channel, a_channel, b_channel)), cv2.COLOR_LAB2BGR)

    blurred = cv2.GaussianBlur(balanced, (0, 0), 1.0)
    return cv2.addWeighted(balanced, 1.0 + sharp, blurred, -sharp, 0)


def label_panel(panel: np.ndarray, label: str) -> np.ndarray:
    out = panel.copy()
    cv2.rectangle(out, (0, 0), (out.shape[1], 28), (0, 0, 0), -1)
    cv2.putText(out, label, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    return out


def make_compare(original: np.ndarray, enhanced: np.ndarray, cropped: np.ndarray) -> np.ndarray:
    target_h = 260

    def fit(image: np.ndarray) -> np.ndarray:
        scale = target_h / image.shape[0]
        return cv2.resize(image, (int(image.shape[1] * scale), target_h), interpolation=cv2.INTER_AREA)

    panels = [
        label_panel(fit(original), "original"),
        label_panel(fit(enhanced), "enhanced for debug"),
        label_panel(fit(cropped), "screen ROI"),
    ]
    return cv2.hconcat(panels)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create debug enhancement and metrics for screen camera captures.")
    parser.add_argument("image", type=Path, help="Input image captured from camera.")
    parser.add_argument("--roi", help="Screen ROI as x,y,w,h. Use this to measure only the game screen.")
    parser.add_argument("--gamma", type=float, default=0.78, help="Gamma correction. Lower darkens highlights.")
    parser.add_argument("--clahe", type=float, default=2.5, help="CLAHE clip limit for local contrast.")
    parser.add_argument("--sharp", type=float, default=1.1, help="Unsharp mask strength.")
    parser.add_argument("--output-dir", type=Path, default=Path("openmvImages") / "tuned")
    args = parser.parse_args()

    image = cv2.imread(str(args.image))
    if image is None:
        print(f"error: cannot read image: {args.image}")
        return 1

    x, y, w, h = parse_roi(args.roi, image.shape)
    roi = image[y : y + h, x : x + w]
    enhanced = enhance_for_debug(image, args.gamma, args.clahe, args.sharp)
    enhanced_roi = enhanced[y : y + h, x : x + w]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = args.image.stem
    enhanced_path = args.output_dir / f"{stem}_enhanced.png"
    compare_path = args.output_dir / f"{stem}_compare.png"
    roi_path = args.output_dir / f"{stem}_roi.png"

    cv2.imwrite(str(enhanced_path), enhanced)
    cv2.imwrite(str(compare_path), make_compare(image, enhanced, enhanced_roi))
    cv2.imwrite(str(roi_path), enhanced_roi)

    print(f"ROI: x={x} y={y} w={w} h={h}")
    print("Original ROI metrics:")
    for key, value in metrics(roi).items():
        print(f"  {key}: {value:.2f}")
    print("Enhanced ROI metrics:")
    for key, value in metrics(enhanced_roi).items():
        print(f"  {key}: {value:.2f}")
    print(f"wrote: {enhanced_path}")
    print(f"wrote: {compare_path}")
    print(f"wrote: {roi_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
