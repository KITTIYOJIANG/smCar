from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class TestJob:
    name: str
    args: list[str]
    required: bool = True


def run_job(job: TestJob) -> bool:
    print(f"\n=== {job.name} ===", flush=True)
    started = subprocess.run(
        [sys.executable, *job.args],
        cwd=ROOT,
        text=True,
    )
    ok = started.returncode == 0
    status = "PASS" if ok else "FAIL"
    print(f"=== {job.name}: {status} exit_code={started.returncode} ===", flush=True)
    return ok or not job.required


def build_jobs(skip_astar: bool) -> list[TestJob]:
    jobs = [
        TestJob("map fixtures bfs", ["run_map_tests.py"]),
    ]
    if not skip_astar:
        jobs.append(TestJob("map fixtures astar", ["run_map_tests.py", "--algorithm", "astar"]))
    jobs.extend(
        [
            TestJob(
                "official VR maps astar",
                [
                    "run_map_tests.py",
                    "--maps",
                    str(ROOT / "maps" / "official"),
                    "--algorithm",
                    "astar",
                    "--require-solved",
                ],
            ),
            TestJob("command consumer cases", ["run_consumer_tests.py"]),
            TestJob("serial protocol unit tests", ["run_serial_tests.py"]),
        ]
    )
    return jobs


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the SmartCar software regression baseline.")
    parser.add_argument(
        "--skip-astar",
        action="store_true",
        help="Skip the A* map regression pass for faster local checks.",
    )
    args = parser.parse_args()

    jobs = build_jobs(skip_astar=args.skip_astar)
    passed = 0
    failed = 0
    for job in jobs:
        if run_job(job):
            passed += 1
        else:
            failed += 1

    print()
    print(f"Regression summary: passed={passed}, failed={failed}, total={len(jobs)}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
