from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
DEFAULT_SOURCE = Path("openmv") / "openmvImages" / "raw_Images" / "right_eye" / "character"
DEFAULT_OUTPUT = Path("reports") / "splits"


@dataclass(frozen=True)
class Sample:
    path: Path
    rel_path: str
    label: str
    label_id: int


def clean_label_name(folder_name: str) -> str:
    if len(folder_name) > 2 and folder_name[:2].isdigit() and folder_name[2].isalpha():
        return folder_name[2:]
    return folder_name


def collect_samples(source: Path, exclude: set[str]) -> tuple[list[Sample], dict[str, int]]:
    labels = sorted(
        clean_label_name(child.name)
        for child in source.iterdir()
        if child.is_dir() and clean_label_name(child.name) not in exclude
    )
    label_map = {label: index for index, label in enumerate(labels)}

    samples: list[Sample] = []
    for label_dir in sorted(child for child in source.iterdir() if child.is_dir()):
        label = clean_label_name(label_dir.name)
        if label not in label_map:
            continue
        for path in sorted(label_dir.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            rel_path = path.relative_to(Path.cwd()).as_posix()
            samples.append(
                Sample(
                    path=path,
                    rel_path=rel_path,
                    label=label,
                    label_id=label_map[label],
                )
            )

    used_labels = sorted({sample.label for sample in samples})
    used_label_map = {label: index for index, label in enumerate(used_labels)}
    remapped = [
        Sample(
            path=sample.path,
            rel_path=sample.rel_path,
            label=sample.label,
            label_id=used_label_map[sample.label],
        )
        for sample in samples
    ]
    return remapped, used_label_map


def split_counts(total: int, train_ratio: float, val_ratio: float) -> tuple[int, int, int]:
    if total <= 0:
        return 0, 0, 0
    if total == 1:
        return 1, 0, 0
    if total == 2:
        return 1, 1, 0

    raw = [total * train_ratio, total * val_ratio, total * (1.0 - train_ratio - val_ratio)]
    counts = [int(value) for value in raw]
    remaining = total - sum(counts)
    order = sorted(range(3), key=lambda index: raw[index] - counts[index], reverse=True)
    for index in order[:remaining]:
        counts[index] += 1

    for index in range(3):
        if counts[index] == 0:
            largest = max(range(3), key=lambda item: counts[item])
            counts[largest] -= 1
            counts[index] += 1

    return counts[0], counts[1], counts[2]


def stratified_split(
    samples: list[Sample],
    train_ratio: float,
    val_ratio: float,
    seed: int,
) -> dict[str, list[Sample]]:
    by_label: dict[str, list[Sample]] = defaultdict(list)
    for sample in samples:
        by_label[sample.label].append(sample)

    rng = random.Random(seed)
    splits = {"train": [], "val": [], "test": []}

    for label in sorted(by_label):
        items = list(by_label[label])
        rng.shuffle(items)
        train_count, val_count, test_count = split_counts(len(items), train_ratio, val_ratio)
        splits["train"].extend(items[:train_count])
        splits["val"].extend(items[train_count : train_count + val_count])
        splits["test"].extend(items[train_count + val_count : train_count + val_count + test_count])

    for split_items in splits.values():
        split_items.sort(key=lambda sample: (sample.label, sample.rel_path))
    return splits


def write_manifest(path: Path, split_name: str, samples: list[Sample]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["path", "label", "label_id", "split"])
        for sample in samples:
            writer.writerow([sample.rel_path, sample.label, sample.label_id, split_name])


def write_all_manifest(path: Path, splits: dict[str, list[Sample]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["path", "label", "label_id", "split"])
        for split_name in ("train", "val", "test"):
            for sample in splits[split_name]:
                writer.writerow([sample.rel_path, sample.label, sample.label_id, split_name])


def split_summary(splits: dict[str, list[Sample]], label_map: dict[str, int], seed: int) -> str:
    lines: list[str] = []
    lines.append("# Dataset Split Summary")
    lines.append("")
    lines.append(f"Seed: {seed}")
    lines.append(f"Classes: {len(label_map)}")
    lines.append(f"Total images: {sum(len(items) for items in splits.values())}")
    lines.append("")
    lines.append("| class | label_id | train | val | test | total |")
    lines.append("|---|---:|---:|---:|---:|---:|")

    labels = sorted(label_map, key=lambda label: label_map[label])
    for label in labels:
        counts = {
            split_name: Counter(sample.label for sample in samples)[label]
            for split_name, samples in splits.items()
        }
        total = sum(counts.values())
        lines.append(
            f"| {label} | {label_map[label]} | {counts['train']} | {counts['val']} | {counts['test']} | {total} |"
        )

    lines.append("")
    lines.append("## Files")
    lines.append("")
    lines.append("- `train.csv`: training set")
    lines.append("- `val.csv`: validation set")
    lines.append("- `test.csv`: final holdout test set")
    lines.append("- `all.csv`: all splits in one file")
    lines.append("- `label_map.json`: class name to numeric id")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create stratified train/val/test manifests.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--train-ratio", type=float, default=0.70)
    parser.add_argument("--val-ratio", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=20260626)
    parser.add_argument("--exclude", nargs="*", default=["map_replay"])
    args = parser.parse_args()

    if args.train_ratio <= 0 or args.val_ratio < 0:
        raise SystemExit("ratios must be positive")
    if args.train_ratio + args.val_ratio >= 1.0:
        raise SystemExit("train_ratio + val_ratio must be < 1.0")

    source = args.source.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    samples, label_map = collect_samples(source, set(args.exclude))
    if not samples:
        raise SystemExit(f"no images found under {source}")

    splits = stratified_split(samples, args.train_ratio, args.val_ratio, args.seed)

    write_manifest(output_dir / "train.csv", "train", splits["train"])
    write_manifest(output_dir / "val.csv", "val", splits["val"])
    write_manifest(output_dir / "test.csv", "test", splits["test"])
    write_all_manifest(output_dir / "all.csv", splits)
    (output_dir / "label_map.json").write_text(
        json.dumps(label_map, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (output_dir / "split_summary.md").write_text(
        split_summary(splits, label_map, args.seed),
        encoding="utf-8",
    )

    print(f"classes={len(label_map)}")
    print(f"train={len(splits['train'])}")
    print(f"val={len(splits['val'])}")
    print(f"test={len(splits['test'])}")
    print(f"output_dir={output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
