"""Condition orchestration: run one fixture through the 4 conditions x N reps.

    python -m harness.run --fixture fixtures/<slug> --model <pinned-model> \
        [--reps 3] [--conditions baseline solidifier ponytail both] \
        [--run-id <id>] [--scratch-config] [--timeout 1800]

Prerequisites: a passing preflight stamp for the current CLI version
(harness/preflight.py) and a vendor manifest (harness/vendor.py). Each rep
runs in a fresh scratch temp dir (a copy of before/ plus the pinned tests),
then everything is archived under:

    results/<run-id>/<fixture>/<condition>/rep-N/
        transcript.jsonl   full stream-json event log
        result.json        the CLI's terminal result record (usage, cost, turns)
        after/             the refactored working copy (tests separated out)
        tests_after/       the run's tests/ copy (for the tamper guard audit)
        diff.patch         unified diff, before -> after (tests excluded)
        metrics.json       everything aggregate.py consumes

Judge scores are added separately by harness/judge.py (it must never see
these transcripts — they name the active skill and would unblind it).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import static_checks
from .common import (CONDITIONS, RESULTS_DIR, Fixture, claude_command,
                     cli_version, condition_env, detect_engagement, engaged_ok,
                     load_fixture, load_vendor_manifest, make_scratch,
                     run_claude_stream)
from .preflight import STAMP


def check_preflight(version: str) -> None:
    if not STAMP.exists():
        sys.exit("no preflight stamp — run `python -m harness.preflight` first")
    stamp = json.loads(STAMP.read_text())
    if stamp["cli_version"] != version:
        sys.exit(f"preflight stamp is for CLI '{stamp['cli_version']}' but the "
                 f"installed CLI is '{version}' — re-run preflight (flag "
                 "semantics are re-verified after every upgrade, not assumed)")


def run_rep(fixture: Fixture, condition: str, rep: int, rep_dir: Path, *,
            model: str, scratch_config: bool, timeout: int) -> dict:
    plugins = CONDITIONS[condition]
    rep_dir.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="skillbench-run-") as tmp:
        tmp = Path(tmp)
        scratch = tmp / "work"
        make_scratch(fixture, scratch)
        cfg = tmp / "config" if scratch_config else None

        cmd = claude_command(fixture.task, model=model, plugins=plugins)
        env = condition_env(plugins, scratch_config=cfg)
        started = datetime.now(timezone.utc).isoformat()
        events, result, raw = run_claude_stream(cmd, cwd=scratch, env=env,
                                                timeout=timeout)

        (rep_dir / "transcript.jsonl").write_text(raw)
        (rep_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n")

        # Taint check and test run happen while tests/ is still in place;
        # then the tests copy is separated out so the pinned tests never
        # appear in the LOC signature or the judge's diff.
        untouched = static_checks.tests_untouched(fixture.tests_dir,
                                                  scratch / "tests")
        tests = static_checks.run_tests(scratch, fixture.test_cmd)
        shutil.move(str(scratch / "tests"), rep_dir / "tests_after")
        stats = static_checks.diff_stats(fixture.before_dir, scratch)
        shutil.move(str(scratch), rep_dir / "after")
        checks = {
            "tests_untouched": untouched,
            "tainted": not untouched,
            "tests_passed": tests["passed"] if untouched else None,
            "tests_output": tests["output"],
            **{k: stats[k] for k in ("loc_added", "loc_removed", "loc_net")},
            "patch": stats["patch"],
        }

    engagement = detect_engagement(events, plugins)
    result = result or {}
    metrics = {
        "fixture": fixture.slug,
        "condition": condition,
        "rep": rep,
        "started": started,
        "model": model,
        "cli_version": cli_version(),
        "vendor": load_vendor_manifest(),
        "flags": cmd[3:],  # everything after `claude -p <task>`
        "subtype": result.get("subtype"),
        "num_turns": result.get("num_turns"),
        "duration_ms": result.get("duration_ms"),
        "total_cost_usd": result.get("total_cost_usd"),
        "usage": result.get("usage"),
        "engagement": engagement,
        "engaged_ok": engaged_ok(engagement),
        **{k: v for k, v in checks.items() if k != "patch"},
    }
    (rep_dir / "diff.patch").write_text(checks["patch"])
    (rep_dir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    return metrics


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fixture", type=Path, required=True)
    ap.add_argument("--model", required=True,
                    help="pinned model for all conditions (never rely on a default)")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--conditions", nargs="+", default=list(CONDITIONS),
                    choices=list(CONDITIONS))
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--scratch-config", action="store_true",
                    help="must match the setting the preflight stamp was made with")
    ap.add_argument("--timeout", type=int, default=1800)
    args = ap.parse_args()

    version = cli_version()
    check_preflight(version)
    fixture = load_fixture(args.fixture)
    vendor = load_vendor_manifest()
    needed = {p for c in args.conditions for p in CONDITIONS[c]}
    missing = needed - set(vendor)
    if missing:
        sys.exit(f"vendor manifest missing pins for: {', '.join(sorted(missing))} "
                 "— run `python -m harness.vendor` first")

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_dir = RESULTS_DIR / run_id
    print(f"run {run_id}: fixture={fixture.slug} model={args.model} "
          f"cli='{version}' reps={args.reps}")

    for condition in args.conditions:
        for rep in range(1, args.reps + 1):
            rep_dir = run_dir / fixture.slug / condition / f"rep-{rep}"
            if rep_dir.exists():
                print(f"  {condition}/rep-{rep}: exists, skipping")
                continue
            m = run_rep(fixture, condition, rep, rep_dir, model=args.model,
                        scratch_config=args.scratch_config, timeout=args.timeout)
            status = ("tainted" if m["tainted"]
                      else "pass" if m["tests_passed"]
                      else "FAIL")
            print(f"  {condition}/rep-{rep}: tests={status} "
                  f"turns={m['num_turns']} loc_net={m['loc_net']:+d} "
                  f"engaged={m['engagement'] or '-'} "
                  f"cost=${m['total_cost_usd'] or 0:.2f}")

    print(f"\ndone. next: python -m harness.judge --run {run_dir}")


if __name__ == "__main__":
    main()
