"""Blind judge: score each run artifact 1-5 on three anchored axes.

The judge sees task.md + before/ sources + the unified diff — never the condition,
model, or transcript. One pass per artifact with a pinned Sonnet judge (scores are
ordinal signals, not calibrated gaps — see planning/PHASE_1.md).
"""

from __future__ import annotations

import json
import re
import subprocess
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
JUDGE_MODEL = "claude-sonnet-5"
CLAUDE = shutil.which("claude") or "claude"
AXES = ("solid", "restraint", "contract")


def before_listing(before: Path) -> str:
    parts = []
    for f in sorted(before.rglob("*.py")):
        if "__pycache__" in f.parts or f.name == "conftest.py":
            continue
        parts.append(f"### {f.relative_to(before).as_posix()}\n```python\n{f.read_text(encoding='utf-8')}\n```")
    return "\n\n".join(parts)


def judge_one(fixture: Path, art: Path) -> dict:
    prompt = "\n\n".join([
        (ROOT / "harness" / "rubric.md").read_text(encoding="utf-8"),
        "# The task that was assigned\n\n" + (fixture / "task.md").read_text(encoding="utf-8"),
        "# Original source files\n\n" + before_listing(fixture / "before"),
        "# The diff produced\n\n```diff\n" + (art / "diff.patch").read_text(encoding="utf-8") + "\n```",
    ])
    import os
    env = dict(os.environ, CLAUDE_CONFIG_DIR=str(ROOT / ".cache" / "scratch-config"))
    with tempfile.TemporaryDirectory(prefix="sb_judge_", ignore_cleanup_errors=True) as td:
        p = subprocess.run(
            [CLAUDE, "-p", "--output-format", "json", "--model", JUDGE_MODEL,
             "--setting-sources", "project,local", "--strict-mcp-config",
             "--dangerously-skip-permissions", "--max-turns", "1"],
            input=prompt, capture_output=True, text=True, cwd=td, timeout=600,
            encoding="utf-8", errors="replace", env=env)
    out = json.loads(p.stdout)
    m = re.search(r"\{.*\}", out.get("result", ""), re.DOTALL)
    scores = json.loads(m.group(0))
    assert all(1 <= scores[a]["score"] <= 5 for a in AXES), f"bad scores: {scores}"
    return {"scores": scores, "judge_cost_usd": out.get("total_cost_usd")}


def main() -> None:
    judged = set()
    jpath = RESULTS / "judgments.jsonl"
    if jpath.exists():
        judged = {json.loads(l)["run_id"] for l in jpath.read_text().splitlines() if l}
    runs = [json.loads(l) for l in (RESULTS / "runs.jsonl").read_text().splitlines() if l]
    for run in runs:
        if run["run_id"] in judged:
            print(f"skip (judged): {run['run_id']}")
            continue
        fixture = ROOT / "fixtures" / run["fixture"]
        art = RESULTS / "artifacts" / run["run_id"]
        print(f"judging: {run['run_id']}", flush=True)
        rec = {"run_id": run["run_id"], "judge_model": JUDGE_MODEL, **judge_one(fixture, art)}
        with open(jpath, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        print("  " + ", ".join(f"{a}={rec['scores'][a]['score']}" for a in AXES), flush=True)


if __name__ == "__main__":
    main()
