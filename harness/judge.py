"""Blind LLM judge: anchored 1-5 rubric, 3 passes per artifact, median.

    python -m harness.judge --run results/<run-id> --judge-model <pinned-model> \
        [--passes 3] [--force]

Blinding is structural: the judge prompt is built from task.md, before/, and
diff.patch ONLY. It never sees the condition label, the run transcript (which
names the active skill), metrics.json, or this repo (each judge call runs in
an empty temp dir with the same clean flag set as scored runs, no plugins).
Known limitation, accepted in PHASE_1.md: a plugin can leave identifying
comments in the diff itself; artifacts are judged as-is, not edited.

Writes judge.json into each rep dir:

    {"passes": [...], "median": {...}, "spread": {...}, "flag_for_review": bool}

Cells where the three passes spread more than a point on any axis get
flag_for_review=true.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

from .common import COMMON_FLAGS, FIXTURES_DIR

AXES = ("solid_compliance", "restraint", "contract_stability")
RUBRIC = (Path(__file__).parent / "rubric.md").read_text()


def build_prompt(task: str, before_dir: Path, patch: str) -> str:
    before_parts = []
    for f in sorted(p for p in before_dir.rglob("*") if p.is_file()):
        before_parts.append(f"--- {f.relative_to(before_dir)} ---\n{f.read_text()}")
    return (
        "You are judging a code refactor produced by an automated tool. "
        "Apply the rubric below exactly.\n\n"
        f"{RUBRIC}\n\n"
        "# The task the tool was given\n\n"
        f"{task}\n\n"
        "# Original code (before)\n\n"
        + "\n\n".join(before_parts)
        + "\n\n# Unified diff (before -> after)\n\n"
        f"```diff\n{patch}\n```\n"
    )


def parse_scores(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    for axis in AXES:
        score = obj.get(axis, {}).get("score")
        if not isinstance(score, int) or not 1 <= score <= 5:
            return None
    return obj


def judge_once(prompt: str, *, model: str) -> dict | None:
    cmd = ["claude", "-p", prompt, "--output-format", "json",
           "--model", model, *COMMON_FLAGS]
    with tempfile.TemporaryDirectory(prefix="skillbench-judge-") as tmp:
        proc = subprocess.run(cmd, cwd=tmp, env=dict(os.environ),
                              capture_output=True, text=True, timeout=600)
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return parse_scores(result.get("result", "") or "")


def judge_rep(rep_dir: Path, *, model: str, passes: int) -> dict | None:
    # rep_dir is results/<run-id>/<fixture-slug>/<condition>/rep-N; the task
    # and before/ live in the fixture, keyed by slug.
    fixture_dir = FIXTURES_DIR / rep_dir.parent.parent.name
    task = (fixture_dir / "task.md").read_text()
    before_dir = fixture_dir / "before"
    patch = (rep_dir / "diff.patch").read_text()
    if not patch.strip():
        return {"passes": [], "median": None, "spread": None,
                "flag_for_review": True, "note": "empty diff — nothing to judge"}

    prompt = build_prompt(task, before_dir, patch)
    results = []
    for _ in range(passes):
        scores = judge_once(prompt, model=model)
        if scores is not None:
            results.append(scores)
    if len(results) < passes:
        print(f"    WARNING: only {len(results)}/{passes} judge passes parsed",
              file=sys.stderr)
    if not results:
        return None

    median = {a: statistics.median(r[a]["score"] for r in results) for a in AXES}
    spread = {a: max(r[a]["score"] for r in results) - min(r[a]["score"] for r in results)
              for a in AXES}
    return {
        "judge_model": model,
        "passes": results,
        "median": median,
        "spread": spread,
        "flag_for_review": any(s > 1 for s in spread.values()),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=Path, required=True, help="results/<run-id> dir")
    ap.add_argument("--judge-model", required=True,
                    help="pinned judge model (record-keeping demands an explicit pin)")
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--force", action="store_true", help="re-judge existing judge.json")
    args = ap.parse_args()

    rep_dirs = sorted(args.run.glob("*/*/rep-*"))
    if not rep_dirs:
        sys.exit(f"no rep dirs under {args.run}")

    for rep_dir in rep_dirs:
        out = rep_dir / "judge.json"
        if out.exists() and not args.force:
            print(f"  {rep_dir.relative_to(args.run)}: judged, skipping")
            continue
        verdict = judge_rep(rep_dir, model=args.judge_model, passes=args.passes)
        if verdict is None:
            print(f"  {rep_dir.relative_to(args.run)}: JUDGE FAILED (no parseable passes)")
            continue
        out.write_text(json.dumps(verdict, indent=2) + "\n")
        med, flag = verdict["median"], verdict["flag_for_review"]
        print(f"  {rep_dir.relative_to(args.run)}: {med}"
              + ("  [FLAGGED: spread > 1]" if flag and med else ""))

    print(f"\ndone. next: python -m harness.aggregate --run {args.run}")


if __name__ == "__main__":
    main()
