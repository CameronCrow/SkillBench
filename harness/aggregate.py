"""Aggregate runs + judgments into a per-fixture table and a direction summary.

Single rep + single judge pass = no noise floor: per-cell gaps are never reported as
results, only direction consistency across fixtures/models (planning/PHASE_1.md).
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
AXES = ("solid", "restraint", "contract")


def load(name: str) -> list[dict]:
    p = RESULTS / name
    return [json.loads(l) for l in p.read_text().splitlines() if l] if p.exists() else []


def main() -> None:
    runs = {r["run_id"]: r for r in load("runs.jsonl")}
    scores = {j["run_id"]: j["scores"] for j in load("judgments.jsonl")}
    fixtures = sorted({r["fixture"] for r in runs.values()})

    for fx in fixtures:
        print(f"\n## {fx}\n")
        print("| condition | model | tests | engaged | turns | cost $ | LOC +/- (net) | SOLID | restraint | contract |")
        print("|---|---|---|---|---|---|---|---|---|---|")
        for r in sorted((r for r in runs.values() if r["fixture"] == fx),
                        key=lambda r: (r["model"], r["condition"])):
            s = scores.get(r["run_id"], {})
            tests = ("TAINTED" if not r["tests_untouched"]
                     else "pass" if r["tests_passed"] else "FAIL")
            cells = [r["condition"], r["model"].replace("claude-", ""), tests,
                     str(r["skill_engaged"]), str(r["num_turns"]),
                     f"{r['total_cost_usd']:.2f}",
                     f"+{r['loc']['added']}/-{r['loc']['removed']} ({r['loc']['net']:+d})",
                     *(str(s[a]["score"]) if a in s else "-" for a in AXES)]
            print("| " + " | ".join(cells) + " |")

    # Direction summary: per axis/model, does each plugin condition beat baseline on this fixture?
    print("\n## Direction vs baseline (per fixture; > means higher judge score)\n")
    for fx in fixtures:
        for model in sorted({r["model"] for r in runs.values() if r["fixture"] == fx}):
            def score(cond, axis):
                rid = f"{fx}_{cond}_{'sonnet' if 'sonnet' in model else 'opus'}"
                return scores.get(rid, {}).get(axis, {}).get("score")
            for cond in ("solidifier", "ponytail"):
                dirs = []
                for axis in AXES:
                    b, c = score("baseline", axis), score(cond, axis)
                    if b is None or c is None:
                        continue
                    dirs.append(f"{axis}: {'>' if c > b else '<' if c < b else '='}")
                if dirs:
                    print(f"- {fx} / {model} / {cond} vs baseline: " + ", ".join(dirs))

    total = sum(r.get("total_cost_usd") or 0 for r in runs.values())
    jtotal = sum(j.get("judge_cost_usd") or 0 for j in load("judgments.jsonl"))
    print(f"\nTotal spend: runs ${total:.2f} + judging ${jtotal:.2f} = ${total + jtotal:.2f}")


if __name__ == "__main__":
    main()
