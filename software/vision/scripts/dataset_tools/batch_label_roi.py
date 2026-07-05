from __future__ import annotations

import argparse
import csv
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from crop_roi import IMAGE_EXTENSIONS, Roi, clean_label_name, parse_roi, read_image, rotate_image


DEFAULT_CONFIG = Path("roi_config.json")
WINDOW_NAME = "batch ROI labeler"


@dataclass(frozen=True)
class Sample:
    path: Path
    rel_path: str
    label: str


@dataclass
class Box:
    x: int
    y: int
    w: int
    h: int

    @classmethod
    def from_roi(cls, roi: Roi) -> "Box":
        return cls(roi.x, roi.y, roi.w, roi.h)

    def normalized(self, width: int, height: int) -> "Box | None":
        x1 = max(0, min(width - 1, self.x))
        y1 = max(0, min(height - 1, self.y))
        x2 = max(0, min(width, self.x + self.w))
        y2 = max(0, min(height, self.y + self.h))
        if x2 <= x1 or y2 <= y1:
            return None
        return Box(x1, y1, x2 - x1, y2 - y1)


class LabelSession:
    def __init__(
        self,
        samples: list[Sample],
        annotations: dict[str, dict[str, str]],
        output: Path,
        config_box: Box,
        rotate_degrees: int,
        review: bool,
        display_width: int,
    ) -> None:
        self.samples = samples
        self.annotations = annotations
        self.output = output
        self.config_box = config_box
        self.rotate_degrees = rotate_degrees
        self.review = review
        self.display_width = display_width

        self.index = self.first_index()
        self.previous_box: Box | None = self.find_previous_box()
        self.current_box: Box | None = None
        self.drag_start: tuple[int, int] | None = None
        self.drag_current: tuple[int, int] | None = None
        self.image: np.ndarray | None = None
        self.display: np.ndarray | None = None
        self.scale = 1.0

    def first_index(self) -> int:
        if self.review:
            return 0
        for index, sample in enumerate(self.samples):
            if sample.rel_path not in self.annotations:
                return index
        return 0

    def find_previous_box(self) -> Box | None:
        labeled = [
            row
            for row in self.annotations.values()
            if row.get("status") == "labeled"
        ]
        if not labeled:
            return None
        row = labeled[-1]
        return Box(int(row["x"]), int(row["y"]), int(row["w"]), int(row["h"]))

    def current_sample(self) -> Sample:
        return self.samples[self.index]

    def current_annotation_box(self, sample: Sample) -> Box | None:
        row = self.annotations.get(sample.rel_path)
        if not row or row.get("status") != "labeled":
            return None
        return Box(int(row["x"]), int(row["y"]), int(row["w"]), int(row["h"]))

    def load_current(self) -> None:
        sample = self.current_sample()
        image = read_image(sample.path)
        if image is None:
            self.skip_current("unreadable")
            return
        self.image = rotate_image(image, self.rotate_degrees)
        height, width = self.image.shape[:2]
        self.scale = min(1.0, self.display_width / max(1, width))
        if self.scale < 1.0:
            self.display = cv2.resize(
                self.image,
                (int(width * self.scale), int(height * self.scale)),
                interpolation=cv2.INTER_AREA,
            )
        else:
            self.display = self.image.copy()

        self.current_box = (
            self.current_annotation_box(sample)
            or self.previous_box
            or self.config_box
        ).normalized(width, height)

    def image_to_display(self, value: int) -> int:
        return int(round(value * self.scale))

    def display_to_image(self, value: int) -> int:
        return int(round(value / max(self.scale, 1e-6)))

    def draw_box(self, canvas: np.ndarray, box: Box, color: tuple[int, int, int], label: str) -> None:
        x1 = self.image_to_display(box.x)
        y1 = self.image_to_display(box.y)
        x2 = self.image_to_display(box.x + box.w)
        y2 = self.image_to_display(box.y + box.h)
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
        cv2.putText(canvas, label, (x1 + 4, max(18, y1 + 18)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

    def overlay(self) -> np.ndarray:
        if self.display is None:
            raise RuntimeError("display not loaded")
        canvas = self.display.copy()
        sample = self.current_sample()
        status = self.annotations.get(sample.rel_path, {}).get("status", "new")
        title = f"{self.index + 1}/{len(self.samples)} {sample.label} {sample.path.name} status={status}"
        help_text = "drag box | Enter/Space accept | p previous | g config | s skip | b back | r reset | q quit"
        cv2.putText(canvas, title, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 3, cv2.LINE_AA)
        cv2.putText(canvas, title, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 0, 0), 1, cv2.LINE_AA)
        cv2.putText(canvas, help_text, (8, 46), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 3, cv2.LINE_AA)
        cv2.putText(canvas, help_text, (8, 46), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 0, 0), 1, cv2.LINE_AA)

        self.draw_box(canvas, self.config_box, (0, 0, 255), "config")
        if self.previous_box is not None:
            self.draw_box(canvas, self.previous_box, (255, 128, 0), "previous")
        if self.current_box is not None:
            self.draw_box(canvas, self.current_box, (0, 255, 0), "current")
        if self.drag_start is not None and self.drag_current is not None:
            x1, y1 = self.drag_start
            x2, y2 = self.drag_current
            cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 255, 255), 2)
        return canvas

    def mouse(self, event: int, x: int, y: int, _flags: int, _param: object) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            self.drag_start = (x, y)
            self.drag_current = (x, y)
        elif event == cv2.EVENT_MOUSEMOVE and self.drag_start is not None:
            self.drag_current = (x, y)
        elif event == cv2.EVENT_LBUTTONUP and self.drag_start is not None:
            x1, y1 = self.drag_start
            x2, y2 = x, y
            left = self.display_to_image(min(x1, x2))
            top = self.display_to_image(min(y1, y2))
            right = self.display_to_image(max(x1, x2))
            bottom = self.display_to_image(max(y1, y2))
            if self.image is not None:
                height, width = self.image.shape[:2]
                self.current_box = Box(left, top, right - left, bottom - top).normalized(width, height)
            self.drag_start = None
            self.drag_current = None

    def write_annotations(self) -> None:
        self.output.parent.mkdir(parents=True, exist_ok=True)
        rows = [self.annotations[key] for key in sorted(self.annotations)]
        with self.output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["path", "label", "x", "y", "w", "h", "rotate_degrees", "status", "note"],
            )
            writer.writeheader()
            writer.writerows(rows)

    def save_labeled(self) -> None:
        sample = self.current_sample()
        if self.current_box is None:
            return
        if self.image is not None:
            height, width = self.image.shape[:2]
            box = self.current_box.normalized(width, height)
            if box is None:
                return
        else:
            box = self.current_box
        self.annotations[sample.rel_path] = {
            "path": sample.rel_path,
            "label": sample.label,
            "x": str(box.x),
            "y": str(box.y),
            "w": str(box.w),
            "h": str(box.h),
            "rotate_degrees": str(self.rotate_degrees),
            "status": "labeled",
            "note": "",
        }
        self.previous_box = box
        self.write_annotations()

    def skip_current(self, note: str = "") -> None:
        sample = self.current_sample()
        self.annotations[sample.rel_path] = {
            "path": sample.rel_path,
            "label": sample.label,
            "x": "",
            "y": "",
            "w": "",
            "h": "",
            "rotate_degrees": str(self.rotate_degrees),
            "status": "skipped",
            "note": note,
        }
        self.write_annotations()

    def next_unlabeled_or_next(self) -> None:
        next_index = min(len(self.samples) - 1, self.index + 1)
        if not self.review:
            for candidate in range(self.index + 1, len(self.samples)):
                if self.samples[candidate].rel_path not in self.annotations:
                    next_index = candidate
                    break
        self.index = next_index

    def run(self) -> None:
        if not self.samples:
            raise SystemExit("no samples to label")
        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(WINDOW_NAME, self.mouse)

        while True:
            self.load_current()
            while True:
                cv2.imshow(WINDOW_NAME, self.overlay())
                key = cv2.waitKey(20) & 0xFF
                if key in (13, 32):
                    self.save_labeled()
                    self.next_unlabeled_or_next()
                    break
                if key == ord("s"):
                    self.skip_current("manual_skip")
                    self.next_unlabeled_or_next()
                    break
                if key == ord("b"):
                    self.index = max(0, self.index - 1)
                    break
                if key == ord("p") and self.previous_box is not None:
                    self.current_box = self.previous_box
                if key == ord("g"):
                    self.current_box = self.config_box
                if key == ord("r"):
                    self.current_box = None
                if key == ord("q"):
                    self.write_annotations()
                    cv2.destroyAllWindows()
                    return


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dataset_config(config: dict[str, Any], dataset: str) -> dict[str, Any]:
    datasets = config.get("datasets", {})
    if dataset not in datasets:
        available = ", ".join(sorted(datasets))
        raise SystemExit(f"dataset '{dataset}' not found. Available: {available}")
    return dict(datasets[dataset])


def relative_to_cwd(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def collect_samples(
    source: Path,
    include_labels: set[str],
    exclude_labels: set[str],
    max_per_label: int,
    shuffle: bool,
    seed: int,
) -> list[Sample]:
    samples: list[Sample] = []
    counts: dict[str, int] = {}
    for label_dir in sorted(path for path in source.iterdir() if path.is_dir()):
        label = clean_label_name(label_dir.name)
        if include_labels and label not in include_labels:
            continue
        if label in exclude_labels:
            continue
        paths = [
            path
            for path in sorted(label_dir.rglob("*"))
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ]
        if shuffle:
            random.Random(seed + len(samples)).shuffle(paths)
        for path in paths:
            if max_per_label > 0 and counts.get(label, 0) >= max_per_label:
                continue
            samples.append(Sample(path=path, rel_path=relative_to_cwd(path), label=label))
            counts[label] = counts.get(label, 0) + 1
    if shuffle:
        random.Random(seed).shuffle(samples)
    return samples


def read_annotations(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", newline="", encoding="utf-8") as handle:
        return {row["path"]: row for row in csv.DictReader(handle)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch-label per-image ROI boxes.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--dataset", default="class")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--roi", default="class_roi")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-per-label", type=int, default=0)
    parser.add_argument("--shuffle", action="store_true")
    parser.add_argument("--seed", type=int, default=20260626)
    parser.add_argument("--review", action="store_true", help="Review existing rows instead of jumping to unlabeled images.")
    parser.add_argument("--display-width", type=int, default=1100)
    args = parser.parse_args()

    config = read_json(args.config)
    dataset = dataset_config(config, args.dataset)
    source = (args.source or Path(dataset["source"])).resolve()
    output = args.output or (Path("reports") / f"roi_annotations_{args.dataset}.csv")
    include_labels = set(dataset.get("include_labels", []))
    exclude_labels = set(dataset.get("exclude_labels", []))
    rotate_degrees = int(config.get("rotate_degrees_clockwise", 0))
    config_box = Box.from_roi(parse_roi(config, args.roi))

    samples = collect_samples(
        source=source,
        include_labels=include_labels,
        exclude_labels=exclude_labels,
        max_per_label=args.max_per_label,
        shuffle=args.shuffle,
        seed=args.seed,
    )
    annotations = read_annotations(output)

    print(f"samples={len(samples)}")
    print(f"existing_annotations={len(annotations)}")
    print(f"output={output.resolve()}")
    print("Keys: Enter/Space accept, p previous, g config, s skip, b back, r reset, q quit")
    LabelSession(
        samples=samples,
        annotations=annotations,
        output=output,
        config_box=config_box,
        rotate_degrees=rotate_degrees,
        review=args.review,
        display_width=args.display_width,
    ).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
