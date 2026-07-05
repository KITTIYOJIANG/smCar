#!/usr/bin/env python3
"""
USB CDC serial helper for the RT1064 chassis wheel PI test.

It is intentionally conservative:
- Parameters are sent only at the start of a trial.
- A stop command is sent after every trial or sweep item.
- If feedback ever reports duty above the hard limit, it sends stop.
"""

from __future__ import annotations

import argparse
import re
import statistics
import sys
import time
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # pragma: no cover - depends on the user's PC environment
    serial = None
    list_ports = None


DUTY_HARD_LIMIT_PERCENT = 35.0
DEFAULT_BAUD = 115200
DEFAULT_DURATION = 8.0
DEFAULT_OPEN_WAIT = 1.5
DEFAULT_LINE_STATE = "seekfree"
LINE_STATE_CHOICES = ("seekfree", "none", "dtr", "rts", "both")

FEEDBACK_RE = re.compile(
    r"\b(?P<wheel>LB|RB|RF|LF)\s+"
    r"run=(?P<run>-?\d+)\s+"
    r"target=(?P<target>-?\d+)\s+"
    r"speed=(?P<speed>-?\d+)\s+"
    r"err=(?P<err>-?\d+)\s+"
    r"duty=(?P<duty>[+-]?\d+(?:\.\d+)?)%\s+"
    r"kp=(?P<kp>[+-]?\d+(?:\.\d+)?)\s+"
    r"ki=(?P<ki>[+-]?\d+(?:\.\d+)?)"
    r"(?:\s+integral=(?P<integral>-?\d+))?"
    r".*?\bmax=(?P<max_duty>\d+(?:\.\d+)?)%"
)


@dataclass
class FeedbackSample:
    timestamp: float
    wheel: str
    run: int
    target: int
    speed: int
    err: int
    duty: float
    kp: float
    ki: float
    integral: Optional[int]
    max_duty: float


@dataclass
class TrialStats:
    samples: int
    target: int
    wheel: str
    first_95_time: Optional[float]
    all_min_speed: int
    all_max_speed: int
    steady_samples: int
    steady_avg_speed: float
    steady_min_speed: int
    steady_max_speed: int
    steady_avg_abs_err: float
    steady_max_abs_err: int
    steady_min_duty: float
    steady_max_duty: float
    steady_within_20_percent: float
    score: float


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
        choice = input("Select port number or port name after checking it manually: ").strip()
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
    # SeekFree's USB CDC stack is a little picky about the first control-line change.
    # Pulse carrier once, then leave it low so usb_cdc_write_string() is enabled.
    time.sleep(0.6)
    set_line_state(ser, "none")
    time.sleep(0.35)
    set_line_state(ser, "both")
    time.sleep(0.35)
    set_line_state(ser, "none")
    time.sleep(0.2)


def open_port(
    port: str,
    baud: int,
    timeout: float,
    open_wait: float = DEFAULT_OPEN_WAIT,
    line_state: str = DEFAULT_LINE_STATE,
):
    require_pyserial()
    if line_state not in LINE_STATE_CHOICES:
        raise ValueError(f"line_state must be one of {', '.join(LINE_STATE_CHOICES)}")

    try:
        ser = serial.Serial(port=port, baudrate=baud, timeout=timeout, write_timeout=1.0, rtscts=False, dsrdtr=False)
    except serial.SerialException as exc:
        raise SystemExit(f"Failed to open {port}: {exc}") from exc

    if line_state == "seekfree":
        seekfree_cdc_handshake(ser)
    else:
        set_line_state(ser, line_state)

    time.sleep(open_wait)
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


def parse_feedback_line(line: str, timestamp: float) -> Optional[FeedbackSample]:
    match = FEEDBACK_RE.search(line)
    if not match:
        return None

    integral_text = match.group("integral")
    return FeedbackSample(
        timestamp=timestamp,
        wheel=match.group("wheel"),
        run=int(match.group("run")),
        target=int(match.group("target")),
        speed=int(match.group("speed")),
        err=int(match.group("err")),
        duty=float(match.group("duty")),
        kp=float(match.group("kp")),
        ki=float(match.group("ki")),
        integral=int(integral_text) if integral_text is not None else None,
        max_duty=float(match.group("max_duty")),
    )


def read_line(ser) -> str:
    data = ser.readline()
    if not data:
        return ""
    return data.decode("utf-8", errors="ignore").strip()


def collect_samples(ser, duration: float, echo_lines: bool = False) -> List[FeedbackSample]:
    start = time.monotonic()
    samples: List[FeedbackSample] = []

    while time.monotonic() - start < duration:
        line = read_line(ser)
        now = time.monotonic()
        if not line:
            continue
        if echo_lines:
            print(line)

        sample = parse_feedback_line(line, now - start)
        if sample is None:
            continue

        if abs(sample.duty) > DUTY_HARD_LIMIT_PERCENT + 0.001 or sample.max_duty > DUTY_HARD_LIMIT_PERCENT:
            write_command(ser, "s")
            raise RuntimeError(f"Duty safety stop: line reported duty={sample.duty} max={sample.max_duty}")

        samples.append(sample)

    return samples


def collect_raw_lines(ser, duration: float) -> int:
    start = time.monotonic()
    count = 0

    while time.monotonic() - start < duration:
        line = read_line(ser)
        if not line:
            continue
        count += 1
        print(line)

    return count


def analyze_samples(samples: Sequence[FeedbackSample], steady_fraction: float = 0.4) -> TrialStats:
    if not samples:
        raise ValueError("No feedback samples parsed.")

    steady_count = max(5, int(len(samples) * steady_fraction))
    steady = list(samples[-steady_count:])
    target = steady[-1].target
    wheel = steady[-1].wheel
    abs_target = abs(target)

    first_95_time: Optional[float] = None
    if abs_target > 0:
        threshold = abs_target * 0.95
        for sample in samples:
            if abs(sample.speed) >= threshold and sample.speed * target >= 0:
                first_95_time = sample.timestamp
                break

    speeds = [sample.speed for sample in samples]
    steady_speeds = [sample.speed for sample in steady]
    steady_abs_err = [abs(sample.err) for sample in steady]
    steady_duties = [sample.duty for sample in steady]
    within_20 = sum(1 for sample in steady if abs(sample.err) <= 20) * 100.0 / len(steady)
    jitter = max(steady_speeds) - min(steady_speeds)
    response_penalty = 0.0 if first_95_time is not None else 30.0
    if first_95_time is not None:
        response_penalty = min(first_95_time * 0.5, 10.0)

    score = statistics.mean(steady_abs_err) + jitter * 0.08 + response_penalty

    return TrialStats(
        samples=len(samples),
        target=target,
        wheel=wheel,
        first_95_time=first_95_time,
        all_min_speed=min(speeds),
        all_max_speed=max(speeds),
        steady_samples=len(steady),
        steady_avg_speed=statistics.mean(steady_speeds),
        steady_min_speed=min(steady_speeds),
        steady_max_speed=max(steady_speeds),
        steady_avg_abs_err=statistics.mean(steady_abs_err),
        steady_max_abs_err=max(steady_abs_err),
        steady_min_duty=min(steady_duties),
        steady_max_duty=max(steady_duties),
        steady_within_20_percent=within_20,
        score=score,
    )


def print_stats(stats: TrialStats, prefix: str = "") -> None:
    first_95 = "never" if stats.first_95_time is None else f"{stats.first_95_time:.2f}s"
    verdict = classify_stats(stats)

    print(
        f"{prefix}wheel={stats.wheel} target={stats.target} samples={stats.samples} "
        f"first95={first_95} allSpeed=[{stats.all_min_speed},{stats.all_max_speed}]"
    )
    print(
        f"{prefix}steady n={stats.steady_samples} avg={stats.steady_avg_speed:.1f} "
        f"range=[{stats.steady_min_speed},{stats.steady_max_speed}] "
        f"avgAbsErr={stats.steady_avg_abs_err:.1f} maxAbsErr={stats.steady_max_abs_err} "
        f"duty=[{stats.steady_min_duty:.3f},{stats.steady_max_duty:.3f}] "
        f"within20={stats.steady_within_20_percent:.1f}% score={stats.score:.2f} verdict={verdict}"
    )


def classify_stats(stats: TrialStats) -> str:
    duty_peak = max(abs(stats.steady_min_duty), abs(stats.steady_max_duty))

    if duty_peak > DUTY_HARD_LIMIT_PERCENT:
        return "UNSAFE_STOP"
    if (
        stats.steady_avg_abs_err <= 12.0
        and stats.steady_within_20_percent >= 90.0
        and stats.steady_max_abs_err <= 35
    ):
        return "GOOD_ENOUGH"
    if stats.steady_avg_abs_err <= 20.0 and stats.steady_within_20_percent >= 80.0:
        return "ACCEPTABLE"
    return "NEEDS_REVIEW"


def setup_trial(
    ser,
    wheel: str,
    target: int,
    kp: Optional[float],
    ki: Optional[float],
    ff: Optional[int] = None,
    ffbase: Optional[float] = None,
    ffslope: Optional[float] = None,
    echo: bool = True,
) -> None:
    wheel = wheel.upper()
    if wheel not in {"LB", "RB", "RF", "LF"}:
        raise ValueError("wheel must be one of LB/RB/RF/LF")

    write_command(ser, "s", echo=echo)
    time.sleep(0.2)
    write_command(ser, f"wheel {wheel.lower()}", echo=echo)
    time.sleep(0.1)

    if kp is not None:
        write_command(ser, f"kp {kp:.3f}", echo=echo)
        time.sleep(0.1)
    if ki is not None:
        write_command(ser, f"ki {ki:.3f}", echo=echo)
        time.sleep(0.1)
    if ff is not None:
        write_command(ser, f"ff {1 if ff else 0}", echo=echo)
        time.sleep(0.1)
    if ffbase is not None:
        write_command(ser, f"ffbase {ffbase:.3f}", echo=echo)
        time.sleep(0.1)
    if ffslope is not None:
        write_command(ser, f"ffslope {ffslope:.3f}", echo=echo)
        time.sleep(0.1)

    write_command(ser, "z", echo=echo)
    time.sleep(0.2)
    if target >= 0:
        write_command(ser, f"r {abs(target)}", echo=echo)
    else:
        write_command(ser, f"b {abs(target)}", echo=echo)


def run_trial(
    ser,
    wheel: str,
    target: int,
    kp: Optional[float],
    ki: Optional[float],
    duration: float,
    echo_lines: bool = False,
    ff: Optional[int] = None,
    ffbase: Optional[float] = None,
    ffslope: Optional[float] = None,
) -> TrialStats:
    ser.reset_input_buffer()
    setup_trial(ser, wheel=wheel, target=target, kp=kp, ki=ki, ff=ff, ffbase=ffbase, ffslope=ffslope)
    samples = collect_samples(ser, duration=duration, echo_lines=echo_lines)
    write_command(ser, "s")
    stats = analyze_samples(samples)
    print_stats(stats)
    return stats


def parse_int_list(text: str) -> List[int]:
    return [int(item.strip()) for item in text.split(",") if item.strip()]


def parse_param_pairs(text: str) -> List[Tuple[float, float]]:
    pairs: List[Tuple[float, float]] = []
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            raise argparse.ArgumentTypeError("pairs must look like 0.020:0.002,0.018:0.002")
        kp_text, ki_text = item.split(":", 1)
        pairs.append((float(kp_text), float(ki_text)))
    if not pairs:
        raise argparse.ArgumentTypeError("at least one kp:ki pair is required")
    return pairs


def confirm_or_exit(args, action: str) -> None:
    if getattr(args, "yes", False):
        return
    answer = input(f"{action}. Wheels must be off the ground. Continue? [y/N] ").strip().lower()
    if answer not in {"y", "yes"}:
        raise SystemExit("Cancelled.")


def command_ports(_args) -> None:
    print_ports()


def command_trial(args) -> None:
    confirm_or_exit(args, f"Run one trial on {args.wheel.upper()}, target={args.target}")
    port = choose_port(args.port)
    with open_port(port, args.baud, args.timeout, args.open_wait, line_state_from_args(args)) as ser:
        run_trial(
            ser,
            wheel=args.wheel,
            target=args.target,
            kp=args.kp,
            ki=args.ki,
            duration=args.duration,
            echo_lines=args.echo_lines,
            ff=args.ff,
            ffbase=args.ffbase,
            ffslope=args.ffslope,
        )


def command_sweep(args) -> None:
    targets = parse_int_list(args.targets)
    pairs = parse_param_pairs(args.pairs)
    total = len(targets) * len(pairs)
    confirm_or_exit(args, f"Run sweep on {args.wheel.upper()} with {total} trials")

    port = choose_port(args.port)
    results: List[Tuple[float, int, float, float, TrialStats]] = []

    with open_port(port, args.baud, args.timeout, args.open_wait, line_state_from_args(args)) as ser:
        try:
            for kp, ki in pairs:
                for target in targets:
                    print(f"\n=== trial wheel={args.wheel.upper()} target={target} kp={kp:.3f} ki={ki:.3f} ===")
                    stats = run_trial(
                        ser,
                        wheel=args.wheel,
                        target=target,
                        kp=kp,
                        ki=ki,
                        duration=args.duration,
                        echo_lines=args.echo_lines,
                        ff=args.ff,
                        ffbase=args.ffbase,
                        ffslope=args.ffslope,
                    )
                    results.append((stats.score, target, kp, ki, stats))
                    time.sleep(args.pause)
        finally:
            write_command(ser, "s")

    print("\n=== ranking, lower score is better ===")
    for rank, (_score, target, kp, ki, stats) in enumerate(sorted(results, key=lambda row: row[0]), start=1):
        print(f"{rank}. target={target} kp={kp:.3f} ki={ki:.3f}")
        print_stats(stats, prefix="   ")


def print_monitor_help() -> None:
    print(
        "Local commands:\n"
        "  :help                         show this help\n"
        "  :ports                        list serial ports\n"
        "  :read 8                       read feedback for 8 seconds and summarize\n"
        "  :trial LB 200 0.020 0.002 8   run one controlled trial\n"
        "  :stop                         send s\n"
        "  :reset                        send z\n"
        "  :quit                         exit\n"
        "Board commands are sent directly, for example: wheel lb, kp 0.020, ki 0.002, r 200, s, z\n"
    )


def command_monitor(args) -> None:
    port = choose_port(args.port)
    print(f"Opening {port} at {args.baud}. Close SeekFree Assistant before connecting.")

    with open_port(port, args.baud, args.timeout, args.open_wait, line_state_from_args(args)) as ser:
        print_monitor_help()
        while True:
            try:
                command = input("pid> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                write_command(ser, "s")
                return

            if not command:
                continue
            if not command.startswith(":"):
                write_command(ser, command)
                continue

            parts = command.split()
            local = parts[0].lower()

            try:
                if local in {":q", ":quit", ":exit"}:
                    write_command(ser, "s")
                    return
                if local == ":help":
                    print_monitor_help()
                elif local == ":ports":
                    print_ports()
                elif local == ":stop":
                    write_command(ser, "s")
                elif local == ":reset":
                    write_command(ser, "z")
                elif local == ":read":
                    duration = float(parts[1]) if len(parts) > 1 else DEFAULT_DURATION
                    samples = collect_samples(ser, duration=duration, echo_lines=True)
                    stats = analyze_samples(samples)
                    print_stats(stats)
                elif local == ":trial":
                    if len(parts) != 6:
                        print("Usage: :trial LB 200 0.020 0.002 8")
                        continue
                    run_trial(
                        ser,
                        wheel=parts[1],
                        target=int(parts[2]),
                        kp=float(parts[3]),
                        ki=float(parts[4]),
                        duration=float(parts[5]),
                        echo_lines=args.echo_lines,
                    )
                else:
                    print("Unknown local command. Use :help.")
            except Exception as exc:  # keep the monitor alive after a bad local command
                print(f"Error: {exc}")
                write_command(ser, "s")


def command_raw(args) -> None:
    port = choose_port(args.port)
    print(f"Opening {port} at {args.baud}; raw read for {args.duration:.1f}s.")

    with open_port(port, args.baud, args.timeout, args.open_wait, line_state_from_args(args)) as ser:
        if args.send:
            write_command(ser, args.send)
        count = collect_raw_lines(ser, args.duration)

    print(f"Raw lines received: {count}")


def command_probe(args) -> None:
    port = choose_port(args.port)
    states = ("seekfree", "none", "dtr", "rts", "both")

    for state in states:
        print(f"\n=== probe line_state={state} ===")
        try:
            with open_port(port, args.baud, args.timeout, args.open_wait, state) as ser:
                if args.send:
                    write_command(ser, args.send)
                count = collect_raw_lines(ser, args.duration)
            print(f"Raw lines received with {state}: {count}")
        except Exception as exc:
            print(f"Probe failed with {state}: {exc}")
        time.sleep(0.5)


def line_state_from_args(args) -> str:
    if getattr(args, "no_cdc_handshake", False):
        return "none"
    return args.line_state


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RT1064 USB CDC wheel PI tuning helper.")
    parser.add_argument("--port", help="Serial port, for example COM13. If omitted, choose from a list.")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD, help=f"Baud rate, default {DEFAULT_BAUD}.")
    parser.add_argument("--timeout", type=float, default=0.2, help="Serial read timeout in seconds.")
    parser.add_argument("--open-wait", type=float, default=DEFAULT_OPEN_WAIT, help="Wait after opening the port.")
    parser.add_argument("--line-state", choices=LINE_STATE_CHOICES, default=DEFAULT_LINE_STATE,
                        help="DTR/RTS state after opening. seekfree toggles then leaves both low.")
    parser.add_argument("--no-cdc-handshake", action="store_true",
                        help="Compatibility shortcut for --line-state none.")
    parser.add_argument("--yes", action="store_true", help="Do not ask for the safety confirmation.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    ports_parser = subparsers.add_parser("ports", help="List serial ports.")
    ports_parser.set_defaults(func=command_ports)

    raw_parser = subparsers.add_parser("raw", help="Read raw serial text, optionally after sending one safe command.")
    raw_parser.add_argument("--duration", type=float, default=5.0)
    raw_parser.add_argument("--send", default="status", help="Command to send once before reading; use empty string to only read.")
    raw_parser.set_defaults(func=command_raw)

    probe_parser = subparsers.add_parser("probe", help="Try DTR/RTS line states with a safe status command.")
    probe_parser.add_argument("--duration", type=float, default=2.0)
    probe_parser.add_argument("--send", default="status", help="Command to send once for each state.")
    probe_parser.set_defaults(func=command_probe)

    monitor_parser = subparsers.add_parser("monitor", help="Interactive manual monitor and command sender.")
    monitor_parser.add_argument("--echo-lines", action="store_true", help="Print raw feedback lines during trials.")
    monitor_parser.set_defaults(func=command_monitor)

    trial_parser = subparsers.add_parser("trial", help="Run one controlled wheel trial.")
    trial_parser.add_argument("--wheel", default="LB", choices=["LB", "RB", "RF", "LF", "lb", "rb", "rf", "lf"])
    trial_parser.add_argument("--target", type=int, default=200)
    trial_parser.add_argument("--kp", type=float, default=None, help="Kp to send once before the trial.")
    trial_parser.add_argument("--ki", type=float, default=None, help="Ki to send once before the trial.")
    trial_parser.add_argument("--ff", type=int, choices=[0, 1], default=None, help="Enable or disable feedforward.")
    trial_parser.add_argument("--ffbase", type=float, default=None, help="Feedforward base duty percent.")
    trial_parser.add_argument("--ffslope", type=float, default=None, help="Feedforward slope duty percent per count/100ms.")
    trial_parser.add_argument("--duration", type=float, default=DEFAULT_DURATION)
    trial_parser.add_argument("--echo-lines", action="store_true", help="Print raw feedback lines during collection.")
    trial_parser.set_defaults(func=command_trial)

    sweep_parser = subparsers.add_parser("sweep", help="Run a small bounded kp/ki sweep.")
    sweep_parser.add_argument("--wheel", default="LB", choices=["LB", "RB", "RF", "LF", "lb", "rb", "rf", "lf"])
    sweep_parser.add_argument("--targets", default="100,150,200,300,400", help="Comma-separated targets.")
    sweep_parser.add_argument("--pairs", default="0.020:0.002", help="Comma-separated kp:ki pairs.")
    sweep_parser.add_argument("--ff", type=int, choices=[0, 1], default=None, help="Enable or disable feedforward.")
    sweep_parser.add_argument("--ffbase", type=float, default=None, help="Feedforward base duty percent.")
    sweep_parser.add_argument("--ffslope", type=float, default=None, help="Feedforward slope duty percent per count/100ms.")
    sweep_parser.add_argument("--duration", type=float, default=DEFAULT_DURATION)
    sweep_parser.add_argument("--pause", type=float, default=1.0, help="Pause after each stopped trial.")
    sweep_parser.add_argument("--echo-lines", action="store_true", help="Print raw feedback lines during collection.")
    sweep_parser.set_defaults(func=command_sweep)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
