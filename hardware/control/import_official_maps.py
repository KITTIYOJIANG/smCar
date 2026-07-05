from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path


CONTROL_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = CONTROL_ROOT.parents[1]
WIDTH = 16
HEIGHT = 12
DEFAULT_OUTPUT_DIR = CONTROL_ROOT / "maps" / "official"


def find_default_source_dir() -> Path:
    local_debug_root = PROJECT_ROOT / "local_assets" / "competition_debug_software"
    matches = sorted(local_debug_root.glob("*/SmartCar_VR_*/map_file"))
    if matches:
        return matches[-1]
    return local_debug_root


DEFAULT_SOURCE_DIR = find_default_source_dir()

DEFAULT_STARTS = {
    "map1.txt": (10, 1),
    "map2.txt": (10, 1),
    "map3.txt": (10, 1),
}

SYMBOLS = {
    "skip": set("#-$."),
    "empty": set("#-$."),
    "target": set("#-$."),
    "classic-star": set("#-$.*"),
}


@dataclass(frozen=True)
class ImportResult:
    source: Path
    output: Path | None
    status: str
    message: str


def read_map(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").strip("\n").splitlines()
    if len(lines) != HEIGHT:
        raise ValueError(f"expected {HEIGHT} rows, got {len(lines)}")
    for index, line in enumerate(lines, start=1):
        if len(line) != WIDTH:
            raise ValueError(f"row {index} expected {WIDTH} cols, got {len(line)}")
    return lines


def apply_bomb_policy(lines: list[str], policy: str) -> list[str]:
    if policy == "skip":
        return lines
    if policy == "empty":
        return [line.replace("*", "-") for line in lines]
    if policy == "target":
        return [line.replace("*", ".") for line in lines]
    if policy == "classic-star":
        return lines
    raise ValueError(f"unknown bomb policy: {policy}")


def normalize_map(path: Path, start: tuple[int, int], bomb_policy: str) -> list[str]:
    lines = apply_bomb_policy(read_map(path), bomb_policy)
    allowed = SYMBOLS[bomb_policy]
    symbols = {char for line in lines for char in line}
    unsupported = sorted(symbols - allowed)
    if unsupported:
        raise ValueError(
            "unsupported symbols "
            + ", ".join(repr(symbol) for symbol in unsupported)
            + ". Use --bomb-policy empty/target/classic-star for experiments."
        )

    row, col = start
    if not (0 <= row < HEIGHT and 0 <= col < WIDTH):
        raise ValueError(f"start ({row}, {col}) is outside {WIDTH}x{HEIGHT}")
    if lines[row][col] != "-":
        raise ValueError(f"start ({row}, {col}) is not an empty '-' cell")

    output = list(lines)
    output[row] = output[row][:col] + "@" + output[row][col + 1 :]
    return output


def import_one(path: Path, output_dir: Path, bomb_policy: str) -> ImportResult:
    start = DEFAULT_STARTS.get(path.name)
    if start is None:
        return ImportResult(path, None, "SKIP", "no default start configured")

    try:
        lines = normalize_map(path, start, bomb_policy)
    except ValueError as exc:
        return ImportResult(path, None, "SKIP", str(exc))

    output_name = f"official_{path.stem}_start_{start[0]:02d}_{start[1]:02d}.txt"
    output_path = output_dir / output_name
    output_dir.mkdir(parents=True, exist_ok=True)
    content = "\n".join(lines) + "\n"
    if output_path.exists() and output_path.read_text(encoding="utf-8") == content:
        return ImportResult(path, output_path, "WRITE", f"unchanged, start row={start[0]} col={start[1]}")
    output_path.write_text(content, encoding="utf-8")
    return ImportResult(path, output_path, "WRITE", f"updated, start row={start[0]} col={start[1]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Import official SmartCar VR map files into planner fixtures.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE_DIR, help="Official SmartCar_VR map_file directory.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR, help="Output directory for imported maps.")
    parser.add_argument(
        "--bomb-policy",
        choices=sorted(SYMBOLS),
        default="skip",
        help="How to handle '*' from official maps. Default skips maps containing it.",
    )
    args = parser.parse_args()

    if not args.source.exists():
        print(f"error: source directory not found: {args.source}")
        return 1

    results = [import_one(path, args.output, args.bomb_policy) for path in sorted(args.source.glob("map*.txt"))]
    writes = 0
    for result in results:
        if result.status == "WRITE":
            writes += 1
            print(f"[WRITE] {result.source.name} -> {result.output.name}: {result.message}")
        else:
            print(f"[SKIP] {result.source.name}: {result.message}")

    print()
    print(f"Summary: written={writes}, skipped={len(results) - writes}, total={len(results)}")
    return 0 if writes else 2


if __name__ == "__main__":
    raise SystemExit(main())
