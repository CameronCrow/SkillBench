"""Preflight probe: verify each condition's actual skill/plugin visibility.

Runs one cheap probe per condition — same flags as scored runs, a scratch
working dir, a prompt asking Claude to enumerate its skills/plugins/context —
and asserts the expected set: baseline sees neither plugin, solidifier-only
doesn't see ponytail, and vice versa. Flag semantics are not assumed stable
across CLI versions; re-run this after every CLI upgrade.

Usage:

    python -m harness.preflight --model <pinned-model> [--scratch-config]

--scratch-config points CLAUDE_CONFIG_DIR at a throwaway dir — the fallback
if user scope leaks through --setting-sources. Probe outputs are saved under
results/preflight/ for human review (the automatic assertions only check
plugin names; skim the outputs once per CLI version for anything else that
leaked in, e.g. a user CLAUDE.md).

Exit status is non-zero if any assertion fails; harness/run.py refuses to
score runs until a passing preflight stamp exists for the current CLI version.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .common import (CONDITIONS, RESULTS_DIR, claude_command, cli_version,
                     condition_env, run_claude_stream)

PROBE_PROMPT = (
    "Do not use any tools. List, verbatim and completely: "
    "(1) every skill available to you, "
    "(2) every plugin loaded, "
    "(3) any CLAUDE.md or other project/user instructions you were given, "
    "(4) any MCP servers available. "
    "For each category, if it is empty, write exactly 'NONE'."
)

STAMP = RESULTS_DIR / "preflight" / "stamp.json"


def probe_condition(name: str, plugins: list[str], *, model: str,
                    scratch_config: bool) -> tuple[bool, list[str], str]:
    with tempfile.TemporaryDirectory(prefix=f"skillbench-probe-{name}-") as tmp:
        tmp = Path(tmp)
        cfg = tmp / "config" if scratch_config else None
        cwd = tmp / "work"
        cwd.mkdir()
        cmd = claude_command(PROBE_PROMPT, model=model, plugins=plugins)
        events, result, _ = run_claude_stream(cmd, cwd=cwd,
                                              env=condition_env(plugins, scratch_config=cfg),
                                              timeout=600)
    text = (result or {}).get("result", "") or ""
    if not text:
        return False, [f"{name}: probe produced no result "
                       f"({json.dumps(result)[:300]})"], ""

    failures = []
    lower = text.lower()
    for plugin in ("solidifier", "ponytail"):
        expected = plugin in plugins
        seen = plugin in lower
        if expected and not seen:
            failures.append(f"{name}: expected {plugin} visible, probe never mentions it")
        if not expected and seen:
            failures.append(f"{name}: {plugin} leaked into a condition that "
                            "should not load it")
    return not failures, failures, text


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True)
    ap.add_argument("--scratch-config", action="store_true",
                    help="point CLAUDE_CONFIG_DIR at a throwaway dir (leak fallback)")
    args = ap.parse_args()

    version = cli_version()
    out_dir = RESULTS_DIR / "preflight"
    out_dir.mkdir(parents=True, exist_ok=True)

    all_failures = []
    for name, plugins in CONDITIONS.items():
        ok, failures, text = probe_condition(name, plugins, model=args.model,
                                             scratch_config=args.scratch_config)
        (out_dir / f"{name}.txt").write_text(text)
        status = "ok" if ok else "FAIL"
        print(f"[{status}] {name}")
        for f in failures:
            print(f"       {f}")
        all_failures += failures

    if all_failures:
        if STAMP.exists():
            STAMP.unlink()
        sys.exit(f"\npreflight FAILED ({len(all_failures)} assertion(s)). "
                 "If the leak is user-scope, retry with --scratch-config.")

    STAMP.write_text(json.dumps({
        "cli_version": version,
        "model": args.model,
        "scratch_config": args.scratch_config,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }, indent=2) + "\n")
    print(f"\npreflight passed for CLI '{version}'; stamp written to {STAMP}")
    print(f"probe outputs saved in {out_dir} — skim them once per CLI version.")


if __name__ == "__main__":
    main()
