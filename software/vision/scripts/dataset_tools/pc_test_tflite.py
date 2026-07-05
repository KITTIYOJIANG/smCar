from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


DEFAULT_MODEL = Path("models") / "openmv_classifier" / "classifier.tflite"
DEFAULT_SPLIT = Path("reports") / "splits" / "test.csv"
DEFAULT_OUTPUT_DIR = Path("reports") / "tflite_eval"


@dataclass(frozen=True)
class Row:
    path: Path
    label: str
    label_id: int


def load_tf():
    import tensorflow as tf

    return tf


def read_rows(csv_path: Path, limit: int) -> list[Row]:
    root = Path.cwd()
    rows: list[Row] = []
    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            path = Path(raw["path"])
            if not path.is_absolute():
                path = root / path
            rows.append(Row(path=path, label=raw["label"], label_id=int(raw["label_id"])))
            if limit > 0 and len(rows) >= limit:
                break
    return rows


def load_label_names(split_path: Path, label_map_path: Path | None) -> list[str]:
    if label_map_path is not None and label_map_path.exists():
        label_map = json.loads(label_map_path.read_text(encoding="utf-8"))
        return [label for label, _ in sorted(label_map.items(), key=lambda item: item[1])]

    candidate = split_path.parent / "label_map.json"
    if candidate.exists():
        label_map = json.loads(candidate.read_text(encoding="utf-8"))
        return [label for label, _ in sorted(label_map.items(), key=lambda item: item[1])]

    labels_by_id: dict[int, str] = {}
    with split_path.open("r", newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            labels_by_id[int(raw["label_id"])] = raw["label"]
    return [labels_by_id[index] for index in sorted(labels_by_id)]


def read_image(path: Path, width: int, height: int) -> np.ndarray:
    with Image.open(path) as image:
        image = image.convert("RGB").resize((width, height), Image.BILINEAR)
        return np.asarray(image, dtype=np.float32)


def quantize_input(image: np.ndarray, details: dict) -> np.ndarray:
    dtype = details["dtype"]
    batched = np.expand_dims(image, axis=0)
    if not np.issubdtype(dtype, np.integer):
        return batched.astype(dtype)

    scale, zero_point = details["quantization"]
    if not scale:
        return batched.astype(dtype)
    quantized = np.round(batched / scale + zero_point)
    limits = np.iinfo(dtype)
    return np.clip(quantized, limits.min, limits.max).astype(dtype)


def dequantize_output(output: np.ndarray, details: dict) -> np.ndarray:
    if not np.issubdtype(output.dtype, np.integer):
        return output.astype(np.float32)
    scale, zero_point = details["quantization"]
    if not scale:
        return output.astype(np.float32)
    return (output.astype(np.float32) - zero_point) * scale


def softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits)
    exp = np.exp(shifted)
    return exp / max(float(exp.sum()), 1e-12)


def denormalized_preview(path: Path, actual: str, predicted: str) -> Image.Image:
    try:
        with Image.open(path) as image:
            thumb = image.convert("RGB")
    except OSError:
        thumb = Image.new("RGB", (160, 120), (230, 230, 230))
    thumb.thumbnail((160, 120), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (160, 156), (255, 255, 255))
    x = (160 - thumb.width) // 2
    y = 36 + (120 - thumb.height) // 2
    canvas.paste(thumb, (x, y))
    draw = ImageDraw.Draw(canvas)
    draw.text((4, 4), f"A: {actual[:15]}", fill=(0, 0, 0))
    draw.text((4, 20), f"P: {predicted[:15]}", fill=(180, 0, 0))
    return canvas


def write_contact_sheet(mistakes: list[dict[str, str]], output: Path, max_images: int) -> None:
    if not mistakes:
        return
    tiles = [
        denormalized_preview(Path(row["path"]), row["actual"], row["predicted"])
        for row in mistakes[:max_images]
    ]
    columns = min(5, len(tiles))
    blank = Image.new("RGB", tiles[0].size, (245, 245, 245))
    while len(tiles) % columns:
        tiles.append(blank)
    rows = len(tiles) // columns
    tile_w, tile_h = tiles[0].size
    sheet = Image.new("RGB", (columns * tile_w, rows * tile_h), (245, 245, 245))
    for index, tile in enumerate(tiles):
        x = (index % columns) * tile_w
        y = (index // columns) * tile_h
        sheet.paste(tile, (x, y))
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, quality=92)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a TFLite classifier on a split CSV.")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--split", type=Path, default=DEFAULT_SPLIT)
    parser.add_argument("--label-map", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-contact-sheet", type=int, default=80)
    args = parser.parse_args()

    rows = read_rows(args.split, args.limit)
    if not rows:
        raise SystemExit(f"empty split: {args.split}")
    labels = load_label_names(args.split, args.label_map)

    tf = load_tf()
    interpreter = tf.lite.Interpreter(model_path=str(args.model))
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()[0]
    output_details = interpreter.get_output_details()[0]
    _, height, width, channels = input_details["shape"].tolist()
    if channels != 3:
        raise SystemExit(f"expected NHWC RGB input with 3 channels, got shape={input_details['shape']}")

    predictions: list[dict[str, str]] = []
    mistakes: list[dict[str, str]] = []
    correct = 0
    for row in rows:
        image = read_image(row.path, width, height)
        input_tensor = quantize_input(image, input_details)
        interpreter.set_tensor(input_details["index"], input_tensor)
        interpreter.invoke()
        output = interpreter.get_tensor(output_details["index"])[0]
        logits = dequantize_output(output, output_details)
        probs = softmax(logits)
        predicted_id = int(np.argmax(probs))
        predicted = labels[predicted_id] if predicted_id < len(labels) else str(predicted_id)
        confidence = float(probs[predicted_id])
        is_correct = predicted_id == row.label_id
        correct += int(is_correct)
        result = {
            "path": str(row.path),
            "actual": row.label,
            "predicted": predicted,
            "confidence": f"{confidence:.6f}",
            "correct": str(is_correct),
        }
        predictions.append(result)
        if not is_correct:
            mistakes.append(result)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    predictions_csv = args.output_dir / "predictions.csv"
    with predictions_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["path", "actual", "predicted", "confidence", "correct"])
        writer.writeheader()
        writer.writerows(predictions)

    mistakes_csv = args.output_dir / "mistakes.csv"
    with mistakes_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["path", "actual", "predicted", "confidence", "correct"])
        writer.writeheader()
        writer.writerows(mistakes)

    sheet_path = args.output_dir / "mistakes_contact_sheet.jpg"
    write_contact_sheet(mistakes, sheet_path, args.max_contact_sheet)

    total = len(rows)
    accuracy = correct / max(1, total)
    print(f"model={args.model}")
    print(f"split={args.split}")
    print(f"input={width}x{height} dtype={input_details['dtype'].__name__}")
    print(f"total={total}")
    print(f"correct={correct}")
    print(f"accuracy={accuracy:.6f}")
    print(f"mistakes={len(mistakes)}")
    print(f"predictions_csv={predictions_csv}")
    print(f"mistakes_csv={mistakes_csv}")
    if sheet_path.exists():
        print(f"contact_sheet={sheet_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
