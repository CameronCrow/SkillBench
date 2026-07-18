"""Static checks: pinned tests, LOC delta, tests-untouched tamper guard.

Library used by harness/run.py after each rep; also runnable standalone to
re-check an existing rep directory:

    python -m harness.static_checks --rep results/<run-id>/<fixture>/<condition>/rep-N \
        --fixture fixtures/<slug>
"""
from __future__ import annotations

import argparse
import filecmp
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from .common import Fixture, load_fixture


def diff_stats(before_dir: Path, after_dir: Path) -> dict:
    """LOC added/removed/net plus the unified diff, before vs after.

    after_dir must not contain tests/ (run.py separates the tests copy out
    before diffing, so the pinned tests never pollute the LOC signature).
    """
    def git_diff(*extra: str) -> subprocess.CompletedProcess:
        # --no-index exits 1 when the trees differ; that is not an error.
        return subprocess.run(
            ["git", "-c", "core.quotepath=false", "diff", "--no-index",
             *extra, str(before_dir), str(after_dir)],
            capture_output=True, text=True)

    added = removed = 0
    for line in git_diff("--numstat").stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            # binary files report "-"; count them as 0 lines
            added += int(parts[0]) if parts[0].isdigit() else 0
            removed += int(parts[1]) if parts[1].isdigit() else 0
    return {"loc_added": added, "loc_removed": removed, "loc_net": added - removed,
            "patch": git_diff().stdout}


def tests_untouched(pinned_tests: Path, run_tests_dir: Path) -> bool:
    """Tamper guard: the run's tests/ must be byte-identical to the pinned copy."""
    def identical(cmp: filecmp.dircmp) -> bool:
        if cmp.left_only or cmp.right_only or cmp.diff_files or cmp.funny_files:
            return False
        return all(identical(sub) for sub in cmp.subdirs.values())
    return identical(filecmp.dircmp(pinned_tests, run_tests_dir))


def run_tests(workdir: Path, test_cmd: str, *, timeout: int = 600) -> dict:
    try:
        proc = subprocess.run(test_cmd, shell=True, cwd=workdir,
                              capture_output=True, text=True, timeout=timeout)
        return {"passed": proc.returncode == 0, "returncode": proc.returncode,
                "output": (proc.stdout + proc.stderr)[-10000:]}
    except subprocess.TimeoutExpired:
        return {"passed": False, "returncode": None, "output": "TIMEOUT"}


def check_rep(fixture: Fixture, after_dir: Path, tests_after_dir: Path,
              test_workdir: Path) -> dict:
    """Full static-check pass for one rep. test_workdir is where test_cmd runs
    (the scratch root, which still contains tests/ at call time)."""
    untouched = tests_untouched(fixture.tests_dir, tests_after_dir)
    tests = run_tests(test_workdir, fixture.test_cmd)
    stats = diff_stats(fixture.before_dir, after_dir)
    return {
        "tests_untouched": untouched,
        # An agent making tests pass by editing them is a failure mode, not a
        # pass — a tainted rep's pass/fail signal is meaningless.
        "tainted": not untouched,
        "tests_passed": tests["passed"] if untouched else None,
        "tests_output": tests["output"],
        "loc_added": stats["loc_added"],
        "loc_removed": stats["loc_removed"],
        "loc_net": stats["loc_net"],
        "patch": stats["patch"],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rep", type=Path, required=True,
                    help="rep dir containing after/ and tests_after/")
    ap.add_argument("--fixture", type=Path, required=True)
    args = ap.parse_args()

    fixture = load_fixture(args.fixture)
    # Reassemble the scratch layout (source at root + tests/) so test_cmd
    # runs against the same tree shape it saw during the original run.
    with tempfile.TemporaryDirectory(prefix="skillbench-recheck-") as tmp:
        workdir = Path(tmp) / "work"
        shutil.copytree(args.rep / "after", workdir)
        shutil.copytree(args.rep / "tests_after", workdir / "tests")
        result = check_rep(fixture, args.rep / "after", args.rep / "tests_after",
                           workdir)
    result.pop("patch")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
