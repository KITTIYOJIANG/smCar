from __future__ import annotations

from pathlib import Path
from time import perf_counter

from sokoban_simulator import MapError, ReplayError, compile_plan, is_solved, parse_map, replay_commands, solve


CONTROL_ROOT = Path(__file__).resolve().parent
MAP_DIR = CONTROL_ROOT / "maps"


def command_counts(commands: list) -> dict[str, int]:
    counts = {"move_to": 0, "align_to_box": 0, "push_box": 0}
    for command in commands:
        counts[command.name] = counts.get(command.name, 0) + 1
    return counts


def run_one(path: Path, max_states: int, algorithm: str) -> tuple[str, str]:
    started = perf_counter()
    try:
        game_map = parse_map(path.read_text(encoding="utf-8"))
        plan = solve(game_map, max_states=max_states, algorithm=algorithm)
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
    try:
        replay_state = replay_commands(game_map, commands)
        replay_pass = is_solved(replay_state, game_map)
    except ReplayError as exc:
        replay_pass = False
        replay_detail = str(exc)
    else:
        replay_detail = "pass" if replay_pass else "final state is not solved"

    counts = command_counts(commands)
    summary = (
        f"{path.name}: solved, "
        f"grid_steps={len(plan)}, "
        f"commands={len(commands)}, "
        f"move_to={counts['move_to']}, "
        f"align_to_box={counts['align_to_box']}, "
        f"push_box={counts['push_box']}, "
        f"replay={'PASS' if replay_pass else 'FAIL'} "
        f"({elapsed_ms:.1f} ms)"
    )
    if not replay_pass:
        return "REPLAY_FAIL", f"{summary}: {replay_detail}"
    return "SOLVED", summary


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run all Sokoban map fixtures.")
    parser.add_argument("--maps", default=str(MAP_DIR), help="Directory containing .txt maps.")
    parser.add_argument("--max-states", type=int, default=100_000, help="Search limit per map.")
    parser.add_argument("--algorithm", choices=["bfs", "astar"], default="bfs", help="Solver algorithm.")
    parser.add_argument(
        "--require-solved",
        action="store_true",
        help="Fail if any map has no solution. Useful for official imported maps.",
    )
    args = parser.parse_args()

    map_dir = Path(args.maps)
    paths = sorted(map_dir.glob("*.txt"))
    if not paths:
        print(f"error: no .txt maps found in {map_dir}")
        return 1

    totals = {"SOLVED": 0, "NO_SOLUTION": 0, "LIMIT": 0, "ERROR": 0, "REPLAY_FAIL": 0}
    for path in paths:
        status, summary = run_one(path, args.max_states, args.algorithm)
        totals[status] += 1
        print(f"[{status}] {summary}")

    print()
    print(
        "Summary: "
        f"solved={totals['SOLVED']}, "
        f"no_solution={totals['NO_SOLUTION']}, "
        f"limit={totals['LIMIT']}, "
        f"replay_fail={totals['REPLAY_FAIL']}, "
        f"errors={totals['ERROR']}, "
        f"total={len(paths)}"
    )

    has_failure = totals["ERROR"] > 0 or totals["LIMIT"] > 0 or totals["REPLAY_FAIL"] > 0
    if args.require_solved and totals["NO_SOLUTION"] > 0:
        has_failure = True
    return 2 if has_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
