from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

from crop_roi import IMAGE_EXTENSIONS, clean_label_name


DEFAULT_OLD = Path("reports") / "roi_annotations_class.csv"
DEFAULT_SOURCE = Path("openmv") / "openmvImages" / "raw_Images" / "right_eye" / "character"
DEFAULT_OUTPUT = Path("reports") / "roi_annotations_class_migrated.csv"
DEFAULT_REVIEW = Path("reports") / "roi_annotations_class_migration_review.csv"


LABEL_ALIASES = {
    "DonaldDuck": "donald_duck",
    "donaldduck": "donald_duck",
    "donald_duck": "donald_duck",
    "GreyWolf": "grey_wolf",
    "greywolf": "grey_wolf",
    "Mickey": "mickey_mouse",
    "mickey": "mickey_mouse",
    "Nazha": "nezha",
    "pika": "pikachu",
    "pleasantSheep": "pleasant_sheep",
    "SpongeBob": "spongebob_squarepants",
    "son": "big_head_son",
    "ggbond": "gg_bond",
    "calabash_brothers": "calabash_brothers",
}


def normalize_label(label: str) -> str:
    stripped = label.strip()
    return LABEL_ALIASES.get(stripped, LABEL_ALIASES.get(stripped.lower(), clean_label_name(stripped)))


def relative_to_cwd(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def build_index(source: Path) -> dict[tuple[str, str], list[Path]]:
    index: dict[tuple[str, str], list[Path]] = defaultdict(list)
    for label_dir in sorted(path for path in source.iterdir() if path.is_dir()):
        label = normalize_label(clean_label_name(label_dir.name))
        for path in sorted(label_dir.rglob("*")):
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
                index[(label, path.name)].append(path)
    return index


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate old ROI annotations to the current right_eye/character layout.")
    parser.add_argument("--old", type=Path, default=DEFAULT_OLD)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument(
        "--prefer-scene",
        help="Resolve ambiguous matches by choosing this scene folder, for example far.",
    )
    args = parser.parse_args()

    rows = load_rows(args.old)
    index = build_index(args.source)

    migrated: list[dict[str, str]] = []
    review: list[dict[str, str]] = []

    for row in rows:
        label = normalize_label(row.get("label", ""))
        old_path = Path(row.get("path", ""))
        filename = old_path.name
        matches = index.get((label, filename), [])

        if len(matches) > 1 and args.prefer_scene:
            preferred = [path for path in matches if args.prefer_scene in path.parts]
            if len(preferred) == 1:
                matches = preferred

        if len(matches) == 1:
            new_row = dict(row)
            new_row["path"] = relative_to_cwd(matches[0])
            new_row["label"] = label
            migrated.append(new_row)
        else:
            review.append(
                {
                    "old_path": row.get("path", ""),
                    "old_label": row.get("label", ""),
                    "normalized_label": label,
                    "filename": filename,
                    "match_count": str(len(matches)),
                    "matches": "|".join(relative_to_cwd(path) for path in matches[:20]),
                    "reason": "not_found" if not matches else "ambiguous",
                }
            )

    fieldnames = ["path", "label", "x", "y", "w", "h", "rotate_degrees", "status", "note"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(migrated)

    review_fields = ["old_path", "old_label", "normalized_label", "filename", "match_count", "matches", "reason"]
    args.review.parent.mkdir(parents=True, exist_ok=True)
    with args.review.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=review_fields)
        writer.writeheader()
        writer.writerows(review)

    print(f"old_rows={len(rows)}")
    print(f"migrated={len(migrated)}")
    print(f"review={len(review)}")
    print(f"output={args.output.resolve()}")
    print(f"review_file={args.review.resolve()}")
    return 0 if migrated else 2


if __name__ == "__main__":
    raise SystemExit(main())
