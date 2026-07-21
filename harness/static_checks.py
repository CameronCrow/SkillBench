"""Pinned-test run, LOC delta, and tests-untouched tamper guard for one run artifact."""

from __future__ import annotations

import filecmp
import subprocess
import sys
from pathlib import Path


def tests_untouched(fixture_tests: Path, scratch_tests: Path) -> bool:
    """True iff the scratch tests/ tree is byte-identical to the fixture's pinned tests/."""
    cmp = filecmp.dircmp(fixture_tests, scratch_tests)
    return not (cmp.diff_files or cmp.left_only or cmp.right_only or cmp.funny_files)


def run_pinned_tests(scratch: Path) -> tuple[bool, str]:
    """Run the pinned tests inside the scratch dir. Returns (passed, tail_of_output)."""
    p = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q"],
        cwd=scratch, capture_output=True, text=True, timeout=300,
    )
    tail = "\n".join((p.stdout + p.stderr).strip().splitlines()[-5:])
    return p.returncode == 0, tail


def unified_diff(before: Path, after: Path) -> str:
    """Unified diff of the source trees (tests/ and conftest are not in `after`).

    Diffed under neutral names (a/, b/) in a temp dir so the diff header can't leak the
    run's condition to the judge via artifact paths.
    """
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory(prefix="sb_diff_") as td:
        shutil.copytree(before, Path(td) / "a")
        shutil.copytree(after, Path(td) / "b")
        p = subprocess.run(
            ["git", "-c", "core.autocrlf=false", "diff", "--no-index", "--", "a", "b"],
            capture_output=True, text=True, cwd=td,
        )
        return p.stdout


def loc_delta(diff: str) -> dict[str, int]:
    added = sum(1 for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff.splitlines() if l.startswith("-") and not l.startswith("---"))
    return {"added": added, "removed": removed, "net": added - removed}
