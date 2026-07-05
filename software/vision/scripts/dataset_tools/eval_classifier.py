from __future__ import annotations

import argparse
import csv
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image
from torch.utils.data import DataLoader

from train_classifier import CsvImageDataset, SmallCNN, build_transforms


DEFAULT_MODEL = Path("models") / "classifier_v1" / "best_model.pt"
DEFAULT_SPLIT = Path("reports") / "splits" / "test.csv"
DEFAULT_OUTPUT_DIR = Path("reports") / "classifier_v1_eval"


def denormalized_preview(path: Path, label: str, predicted: str) -> np.ndarray:
    with Image.open(path) as image:
        image = image.convert("RGB")
        arr = np.array(image)
    arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    thumb = cv2.resize(arr, (160, 120), interpolation=cv2.INTER_AREA)
    canvas = np.full((156, 160, 3), 255, dtype=np.uint8)
    canvas[36:, :] = thumb
    cv2.putText(canvas, f"A: {label[:15]}", (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(canvas, f"P: {predicted[:15]}", (4, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 180), 1, cv2.LINE_AA)
    return canvas


def write_contact_sheet(rows: list[dict[str, str]], output_path: Path, max_images: int = 80) -> None:
    if not rows:
        return
    tiles = [
        denormalized_preview(Path(row["path"]), row["actual"], row["predicted"])
        for row in rows[:max_images]
    ]
    cols = min(5, len(tiles))
    padded = list(tiles)
    blank = np.full_like(tiles[0], 245)
    while len(padded) % cols:
        padded.append(blank.copy())
    image_rows = [
        cv2.hconcat(padded[index : index + cols])
        for index in range(0, len(padded), cols)
    ]
    sheet = cv2.vconcat(image_rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imencode(".jpg", sheet, [int(cv2.IMWRITE_JPEG_QUALITY), 92])[1].tofile(str(output_path))


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a saved classifier and export mistakes.")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--split", type=Path, default=DEFAULT_SPLIT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()

    checkpoint = torch.load(args.model, map_location="cpu", weights_only=False)
    label_map: dict[str, int] = checkpoint["label_map"]
    id_to_label = {label_id: label for label, label_id in label_map.items()}
    input_size = int(checkpoint.get("input_size", 128))

    _, eval_transform = build_transforms(input_size)
    dataset = CsvImageDataset(args.split, transform=eval_transform)
    loader = DataLoader(dataset, batch_size=args.batch_size, shuffle=False, num_workers=0)

    model = SmallCNN(num_classes=len(label_map))
    model.load_state_dict(checkpoint["model_state"])
    model.eval()

    mistakes: list[dict[str, str]] = []
    total = 0
    correct = 0
    offset = 0
    with torch.no_grad():
        for images, targets in loader:
            logits = model(images)
            probabilities = torch.softmax(logits, dim=1)
            predictions = probabilities.argmax(dim=1)
            for batch_index, (target, prediction) in enumerate(zip(targets.tolist(), predictions.tolist())):
                sample = dataset.samples[offset + batch_index]
                total += 1
                if target == prediction:
                    correct += 1
                    continue
                mistakes.append(
                    {
                        "path": str(sample.path),
                        "actual": id_to_label[target],
                        "predicted": id_to_label[prediction],
                        "confidence": f"{float(probabilities[batch_index, prediction]):.6f}",
                    }
                )
            offset += len(targets)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    mistake_csv = args.output_dir / "mistakes.csv"
    with mistake_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["path", "actual", "predicted", "confidence"])
        writer.writeheader()
        writer.writerows(mistakes)

    sheet_path = args.output_dir / "mistakes_contact_sheet.jpg"
    write_contact_sheet(mistakes, sheet_path)

    print(f"total={total}")
    print(f"correct={correct}")
    print(f"accuracy={correct / max(1, total):.6f}")
    print(f"mistakes={len(mistakes)}")
    print(f"mistake_csv={mistake_csv}")
    if sheet_path.exists():
        print(f"contact_sheet={sheet_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
