from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from PIL import Image
from torch.utils.data import DataLoader, Dataset, Subset, WeightedRandomSampler
from torchvision import transforms


DEFAULT_SPLIT_DIR = Path("reports") / "splits"
DEFAULT_OUTPUT_DIR = Path("models") / "classifier"


@dataclass(frozen=True)
class CsvSample:
    path: Path
    label: str
    label_id: int


class CsvImageDataset(Dataset):
    def __init__(self, csv_path: Path, transform: transforms.Compose | None = None) -> None:
        self.root = Path.cwd()
        self.transform = transform
        self.samples = self._read_samples(csv_path)

    def _read_samples(self, csv_path: Path) -> list[CsvSample]:
        samples: list[CsvSample] = []
        with csv_path.open("r", newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                image_path = Path(row["path"])
                if not image_path.is_absolute():
                    image_path = self.root / image_path
                samples.append(
                    CsvSample(
                        path=image_path,
                        label=row["label"],
                        label_id=int(row["label_id"]),
                    )
                )
        if not samples:
            raise ValueError(f"empty split file: {csv_path}")
        return samples

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, int]:
        sample = self.samples[index]
        with Image.open(sample.path) as image:
            image = image.convert("RGB")
            if self.transform is not None:
                image = self.transform(image)
        return image, sample.label_id


class SmallCNN(nn.Module):
    def __init__(self, num_classes: int) -> None:
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(3, 16, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(16),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(16, 32, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(32, 64, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(64, 96, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm2d(96),
            nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d((1, 1)),
        )
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Dropout(0.25),
            nn.Linear(96, num_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.classifier(self.features(x))


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def build_transforms(input_size: int) -> tuple[transforms.Compose, transforms.Compose]:
    mean = (0.485, 0.456, 0.406)
    std = (0.229, 0.224, 0.225)
    train_transform = transforms.Compose(
        [
            transforms.Resize((input_size, input_size)),
            transforms.RandomApply(
                [
                    transforms.ColorJitter(
                        brightness=0.16,
                        contrast=0.16,
                        saturation=0.10,
                    )
                ],
                p=0.65,
            ),
            transforms.RandomAffine(
                degrees=3,
                translate=(0.025, 0.025),
                scale=(0.96, 1.04),
            ),
            transforms.ToTensor(),
            transforms.Normalize(mean=mean, std=std),
        ]
    )
    eval_transform = transforms.Compose(
        [
            transforms.Resize((input_size, input_size)),
            transforms.ToTensor(),
            transforms.Normalize(mean=mean, std=std),
        ]
    )
    return train_transform, eval_transform


def limit_dataset(dataset: CsvImageDataset, max_samples: int, seed: int) -> Dataset:
    if max_samples <= 0 or max_samples >= len(dataset):
        return dataset
    by_label: dict[int, list[int]] = {}
    for index, sample in enumerate(dataset.samples):
        by_label.setdefault(sample.label_id, []).append(index)
    rng = random.Random(seed)
    selected: list[int] = []
    labels = sorted(by_label)
    quota = max(1, max_samples // max(1, len(labels)))
    for label_id in labels:
        indices = list(by_label[label_id])
        rng.shuffle(indices)
        selected.extend(indices[:quota])
    if len(selected) < max_samples:
        remaining = sorted(set(range(len(dataset))) - set(selected))
        rng.shuffle(remaining)
        selected.extend(remaining[: max_samples - len(selected)])
    rng.shuffle(selected)
    return Subset(dataset, selected[:max_samples])


def labels_from_dataset(dataset: Dataset) -> list[int]:
    if isinstance(dataset, CsvImageDataset):
        return [sample.label_id for sample in dataset.samples]
    if isinstance(dataset, Subset) and isinstance(dataset.dataset, CsvImageDataset):
        return [dataset.dataset.samples[index].label_id for index in dataset.indices]
    raise TypeError("unsupported dataset type")


def make_train_loader(dataset: Dataset, batch_size: int) -> DataLoader:
    labels = labels_from_dataset(dataset)
    counts = Counter(labels)
    weights = torch.DoubleTensor([1.0 / counts[label] for label in labels])
    sampler = WeightedRandomSampler(weights, num_samples=len(weights), replacement=True)
    return DataLoader(dataset, batch_size=batch_size, sampler=sampler, num_workers=0)


def make_eval_loader(dataset: Dataset, batch_size: int) -> DataLoader:
    return DataLoader(dataset, batch_size=batch_size, shuffle=False, num_workers=0)


def class_weights(dataset: Dataset, num_classes: int, device: torch.device) -> torch.Tensor:
    labels = labels_from_dataset(dataset)
    counts = Counter(labels)
    total = sum(counts.values())
    weights = []
    for label_id in range(num_classes):
        count = max(1, counts[label_id])
        weights.append(total / (num_classes * count))
    return torch.tensor(weights, dtype=torch.float32, device=device)


def run_epoch(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    device: torch.device,
    optimizer: optim.Optimizer | None = None,
) -> tuple[float, float, list[list[int]]]:
    training = optimizer is not None
    model.train(training)
    total_loss = 0.0
    total = 0
    correct = 0
    num_classes = model.classifier[-1].out_features
    confusion = [[0 for _ in range(num_classes)] for _ in range(num_classes)]

    context = torch.enable_grad() if training else torch.no_grad()
    with context:
        for images, targets in loader:
            images = images.to(device)
            targets = targets.to(device)
            logits = model(images)
            loss = criterion(logits, targets)

            if training:
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                optimizer.step()

            predictions = logits.argmax(dim=1)
            batch_size = int(targets.numel())
            total_loss += float(loss.item()) * batch_size
            total += batch_size
            correct += int((predictions == targets).sum().item())
            for target, prediction in zip(targets.cpu().tolist(), predictions.cpu().tolist()):
                confusion[target][prediction] += 1

    return total_loss / max(1, total), correct / max(1, total), confusion


def confusion_to_metrics(confusion: list[list[int]], label_map: dict[str, int]) -> list[dict[str, float | int | str]]:
    id_to_label = {label_id: label for label, label_id in label_map.items()}
    rows: list[dict[str, float | int | str]] = []
    for label_id, row in enumerate(confusion):
        total = sum(row)
        correct = row[label_id] if label_id < len(row) else 0
        rows.append(
            {
                "label": id_to_label.get(label_id, str(label_id)),
                "label_id": label_id,
                "correct": correct,
                "total": total,
                "accuracy": correct / total if total else 0.0,
            }
        )
    return rows


def write_confusion_csv(path: Path, confusion: list[list[int]], label_map: dict[str, int]) -> None:
    id_to_label = {label_id: label for label, label_id in label_map.items()}
    labels = [id_to_label[index] for index in range(len(label_map))]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["actual\\predicted", *labels])
        for index, row in enumerate(confusion):
            writer.writerow([labels[index], *row])


def main() -> int:
    parser = argparse.ArgumentParser(description="Train a small image classifier from split CSV files.")
    parser.add_argument("--split-dir", type=Path, default=DEFAULT_SPLIT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--input-size", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--seed", type=int, default=20260626)
    parser.add_argument("--max-train-samples", type=int, default=0)
    parser.add_argument("--max-val-samples", type=int, default=0)
    parser.add_argument("--max-test-samples", type=int, default=0)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()

    seed_everything(args.seed)
    torch.set_num_threads(max(1, args.threads))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    label_map_path = args.split_dir / "label_map.json"
    label_map = json.loads(label_map_path.read_text(encoding="utf-8"))
    num_classes = len(label_map)

    train_transform, eval_transform = build_transforms(args.input_size)
    train_dataset = CsvImageDataset(args.split_dir / "train.csv", transform=train_transform)
    val_dataset = CsvImageDataset(args.split_dir / "val.csv", transform=eval_transform)
    test_dataset = CsvImageDataset(args.split_dir / "test.csv", transform=eval_transform)

    train_dataset = limit_dataset(train_dataset, args.max_train_samples, args.seed)
    val_dataset = limit_dataset(val_dataset, args.max_val_samples, args.seed)
    test_dataset = limit_dataset(test_dataset, args.max_test_samples, args.seed)

    train_loader = make_train_loader(train_dataset, args.batch_size)
    val_loader = make_eval_loader(val_dataset, args.batch_size)
    test_loader = make_eval_loader(test_dataset, args.batch_size)

    model = SmallCNN(num_classes=num_classes).to(device)
    criterion = nn.CrossEntropyLoss(weight=class_weights(train_dataset, num_classes, device))
    optimizer = optim.AdamW(
        model.parameters(),
        lr=args.learning_rate,
        weight_decay=args.weight_decay,
    )
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(1, args.epochs))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    best_val_acc = -1.0
    history: list[dict[str, float | int]] = []
    best_path = args.output_dir / "best_model.pt"

    print(f"device={device}")
    print(f"classes={num_classes}")
    print(f"train={len(train_dataset)} val={len(val_dataset)} test={len(test_dataset)}")

    for epoch in range(1, args.epochs + 1):
        train_loss, train_acc, _ = run_epoch(model, train_loader, criterion, device, optimizer)
        val_loss, val_acc, _ = run_epoch(model, val_loader, criterion, device)
        scheduler.step()

        row = {
            "epoch": epoch,
            "train_loss": train_loss,
            "train_acc": train_acc,
            "val_loss": val_loss,
            "val_acc": val_acc,
        }
        history.append(row)
        print(
            f"epoch={epoch:03d} "
            f"train_loss={train_loss:.4f} train_acc={train_acc:.4f} "
            f"val_loss={val_loss:.4f} val_acc={val_acc:.4f}"
        )

        if val_acc > best_val_acc:
            best_val_acc = val_acc
            torch.save(
                {
                    "model_state": model.state_dict(),
                    "label_map": label_map,
                    "input_size": args.input_size,
                    "epoch": epoch,
                    "val_acc": val_acc,
                    "args": vars(args),
                },
                best_path,
            )

    checkpoint = torch.load(best_path, map_location=device, weights_only=False)
    model.load_state_dict(checkpoint["model_state"])
    test_loss, test_acc, test_confusion = run_epoch(model, test_loader, criterion, device)
    per_class = confusion_to_metrics(test_confusion, label_map)

    metrics = {
        "best_val_acc": best_val_acc,
        "test_loss": test_loss,
        "test_acc": test_acc,
        "history": history,
        "per_class_test": per_class,
        "label_map": label_map,
        "input_size": args.input_size,
    }
    (args.output_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    write_confusion_csv(args.output_dir / "confusion_matrix_test.csv", test_confusion, label_map)
    print(f"best_model={best_path}")
    print(f"test_loss={test_loss:.4f} test_acc={test_acc:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
