#!/usr/bin/env python3
"""Build or send a sample OpenART global-map UART frame."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROWS = 12
COLS = 16
CMD_MAP = 0x02


def load_map(path: Path | None) -> list[str]:
    if path is None:
        rows = [
            "################",
            "#--------------#",
            "#---A------B---#",
            "#--------------#",
            "#-----@--------#",
            "#--------------#",
            "#---a------b---#",
            "#--------------#",
            "#--------------#",
            "#--------------#",
            "#--------------#",
            "################",
        ]
    else:
        rows = [line.rstrip("\n") for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    if len(rows) != ROWS:
        raise ValueError(f"map must have {ROWS} rows, got {len(rows)}")
    for i, row in enumerate(rows):
        if len(row) != COLS:
            raise ValueError(f"row {i} must have {COLS} columns, got {len(row)}")
        if any(ord(ch) > 0x7F for ch in row):
            raise ValueError(f"row {i} contains non-ASCII characters")
    return rows


def build_frame(rows: list[str], direction: str, col: int, row: int) -> bytes:
    if len(direction) != 1 or ord(direction) > 0x7F:
        raise ValueError("direction must be one ASCII character")
    if not (0 <= col < COLS):
        raise ValueError(f"col must be 0..{COLS - 1}")
    if not (0 <= row < ROWS):
        raise ValueError(f"row must be 0..{ROWS - 1}")

    payload = bytearray()
    for line in rows:
        payload.extend(line.encode("ascii"))
    payload.append(ord(direction))
    payload.append(col)
    payload.append(row)

    checksum = (CMD_MAP + len(payload) + sum(payload)) & 0xFF
    return bytes([0x5A, 0xA5, CMD_MAP, len(payload)]) + bytes(payload) + bytes([checksum, 0xED])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", type=Path, help="16x12 ASCII map text file")
    parser.add_argument("--dir", default="U", help="car direction character")
    parser.add_argument("--col", type=int, default=5, help="car column")
    parser.add_argument("--row", type=int, default=4, help="car row")
    parser.add_argument("--port", help="optional serial port connected to RT1064 UART1")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--hex", action="store_true", help="print frame as hex text")
    args = parser.parse_args()

    frame = build_frame(load_map(args.map), args.dir, args.col, args.row)

    if args.port:
        try:
            import serial
        except ImportError as exc:
            raise SystemExit("pyserial is required when --port is used") from exc
        with serial.Serial(args.port, args.baud, timeout=1) as ser:
            ser.write(frame)
            ser.flush()

    if args.hex or not args.port:
        print(frame.hex(" "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
