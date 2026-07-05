from __future__ import annotations

import argparse
import csv
import hashlib
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


DEFAULT_SOURCE = Path("openmv") / "openmvImages" / "raw_Images" / "right_eye" / "character"
DEFAULT_REPORT_DIR = Path("reports")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


@dataclass(frozen=True)
class ImageRecord:
    path: Path
    label: str
    width: int
    height: int
    bytes_size: int
    sharpness: float
    mean_luma: float
    overexposed_percent: float
    underexposed_percent: float
    mean_saturation: float
    md5: str
    warnings: tuple[str, ...]


def read_image(path: Path) -> np.ndarray | None:
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def file_md5(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_metrics(image: np.ndarray) -> dict[str, float]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    return {
        "sharpness": float(cv2.Laplacian(gray, cv2.CV_64F).var()),
        "mean_luma": float(gray.mean()),
        "overexposed_percent": float((gray >= 245).mean() * 100.0),
        "underexposed_percent": float((gray <= 10).mean() * 100.0),
        "mean_saturation": float(hsv[:, :, 1].mean()),
    }


def collect_images(source: Path) -> list[Path]:
    return sorted(
        path
        for path in source.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def classify_path(source: Path, path: Path) -> str:
    relative = path.relative_to(source)
    if len(relative.parts) <= 1:
        return "__root__"
    folder = relative.parts[0]
    if len(folder) > 2 and folder[:2].isdigit() and folder[2].isalpha():
        return folder[2:]
    return folder


def build_record(
    source: Path,
    path: Path,
    min_sharpness: float,
    max_overexposed: float,
    min_saturation: float,
) -> ImageRecord | tuple[Path, str]:
    label = classify_path(source, path)
    image = read_image(path)
    if image is None:
        return path, "unreadable"

    height, width = image.shape[:2]
    metrics = image_metrics(image)
    warnings: list[str] = []
    if metrics["sharpness"] < min_sharpness:
        warnings.append("low_sharpness")
    if metrics["overexposed_percent"] > max_overexposed:
        warnings.append("overexposed")
    if metrics["mean_saturation"] < min_saturation:
        warnings.append("low_saturation")

    return ImageRecord(
        path=path,
        label=label,
        width=width,
        height=height,
        bytes_size=path.stat().st_size,
        sharpness=metrics["sharpness"],
        mean_luma=metrics["mean_luma"],
        overexposed_percent=metrics["overexposed_percent"],
        underexposed_percent=metrics["underexposed_percent"],
        mean_saturation=metrics["mean_saturation"],
        md5=file_md5(path),
        warnings=tuple(warnings),
    )


def write_csv(records: list[ImageRecord], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "path",
                "label",
                "width",
                "height",
                "bytes",
                "sharpness",
                "mean_luma",
                "overexposed_percent",
                "underexposed_percent",
                "mean_saturation",
                "md5",
                "warnings",
            ]
        )
        for record in records:
            writer.writerow(
                [
                    str(record.path),
                    record.label,
                    record.width,
                    record.height,
                    record.bytes_size,
                    f"{record.sharpness:.2f}",
                    f"{record.mean_luma:.2f}",
                    f"{record.overexposed_percent:.2f}",
                    f"{record.underexposed_percent:.2f}",
                    f"{record.mean_saturation:.2f}",
                    record.md5,
                    ";".join(record.warnings),
                ]
            )


def write_unreadable(unreadable: list[tuple[Path, str]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["path", "reason"])
        for path, reason in unreadable:
            writer.writerow([str(path), reason])


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(np.array(values, dtype=np.float64), q))


def summarize(records: list[ImageRecord], min_count: int) -> str:
    by_label: dict[str, list[ImageRecord]] = defaultdict(list)
    for record in records:
        by_label[record.label].append(record)

    duplicate_groups = Counter(record.md5 for record in records)
    duplicate_images = sum(count for count in duplicate_groups.values() if count > 1)

    lines: list[str] = []
    lines.append("# Raw Image Dataset Check")
    lines.append("")
    lines.append(f"Total readable images: {len(records)}")
    lines.append(f"Classes: {len(by_label)}")
    lines.append(f"Duplicate images by exact MD5: {duplicate_images}")
    lines.append("")
    lines.append("## Class Summary")
    lines.append("")
    lines.append(
        "| class | count | main size | sharp p10 | sharp median | overexp mean | sat mean | warnings |"
    )
    lines.append("|---|---:|---|---:|---:|---:|---:|---|")

    for label in sorted(by_label):
        items = by_label[label]
        sizes = Counter((record.width, record.height) for record in items)
        main_size, main_size_count = sizes.most_common(1)[0]
        sharp_values = [record.sharpness for record in items]
        over_values = [record.overexposed_percent for record in items]
        sat_values = [record.mean_saturation for record in items]
        warning_counts = Counter(warning for record in items for warning in record.warnings)
        warnings = []
        if len(items) < min_count:
            warnings.append(f"low_count<{min_count}")
        warnings.extend(f"{key}:{value}" for key, value in sorted(warning_counts.items()))
        if len(sizes) > 1:
            warnings.append(f"mixed_sizes:{len(sizes)}")

        lines.append(
            "| {label} | {count} | {width}x{height} ({main_count}) | {p10:.1f} | {median:.1f} | {over:.2f}% | {sat:.1f} | {warnings} |".format(
                label=label,
                count=len(items),
                width=main_size[0],
                height=main_size[1],
                main_count=main_size_count,
                p10=percentile(sharp_values, 10),
                median=percentile(sharp_values, 50),
                over=float(np.mean(over_values)) if over_values else 0.0,
                sat=float(np.mean(sat_values)) if sat_values else 0.0,
                warnings=", ".join(warnings) if warnings else "-",
            )
        )

    lines.append("")
    lines.append("## Next Checks")
    lines.append("")
    lines.append("- Review classes with `low_count` and decide whether to capture more images.")
    lines.append("- Review `low_sharpness` and `overexposed` rows in the CSV before training.")
    lines.append("- Keep `map_replay` out of the image-class classifier unless it is a real label.")
    lines.append("")
    return "\n".join(lines)


def make_contact_sheet(records: list[ImageRecord], output: Path, samples_per_class: int, seed: int) -> None:
    by_label: dict[str, list[ImageRecord]] = defaultdict(list)
    for record in records:
        by_label[record.label].append(record)

    rng = random.Random(seed)
    tile_w, tile_h = 160, 120
    label_h = 24
    rows: list[np.ndarray] = []

    for label in sorted(by_label):
        items = list(by_label[label])
        rng.shuffle(items)
        selected = items[:samples_per_class]
        tiles: list[np.ndarray] = []
        for record in selected:
            image = read_image(record.path)
            if image is None:
                continue
            resized = cv2.resize(image, (tile_w, tile_h), interpolation=cv2.INTER_AREA)
            tile = np.full((tile_h + label_h, tile_w, 3), 255, dtype=np.uint8)
            tile[label_h:, :] = resized
            text = label[:18]
            cv2.putText(tile, text, (4, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 0, 0), 1, cv2.LINE_AA)
            tiles.append(tile)
        if tiles:
            rows.append(cv2.hconcat(tiles))

    if not rows:
        return

    max_width = max(row.shape[1] for row in rows)
    padded_rows = []
    for row in rows:
        if row.shape[1] < max_width:
            pad = np.full((row.shape[0], max_width - row.shape[1], 3), 255, dtype=np.uint8)
            row = cv2.hconcat([row, pad])
        padded_rows.append(row)

    sheet = cv2.vconcat(padded_rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output), sheet)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check raw SmartCar image dataset quality.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--min-count", type=int, default=100)
    parser.add_argument("--min-sharpness", type=float, default=120.0)
    parser.add_argument("--max-overexposed", type=float, default=8.0)
    parser.add_argument("--min-saturation", type=float, default=40.0)
    parser.add_argument("--samples-per-class", type=int, default=6)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    if not args.source.exists():
        print(f"error: source directory does not exist: {args.source}")
        return 1

    image_paths = collect_images(args.source)
    records: list[ImageRecord] = []
    unreadable: list[tuple[Path, str]] = []
    for path in image_paths:
        result = build_record(
            args.source,
            path,
            min_sharpness=args.min_sharpness,
            max_overexposed=args.max_overexposed,
            min_saturation=args.min_saturation,
        )
        if isinstance(result, ImageRecord):
            records.append(result)
        else:
            unreadable.append(result)

    args.report_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.report_dir / "raw_images_report.csv"
    unreadable_path = args.report_dir / "raw_images_unreadable.csv"
    md_path = args.report_dir / "raw_images_summary.md"
    sheet_path = args.report_dir / "raw_images_contact_sheet.jpg"

    write_csv(records, csv_path)
    write_unreadable(unreadable, unreadable_path)
    md_path.write_text(summarize(records, min_count=args.min_count), encoding="utf-8")
    make_contact_sheet(records, sheet_path, samples_per_class=args.samples_per_class, seed=args.seed)

    print(f"scanned_files={len(image_paths)}")
    print(f"readable_images={len(records)}")
    print(f"unreadable_images={len(unreadable)}")
    print(f"wrote={csv_path}")
    print(f"wrote={unreadable_path}")
    print(f"wrote={md_path}")
    print(f"wrote={sheet_path}")
    if unreadable:
        print("unreadable:")
        for path, reason in unreadable[:20]:
            print(f"  {path}: {reason}")
    return 0 if records else 2


if __name__ == "__main__":
    raise SystemExit(main())
