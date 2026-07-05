from __future__ import annotations

import argparse
import csv
import hashlib
from collections import defaultdict
from pathlib import Path


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
DEFAULT_SOURCE = Path("openmvImages") / "raw_Images"
DEFAULT_UNREADABLE = Path("reports") / "raw_images" / "raw_images_unreadable.csv"


def resolve_inside(root: Path, candidate: Path) -> Path:
    root_resolved = root.resolve()
    candidate_resolved = candidate.resolve()
    try:
        candidate_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"refusing path outside source: {candidate}") from exc
    return candidate_resolved


def read_unreadable_paths(source: Path, unreadable_csv: Path) -> list[Path]:
    if not unreadable_csv.exists():
        return []

    paths: list[Path] = []
    with unreadable_csv.open("r", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            raw_path = row.get("path", "").strip()
            if not raw_path:
                continue
            path = Path(raw_path)
            if not path.is_absolute():
                path = Path.cwd() / path
            paths.append(resolve_inside(source, path))
    return sorted(set(paths))


def collect_images(source: Path) -> list[Path]:
    return sorted(
        path.resolve()
        for path in source.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def file_md5(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def duplicate_paths(source: Path) -> list[Path]:
    by_digest: dict[str, list[Path]] = defaultdict(list)
    for path in collect_images(source):
        by_digest[file_md5(path)].append(path)

    duplicates: list[Path] = []
    for paths in by_digest.values():
        if len(paths) <= 1:
            continue
        # Keep the lexicographically first path so reruns are deterministic.
        duplicates.extend(sorted(paths)[1:])
    return sorted(duplicates)


def delete_files(paths: list[Path], dry_run: bool) -> int:
    deleted = 0
    for path in paths:
        if not path.exists():
            continue
        print(("would delete " if dry_run else "delete ") + str(path))
        if not dry_run:
            path.unlink()
        deleted += 1
    return deleted


def main() -> int:
    parser = argparse.ArgumentParser(description="Delete unreadable images and exact duplicate images.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--unreadable-csv", type=Path, default=DEFAULT_UNREADABLE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source = args.source.resolve()
    if not source.exists():
        raise SystemExit(f"source does not exist: {source}")

    bad_paths = read_unreadable_paths(source, args.unreadable_csv)
    bad_set = set(bad_paths)
    duplicate_candidates = [path for path in duplicate_paths(source) if path not in bad_set]

    print(f"source={source}")
    print(f"unreadable_files={len(bad_paths)}")
    print(f"duplicate_extra_files={len(duplicate_candidates)}")

    deleted_bad = delete_files(bad_paths, args.dry_run)
    deleted_duplicates = delete_files(duplicate_candidates, args.dry_run)

    print(f"deleted_unreadable={deleted_bad}")
    print(f"deleted_duplicates={deleted_duplicates}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
