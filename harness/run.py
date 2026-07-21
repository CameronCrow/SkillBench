"""SkillBench run orchestration: preflight probes + fixture x condition x model cells.

Each cell = one `claude -p` refactor run in a scratch copy of the fixture's before/.
Sonnet cells are scheduled before Opus cells; a cumulative total_cost_usd cap stops
new launches so a budget stop degrades to fewer Opus cells, not a half-run grid.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import static_checks

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache"
RESULTS = ROOT / "results"
CLAUDE = shutil.which("claude") or "claude"

CONDITIONS: dict[str, list[str]] = {
    "baseline": [],
    "solidifier": [str(CACHE / "solidifier" / "claude-code" / "plugins" / "solidifier")],
    "ponytail": [str(CACHE / "ponytail")],
}
MODELS = {"sonnet": "claude-sonnet-5", "opus": "claude-opus-4-8"}
COMMON_FLAGS = [
    "--setting-sources", "project,local",
    "--strict-mcp-config",
    "--dangerously-skip-permissions",
]
# User-scope skill that must NOT be visible in any condition (isolation sentinel).
LEAK_SENTINEL = "graphify"


# Isolation (verified 2026-07-20, CLI 2.1.216): `--setting-sources project,local` alone
# still loads user-scope skills + global CLAUDE.md. A scratch CLAUDE_CONFIG_DIR (with
# credentials copied in) removes user skills/settings/plugins; the global CLAUDE.md is
# read from the HOME dir unconditionally, so it is renamed aside for the duration of
# each invocation (restored in `finally`; self-heals on startup if a crash left it).
SCRATCH_CONFIG = CACHE / "scratch-config"
USER_CLAUDE_MD = Path.home() / ".claude" / "CLAUDE.md"
SIDELINED = USER_CLAUDE_MD.with_suffix(".md.skillbench-sidelined")


def ensure_isolation_setup() -> None:
    if SIDELINED.exists() and not USER_CLAUDE_MD.exists():  # crashed mid-run last time
        SIDELINED.rename(USER_CLAUDE_MD)
    SCRATCH_CONFIG.mkdir(parents=True, exist_ok=True)
    creds = Path.home() / ".claude" / ".credentials.json"
    if creds.exists() and not (SCRATCH_CONFIG / ".credentials.json").exists():
        shutil.copy(creds, SCRATCH_CONFIG / ".credentials.json")


def clean_env(condition: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "PONYTAIL_DEFAULT_MODE"}
    env["CLAUDE_CONFIG_DIR"] = str(SCRATCH_CONFIG)
    if condition == "ponytail":
        env["PONYTAIL_DEFAULT_MODE"] = "full"  # deterministic mode regardless of machine state
    return env


def run_claude(prompt: str, cwd: Path, model: str, condition: str, timeout: int = 1800) -> dict:
    """One `claude -p` invocation (stream-json). Returns {result, transcript}."""
    cmd = [CLAUDE, "-p", "--output-format", "stream-json", "--verbose",
           "--model", model, *COMMON_FLAGS]
    for d in CONDITIONS[condition]:
        cmd += ["--plugin-dir", d]
    sidelined = False
    try:
        if USER_CLAUDE_MD.exists():
            USER_CLAUDE_MD.rename(SIDELINED)
            sidelined = True
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=cwd,
                           env=clean_env(condition), timeout=timeout, encoding="utf-8",
                           errors="replace")
    finally:
        if sidelined:
            SIDELINED.rename(USER_CLAUDE_MD)
    result = None
    for line in p.stdout.splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") == "result":
            result = obj
    if result is None:
        raise RuntimeError(f"no result event (exit {p.returncode}): {p.stderr[-2000:]}")
    return {"result": result, "transcript": p.stdout}


def detect_engagement(condition: str, transcript: str) -> bool | None:
    """Did the intended skill actually fire? (None for baseline — nothing to fire.)"""
    if condition == "solidifier":
        # the model invoking the skill shows up as a Skill/skill tool reference
        return '"solidifier"' in transcript or "skills/solidifier" in transcript.lower()
    if condition == "ponytail":
        return "PONYTAIL" in transcript  # SessionStart hook banner injected into context
    return None


def preflight(condition: str) -> None:
    """Assert this condition's actual skill visibility before any scored run."""
    with tempfile.TemporaryDirectory(prefix="sb_probe_", ignore_cleanup_errors=True) as td:
        out = run_claude(
            "List the names of every skill, plugin, and CLAUDE.md instruction source "
            "available to you in this session. Names only, one per line. Do not use tools.",
            Path(td), MODELS["sonnet"], condition, timeout=300)
    text = out["result"].get("result", "") + out["transcript"]
    lower = text.lower()
    assert LEAK_SENTINEL not in lower, f"[{condition}] user scope leaked into probe"
    if condition == "solidifier":
        assert "solidifier" in lower, "[solidifier] skill not visible"
        assert "ponytail" not in lower, "[solidifier] ponytail leaked in"
    elif condition == "ponytail":
        assert "ponytail" in lower, "[ponytail] plugin not visible"
        assert "solidifier" not in lower, "[ponytail] solidifier leaked in"
    else:
        assert "solidifier" not in lower and "ponytail" not in lower, "[baseline] plugin leaked in"
    print(f"probe ok: {condition}")


def spent_so_far() -> float:
    runs = RESULTS / "runs.jsonl"
    if not runs.exists():
        return 0.0
    return sum(json.loads(l).get("total_cost_usd", 0) for l in runs.read_text().splitlines() if l)


def run_cell(fixture: Path, condition: str, mkey: str) -> dict:
    run_id = f"{fixture.name}_{condition}_{mkey}"
    art = RESULTS / "artifacts" / run_id
    scratch = Path(tempfile.mkdtemp(prefix=f"sb_{run_id}_"))
    shutil.copytree(fixture / "before", scratch, dirs_exist_ok=True)
    shutil.copytree(fixture / "tests", scratch / "tests")

    out = run_claude((fixture / "task.md").read_text(), scratch, MODELS[mkey], condition)
    res = out["result"]

    untouched = static_checks.tests_untouched(fixture / "tests", scratch / "tests")
    passed, test_tail = static_checks.run_pinned_tests(scratch)
    art.mkdir(parents=True, exist_ok=True)
    shutil.copytree(scratch, art / "after", ignore=shutil.ignore_patterns("tests", "conftest.py",
                    "__pycache__", ".pytest_cache", ".claude"), dirs_exist_ok=True)
    diff = static_checks.unified_diff(fixture / "before", art / "after")
    (art / "diff.patch").write_text(diff, encoding="utf-8")
    (art / "transcript.jsonl").write_text(out["transcript"], encoding="utf-8")
    shutil.rmtree(scratch, ignore_errors=True)

    record = {
        "run_id": run_id, "fixture": fixture.name, "condition": condition, "model": MODELS[mkey],
        "cli_version": subprocess.run([CLAUDE, "--version"], capture_output=True,
                                      text=True).stdout.strip(),
        "num_turns": res.get("num_turns"), "duration_ms": res.get("duration_ms"),
        "total_cost_usd": res.get("total_cost_usd"), "usage": res.get("usage"),
        "skill_engaged": detect_engagement(condition, out["transcript"]),
        "tests_untouched": untouched,
        "tests_passed": passed if untouched else None,  # tainted if tests were edited
        "test_tail": test_tail,
        "loc": static_checks.loc_delta(diff),
    }
    with open(RESULTS / "runs.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    return record


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", nargs="*", default=None)
    ap.add_argument("--cap", type=float, default=15.0, help="cumulative total_cost_usd cap")
    ap.add_argument("--probe-only", action="store_true")
    ap.add_argument("--skip-probes", action="store_true")
    args = ap.parse_args()

    ensure_isolation_setup()
    if not args.skip_probes:
        for cond in CONDITIONS:
            preflight(cond)
    if args.probe_only:
        return

    fixtures = [ROOT / "fixtures" / f for f in args.fixtures] if args.fixtures else \
               sorted(p for p in (ROOT / "fixtures").iterdir() if (p / "task.md").exists())
    RESULTS.mkdir(exist_ok=True)
    done = set()
    if (RESULTS / "runs.jsonl").exists():
        done = {json.loads(l)["run_id"] for l in (RESULTS / "runs.jsonl").read_text().splitlines() if l}

    for mkey in ["sonnet", "opus"]:  # all sonnet cells before any opus cell
        for fixture in fixtures:
            for cond in CONDITIONS:
                run_id = f"{fixture.name}_{cond}_{mkey}"
                if run_id in done:
                    print(f"skip (done): {run_id}")
                    continue
                spent = spent_so_far()
                if spent >= args.cap:
                    print(f"COST CAP reached (${spent:.2f} >= ${args.cap}); stopping.")
                    return
                print(f"run: {run_id} (spent ${spent:.2f})", flush=True)
                rec = run_cell(fixture, cond, mkey)
                print(f"  done: ${rec['total_cost_usd']:.3f}, {rec['num_turns']} turns, "
                      f"tests={'pass' if rec['tests_passed'] else 'FAIL'}, "
                      f"engaged={rec['skill_engaged']}, loc={rec['loc']['net']:+d}", flush=True)


if __name__ == "__main__":
    main()
