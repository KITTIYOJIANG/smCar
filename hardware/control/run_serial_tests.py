from __future__ import annotations

from vehicle_serial import SerialConfig, SerialVehicleController, build_frame, parse_response


class FakeSerial:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.writes: list[bytes] = []
        self.responses: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        seq = data.decode("ascii").split(",", 2)[1]
        self.responses.append(f"SMCAR,{seq},OK,done\n".encode("ascii"))
        return len(data)

    def flush(self) -> None:
        pass

    def readline(self) -> bytes:
        if self.responses:
            return self.responses.pop(0)
        return b""

    def close(self) -> None:
        self.closed = True


def test_frame_format() -> None:
    assert build_frame(1, "MOVE_TO", 2, 5) == b"SMCAR,1,MOVE_TO,2,5\n"
    assert build_frame(2, "ALIGN_TO_BOX", 2, 6, "R") == b"SMCAR,2,ALIGN_TO_BOX,2,6,R\n"
    assert build_frame(3, "PUSH_BOX", "R", 2) == b"SMCAR,3,PUSH_BOX,R,2\n"


def test_response_parser() -> None:
    ok = parse_response(b"SMCAR,7,OK,reached\n", expected_seq=7)
    assert ok.ok
    assert ok.message == "reached"

    err = parse_response(b"SMCAR,8,ERR,ERR_TIMEOUT,stalled\n", expected_seq=8)
    assert not err.ok
    assert err.code == "ERR_TIMEOUT"
    assert err.message == "stalled"


def test_controller_sequence() -> None:
    opened: list[FakeSerial] = []

    def factory(**kwargs) -> FakeSerial:
        serial = FakeSerial(**kwargs)
        opened.append(serial)
        return serial

    controller = SerialVehicleController(
        SerialConfig(port="COM_TEST", baudrate=115200, ack_timeout_s=0.1),
        serial_factory=factory,
    )
    try:
        assert controller.move_to(2, 5).ok
        assert controller.align_to_box(2, 6, "R").ok
        assert controller.push_box("R", 2).ok
    finally:
        controller.close()

    serial = opened[0]
    assert serial.kwargs["port"] == "COM_TEST"
    assert serial.kwargs["baudrate"] == 115200
    assert serial.writes == [
        b"SMCAR,1,MOVE_TO,2,5\n",
        b"SMCAR,2,ALIGN_TO_BOX,2,6,R\n",
        b"SMCAR,3,PUSH_BOX,R,2\n",
    ]
    assert serial.closed


def main() -> int:
    tests = [
        test_frame_format,
        test_response_parser,
        test_controller_sequence,
    ]

    passed = 0
    for test in tests:
        test()
        passed += 1
        print(f"[PASS] {test.__name__}")

    print()
    print(f"Summary: passed={passed}, failed=0, total={len(tests)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
