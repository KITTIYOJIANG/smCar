# Vehicle Command Specification

This document defines the first real-car interface for the AI vision Sokoban planner.
The goal is to make the planner output executable by the chassis team without guessing.

## Scope

The planner exports three command types:

- `move_to`
- `align_to_box`
- `push_box`

The vehicle firmware or upper-control layer should execute these commands in order.
After each command, the controller should return success or a failure code.

## Coordinate System

The planner uses a 16 x 12 grid:

- `row`: 0 to 11, increasing downward.
- `col`: 0 to 15, increasing rightward.
- One grid cell corresponds to one virtual map tile.
- Real-world cell size must be measured from the official game display or field calibration.

Recommended first calibration variables:

```text
CELL_SIZE_MM = TBD
GRID_ORIGIN_X_MM = TBD
GRID_ORIGIN_Y_MM = TBD
ROW_AXIS_SIGN = TBD
COL_AXIS_SIGN = TBD
```

Coordinate conversion:

```text
x_mm = GRID_ORIGIN_X_MM + col * CELL_SIZE_MM * COL_AXIS_SIGN
y_mm = GRID_ORIGIN_Y_MM + row * CELL_SIZE_MM * ROW_AXIS_SIGN
```

Do not hard-code `CELL_SIZE_MM` until the real screen/field scale is measured.

## Direction Convention

Directions use planner grid direction:

| Direction | Grid Meaning | Vehicle Meaning |
|---|---|---|
| `U` | row - 1 | move toward smaller row |
| `D` | row + 1 | move toward larger row |
| `L` | col - 1 | move toward smaller col |
| `R` | col + 1 | move toward larger col |

The vehicle layer must convert this into chassis-frame velocity based on current pose.

## JSON Format

### `move_to`

Move the car center to the target grid cell without pushing any box.

```json
{
  "command": "move_to",
  "target": {
    "row": 2,
    "col": 5
  }
}
```

### `align_to_box`

Move or rotate the car so it is directly behind the box in the push direction.

```json
{
  "command": "align_to_box",
  "box": {
    "row": 2,
    "col": 6
  },
  "direction": "R"
}
```

For `direction = "R"`, the car should be at the cell immediately left of the box.

### `push_box`

Push the currently aligned box for a fixed number of grid cells.

```json
{
  "command": "push_box",
  "direction": "R",
  "cells": 3
}
```

`push_box` must only run after a matching `align_to_box`.

## First-Version Control Parameters

These are conservative starting values. Tune them on the real car.

| Parameter | Initial Value | Meaning |
|---|---:|---|
| `MOVE_SPEED_MM_S` | 150 | Normal translation speed |
| `ALIGN_SPEED_MM_S` | 60 | Slow positioning speed near box |
| `PUSH_SPEED_MM_S` | 50 | Low push speed to avoid box deflection |
| `ROTATE_SPEED_DEG_S` | 45 | Rotation speed during alignment |
| `POSITION_TOLERANCE_MM` | 15 | Position error accepted for `move_to` |
| `ALIGN_POSITION_TOLERANCE_MM` | 8 | Position error accepted before pushing |
| `ANGLE_TOLERANCE_DEG` | 3 | Heading error accepted before pushing |
| `PUSH_EXTRA_MM` | 10 | Extra push distance to ensure box crosses cell boundary |
| `COMMAND_TIMEOUT_MS` | 5000 | Default timeout per command |
| `MAX_RETRY_COUNT` | 2 | Retry count before returning failure |

These values are intentionally slow. First make it reliable, then make it fast.

## Command Completion Rules

### `move_to`

Success conditions:

- Car pose is within `POSITION_TOLERANCE_MM` of target.
- No box is contacted during the move.
- Global/local localization remains valid.

Failure conditions:

- Timeout.
- Target cell is blocked.
- Localization is lost.
- Car pose error grows instead of shrinking for a sustained period.

### `align_to_box`

Success conditions:

- The detected box is still at the requested grid cell.
- Car is behind the box along the requested direction.
- Position error is within `ALIGN_POSITION_TOLERANCE_MM`.
- Heading error is within `ANGLE_TOLERANCE_DEG`.

Failure conditions:

- Box is missing or moved.
- Car cannot reach the required alignment cell.
- Heading cannot be stabilized.
- Localization is lost.

### `push_box`

Success conditions:

- Box moves by the requested number of grid cells.
- Car remains behind the box.
- Box does not hit a wall or another box.
- Final box grid cell matches expected result.

Failure conditions:

- Box does not move after push starts.
- Box deviates laterally.
- Box hits an obstacle.
- Car loses alignment.
- Localization is lost.

## Failure Codes

Use these failure codes in logs and tests:

| Code | Meaning |
|---|---|
| `OK` | Command succeeded |
| `ERR_TIMEOUT` | Command exceeded timeout |
| `ERR_LOCALIZATION_LOST` | Car or field pose is unavailable |
| `ERR_TARGET_BLOCKED` | Target cell or path is blocked |
| `ERR_BOX_MISSING` | Expected box is not detected |
| `ERR_ALIGN_FAILED` | Car cannot align behind box |
| `ERR_PUSH_STALLED` | Box does not move during push |
| `ERR_PUSH_DEVIATED` | Box moved away from expected line |
| `ERR_COLLISION_RISK` | Obstacle or wall too close |
| `ERR_UNKNOWN` | Unexpected failure |

## Runtime Loop

Recommended execution loop:

```text
for command in plan:
    refresh localization
    execute command
    if command fails:
        stop
        retry command up to MAX_RETRY_COUNT
    if still fails:
        request new map observation and replan
```

Do not continue blindly after a failed push. Re-observe and replan.

## Serial Transport

The first PC-to-RT1064 transport is an ASCII line protocol over UART.

Default debug UART:

```text
UART_1, 115200 baud, TX B12, RX B13
```

Wireless UART option:

```text
UART_8, 115200 baud, TX D16, RX D17
```

Request frames:

```text
SMCAR,<seq>,MOVE_TO,<row>,<col>
SMCAR,<seq>,ALIGN_TO_BOX,<row>,<col>,<direction>
SMCAR,<seq>,PUSH_BOX,<direction>,<cells>
```

Response frames:

```text
SMCAR,<seq>,OK,<message>
SMCAR,<seq>,ERR,<failure_code>,<message>
```

`seq` is a positive command sequence number. The PC side ignores stale responses with a mismatched sequence number.

Implementation files:

```text
vehicle_serial.py
firmware/rt1064_serial_receiver_reference.c
docs/rt1064_serial_protocol.md
```

## Team Responsibilities

| Person | Responsibility |
|---|---|
| Xuan | Planner output, JSON format, command semantics, replan strategy |
| Song | Chassis execution, speed control, alignment, mechanical repeatability |
| Yang | Test maps, run logs, video recording, failure classification |

## Real-Car Test Checklist

Use this checklist before connecting full autonomous planning.

| Test ID | Test | Expected Result | Owner |
|---|---|---|---|
| T01 | `move_to` one cell right | Stops within tolerance | Song |
| T02 | `move_to` three cells straight | No oscillation or drift | Song |
| T03 | `move_to` L-shaped path from two commands | Both segments complete | You + Song |
| T04 | `align_to_box` from left side | Car stops behind box | Song |
| T05 | `push_box("R", 1)` | Box moves one cell right | Song |
| T06 | `push_box("R", 3)` | Box moves three cells without large lateral drift | Song |
| T07 | Box missing during `align_to_box` | Returns `ERR_BOX_MISSING` | Yang |
| T08 | Block target cell | Returns `ERR_TARGET_BLOCKED` | Yang |
| T09 | Full JSON plan on simple map | Final box reaches target | You + Yang |
| T10 | Full JSON plan with wall detour | Replay and real test agree | You + Yang |

## Logging Format

Each command execution should produce one log row:

```text
timestamp_ms, command_index, command_name, args, result_code, duration_ms, x_mm, y_mm, theta_deg, note
```

Example:

```text
12345, 3, push_box, R:2, OK, 1840, 520, 310, 0.8, box reached target cell
```

This is enough for Yang to classify failures without reading source code.

## Immediate Next Step

Build a small command consumer that reads planner JSON and calls `VehicleController`.
After that, replace `vehicle_stub.py` with real chassis functions.
