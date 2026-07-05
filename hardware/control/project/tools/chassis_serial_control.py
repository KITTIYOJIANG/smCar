#!/usr/bin/env python3
"""PC serial controller for the RT1064 chassis firmware in user/src/main.c.

Examples:
    python chassis_serial_control.py ports
    python chassis_serial_control.py --port COM13 status
    python chassis_serial_control.py --port COM13 forward --speed 200 --duration 1.0 --yes
    python chassis_serial_control.py --port COM13 drive --vx 0 --vy 200 --wz 0 --duration 1.0 --yes
    python chassis_serial_control.py --port COM13 turn 90 --read-duration 8 --yes
    python chassis_serial_control.py --port COM13 monitor
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Optional, Sequence

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # pragma: no cover - depends on the user's PC environment
    serial = None
    list_ports = None


DEFAULT_BAUD = 115200
DEFAULT_TIMEOUT = 0.2
DEFAULT_OPEN_WAIT = 1.5
DEFAULT_LINE_STATE = "seekfree"
LINE_STATE_CHOICES = ("seekfree", "none", "dtr", "rts", "both")


def require_pyserial() -> None:
    if serial is None or list_ports is None:
        print("pyserial is not installed. Install it with: python -m pip install pyserial", file=sys.stderr)
        raise SystemExit(2)


def print_ports() -> None:
    require_pyserial()
    ports = list(list_ports.comports())
    if not ports:
        print("No serial ports found.")
        return

    for index, port in enumerate(ports, start=1):
        print(f"{index}: {port.device} | {port.description} | {port.hwid}")


def choose_port(explicit_port: Optional[str]) -> str:
    require_pyserial()
    if explicit_port:
        return explicit_port

    ports = list(list_ports.comports())
    if not ports:
        raise SystemExit("No serial ports found. Check the Type-C cable and close other serial tools.")

    print("Available serial ports:")
    for index, port in enumerate(ports, start=1):
        print(f"  {index}: {port.device} | {port.description}")

    while True:
        choice = input("Select port number or port name: ").strip()
        if not choice:
            continue
        if choice.isdigit():
            index = int(choice)
            if 1 <= index <= len(ports):
                return ports[index - 1].device
        for port in ports:
            if choice.upper() == port.device.upper():
                return port.device
        print("Bad selection. Example: 1 or COM13")


def set_line_state(ser, mode: str) -> None:
    if mode == "none":
        ser.dtr = False
        ser.rts = False
    elif mode == "dtr":
        ser.dtr = True
        ser.rts = False
    elif mode == "rts":
        ser.dtr = False
        ser.rts = True
    elif mode == "both":
        ser.dtr = True
        ser.rts = True
    else:
        raise ValueError(f"bad line state: {mode}")


def seekfree_cdc_handshake(ser) -> None:
    time.sleep(0.6)
    set_line_state(ser, "none")
    time.sleep(0.35)
    set_line_state(ser, "both")
    time.sleep(0.35)
    # This SeekFree CDC driver enables usb_cdc_write_string() after carrier is
    # deactivated once, so leave DTR/RTS low after the initial pulse.
    set_line_state(ser, "none")
    time.sleep(0.2)


def open_port(args):
    require_pyserial()
    port = choose_port(args.port)
    line_state = "none" if args.no_cdc_handshake else args.line_state

    try:
        ser = serial.Serial(
            port=port,
            baudrate=args.baud,
            timeout=args.timeout,
            write_timeout=1.0,
            rtscts=False,
            dsrdtr=False,
        )
    except serial.SerialException as exc:
        raise SystemExit(f"Failed to open {port}: {exc}") from exc

    if line_state == "seekfree":
        seekfree_cdc_handshake(ser)
    else:
        set_line_state(ser, line_state)

    time.sleep(args.open_wait)
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    return ser


def write_command(ser, command: str, echo: bool = True) -> None:
    command = command.strip()
    if not command:
        return
    if echo:
        print(f">> {command}")
    ser.write((command + "\n").encode("ascii", errors="ignore"))
    ser.flush()


def read_line(ser) -> str:
    data = ser.readline()
    if not data:
        return ""
    return data.decode("utf-8", errors="ignore").strip()


def read_for(ser, duration: float, echo: bool = True) -> int:
    if duration <= 0:
        return 0

    start = time.monotonic()
    count = 0
    while time.monotonic() - start < duration:
        line = read_line(ser)
        if not line:
            continue
        count += 1
        if echo:
            print(line)
    return count


def confirm_or_exit(args, action: str) -> None:
    if getattr(args, "yes", False):
        return
    answer = input(f"{action}. Keep the car lifted or in a clear test area. Continue? [y/N] ").strip().lower()
    if answer not in {"y", "yes"}:
        raise SystemExit("Cancelled.")


def command_ports(_args) -> None:
    print_ports()


def command_status(args) -> None:
    with open_port(args) as ser:
        write_command(ser, "status")
        read_for(ser, args.read_duration)


def command_stop(args) -> None:
    with open_port(args) as ser:
        write_command(ser, "s")
        read_for(ser, args.read_duration)


def command_send(args) -> None:
    text = " ".join(args.text).strip()
    if not text:
        raise SystemExit("send needs a board command, for example: send status")

    with open_port(args) as ser:
        write_command(ser, text)
        read_for(ser, args.read_duration)
        if args.stop_after:
            write_command(ser, "s")
            read_for(ser, 0.5)


def run_velocity(args, vx: int, vy: int, wz: int) -> None:
    confirm_or_exit(args, f"Run velocity vx={vx} vy={vy} wz={wz} for {args.duration:.2f}s")
    with open_port(args) as ser:
        try:
            write_command(ser, f"vel {vx} {vy} {wz}")
            read_for(ser, args.duration)
        finally:
            if not args.no_stop:
                write_command(ser, "s")
                read_for(ser, 0.5)


def command_drive(args) -> None:
    run_velocity(args, args.vx, args.vy, args.wz)


def command_forward(args) -> None:
    run_velocity(args, 0, args.speed, 0)


def command_back(args) -> None:
    run_velocity(args, 0, -args.speed, 0)


def command_right(args) -> None:
    run_velocity(args, args.speed, 0, 0)


def command_left(args) -> None:
    run_velocity(args, -args.speed, 0, 0)


def command_spin(args) -> None:
    run_velocity(args, 0, 0, args.wz)


def command_turn(args) -> None:
    confirm_or_exit(args, f"Turn {args.angle} degrees with IMU yaw closed loop")
    with open_port(args) as ser:
        write_command(ser, f"turn {args.angle}")
        read_for(ser, args.read_duration)
        if args.stop_after:
            write_command(ser, "s")
            read_for(ser, 0.5)


def command_imu_cal(args) -> None:
    confirm_or_exit(args, "Calibrate IMU gyro-z while the car is perfectly still")
    with open_port(args) as ser:
        write_command(ser, "imu cal")
        read_for(ser, args.read_duration)


def print_monitor_help() -> None:
    print(
        "Local commands:\n"
        "  :help                show this help\n"
        "  :read 3              read board output for 3 seconds\n"
        "  :stop                send s\n"
        "  :status              send status\n"
        "  :imu                 send imu status\n"
        "  :yaw                 send yaw\n"
        "  :quit                send s and exit\n"
        "Board commands go directly to main.c, for example:\n"
        "  vel 0 200 0\n"
        "  turn 90\n"
        "  imu cal\n"
        "  status\n"
        "  s\n"
    )


def command_monitor(args) -> None:
    port = choose_port(args.port)
    args.port = port
    print(f"Opening {port} at {args.baud}. Close other serial tools before connecting.")

    with open_port(args) as ser:
        print_monitor_help()
        while True:
            try:
                command = input("car> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                write_command(ser, "s")
                return

            if not command:
                continue

            if not command.startswith(":"):
                write_command(ser, command)
                if args.read_after_send > 0:
                    read_for(ser, args.read_after_send)
                continue

            parts = command.split()
            local = parts[0].lower()
            try:
                if local in {":q", ":quit", ":exit"}:
                    write_command(ser, "s")
                    return
                if local == ":help":
                    print_monitor_help()
                elif local == ":read":
                    duration = float(parts[1]) if len(parts) > 1 else 3.0
                    read_for(ser, duration)
                elif local == ":stop":
                    write_command(ser, "s")
                    read_for(ser, 0.5)
                elif local == ":status":
                    write_command(ser, "status")
                    read_for(ser, 1.0)
                elif local == ":imu":
                    write_command(ser, "imu status")
                    read_for(ser, 1.0)
                elif local == ":yaw":
                    write_command(ser, "yaw")
                    read_for(ser, 1.0)
                else:
                    print("Unknown local command. Use :help.")
            except Exception as exc:
                print(f"Error: {exc}")
                write_command(ser, "s")


def add_serial_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--port", help="Serial port, for example COM13. If omitted, choose from a list.")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD, help=f"Baud rate, default {DEFAULT_BAUD}.")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="Serial read timeout in seconds.")
    parser.add_argument("--open-wait", type=float, default=DEFAULT_OPEN_WAIT, help="Wait after opening the port.")
    parser.add_argument(
        "--line-state",
        choices=LINE_STATE_CHOICES,
        default=DEFAULT_LINE_STATE,
        help="DTR/RTS state after opening. seekfree toggles then raises both lines.",
    )
    parser.add_argument("--no-cdc-handshake", action="store_true", help="Compatibility shortcut for --line-state none.")


def add_motion_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--duration", type=float, default=1.0, help="Seconds to run before auto stop.")
    parser.add_argument("--no-stop", action="store_true", help="Do not auto-send s after the timed command.")
    parser.add_argument("--yes", action="store_true", help="Do not ask for the safety confirmation.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RT1064 chassis serial controller.")
    add_serial_args(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    ports_parser = subparsers.add_parser("ports", help="List serial ports.")
    ports_parser.set_defaults(func=command_ports)

    status_parser = subparsers.add_parser("status", help="Send status and read a short response.")
    status_parser.add_argument("--read-duration", type=float, default=1.5)
    status_parser.set_defaults(func=command_status)

    stop_parser = subparsers.add_parser("stop", help="Send immediate stop command s.")
    stop_parser.add_argument("--read-duration", type=float, default=0.8)
    stop_parser.set_defaults(func=command_stop)

    send_parser = subparsers.add_parser("send", help="Send one raw board command.")
    send_parser.add_argument("text", nargs=argparse.REMAINDER, help="Board command text, for example: status")
    send_parser.add_argument("--read-duration", type=float, default=1.0)
    send_parser.add_argument("--stop-after", action="store_true", help="Send s after reading.")
    send_parser.set_defaults(func=command_send)

    drive_parser = subparsers.add_parser("drive", help="Send vel vx vy wz for a bounded time.")
    drive_parser.add_argument("--vx", type=int, default=0, help="Right-positive body velocity, mm/s.")
    drive_parser.add_argument("--vy", type=int, default=0, help="Forward-positive body velocity, mm/s.")
    drive_parser.add_argument("--wz", type=int, default=0, help="CCW-positive yaw velocity, deg/s.")
    add_motion_args(drive_parser)
    drive_parser.set_defaults(func=command_drive)

    for name, help_text, func in (
        ("forward", "Move forward with vel 0 speed 0.", command_forward),
        ("back", "Move backward with vel 0 -speed 0.", command_back),
        ("left", "Strafe left with vel -speed 0 0.", command_left),
        ("right", "Strafe right with vel speed 0 0.", command_right),
    ):
        motion_parser = subparsers.add_parser(name, help=help_text)
        motion_parser.add_argument("--speed", type=int, default=200, help="Speed magnitude in mm/s.")
        add_motion_args(motion_parser)
        motion_parser.set_defaults(func=func)

    spin_parser = subparsers.add_parser("spin", help="Rotate with vel 0 0 wz for a bounded time.")
    spin_parser.add_argument("--wz", type=int, default=45, help="CCW-positive yaw velocity, deg/s.")
    add_motion_args(spin_parser)
    spin_parser.set_defaults(func=command_spin)

    turn_parser = subparsers.add_parser("turn", help="Send turn angle using IMU yaw closed loop.")
    turn_parser.add_argument("angle", type=int, help="Degrees. Positive is left/CCW, negative is right/CW.")
    turn_parser.add_argument("--read-duration", type=float, default=8.0)
    turn_parser.add_argument("--stop-after", action="store_true", help="Send s after reading.")
    turn_parser.add_argument("--yes", action="store_true", help="Do not ask for the safety confirmation.")
    turn_parser.set_defaults(func=command_turn)

    imu_parser = subparsers.add_parser("imu-cal", help="Send imu cal and read calibration output.")
    imu_parser.add_argument("--read-duration", type=float, default=4.0)
    imu_parser.add_argument("--yes", action="store_true", help="Do not ask for the safety confirmation.")
    imu_parser.set_defaults(func=command_imu_cal)

    monitor_parser = subparsers.add_parser("monitor", help="Interactive raw board command monitor.")
    monitor_parser.add_argument("--read-after-send", type=float, default=0.4)
    monitor_parser.set_defaults(func=command_monitor)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
