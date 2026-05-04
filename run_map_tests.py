from __future__ import annotations

from pathlib import Path
from time import perf_counter

from sokoban_simulator import MapError, compile_plan, parse_map, solve


MAP_DIR = Path("maps")


def command_counts(commands: list) -> dict[str, int]:
    counts = {"move_to": 0, "align_to_box": 0, "push_box": 0}
    for command in commands:
        counts[command.name] = counts.get(command.name, 0) + 1
    return counts


def run_one(path: Path, max_states: int) -> tuple[str, str]:
    started = perf_counter()
    try:
        game_map = parse_map(path.read_text(encoding="utf-8"))
        plan = solve(game_map, max_states=max_states)
    except MapError as exc:
        elapsed_ms = (perf_counter() - started) * 1000
        return "ERROR", f"{path.name}: {exc} ({elapsed_ms:.1f} ms)"
    except RuntimeError as exc:
        elapsed_ms = (perf_counter() - started) * 1000
        return "LIMIT", f"{path.name}: {exc} ({elapsed_ms:.1f} ms)"

    elapsed_ms = (perf_counter() - started) * 1000
    if plan is None:
        return "NO_SOLUTION", f"{path.name}: no solution ({elapsed_ms:.1f} ms)"

    commands = compile_plan(plan)
    counts = command_counts(commands)
    summary = (
        f"{path.name}: solved, "
        f"grid_steps={len(plan)}, "
        f"commands={len(commands)}, "
        f"move_to={counts['move_to']}, "
        f"align_to_box={counts['align_to_box']}, "
        f"push_box={counts['push_box']} "
        f"({elapsed_ms:.1f} ms)"
    )
    return "SOLVED", summary


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run all Sokoban map fixtures.")
    parser.add_argument("--maps", default=str(MAP_DIR), help="Directory containing .txt maps.")
    parser.add_argument("--max-states", type=int, default=100_000, help="Search limit per map.")
    args = parser.parse_args()

    map_dir = Path(args.maps)
    paths = sorted(map_dir.glob("*.txt"))
    if not paths:
        print(f"error: no .txt maps found in {map_dir}")
        return 1

    totals = {"SOLVED": 0, "NO_SOLUTION": 0, "LIMIT": 0, "ERROR": 0}
    for path in paths:
        status, summary = run_one(path, args.max_states)
        totals[status] += 1
        print(f"[{status}] {summary}")

    print()
    print(
        "Summary: "
        f"solved={totals['SOLVED']}, "
        f"no_solution={totals['NO_SOLUTION']}, "
        f"limit={totals['LIMIT']}, "
        f"errors={totals['ERROR']}, "
        f"total={len(paths)}"
    )

    return 0 if totals["ERROR"] == 0 and totals["LIMIT"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
