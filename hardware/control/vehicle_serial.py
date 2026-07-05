from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Callable, Protocol

from vehicle_stub import CommandResult


class SerialProtocolError(ValueError):
    pass


class SerialLike(Protocol):
    def write(self, data: bytes) -> int | None:
        ...

    def flush(self) -> None:
        ...

    def readline(self) -> bytes:
        ...

    def close(self) -> None:
        ...


@dataclass(frozen=True)
class SerialConfig:
    port: str
    baudrate: int = 115200
    read_timeout_s: float = 0.25
    write_timeout_s: float = 2.0
    ack_timeout_s: float = 5.0


SerialFactory = Callable[..., SerialLike]


def build_frame(seq: int, command: str, *args: object) -> bytes:
    if seq <= 0:
        raise SerialProtocolError("Sequence number must be positive.")
    fields = ["SMCAR", str(seq), command]
    fields.extend(str(arg) for arg in args)
    return (",".join(fields) + "\n").encode("ascii")


def parse_response(line: bytes | str, expected_seq: int | None = None) -> CommandResult:
    if isinstance(line, bytes):
        text = line.decode("ascii", errors="replace").strip()
    else:
        text = line.strip()

    if not text:
        raise SerialProtocolError("Empty serial response.")

    parts = text.split(",", 4)
    if len(parts) < 3 or parts[0] != "SMCAR":
        raise SerialProtocolError(f"Unexpected serial response: {text!r}.")

    try:
        seq = int(parts[1])
    except ValueError as exc:
        raise SerialProtocolError(f"Invalid response sequence: {parts[1]!r}.") from exc

    if expected_seq is not None and seq != expected_seq:
        raise SerialProtocolError(f"Response sequence {seq} does not match request {expected_seq}.")

    status = parts[2]
    if status == "OK":
        return CommandResult("OK", parts[3] if len(parts) >= 4 else "")

    if status == "ERR":
        code = parts[3] if len(parts) >= 4 and parts[3] else "ERR_UNKNOWN"
        message = parts[4] if len(parts) >= 5 else ""
        return CommandResult(code, message)

    raise SerialProtocolError(f"Unknown response status: {status!r}.")


def list_serial_ports() -> list[str]:
    try:
        from serial.tools import list_ports
    except ImportError as exc:
        raise RuntimeError("pyserial is required to list serial ports. Install it with: pip install pyserial") from exc

    ports: list[str] = []
    for port in list_ports.comports():
        if not port.device:
            continue
        description = port.description or "serial port"
        ports.append(f"{port.device} - {description}")
    return ports


class SerialVehicleController:
    def __init__(self, config: SerialConfig, serial_factory: SerialFactory | None = None) -> None:
        self.config = config
        self._seq = 0
        self._serial = self._open_serial(config, serial_factory)

    @staticmethod
    def _open_serial(config: SerialConfig, serial_factory: SerialFactory | None) -> SerialLike:
        if serial_factory is None:
            try:
                import serial
            except ImportError as exc:
                raise RuntimeError("pyserial is required for --serial-port. Install it with: pip install pyserial") from exc
            serial_factory = serial.Serial

        return serial_factory(
            port=config.port,
            baudrate=config.baudrate,
            timeout=config.read_timeout_s,
            write_timeout=config.write_timeout_s,
        )

    def close(self) -> None:
        self._serial.close()

    def move_to(self, row: int, col: int) -> CommandResult:
        return self._send("MOVE_TO", row, col)

    def align_to_box(self, row: int, col: int, direction: str) -> CommandResult:
        return self._send("ALIGN_TO_BOX", row, col, direction)

    def push_box(self, direction: str, cells: int) -> CommandResult:
        return self._send("PUSH_BOX", direction, cells)

    def _send(self, command: str, *args: object) -> CommandResult:
        self._seq += 1
        frame = build_frame(self._seq, command, *args)
        self._serial.write(frame)
        self._serial.flush()

        deadline = monotonic() + self.config.ack_timeout_s
        last_error = ""
        while monotonic() < deadline:
            line = self._serial.readline()
            if not line:
                continue
            try:
                return parse_response(line, expected_seq=self._seq)
            except SerialProtocolError as exc:
                last_error = str(exc)

        detail = f" waiting for {command} ack"
        if last_error:
            detail += f"; last ignored response: {last_error}"
        return CommandResult("ERR_TIMEOUT", detail)
