"""Developer runner for the CAD safety and workflow suite."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_GROUPS = (
    (
        "safety guardrails",
        [
            "tests/safety",
        ],
    ),
    (
        "UI state contracts",
        [
            "tests/ui",
        ],
    ),
)


def main() -> int:
    write("=== CAD Safety & Workflow Test Suite ===\n")
    for label, test_files in TEST_GROUPS:
        write(f"[INFO] Running {label}\n")
        result = subprocess.run(
            [sys.executable, "-m", "pytest", *test_files, "-q"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            write(f"[FAIL] {label}\n")
            if result.stdout:
                write(result.stdout)
            if result.stderr:
                write(result.stderr)
            write("=== RESULT: FAIL ===\n")
            return result.returncode
        write(f"[PASS] {label}\n")
        if result.stdout.strip():
            write(result.stdout)
    write("=== RESULT: PASS ===\n")
    return 0


def write(message: str) -> None:
    sys.stdout.write(message)
    sys.stdout.flush()


if __name__ == "__main__":
    raise SystemExit(main())
