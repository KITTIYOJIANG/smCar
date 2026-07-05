"""Copy OpenMV screenshots into the OpenMV raw image inbox.

OpenMV firmware cannot save directly to a Windows path such as D:\\Projects\\...
It saves to the camera filesystem first, for example /screen_000.jpg. After the
camera is mounted as a USB drive, run this script on the PC to copy those files.

Examples:
    python openmv\\scripts\\pc\\pull_openmv_screenshots.py --source E:\\
    python openmv\\scripts\\pc\\pull_openmv_screenshots.py --source E:\\ --watch
    python openmv\\scripts\\pc\\pull_openmv_screenshots.py --source E:\\ --dest openmv\\openmvImages\\raw_Images\\mickey_mouse_far
"""

from __future__ import annotations

import argparse
import ctypes
import shutil
import string
import time
from pathlib import Path


OPENMV_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DEST = OPENMV_ROOT / "openmvImages" / "raw_Images" / "right_eye" / "_incoming_unsorted"
DEFAULT_PATTERN = "screen_*.jpg"


def windows_drive_roots() -> list[Path]:
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    roots: list[Path] = []
    for index, letter in enumerate(string.ascii_uppercase):
        if bitmask & (1 << index):
            roots.append(Path(f"{letter}:\\"))
    return roots


def screenshot_files(source: Path, pattern: str, recursive: bool = True) -> list[Path]:
    try:
        if recursive:
            files = source.rglob(pattern)
        else:
            roots = [source, source / "sd"]
            files = (path for root in roots for path in root.glob(pattern))
        return sorted(path for path in files if path.is_file())
    except OSError:
        return []


def find_sources(pattern: str) -> list[Path]:
    candidates: list[Path] = []
    for root in windows_drive_roots():
        if screenshot_files(root, pattern, recursive=False):
            candidates.append(root)
    return candidates


def unique_destination(dest_dir: Path, name: str) -> Path:
    candidate = dest_dir / name
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    for index in range(1, 1000):
        numbered = dest_dir / f"{stem}_copy{index}{suffix}"
        if not numbered.exists():
            return numbered
    raise RuntimeError(f"too many existing copies for {name}")


def copy_once(source: Path, dest: Path, pattern: str) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0

    for src in screenshot_files(source, pattern):
        dst = dest / src.name
        if dst.exists():
            try:
                if dst.stat().st_size == src.stat().st_size:
                    continue
            except OSError:
                pass
            dst = unique_destination(dest, src.name)

        shutil.copy2(src, dst)
        copied += 1
        print(f"copied {src} -> {dst}")

    return copied


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        help="Mounted OpenMV drive root, for example E:\\",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=DEFAULT_DEST,
        help=f"Destination folder, default: {DEFAULT_DEST}",
    )
    parser.add_argument(
        "--pattern",
        default=DEFAULT_PATTERN,
        help=f"Screenshot file pattern, default: {DEFAULT_PATTERN}",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Keep running and copy new screenshots every second.",
    )
    return parser.parse_args()


def resolve_source(args: argparse.Namespace) -> Path:
    if args.source is not None:
        return args.source

    candidates = find_sources(args.pattern)
    if len(candidates) == 1:
        return candidates[0]

    if not candidates:
        raise SystemExit(
            "No OpenMV screenshot files found. Mount the OpenMV drive and pass "
            "--source, for example: python openmv\\scripts\\pc\\pull_openmv_screenshots.py --source E:\\"
        )

    choices = ", ".join(str(path) for path in candidates)
    raise SystemExit(f"Multiple possible sources found: {choices}. Pass --source explicitly.")


def main() -> int:
    args = parse_args()
    source = resolve_source(args)
    dest = args.dest

    if not source.exists():
        raise SystemExit(f"Source does not exist: {source}")

    print(f"source: {source}")
    print(f"dest:   {dest}")

    while True:
        copied = copy_once(source, dest, args.pattern)
        if not args.watch:
            print(f"done, copied {copied} file(s)")
            return 0
        if copied:
            print(f"watch copied {copied} file(s)")
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
