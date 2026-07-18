"""Aggregate a run: per-axis profile across conditions, paired comparisons.

    python -m harness.aggregate --run results/<run-id>

Reads every rep's metrics.json + judge.json and writes report.md and
summary.json into the run dir. Rules (from planning/PHASE_1.md):

- A rep enters the quality comparison only if it is untainted AND every
  intended plugin actually engaged. Excluded reps still count toward the
  reported trigger rate.
- Per-cell values are medians with (min–max) ranges. No composite score —
  the axes pull in opposite directions on purpose.
- A paired difference smaller than the judge's own run-to-run spread on the
  cells involved is reported as "no detectable difference" — a valid
  outcome, not a failure.
- With one fixture (the pilot), the report carries a variance-only banner:
  no skill conclusions are supported.
"""
from __future__ import annotations

import argparse
import itertools
import json
import statistics
import sys
from pathlib import Path

from .judge import AXES

CONDITION_ORDER = ["baseline", "solidifier", "ponytail", "both"]


def load_cells(run_dir: Path) -> dict:
    """{fixture: {condition: [rep records]}} — each record merges metrics+judge."""
    cells: dict = {}
    for metrics_file in sorted(run_dir.glob("*/*/rep-*/metrics.json")):
        rep_dir = metrics_file.parent
        rec = json.loads(metrics_file.read_text())
        judge_file = rep_dir / "judge.json"
        rec["judge"] = json.loads(judge_file.read_text()) if judge_file.exists() else None
        cells.setdefault(rec["fixture"], {}).setdefault(rec["condition"], []).append(rec)
    return cells


def med_range(values: list) -> str:
    values = [v for v in values if v is not None]
    if not values:
        return "—"
    med = statistics.median(values)
    lo, hi = min(values), max(values)
    if lo == hi:
        return f"{med:g}"
    return f"{med:g} ({lo:g}–{hi:g})"


def quality_reps(reps: list) -> list:
    return [r for r in reps
            if not r["tainted"] and r["engaged_ok"]
            and r.get("judge") and r["judge"].get("median")]


def axis_values(reps: list, axis: str) -> list[float]:
    return [r["judge"]["median"][axis] for r in quality_reps(reps)]


def axis_noise(reps: list, axis: str) -> float:
    """The judge's own run-to-run spread on this cell (worst artifact)."""
    spreads = [r["judge"]["spread"][axis] for r in quality_reps(reps)]
    return max(spreads) if spreads else 0.0


def compare(fixture_cells: dict, axis: str) -> list[str]:
    lines = []
    for a, b in itertools.combinations(
            [c for c in CONDITION_ORDER if c in fixture_cells], 2):
        va, vb = axis_values(fixture_cells[a], axis), axis_values(fixture_cells[b], axis)
        if not va or not vb:
            lines.append(f"| {a} vs {b} | — | insufficient eligible reps |")
            continue
        diff = statistics.median(vb) - statistics.median(va)
        noise = max(axis_noise(fixture_cells[a], axis),
                    axis_noise(fixture_cells[b], axis))
        if abs(diff) <= noise:
            verdict = f"no detectable difference (Δ={diff:+g} ≤ judge spread {noise:g})"
        else:
            winner = b if diff > 0 else a
            verdict = f"**{winner}** higher (Δ={diff:+g}, judge spread {noise:g})"
        lines.append(f"| {a} vs {b} | {diff:+g} | {verdict} |")
    return lines


def fixture_report(slug: str, fixture_cells: dict) -> str:
    out = [f"## Fixture: {slug}\n"]

    header = "| condition | reps | quality-eligible | trigger | tests pass | tainted | " \
             + " | ".join(AXES) + " | num_turns | tokens in/out | cost USD | LOC net |"
    sep = "|" + "---|" * (len(header.split("|")) - 2)
    out += [header, sep]
    for cond in [c for c in CONDITION_ORDER if c in fixture_cells]:
        reps = fixture_cells[cond]
        eligible = quality_reps(reps)
        engaged = [r for r in reps if r["engaged_ok"]]
        trigger = f"{len(engaged)}/{len(reps)}" if reps and reps[0]["engagement"] else "n/a"
        untainted = [r for r in reps if not r["tainted"]]
        passed = [r for r in untainted if r["tests_passed"]]
        judge_cols = " | ".join(med_range(axis_values(reps, a)) for a in AXES)
        tok_in = med_range([(r.get("usage") or {}).get("input_tokens") for r in reps])
        tok_out = med_range([(r.get("usage") or {}).get("output_tokens") for r in reps])
        out.append(
            f"| {cond} | {len(reps)} | {len(eligible)} | {trigger} "
            f"| {len(passed)}/{len(untainted)} | {len(reps) - len(untainted)} "
            f"| {judge_cols} "
            f"| {med_range([r['num_turns'] for r in reps])} "
            f"| {tok_in} / {tok_out} "
            f"| {med_range([r['total_cost_usd'] for r in reps])} "
            f"| {med_range([r['loc_net'] for r in reps])} |")

    for axis in AXES:
        out += [f"\n### Paired comparisons — {axis}\n",
                "| pair | Δ median | verdict |", "|---|---|---|",
                *compare(fixture_cells, axis)]

    flagged = [f"{c}/rep-{r['rep']}" for c, reps in fixture_cells.items()
               for r in reps if r.get("judge") and r["judge"].get("flag_for_review")]
    if flagged:
        out.append("\nFlagged for human review (judge spread > 1 point): "
                   + ", ".join(sorted(flagged)))
    return "\n".join(out) + "\n"


def direction_consistency(cells: dict) -> str:
    """Across fixtures: does each pairwise direction hold? (Only meaningful
    with several fixtures — the strongest claim this corpus design supports.)"""
    out = ["## Cross-fixture direction consistency\n"]
    for axis in AXES:
        out.append(f"### {axis}\n")
        out += ["| pair | higher per fixture |", "|---|---|"]
        for a, b in itertools.combinations(CONDITION_ORDER, 2):
            directions = []
            for slug, fixture_cells in cells.items():
                if a not in fixture_cells or b not in fixture_cells:
                    continue
                va, vb = axis_values(fixture_cells[a], axis), axis_values(fixture_cells[b], axis)
                if not va or not vb:
                    continue
                diff = statistics.median(vb) - statistics.median(va)
                noise = max(axis_noise(fixture_cells[a], axis),
                            axis_noise(fixture_cells[b], axis))
                directions.append(f"{slug}: " + ("tie" if abs(diff) <= noise
                                                 else b if diff > 0 else a))
            if directions:
                out.append(f"| {a} vs {b} | {'; '.join(directions)} |")
        out.append("")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=Path, required=True, help="results/<run-id> dir")
    args = ap.parse_args()

    cells = load_cells(args.run)
    if not cells:
        sys.exit(f"no metrics.json found under {args.run}")

    parts = [f"# SkillBench report — run {args.run.name}\n"]
    if len(cells) == 1:
        parts.append(
            "> **Pilot run — variance measurement only.** One fixture supports "
            "no conclusions about the skills; this report exists to validate "
            "the pipeline and measure within-condition and judge variance.\n")
    for slug, fixture_cells in cells.items():
        parts.append(fixture_report(slug, fixture_cells))
    if len(cells) > 1:
        parts.append(direction_consistency(cells))

    report = "\n".join(parts)
    (args.run / "report.md").write_text(report)
    (args.run / "summary.json").write_text(json.dumps({
        slug: {cond: [{k: r.get(k) for k in
                       ("rep", "tainted", "engaged_ok", "tests_passed",
                        "num_turns", "total_cost_usd", "loc_net")}
                      | {"judge_median": (r.get("judge") or {}).get("median")}
                      for r in reps]
               for cond, reps in fixture_cells.items()}
        for slug, fixture_cells in cells.items()}, indent=2) + "\n")
    print(report)
    print(f"\nwritten: {args.run / 'report.md'} and summary.json")


if __name__ == "__main__":
    main()
