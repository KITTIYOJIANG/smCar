from __future__ import annotations

import heapq
import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


WIDTH = 16
HEIGHT = 12


DIRECTIONS = {
    "U": (-1, 0),
    "D": (1, 0),
    "L": (0, -1),
    "R": (0, 1),
}


TILE_HELP = """
Map symbols:
  # wall
  - empty
  @ car
  $ unlabeled box
  . unlabeled target
  a-z labeled box
  A-Z matching labeled target
  * unlabeled box on target
  + car on target
"""


DEFAULT_MAP = """
################
#--------------#
#--------------#
#----@-$-------#
#--------------#
#--------------#
#-----------.--#
#--------------#
#--------------#
#--------------#
#--------------#
################
"""


@dataclass(frozen=True)
class Pos:
    row: int
    col: int

    def step(self, direction: str) -> "Pos":
        dr, dc = DIRECTIONS[direction]
        return Pos(self.row + dr, self.col + dc)


@dataclass(frozen=True)
class Box:
    label: str
    pos: Pos


@dataclass(frozen=True)
class State:
    car: Pos
    boxes: frozenset[Box]


@dataclass(frozen=True)
class Step:
    kind: str
    direction: str
    before: State
    after: State


@dataclass(frozen=True)
class CarCommand:
    name: str
    args: tuple[object, ...]

    def format(self) -> str:
        rendered_args = ", ".join(format_command_arg(arg) for arg in self.args)
        return f"{self.name}({rendered_args})"


@dataclass(frozen=True)
class SokobanMap:
    walls: frozenset[Pos]
    targets: frozenset[Pos]
    labeled_targets: dict[str, Pos]
    start: State
    width: int
    height: int


class MapError(ValueError):
    pass


class ReplayError(ValueError):
    pass


def parse_map(text: str) -> SokobanMap:
    lines = [line.rstrip("\n") for line in text.strip("\n").splitlines()]
    if not lines:
        raise MapError("Map is empty.")

    height = len(lines)
    width = max(len(line) for line in lines)
    if width != WIDTH or height != HEIGHT:
        raise MapError(f"Expected {WIDTH}x{HEIGHT}, got {width}x{height}.")

    walls: set[Pos] = set()
    targets: set[Pos] = set()
    boxes: set[Box] = set()
    labeled_targets: dict[str, Pos] = {}
    car: Pos | None = None

    for row, line in enumerate(lines):
        if len(line) != width:
            raise MapError(f"Line {row + 1} has length {len(line)}, expected {width}.")

        for col, char in enumerate(line):
            pos = Pos(row, col)
            if char == "#":
                walls.add(pos)
            elif char == "-":
                pass
            elif char == "@":
                if car is not None:
                    raise MapError("Map has more than one car.")
                car = pos
            elif char == "$":
                boxes.add(Box("", pos))
            elif char == ".":
                targets.add(pos)
            elif char == "*":
                boxes.add(Box("", pos))
                targets.add(pos)
            elif char == "+":
                if car is not None:
                    raise MapError("Map has more than one car.")
                car = pos
                targets.add(pos)
            elif "a" <= char <= "z":
                if any(box.label == char for box in boxes):
                    raise MapError(f"Duplicate labeled box {char!r}.")
                boxes.add(Box(char, pos))
            elif "A" <= char <= "Z":
                label = char.lower()
                if label in labeled_targets:
                    raise MapError(f"Duplicate labeled target {char!r}.")
                labeled_targets[label] = pos
            else:
                raise MapError(f"Invalid symbol {char!r} at row {row + 1}, col {col + 1}.")

    if car is None:
        raise MapError("Map must contain one car '@'.")
    if not boxes:
        raise MapError("Map must contain at least one box '$'.")
    if not targets and not labeled_targets:
        raise MapError("Map must contain at least one target '.'.")
    unlabeled_boxes = [box for box in boxes if not box.label]
    if unlabeled_boxes and not targets:
        raise MapError("Unlabeled boxes '$' need at least one unlabeled target '.'.")

    box_labels = {box.label for box in boxes if box.label}
    target_labels = set(labeled_targets)
    missing_targets = box_labels - target_labels
    missing_boxes = target_labels - box_labels
    if missing_targets:
        missing = ", ".join(sorted(missing_targets))
        raise MapError(f"Labeled boxes missing targets: {missing}.")
    if missing_boxes:
        missing = ", ".join(sorted(missing_boxes))
        raise MapError(f"Labeled targets missing boxes: {missing}.")

    return SokobanMap(
        walls=frozenset(walls),
        targets=frozenset(targets),
        labeled_targets=labeled_targets,
        start=State(car=car, boxes=frozenset(boxes)),
        width=width,
        height=height,
    )


def is_solved(state: State, game_map: SokobanMap) -> bool:
    for box in state.boxes:
        if not is_box_on_its_target(box, game_map):
            return False
    return True


def is_box_on_its_target(box: Box, game_map: SokobanMap) -> bool:
    if box.label:
        return game_map.labeled_targets.get(box.label) == box.pos
    return box.pos in game_map.targets


def in_bounds(pos: Pos, game_map: SokobanMap) -> bool:
    return 0 <= pos.row < game_map.height and 0 <= pos.col < game_map.width


def is_blocked_cell(pos: Pos, game_map: SokobanMap) -> bool:
    return not in_bounds(pos, game_map) or pos in game_map.walls


def is_free(pos: Pos, state: State, game_map: SokobanMap) -> bool:
    return in_bounds(pos, game_map) and pos not in game_map.walls and box_at(pos, state) is None


def is_deadlocked(state: State, game_map: SokobanMap) -> bool:
    for box in state.boxes:
        if is_box_on_its_target(box, game_map):
            continue

        up = is_blocked_cell(box.pos.step("U"), game_map)
        down = is_blocked_cell(box.pos.step("D"), game_map)
        left = is_blocked_cell(box.pos.step("L"), game_map)
        right = is_blocked_cell(box.pos.step("R"), game_map)

        if (up or down) and (left or right):
            return True

    return False


def box_at(pos: Pos, state: State) -> Box | None:
    for box in state.boxes:
        if box.pos == pos:
            return box
    return None


def neighbors(state: State, game_map: SokobanMap) -> Iterable[tuple[str, State]]:
    for direction in DIRECTIONS:
        next_car = state.car.step(direction)
        if next_car in game_map.walls or not in_bounds(next_car, game_map):
            continue

        next_box = box_at(next_car, state)
        if next_box is None:
            yield f"move {direction}", State(car=next_car, boxes=state.boxes)
            continue

        pushed_box = next_car.step(direction)
        if not is_free(pushed_box, state, game_map):
            continue

        new_boxes = set(state.boxes)
        new_boxes.remove(next_box)
        new_boxes.add(Box(next_box.label, pushed_box))
        yield f"push {direction}", State(car=next_car, boxes=frozenset(new_boxes))


def solve(game_map: SokobanMap, max_states: int = 100_000, algorithm: str = "bfs") -> list[Step] | None:
    if algorithm == "bfs":
        return solve_bfs(game_map, max_states=max_states)
    if algorithm == "astar":
        return solve_astar(game_map, max_states=max_states)
    raise ValueError(f"Unknown algorithm: {algorithm}")


def solve_bfs(game_map: SokobanMap, max_states: int = 100_000) -> list[Step] | None:
    queue: deque[State] = deque([game_map.start])
    visited: set[State] = {game_map.start}
    parent: dict[State, tuple[State, Step]] = {}

    while queue:
        state = queue.popleft()
        if is_solved(state, game_map):
            return reconstruct_path(state, parent)

        if len(visited) > max_states:
            raise RuntimeError(f"Search stopped after {max_states} states.")

        for action, next_state in neighbors(state, game_map):
            if next_state in visited:
                continue
            if is_deadlocked(next_state, game_map):
                continue
            visited.add(next_state)
            kind, direction = action.split()
            parent[next_state] = (
                state,
                Step(kind=kind, direction=direction, before=state, after=next_state),
            )
            queue.append(next_state)

    return None


def solve_astar(game_map: SokobanMap, max_states: int = 100_000) -> list[Step] | None:
    counter = 0
    start = game_map.start
    open_heap: list[tuple[int, int, int, State]] = [(heuristic(start, game_map), 0, counter, start)]
    best_cost: dict[State, int] = {start: 0}
    parent: dict[State, tuple[State, Step]] = {}

    while open_heap:
        _, cost, _, state = heapq.heappop(open_heap)
        if cost != best_cost[state]:
            continue
        if is_solved(state, game_map):
            return reconstruct_path(state, parent)

        if len(best_cost) > max_states:
            raise RuntimeError(f"Search stopped after {max_states} states.")

        for action, next_state in neighbors(state, game_map):
            if is_deadlocked(next_state, game_map):
                continue

            next_cost = cost + 1
            if next_cost >= best_cost.get(next_state, 1_000_000_000):
                continue

            kind, direction = action.split()
            parent[next_state] = (
                state,
                Step(kind=kind, direction=direction, before=state, after=next_state),
            )
            best_cost[next_state] = next_cost
            counter += 1
            priority = next_cost + heuristic(next_state, game_map)
            heapq.heappush(open_heap, (priority, next_cost, counter, next_state))

    return None


def heuristic(state: State, game_map: SokobanMap) -> int:
    total = 0
    for box in state.boxes:
        if is_box_on_its_target(box, game_map):
            continue
        if box.label:
            target = game_map.labeled_targets[box.label]
            total += manhattan(box.pos, target)
        else:
            total += min(manhattan(box.pos, target) for target in game_map.targets)
    return total


def manhattan(a: Pos, b: Pos) -> int:
    return abs(a.row - b.row) + abs(a.col - b.col)


def reconstruct_path(state: State, parent: dict[State, tuple[State, Step]]) -> list[Step]:
    actions: list[Step] = []
    while state in parent:
        previous_state, step = parent[state]
        actions.append(step)
        state = previous_state
    actions.reverse()
    return actions


def compile_plan(steps: list[Step]) -> list[CarCommand]:
    commands: list[CarCommand] = []
    move_segment_start: Pos | None = None
    move_segment_end: Pos | None = None
    move_segment_direction: str | None = None
    index = 0

    while index < len(steps):
        step = steps[index]

        if step.kind == "move":
            if move_segment_start is None:
                move_segment_start = step.before.car
                move_segment_direction = step.direction
            elif step.direction != move_segment_direction:
                flush_move_segment(commands, move_segment_start, move_segment_end)
                move_segment_start = step.before.car
                move_segment_direction = step.direction
            move_segment_end = step.after.car
            index += 1
            continue

        if step.kind == "push":
            flush_move_segment(commands, move_segment_start, move_segment_end)
            move_segment_start = None
            move_segment_end = None
            move_segment_direction = None

            box_before = pushed_box_before(step)
            commands.append(CarCommand("align_to_box", (box_before, step.direction)))

            push_cells = 1
            after_push = step.after
            index += 1
            while index < len(steps):
                next_step = steps[index]
                if next_step.kind != "push" or next_step.direction != step.direction:
                    break
                push_cells += 1
                index += 1

            commands.append(CarCommand("push_box", (step.direction, push_cells)))
            continue

        raise ValueError(f"Unknown step kind: {step.kind}")

    flush_move_segment(commands, move_segment_start, move_segment_end)
    return commands


def replay_commands(game_map: SokobanMap, commands: list[CarCommand]) -> State:
    state = game_map.start
    aligned_box: Pos | None = None
    aligned_direction: str | None = None

    for command in commands:
        if command.name == "move_to":
            (target,) = command.args
            if not isinstance(target, Pos):
                raise ReplayError("move_to expects a Pos target.")
            state = replay_move_to(state, target, game_map)
            aligned_box = None
            aligned_direction = None
        elif command.name == "align_to_box":
            box_pos, direction = command.args
            if not isinstance(box_pos, Pos) or not isinstance(direction, str):
                raise ReplayError("align_to_box expects a Pos and direction.")
            validate_alignment(state, box_pos, direction)
            aligned_box = box_pos
            aligned_direction = direction
        elif command.name == "push_box":
            direction, cells = command.args
            if not isinstance(direction, str) or not isinstance(cells, int):
                raise ReplayError("push_box expects a direction and cell count.")
            if aligned_direction != direction or aligned_box is None:
                raise ReplayError("push_box must follow a matching align_to_box command.")
            state = replay_push_box(state, aligned_box, direction, cells, game_map)
            aligned_box = None
            aligned_direction = None
        else:
            raise ReplayError(f"Unknown command: {command.name}")

    return state


def replay_move_to(state: State, target: Pos, game_map: SokobanMap) -> State:
    if target == state.car:
        return state
    if target.row != state.car.row and target.col != state.car.col:
        raise ReplayError("move_to currently supports one straight grid segment.")

    direction = direction_between(state.car, target)
    car = state.car
    while car != target:
        car = car.step(direction)
        if not is_free(car, state, game_map):
            raise ReplayError(f"move_to path blocked at row={car.row}, col={car.col}.")

    return State(car=target, boxes=state.boxes)


def replay_push_box(state: State, box_pos: Pos, direction: str, cells: int, game_map: SokobanMap) -> State:
    if cells <= 0:
        raise ReplayError("push_box cell count must be positive.")
    validate_alignment(state, box_pos, direction)

    current_box = box_at(box_pos, state)
    if current_box is None:
        raise ReplayError("push_box target box is missing.")

    car = state.car
    boxes = set(state.boxes)
    boxes.remove(current_box)
    box = current_box

    for _ in range(cells):
        next_box_pos = box.pos.step(direction)
        interim_state = State(car=car, boxes=frozenset(boxes))
        if not is_free(next_box_pos, interim_state, game_map):
            raise ReplayError(f"push_box blocked at row={next_box_pos.row}, col={next_box_pos.col}.")
        car = box.pos
        box = Box(box.label, next_box_pos)

    boxes.add(box)
    return State(car=car, boxes=frozenset(boxes))


def validate_alignment(state: State, box_pos: Pos, direction: str) -> None:
    if direction not in DIRECTIONS:
        raise ReplayError(f"Invalid direction: {direction}")
    if box_at(box_pos, state) is None:
        raise ReplayError(f"No box at row={box_pos.row}, col={box_pos.col}.")
    expected_car = opposite_pos(box_pos, direction)
    if state.car != expected_car:
        raise ReplayError(
            "Car is not aligned behind box: "
            f"car=({state.car.row},{state.car.col}), "
            f"expected=({expected_car.row},{expected_car.col})."
        )


def opposite_pos(pos: Pos, direction: str) -> Pos:
    dr, dc = DIRECTIONS[direction]
    return Pos(pos.row - dr, pos.col - dc)


def direction_between(start: Pos, end: Pos) -> str:
    if start.row == end.row:
        if end.col > start.col:
            return "R"
        if end.col < start.col:
            return "L"
    if start.col == end.col:
        if end.row > start.row:
            return "D"
        if end.row < start.row:
            return "U"
    raise ReplayError("Positions are not aligned on one grid axis.")


def command_to_dict(command: CarCommand) -> dict[str, object]:
    payload: dict[str, object] = {"command": command.name}
    if command.name == "move_to":
        (target,) = command.args
        payload["target"] = pos_to_dict(target)
    elif command.name == "align_to_box":
        box_pos, direction = command.args
        payload["box"] = pos_to_dict(box_pos)
        payload["direction"] = direction
    elif command.name == "push_box":
        direction, cells = command.args
        payload["direction"] = direction
        payload["cells"] = cells
    else:
        payload["args"] = list(command.args)
    return payload


def commands_to_json(commands: list[CarCommand]) -> str:
    return json.dumps([command_to_dict(command) for command in commands], indent=2)


def pos_to_dict(pos: object) -> dict[str, int]:
    if not isinstance(pos, Pos):
        raise TypeError("Expected Pos.")
    return {"row": pos.row, "col": pos.col}


def flush_move_segment(commands: list[CarCommand], start: Pos | None, end: Pos | None) -> None:
    if start is None or end is None or start == end:
        return
    commands.append(CarCommand("move_to", (end,)))


def pushed_box_before(step: Step) -> Pos:
    moved_boxes = step.before.boxes - step.after.boxes
    if len(moved_boxes) != 1:
        raise ValueError("Push step must move exactly one box.")
    return next(iter(moved_boxes)).pos


def format_command_arg(arg: object) -> str:
    if isinstance(arg, Pos):
        return f"row={arg.row}, col={arg.col}"
    if isinstance(arg, str):
        return repr(arg)
    return str(arg)


def render(game_map: SokobanMap, state: State | None = None) -> str:
    state = state or game_map.start
    rows: list[str] = []
    boxes_by_pos = {box.pos: box for box in state.boxes}
    labeled_targets_by_pos = {pos: label for label, pos in game_map.labeled_targets.items()}
    target_positions = game_map.targets | frozenset(labeled_targets_by_pos)

    for row in range(game_map.height):
        chars: list[str] = []
        for col in range(game_map.width):
            pos = Pos(row, col)
            box = boxes_by_pos.get(pos)
            if pos == state.car and pos in target_positions:
                chars.append("+")
            elif pos == state.car:
                chars.append("@")
            elif box is not None and not box.label and pos in game_map.targets:
                chars.append("*")
            elif box is not None:
                chars.append(box.label or "$")
            elif pos in game_map.walls:
                chars.append("#")
            elif pos in labeled_targets_by_pos:
                chars.append(labeled_targets_by_pos[pos].upper())
            elif pos in game_map.targets:
                chars.append(".")
            else:
                chars.append("-")
        rows.append("".join(chars))

    return "\n".join(rows)


def load_map(path: str | None) -> str:
    if path is None:
        return DEFAULT_MAP
    return Path(path).read_text(encoding="utf-8")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Minimal text-map Sokoban planner for AI vision car training.",
        epilog=TILE_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("map_file", nargs="?", help="Optional UTF-8 text file containing a 16x12 map.")
    parser.add_argument("--max-states", type=int, default=100_000, help="Search limit. Default: 100000.")
    parser.add_argument("--algorithm", choices=["bfs", "astar"], default="bfs", help="Solver algorithm.")
    parser.add_argument("--json", action="store_true", help="Print compiled car commands as JSON.")
    args = parser.parse_args()

    try:
        game_map = parse_map(load_map(args.map_file))
        plan = solve(game_map, max_states=args.max_states, algorithm=args.algorithm)
    except (MapError, RuntimeError, ValueError, ReplayError) as exc:
        print(f"error: {exc}")
        return 1

    if plan is None:
        print("No solution found.")
        return 2

    commands = compile_plan(plan)
    replay_state = replay_commands(game_map, commands)
    replay_ok = is_solved(replay_state, game_map)

    if args.json:
        print(commands_to_json(commands))
        return 0 if replay_ok else 3

    print("Initial map:")
    print(render(game_map))
    print()

    print(f"Grid solution found by {args.algorithm}: {len(plan)} steps")
    for index, step in enumerate(plan, start=1):
        print(f"{index:03d}: {step.kind} {step.direction}")

    print()
    print(f"Compiled car commands: {len(commands)} commands")
    for index, command in enumerate(commands, start=1):
        print(f"{index:03d}: {command.format()}")
    print()
    print(f"Replay validation: {'PASS' if replay_ok else 'FAIL'}")

    return 0 if replay_ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
