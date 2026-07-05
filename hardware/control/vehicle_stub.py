from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandResult:
    code: str
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.code == "OK"


class VehicleController:
    """Stub vehicle controller.

    Replace this class with real chassis control code when hardware is ready.
    The command consumer should not need to know whether this is a stub or real car.
    """

    def move_to(self, row: int, col: int) -> CommandResult:
        return CommandResult("OK", f"target row={row} col={col}")

    def align_to_box(self, row: int, col: int, direction: str) -> CommandResult:
        return CommandResult("OK", f"box row={row} col={col} direction={direction}")

    def push_box(self, direction: str, cells: int) -> CommandResult:
        return CommandResult("OK", f"direction={direction} cells={cells}")
