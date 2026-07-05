from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vehicle_stub import CommandResult, VehicleController


VALID_DIRECTIONS = {"U", "D", "L", "R"}


class CommandError(ValueError):
    pass


def load_commands(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(read_json_text(path))
    except json.JSONDecodeError as exc:
        raise CommandError(f"Invalid JSON: {exc}") from exc

    if not isinstance(data, list):
        raise CommandError("Plan JSON must be a list of commands.")

    return [validate_command(index + 1, item) for index, item in enumerate(data)]


def read_json_text(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "utf-16"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise CommandError("Could not decode JSON file as UTF-8 or UTF-16.")


def validate_command(index: int, item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise CommandError(f"Command {index} must be an object.")

    command = item.get("command")
    if command == "move_to":
        target = validate_pos(index, item.get("target"), "target")
        return {"command": command, "target": target}

    if command == "align_to_box":
        box = validate_pos(index, item.get("box"), "box")
        direction = validate_direction(index, item.get("direction"))
        return {"command": command, "box": box, "direction": direction}

    if command == "push_box":
        direction = validate_direction(index, item.get("direction"))
        cells = item.get("cells")
        if not isinstance(cells, int) or cells <= 0:
            raise CommandError(f"Command {index} push_box.cells must be a positive integer.")
        return {"command": command, "direction": direction, "cells": cells}

    raise CommandError(f"Command {index} has unknown command type: {command!r}.")


def validate_pos(index: int, value: Any, field_name: str) -> dict[str, int]:
    if not isinstance(value, dict):
        raise CommandError(f"Command {index} {field_name} must be an object.")

    row = value.get("row")
    col = value.get("col")
    if not isinstance(row, int) or not isinstance(col, int):
        raise CommandError(f"Command {index} {field_name}.row and {field_name}.col must be integers.")
    if not 0 <= row <= 11 or not 0 <= col <= 15:
        raise CommandError(f"Command {index} {field_name} is outside 16x12 grid.")

    return {"row": row, "col": col}


def validate_direction(index: int, value: Any) -> str:
    if value not in VALID_DIRECTIONS:
        raise CommandError(f"Command {index} direction must be one of U, D, L, R.")
    return value


def execute_plan(commands: list[dict[str, Any]], controller: VehicleController | None = None) -> int:
    controller = controller or VehicleController()
    for index, command in enumerate(commands, start=1):
        result = execute_command(command, controller)
        print(format_log_line(index, command, result))
        if not result.ok:
            return 2
    return 0


def execute_command(command: dict[str, Any], controller: VehicleController) -> CommandResult:
    name = command["command"]
    if name == "move_to":
        return controller.move_to(command["target"]["row"], command["target"]["col"])
    if name == "align_to_box":
        return controller.align_to_box(command["box"]["row"], command["box"]["col"], command["direction"])
    if name == "push_box":
        return controller.push_box(command["direction"], command["cells"])
    return CommandResult("ERR_UNKNOWN", f"Unknown command {name!r}.")


def format_log_line(index: int, command: dict[str, Any], result: CommandResult) -> str:
    name = command["command"]
    if name == "move_to":
        args = f"row={command['target']['row']} col={command['target']['col']}"
    elif name == "align_to_box":
        args = f"row={command['box']['row']} col={command['box']['col']} direction={command['direction']}"
    elif name == "push_box":
        args = f"direction={command['direction']} cells={command['cells']}"
    else:
        args = ""

    suffix = f" {result.message}" if result.message else ""
    return f"{index:03d} {name} {args} -> {result.code}{suffix}"


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Consume planner JSON commands and execute vehicle stubs.")
    parser.add_argument("plan_json", nargs="?", help="Path to planner JSON output.")
    parser.add_argument("--serial-port", help="Send commands to an RT1064 over this COM port.")
    parser.add_argument("--baudrate", type=int, default=115200, help="Serial baudrate. Default: 115200.")
    parser.add_argument("--serial-timeout", type=float, default=5.0, help="Seconds to wait for each serial ACK.")
    parser.add_argument("--list-serial-ports", action="store_true", help="List detected serial ports and exit.")
    args = parser.parse_args()

    if args.list_serial_ports:
        from vehicle_serial import list_serial_ports

        ports = list_serial_ports()
        if not ports:
            print("No serial ports detected.")
            return 1
        for port in ports:
            print(port)
        return 0

    if args.plan_json is None:
        parser.error("plan_json is required unless --list-serial-ports is used.")

    try:
        commands = load_commands(Path(args.plan_json))
    except CommandError as exc:
        print(f"error: {exc}")
        return 1

    controller = None
    try:
        if args.serial_port:
            from vehicle_serial import SerialConfig, SerialVehicleController

            controller = SerialVehicleController(
                SerialConfig(
                    port=args.serial_port,
                    baudrate=args.baudrate,
                    ack_timeout_s=args.serial_timeout,
                )
            )
        return execute_plan(commands, controller)
    finally:
        if controller is not None:
            controller.close()


if __name__ == "__main__":
    raise SystemExit(main())
