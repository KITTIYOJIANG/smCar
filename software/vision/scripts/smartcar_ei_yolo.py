from __future__ import annotations

import argparse
import csv
import json
import math
import random
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError


LABELS = [
    "00",
    "01",
    "02",
    "03",
    "04",
    "05",
    "06",
    "07",
    "08",
    "09",
    "mickey_mouse",
    "pikachu",
    "spongebob_squarepants",
    "pleasant_sheep",
    "donald_duck",
    "nezha",
    "big_head_son",
    "gg_bond",
    "calabash_brothers",
    "grey_wolf",
]
VALID_LABELS = set(LABELS)
LABEL_TO_ID = {label: index for index, label in enumerate(LABELS)}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


@dataclass(frozen=True)
class ImageEntry:
    path: str
    name: str
    category: str
    top_label: str
    boxes: list[dict[str, Any]]


def as_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def default_output_root(export_dir: Path) -> Path:
    return export_dir.resolve().parent


def find_info_labels(export_dir: Path, labels_file: str | Path | None = None) -> Path:
    if labels_file:
        path = as_path(labels_file)
        if not path.exists():
            raise FileNotFoundError(f"labels file not found: {path}")
        return path
    preferred = export_dir / "info.labels"
    if preferred.exists():
        return preferred
    candidates = sorted(export_dir.rglob("*.labels"))
    if not candidates:
        raise FileNotFoundError(f"no .labels file found under {export_dir}")
    return candidates[0]


def load_entries(export_dir: Path, labels_file: Path) -> list[ImageEntry]:
    data = json.loads(labels_file.read_text(encoding="utf-8"))
    if "files" in data:
        entries = []
        for item in data.get("files", []):
            label_obj = item.get("label") or {}
            entries.append(
                ImageEntry(
                    path=str(item.get("path", "")).replace("\\", "/"),
                    name=str(item.get("name", "")),
                    category=str(item.get("category", "")),
                    top_label=str(label_obj.get("label", "")),
                    boxes=list(item.get("boundingBoxes") or []),
                )
            )
        return entries

    if data.get("type") == "bounding-box-labels":
        boxes_by_name = data.get("boundingBoxes") or {}
        entries = []
        for image_path in sorted(find_images(export_dir)):
            rel = image_path.relative_to(export_dir).as_posix()
            entries.append(
                ImageEntry(
                    path=rel,
                    name=image_path.stem,
                    category=image_path.parent.name,
                    top_label=image_path.stem,
                    boxes=list(boxes_by_name.get(image_path.name) or []),
                )
            )
        return entries

    raise ValueError(f"unsupported labels format: {labels_file}")


def find_images(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def image_path(export_dir: Path, entry: ImageEntry) -> Path:
    return export_dir / entry.path


def clean_output_dir(path: Path, allowed_root: Path) -> None:
    path = path.resolve()
    allowed_root = allowed_root.resolve()
    try:
        path.relative_to(allowed_root)
    except ValueError as exc:
        raise ValueError(f"refusing to clean outside output root: {path}") from exc
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def safe_name(value: str) -> str:
    result = []
    for char in value.replace("\\", "/"):
        if char.isalnum() or char in ("-", "_", "."):
            result.append(char)
        elif char == "/":
            result.append("__")
        else:
            result.append("_")
    return "".join(result)


def open_rgb(path: Path) -> Image.Image:
    image = Image.open(path)
    image.load()
    return image.convert("RGB")


def draw_boxes(
    source_path: Path,
    boxes: list[dict[str, Any]],
    output_path: Path,
    highlight: set[int] | None = None,
) -> None:
    highlight = highlight or set()
    image = open_rgb(source_path)
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except OSError:
        font = ImageFont.load_default()

    for index, box in enumerate(boxes):
        label = str(box.get("label", ""))
        x = float(box.get("x", 0))
        y = float(box.get("y", 0))
        w = float(box.get("width", 0))
        h = float(box.get("height", 0))
        color = (255, 0, 0) if index in highlight else (0, 220, 80)
        x1 = max(0, min(image.width - 1, int(round(x))))
        y1 = max(0, min(image.height - 1, int(round(y))))
        x2 = max(0, min(image.width - 1, int(round(x + w))))
        y2 = max(0, min(image.height - 1, int(round(y + h))))
        draw.rectangle((x1, y1, x2, y2), outline=color, width=3)
        text = label
        bbox = draw.textbbox((x1, y1), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.rectangle((x1, max(0, y1 - th - 6), x1 + tw + 8, y1), fill=color)
        draw.text((x1 + 4, max(0, y1 - th - 4)), text, fill=(255, 255, 255), font=font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, quality=92)


def bbox_rows(entries: list[ImageEntry], export_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for entry in entries:
        for index, box in enumerate(entry.boxes):
            rows.append(
                {
                    "image_path": str(image_path(export_dir, entry)),
                    "relative_path": entry.path,
                    "category": entry.category,
                    "name": entry.name,
                    "box_index": index,
                    "label": str(box.get("label", "")),
                    "x": float(box.get("x", 0)),
                    "y": float(box.get("y", 0)),
                    "width": float(box.get("width", 0)),
                    "height": float(box.get("height", 0)),
                }
            )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    ensure_parent(path)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def audit_labels(export_dir: Path, output_root: Path, labels_file: Path) -> dict[str, Any]:
    entries = load_entries(export_dir, labels_file)
    rows = bbox_rows(entries, export_dir)
    category_counts = Counter(entry.category for entry in entries)
    label_counts = Counter(row["label"] for row in rows)
    unknown_rows = [row for row in rows if row["label"] not in VALID_LABELS]
    missing_images = [entry.path for entry in entries if not image_path(export_dir, entry).exists()]
    with_boxes = sum(1 for entry in entries if entry.boxes)
    without_boxes = len(entries) - with_boxes

    report = {
        "labels_file": str(labels_file),
        "total_images": len(entries),
        "category_counts": dict(category_counts),
        "images_with_boxes": with_boxes,
        "images_without_boxes": without_boxes,
        "total_boxes": len(rows),
        "label_counts": dict(label_counts),
        "unknown_box_labels": sorted(set(row["label"] for row in unknown_rows)),
        "unknown_box_count": len(unknown_rows),
        "missing_image_count": len(missing_images),
    }

    lines = [
        "# Label Audit Report",
        "",
        f"- Export directory: `{export_dir}`",
        f"- Labels file: `{labels_file}`",
        f"- Total images in labels file: `{len(entries)}`",
        f"- Training images: `{category_counts.get('training', 0)}`",
        f"- Testing images: `{category_counts.get('testing', 0)}`",
        f"- Images with boundingBoxes: `{with_boxes}`",
        f"- Images without boundingBoxes: `{without_boxes}`",
        f"- Total bounding boxes: `{len(rows)}`",
        f"- Missing image files: `{len(missing_images)}`",
        "",
        "## Bounding Box Label Counts",
        "",
    ]
    for label in LABELS:
        lines.append(f"- `{label}`: `{label_counts.get(label, 0)}`")
    extra = sorted(label for label in label_counts if label not in VALID_LABELS)
    if extra:
        lines.extend(["", "## Unknown Labels", ""])
        for label in extra:
            lines.append(f"- `{label}`: `{label_counts[label]}`")
    else:
        lines.extend(["", "## Unknown Labels", "", "- None"])
    if missing_images:
        lines.extend(["", "## Missing Images", ""])
        for path in missing_images[:100]:
            lines.append(f"- `{path}`")
        if len(missing_images) > 100:
            lines.append(f"- ... {len(missing_images) - 100} more")

    (output_root / "label_audit_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if unknown_rows:
        write_csv(
            output_root / "manual_review_list.csv",
            unknown_rows,
            ["image_path", "relative_path", "category", "name", "box_index", "label", "x", "y", "width", "height"],
        )
        dirty_lines = [
            "# Dirty Labels Report",
            "",
            "Training is blocked because bounding box labels outside the approved 20-class schema were found.",
            "",
            "## Approved Labels",
            "",
            ", ".join(f"`{label}`" for label in LABELS),
            "",
            "## Dirty Labels",
            "",
        ]
        for label in extra:
            dirty_lines.append(f"- `{label}`: `{label_counts[label]}`")
        dirty_lines.extend(["", "See `manual_review_list.csv` for exact images and boxes."])
        (output_root / "dirty_labels_report.md").write_text("\n".join(dirty_lines) + "\n", encoding="utf-8")

    return {"entries": entries, "bbox_rows": rows, "report": report, "unknown_rows": unknown_rows}


def suspicious_reason(row: dict[str, Any]) -> str:
    reasons = []
    is_small = row["width"] <= 60 or row["height"] <= 60
    if is_small:
        reasons.append("suspicious_small_box")
    if is_small and row["label"] in {"00", "05", "06"}:
        near_top_left = abs(row["x"] - 320) <= 40 and abs(row["y"] - 240) <= 40
        near_center = abs((row["x"] + row["width"] / 2) - 320) <= 40 and abs(
            (row["y"] + row["height"] / 2) - 240
        ) <= 40
        if near_top_left:
            reasons.append("00_05_06_near_x320_y240_top_left")
        if near_center:
            reasons.append("00_05_06_near_x320_y240_center")
    return ";".join(reasons)


def write_suspicious_report(rows: list[dict[str, Any]], output_root: Path) -> list[dict[str, Any]]:
    suspicious = []
    for row in rows:
        reason = suspicious_reason(row)
        if reason:
            out = dict(row)
            out["reason"] = reason
            suspicious.append(out)

    write_csv(
        output_root / "suspicious_boxes.csv",
        suspicious,
        [
            "image_path",
            "relative_path",
            "category",
            "name",
            "box_index",
            "label",
            "x",
            "y",
            "width",
            "height",
            "reason",
        ],
    )

    by_label = Counter(row["label"] for row in suspicious)
    near_counts = Counter()
    for row in suspicious:
        if "x320_y240" in str(row["reason"]):
            near_counts[row["label"]] += 1

    lines = [
        "# Suspicious Boxes Report",
        "",
        f"- Suspicious boxes: `{len(suspicious)}`",
        f"- Rule: width <= 60 or height <= 60 is suspicious.",
        "- Additional check: labels `00`, `05`, `06` near x=320, y=240 are flagged.",
        "",
        "## Counts By Label",
        "",
    ]
    for label, count in sorted(by_label.items()):
        lines.append(f"- `{label}`: `{count}`")
    lines.extend(["", "## 00/05/06 Near x=320,y=240 Counts", ""])
    for label in ["00", "05", "06"]:
        total = sum(1 for row in rows if row["label"] == label)
        near = near_counts.get(label, 0)
        ratio = near / total if total else 0
        lines.append(f"- `{label}`: `{near}/{total}` ({ratio:.1%})")
    lines.extend(["", "See `suspicious_boxes.csv` for exact boxes."])
    (output_root / "suspicious_boxes_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return suspicious


def generate_label_previews(entries: list[ImageEntry], export_dir: Path, output_root: Path, seed: int) -> int:
    preview_dir = output_root / "preview_boxes"
    clean_output_dir(preview_dir, output_root)
    rng = random.Random(seed)
    by_label: dict[str, list[ImageEntry]] = defaultdict(list)
    for entry in entries:
        labels = {str(box.get("label", "")) for box in entry.boxes}
        for label in labels:
            if label in VALID_LABELS:
                by_label[label].append(entry)

    written = 0
    for label in LABELS:
        choices = list(by_label.get(label, []))
        rng.shuffle(choices)
        for entry in choices[:10]:
            src = image_path(export_dir, entry)
            if not src.exists():
                continue
            out = preview_dir / label / f"{safe_name(entry.path)}"
            draw_boxes(src, entry.boxes, out)
            written += 1
    return written


def generate_suspicious_previews(
    entries: list[ImageEntry],
    suspicious: list[dict[str, Any]],
    export_dir: Path,
    output_root: Path,
    max_count: int,
) -> int:
    preview_dir = output_root / "suspicious_preview"
    clean_output_dir(preview_dir, output_root)
    entry_by_rel = {entry.path: entry for entry in entries}
    written = 0
    seen = set()
    for row in suspicious[:max_count]:
        rel = row["relative_path"]
        if rel in seen:
            continue
        seen.add(rel)
        entry = entry_by_rel.get(rel)
        if not entry:
            continue
        src = image_path(export_dir, entry)
        if not src.exists():
            continue
        highlight = {int(r["box_index"]) for r in suspicious if r["relative_path"] == rel}
        out = preview_dir / f"{safe_name(rel)}"
        draw_boxes(src, entry.boxes, out, highlight=highlight)
        written += 1
    return written


def command_audit_preview(args: argparse.Namespace) -> int:
    export_dir = as_path(args.export_dir)
    output_root = as_path(args.output_root) if args.output_root else default_output_root(export_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    labels_file = find_info_labels(export_dir, args.labels_file)
    audit = audit_labels(export_dir, output_root, labels_file)
    if audit["unknown_rows"]:
        print("Dirty labels found. Stopped before suspicious-box checks and previews.")
        print(f"Report: {output_root / 'dirty_labels_report.md'}")
        print(f"Manual review: {output_root / 'manual_review_list.csv'}")
        return 2

    suspicious = write_suspicious_report(audit["bbox_rows"], output_root)
    preview_count = generate_label_previews(audit["entries"], export_dir, output_root, args.seed)
    suspicious_preview_count = generate_suspicious_previews(
        audit["entries"],
        suspicious,
        export_dir,
        output_root,
        args.max_suspicious_previews,
    )

    summary = {
        "label_audit_report": str((output_root / "label_audit_report.md").resolve()),
        "suspicious_boxes_csv": str((output_root / "suspicious_boxes.csv").resolve()),
        "preview_boxes": str((output_root / "preview_boxes").resolve()),
        "suspicious_preview": str((output_root / "suspicious_preview").resolve()),
        "preview_count": preview_count,
        "suspicious_preview_count": suspicious_preview_count,
        "total_images": audit["report"]["total_images"],
        "images_with_boxes": audit["report"]["images_with_boxes"],
        "images_without_boxes": audit["report"]["images_without_boxes"],
        "total_boxes": audit["report"]["total_boxes"],
        "suspicious_boxes": len(suspicious),
    }
    (output_root / "audit_preview_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def image_primary_label(entry: ImageEntry) -> str:
    labels = [str(box.get("label", "")) for box in entry.boxes if str(box.get("label", "")) in VALID_LABELS]
    return labels[0] if labels else ""


def split_entries(entries: list[ImageEntry], val_ratio: float, seed: int) -> tuple[list[ImageEntry], list[ImageEntry]]:
    by_label: dict[str, list[ImageEntry]] = defaultdict(list)
    for entry in entries:
        by_label[image_primary_label(entry)].append(entry)

    rng = random.Random(seed)
    train: list[ImageEntry] = []
    val: list[ImageEntry] = []
    for label in LABELS:
        items = by_label.get(label, [])
        rng.shuffle(items)
        if not items:
            continue
        if len(items) >= 25:
            val_count = max(5, int(round(len(items) * val_ratio)))
        elif len(items) >= 10:
            val_count = max(3, int(round(len(items) * val_ratio)))
        elif len(items) >= 2:
            val_count = 1
        else:
            val_count = 0
        val.extend(items[:val_count])
        train.extend(items[val_count:])
    rng.shuffle(train)
    rng.shuffle(val)
    return train, val


def write_data_yaml(yolo_dir: Path) -> None:
    lines = [
        f"path: {yolo_dir.as_posix()}",
        "train: train/images",
        "val: val/images",
        "names:",
    ]
    for index, label in enumerate(LABELS):
        lines.append(f'  {index}: "{label}"')
    (yolo_dir / "data.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def yolo_bbox_line(box: dict[str, Any], image_w: int, image_h: int) -> str | None:
    label = str(box.get("label", ""))
    if label not in LABEL_TO_ID:
        return None
    x = float(box.get("x", 0))
    y = float(box.get("y", 0))
    w = float(box.get("width", 0))
    h = float(box.get("height", 0))
    x1 = max(0.0, min(float(image_w), x))
    y1 = max(0.0, min(float(image_h), y))
    x2 = max(0.0, min(float(image_w), x + w))
    y2 = max(0.0, min(float(image_h), y + h))
    bw = x2 - x1
    bh = y2 - y1
    if bw <= 0 or bh <= 0:
        return None
    xc = (x1 + bw / 2) / image_w
    yc = (y1 + bh / 2) / image_h
    return f"{LABEL_TO_ID[label]} {xc:.8f} {yc:.8f} {bw / image_w:.8f} {bh / image_h:.8f}"


def copy_yolo_entry(export_dir: Path, yolo_dir: Path, split: str, entry: ImageEntry) -> dict[str, Any]:
    src = image_path(export_dir, entry)
    with Image.open(src) as image:
        image_w, image_h = image.size
    image_name = safe_name(entry.path)
    if Path(image_name).suffix.lower() not in IMAGE_EXTENSIONS:
        image_name += ".jpg"
    dst_image = yolo_dir / split / "images" / image_name
    dst_label = yolo_dir / split / "labels" / f"{Path(image_name).stem}.txt"
    dst_image.parent.mkdir(parents=True, exist_ok=True)
    dst_label.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst_image)
    lines = [line for box in entry.boxes if (line := yolo_bbox_line(box, image_w, image_h))]
    dst_label.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "source": str(src),
        "split": split,
        "image": str(dst_image),
        "label": str(dst_label),
        "boxes": len(lines),
    }


def draw_yolo_preview(image_path_: Path, label_path: Path, output_path: Path) -> None:
    image = open_rgb(image_path_)
    boxes = []
    if label_path.exists():
        for line in label_path.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) != 5:
                continue
            class_id = int(parts[0])
            xc, yc, bw, bh = [float(value) for value in parts[1:]]
            w = bw * image.width
            h = bh * image.height
            x = xc * image.width - w / 2
            y = yc * image.height - h / 2
            boxes.append({"label": LABELS[class_id], "x": x, "y": y, "width": w, "height": h})
    temp = output_path
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 16)
    except OSError:
        font = ImageFont.load_default()
    for box in boxes:
        x = int(round(box["x"]))
        y = int(round(box["y"]))
        w = int(round(box["width"]))
        h = int(round(box["height"]))
        draw.rectangle((x, y, x + w, y + h), outline=(0, 220, 80), width=3)
        draw.text((x, max(0, y - 14)), str(box["label"]), fill=(255, 255, 255), font=font)
    temp.parent.mkdir(parents=True, exist_ok=True)
    image.save(temp, quality=92)


def command_convert(args: argparse.Namespace) -> int:
    export_dir = as_path(args.export_dir)
    output_root = as_path(args.output_root) if args.output_root else default_output_root(export_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    labels_file = find_info_labels(export_dir, args.labels_file)
    audit = audit_labels(export_dir, output_root, labels_file)
    if audit["unknown_rows"]:
        print("Dirty labels found. Conversion blocked.")
        return 2

    yolo_dir = output_root / "yolo_seed"
    clean_output_dir(yolo_dir, output_root)
    for sub in ("train/images", "train/labels", "val/images", "val/labels"):
        (yolo_dir / sub).mkdir(parents=True, exist_ok=True)

    labeled = [entry for entry in audit["entries"] if entry.boxes]
    unlabeled = [entry for entry in audit["entries"] if not entry.boxes]
    train, val = split_entries(labeled, args.val_ratio, args.seed)
    manifest = []
    for entry in train:
        manifest.append(copy_yolo_entry(export_dir, yolo_dir, "train", entry))
    for entry in val:
        manifest.append(copy_yolo_entry(export_dir, yolo_dir, "val", entry))
    write_data_yaml(yolo_dir)

    (yolo_dir / "unlabeled_pool.txt").write_text(
        "\n".join(str(image_path(export_dir, entry)) for entry in unlabeled) + "\n",
        encoding="utf-8",
    )
    write_csv(
        yolo_dir / "manifest.csv",
        manifest,
        ["source", "split", "image", "label", "boxes"],
    )

    rng = random.Random(args.seed)
    preview_dir = output_root / "yolo_preview"
    clean_output_dir(preview_dir, output_root)
    candidates = list(yolo_dir.glob("train/images/*")) + list(yolo_dir.glob("val/images/*"))
    rng.shuffle(candidates)
    for image_file in candidates[:100]:
        split = image_file.parent.parent.name
        label_file = yolo_dir / split / "labels" / f"{image_file.stem}.txt"
        draw_yolo_preview(image_file, label_file, preview_dir / image_file.name)

    label_image_counts = Counter(image_primary_label(entry) for entry in labeled)
    warnings = []
    for label in LABELS:
        count = label_image_counts.get(label, 0)
        if count < 30:
            warnings.append(f"{label}: only {count} labeled images")

    lines = [
        "# YOLO Convert Report",
        "",
        f"- Source export: `{export_dir}`",
        f"- YOLO dataset: `{yolo_dir}`",
        f"- Labeled images used: `{len(labeled)}`",
        f"- Unlabeled images recorded: `{len(unlabeled)}`",
        f"- Train images: `{len(train)}`",
        f"- Val images: `{len(val)}`",
        f"- Data yaml: `{yolo_dir / 'data.yaml'}`",
        f"- Preview dir: `{preview_dir}`",
        "",
        "## Label Image Counts",
        "",
    ]
    for label in LABELS:
        lines.append(f"- `{label}`: `{label_image_counts.get(label, 0)}`")
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    (output_root / "yolo_convert_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"YOLO dataset written to {yolo_dir}")
    return 0


def command_train(args: argparse.Namespace) -> int:
    data_yaml = as_path(args.data_yaml)
    if not data_yaml.exists():
        raise FileNotFoundError(data_yaml)
    output_root = as_path(args.output_root) if args.output_root else data_yaml.parent.parent
    train_report = output_root / "train_report.md"
    batches = [args.batch, 8, 4, 2, 1]
    seen = set()
    batches = [batch for batch in batches if not (batch in seen or seen.add(batch))]
    last_error = ""
    for batch in batches:
        cmd = [
            "yolo",
            "detect",
            "train",
            f"model={args.model}",
            f"data={data_yaml}",
            f"imgsz={args.imgsz}",
            f"epochs={args.epochs}",
            f"batch={batch}",
            f"project={output_root / 'yolo_runs'}",
            "name=teacher",
            "exist_ok=True",
        ]
        try:
            completed = subprocess.run(cmd, check=True, text=True, capture_output=True)
            (output_root / "train_stdout.log").write_text(completed.stdout, encoding="utf-8")
            (output_root / "train_stderr.log").write_text(completed.stderr, encoding="utf-8")
            best = output_root / "yolo_runs" / "teacher" / "weights" / "best.pt"
            lines = [
                "# YOLO Teacher Train Report",
                "",
                f"- Command: `{' '.join(cmd)}`",
                f"- Batch: `{batch}`",
                f"- Best weights: `{best}`",
                f"- Run directory: `{output_root / 'yolo_runs' / 'teacher'}`",
                "",
                "Review metrics and confusion matrix in the run directory before pseudo-labeling.",
            ]
            train_report.write_text("\n".join(lines) + "\n", encoding="utf-8")
            print(f"Training complete: {best}")
            return 0
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            last_error = str(exc)
            if "out of memory" not in last_error.lower() and batch != args.batch:
                break
            print(f"Training failed with batch={batch}, trying smaller batch if available.")

    train_report.write_text(
        "# YOLO Teacher Train Report\n\n"
        f"Training failed.\n\nLast error:\n\n```text\n{last_error}\n```\n",
        encoding="utf-8",
    )
    return 1


def command_pseudo200(args: argparse.Namespace) -> int:
    model = as_path(args.model)
    yolo_dir = as_path(args.yolo_dir)
    output_root = as_path(args.output_root) if args.output_root else yolo_dir.parent
    pool_file = yolo_dir / "unlabeled_pool.txt"
    if not model.exists():
        raise FileNotFoundError(model)
    if not pool_file.exists():
        raise FileNotFoundError(pool_file)
    pool = [Path(line.strip()) for line in pool_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    rng = random.Random(args.seed)
    rng.shuffle(pool)
    selected = pool[: args.count]
    selected_file = output_root / "pseudo_selected_200.txt"
    selected_file.write_text("\n".join(str(path) for path in selected) + "\n", encoding="utf-8")

    pred_dir = output_root / "pseudo_predictions_200"
    preview_dir = output_root / "pseudo_preview_200"
    low_dir = output_root / "low_confidence_review"
    for folder in (pred_dir, preview_dir, low_dir):
        clean_output_dir(folder, output_root)

    cmd = [
        "yolo",
        "detect",
        "predict",
        f"model={model}",
        f"source={selected_file}",
        f"imgsz={args.imgsz}",
        f"conf={args.conf}",
        f"project={output_root}",
        "name=pseudo_preview_200",
        "save=True",
        "save_txt=True",
        "save_conf=True",
        "exist_ok=True",
    ]
    completed = subprocess.run(cmd, check=False, text=True, capture_output=True)
    (output_root / "pseudo200_stdout.log").write_text(completed.stdout, encoding="utf-8")
    (output_root / "pseudo200_stderr.log").write_text(completed.stderr, encoding="utf-8")
    report = [
        "# Pseudo Label 200 Report",
        "",
        f"- Model: `{model}`",
        f"- Selected images: `{len(selected)}`",
        f"- Selected list: `{selected_file}`",
        f"- Command: `{' '.join(cmd)}`",
        f"- Exit code: `{completed.returncode}`",
        "",
        "Inspect `pseudo_preview_200/` before any large-scale pseudo-labeling.",
    ]
    (output_root / "pseudo_label_200_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return completed.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SmartCar Edge Impulse to YOLO utility")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit-preview", help="Run phases 1-3 only")
    audit.add_argument("--export-dir", required=True)
    audit.add_argument("--labels-file")
    audit.add_argument("--output-root")
    audit.add_argument("--seed", type=int, default=20260628)
    audit.add_argument("--max-suspicious-previews", type=int, default=200)
    audit.set_defaults(func=command_audit_preview)

    convert = sub.add_parser("convert", help="Build yolo_seed after manual preview approval")
    convert.add_argument("--export-dir", required=True)
    convert.add_argument("--labels-file")
    convert.add_argument("--output-root")
    convert.add_argument("--seed", type=int, default=20260628)
    convert.add_argument("--val-ratio", type=float, default=0.2)
    convert.set_defaults(func=command_convert)

    train = sub.add_parser("train", help="Train YOLO teacher model")
    train.add_argument("--data-yaml", required=True)
    train.add_argument("--output-root")
    train.add_argument("--model", default="yolov8n.pt")
    train.add_argument("--imgsz", type=int, default=640)
    train.add_argument("--epochs", type=int, default=80)
    train.add_argument("--batch", type=int, default=16)
    train.set_defaults(func=command_train)

    pseudo = sub.add_parser("pseudo200", help="Run only small-scale 200-image pseudo-label test")
    pseudo.add_argument("--model", required=True)
    pseudo.add_argument("--yolo-dir", required=True)
    pseudo.add_argument("--output-root")
    pseudo.add_argument("--imgsz", type=int, default=640)
    pseudo.add_argument("--conf", type=float, default=0.45)
    pseudo.add_argument("--count", type=int, default=200)
    pseudo.add_argument("--seed", type=int, default=20260628)
    pseudo.set_defaults(func=command_pseudo200)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
