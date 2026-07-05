from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from command_consumer import CommandError, execute_plan, load_commands


CONTROL_ROOT = Path(__file__).resolve().parent
CASE_DIR = CONTROL_ROOT / "tests" / "consumer_cases"


@dataclass(frozen=True)
class ConsumerCase:
    path: Path
    should_pass: bool
    reason: str


CASES = [
    ConsumerCase(CASE_DIR / "valid_plan.json", True, "valid plan should execute stubs"),
    ConsumerCase(CASE_DIR / "non_json.txt", False, "non-JSON input must be rejected"),
    ConsumerCase(CASE_DIR / "missing_command.json", False, "missing command field must be rejected"),
    ConsumerCase(CASE_DIR / "bad_direction.json", False, "invalid direction must be rejected"),
    ConsumerCase(CASE_DIR / "out_of_bounds.json", False, "out-of-bounds grid position must be rejected"),
    ConsumerCase(CASE_DIR / "zero_cells.json", False, "push_box cells must be positive"),
    ConsumerCase(CASE_DIR / "not_a_list.json", False, "top-level JSON must be a list"),
]


def run_case(case: ConsumerCase) -> bool:
    try:
        commands = load_commands(case.path)
        exit_code = execute_plan(commands)
        passed = exit_code == 0
        detail = f"exit_code={exit_code}"
    except CommandError as exc:
        passed = False
        detail = str(exc)

    ok = passed == case.should_pass
    status = "PASS" if ok else "FAIL"
    expectation = "should_pass" if case.should_pass else "should_fail"
    print(f"[{status}] {case.path.name}: {expectation}, observed={'pass' if passed else 'fail'} ({detail})")
    if not ok:
        print(f"       reason: {case.reason}")
    return ok


def main() -> int:
    passed = 0
    for case in CASES:
        if run_case(case):
            passed += 1

    failed = len(CASES) - passed
    print()
    print(f"Summary: passed={passed}, failed={failed}, total={len(CASES)}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
