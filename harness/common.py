"""Shared plumbing for the SkillBench harness.

Stdlib only. Every script in harness/ imports from here so the condition
definitions, flag sets, and claude invocation live in exactly one place —
the isolation design in planning/PHASE_1.md depends on all four conditions
sharing identical flags.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / ".cache"
FIXTURES_DIR = REPO_ROOT / "fixtures"
RESULTS_DIR = REPO_ROOT / "results"
VENDOR_MANIFEST = CACHE_DIR / "vendor.json"

# --plugin-dir must point at the plugin dir itself, not the repo root
# (for solidifier that is claude-code/plugins/solidifier inside the clone).
PLUGIN_DIRS = {
    "solidifier": CACHE_DIR / "solidifier" / "claude-code" / "plugins" / "solidifier",
    "ponytail": CACHE_DIR / "ponytail",
}

# The condition IS the plugin set; everything else is held constant.
CONDITIONS = {
    "baseline": [],
    "solidifier": ["solidifier"],
    "ponytail": ["ponytail"],
    "both": ["solidifier", "ponytail"],
}

# Identical for every condition — see PHASE_1.md "isolation mechanics".
COMMON_FLAGS = [
    "--setting-sources", "project,local",
    "--strict-mcp-config",
    "--dangerously-skip-permissions",
]


def claude_command(prompt: str, *, model: str, plugins: list[str] = (),
                   output_format: str = "stream-json") -> list[str]:
    cmd = ["claude", "-p", prompt, "--output-format", output_format,
           "--model", model, *COMMON_FLAGS]
    if output_format == "stream-json":
        cmd.append("--verbose")  # required by the CLI for stream-json with -p
    for name in plugins:
        cmd += ["--plugin-dir", str(PLUGIN_DIRS[name])]
    return cmd


def condition_env(plugins: list[str], *, scratch_config: Path | None = None) -> dict:
    env = dict(os.environ)
    if "ponytail" in plugins:
        # Pin ponytail's mode regardless of machine state (its mode otherwise
        # resolves from per-user config written by previous sessions).
        env["PONYTAIL_DEFAULT_MODE"] = "full"
    if scratch_config is not None:
        # Fallback for user-scope leakage through --setting-sources.
        scratch_config.mkdir(parents=True, exist_ok=True)
        env["CLAUDE_CONFIG_DIR"] = str(scratch_config)
    return env


def run_claude_stream(cmd: list[str], *, cwd: Path, env: dict,
                      timeout: int = 1800) -> tuple[list[dict], dict | None, str]:
    """Run claude with --output-format stream-json.

    Returns (events, result_event_or_None, raw_stdout). The result event is
    the terminal {"type": "result", ...} record carrying usage/cost/num_turns.
    """
    proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True,
                          text=True, timeout=timeout)
    events = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            events.append({"type": "unparsed", "raw": line})
    result = next((e for e in events if e.get("type") == "result"), None)
    if result is None and proc.returncode != 0:
        result = {"type": "result", "subtype": "error",
                  "error": proc.stderr[-4000:], "returncode": proc.returncode}
    return events, result, proc.stdout


def cli_version() -> str:
    try:
        return subprocess.run(["claude", "--version"], capture_output=True,
                              text=True, timeout=60).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def load_vendor_manifest() -> dict:
    if VENDOR_MANIFEST.exists():
        return json.loads(VENDOR_MANIFEST.read_text())
    return {}


@dataclass
class Fixture:
    slug: str
    path: Path
    task: str
    test_cmd: str
    meta: dict

    @property
    def before_dir(self) -> Path:
        return self.path / "before"

    @property
    def tests_dir(self) -> Path:
        return self.path / "tests"


def load_fixture(path: Path) -> Fixture:
    path = path.resolve()
    meta = json.loads((path / "fixture.json").read_text())
    task = (path / "task.md").read_text()
    for sub in ("before", "tests"):
        if not (path / sub).is_dir():
            raise FileNotFoundError(f"fixture {path.name} is missing {sub}/")
    return Fixture(slug=path.name, path=path, task=task,
                   test_cmd=meta["test_cmd"], meta=meta)


def make_scratch(fixture: Fixture, scratch: Path) -> None:
    """Fresh working copy: before/* at the scratch root, pinned tests in tests/."""
    scratch.mkdir(parents=True)
    shutil.copytree(fixture.before_dir, scratch, dirs_exist_ok=True)
    shutil.copytree(fixture.tests_dir, scratch / "tests")


def detect_engagement(events: list[dict], plugins: list[str]) -> dict:
    """Did each intended plugin actually influence the run?

    Heuristics over the stream-json transcript:
    - solidifier is a model-invoked skill: look for a tool_use block whose
      name/input mentions it (Skill tool invocation).
    - ponytail injects its ruleset via a SessionStart hook: look for its name
      in any non-assistant event (hook output arrives as injected context).
    Loading a plugin does not imply influence — see PHASE_1.md "activation
    asymmetry".
    """
    engagement = {}
    if "solidifier" in plugins:
        fired = False
        for e in events:
            if e.get("type") != "assistant":
                continue
            for block in e.get("message", {}).get("content", []):
                if block.get("type") == "tool_use" and \
                        "solidifier" in json.dumps(block).lower():
                    fired = True
        engagement["solidifier"] = fired
    if "ponytail" in plugins:
        injected = any(
            e.get("type") != "assistant" and "ponytail" in json.dumps(e).lower()
            for e in events
        )
        engagement["ponytail"] = injected
    return engagement


def engaged_ok(engagement: dict) -> bool:
    """A run is quality-eligible only if every intended plugin engaged."""
    return all(engagement.values())
