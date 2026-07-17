---
type: reference
tags: [repo/SkillBench]
up: "[[Repos/SkillBench/planning/PLAN_MAIN|PLAN_MAIN]]"
---
# Phase 1 - Harness + pilot fixture

## Fixture schema

```
fixtures/<slug>/
  before/         extracted source file(s) + any minimal supporting context
                  (interfaces, a sibling file) needed for the task to make sense
  tests/          pinned tests (from the source repo if they exist, else hand-written
                  characterization tests) — must still pass post-refactor
  task.md         the refactor ask, phrased like solidifier's own examples
                  ("Review X for SOLID violations", "clean up this switch statement")
```

Fixtures are hand-picked real files from repos Cameron owns (irl-core, LLT, papyrus-ade
are the first candidates), stripped of anything sensitive — not synthetic snippets.

## The 4 conditions — isolation mechanics

All four conditions run with the **same** flags and environment, differing only in which
plugins get loaded via `--plugin-dir` (repeatable). The condition is the plugin set;
everything else is held constant:

| Condition | Plugin dirs |
|---|---|
| baseline | none |
| solidifier only | `--plugin-dir .cache/solidifier/claude-code/plugins/solidifier` |
| ponytail only | `--plugin-dir .cache/ponytail` |
| both | both `--plugin-dir` flags |

Common flags for every condition: `--setting-sources project,local` (the scratch dir has
no project config, so this is effectively a clean context), `--strict-mcp-config` (no MCP
servers), a pinned `--model`, `--dangerously-skip-permissions`.

An earlier draft used an asymmetric scheme — `--safe-mode` for baseline, default setting
sources for the ponytail conditions (letting the live marketplace install load from user
scope). Dropped, for three reasons, recorded here so it doesn't come back:

- **Default setting sources load the whole live user environment**, not just ponytail:
  global CLAUDE.md, every user-scope agent and skill, other installed plugins, user MCP
  servers. That compares "solidifier in a clean room" against "ponytail plus everything
  else on the machine" — an environment confound, not a skill comparison.
- **`--safe-mode` disables more than plugins** (CLAUDE.md, hooks, MCP, commands), so the
  baseline would differ from the other conditions on several axes besides skill presence.
  And the CLI's minimal modes can suppress even an explicit `--plugin-dir` (`--bare`
  documents exactly that), so mixing a kill-switch flag with plugin loading is fragile.
- **Ponytail's live install has session-persistent mode state.** Its mode resolves from
  the `PONYTAIL_DEFAULT_MODE` env var, then a per-user `ponytail/config.json`, then
  defaults to `full`, and its SessionStart hook writes a `.ponytail-active` flag file
  into the Claude config dir. A "default sources" run inherits whatever mode was last set
  on the machine — not reproducible.

Both plugins are vendored at pinned versions into `.cache/` (gitignored): solidifier
cloned at a recorded commit SHA (note `--plugin-dir` must point at the
`claude-code/plugins/solidifier` subdirectory, not the repo root), ponytail copied at a
recorded version from the marketplace cache. The harness sets `PONYTAIL_DEFAULT_MODE=full`
for ponytail-condition runs so the mode is deterministic regardless of machine state, and
records the Claude Code CLI version and model alongside every run's metrics.

Each fixture x condition run happens in its own scratch copy of `before/` (a fresh temp
dir) so runs never interfere with each other or with the fixture's canonical copy.

### Activation asymmetry — verify the skill actually fired

The two plugins engage by different mechanisms, and the harness must not assume loading
implies influence. Ponytail injects its ruleset via a SessionStart hook — always-on, but
only if `node` is on PATH (its hooks silently no-op without it). Solidifier is a pure
skill: it only shapes the run if the model chooses to invoke it. So every run records
whether the intended skill actually engaged, from the run transcript
(`--output-format stream-json` shows skill invocations and injected hook context). A
solidifier-condition run where the skill never fired is not a data point about
solidifier's refactoring quality — it counts toward a reported trigger rate and is
excluded from the quality comparison. `task.md` stays neutral: it never names either
skill, because whether trigger-shaped phrasing engages the skill is itself part of what's
being measured.

### Preflight probe

Before any scored run, the harness runs one probe per condition — same flags, a scratch
dir, a prompt asking Claude to list the skills, plugins, and CLAUDE.md context available
to it — and asserts the expected set: baseline sees nothing, solidifier-only doesn't see
ponytail, and no user-scope customization leaks into any condition. If user scope does
leak through `--setting-sources`, the fallback is pointing `CLAUDE_CONFIG_DIR` at a
scratch config dir. The probe is cheap and re-runs after every CLI upgrade, which is also
the durability answer: flag semantics aren't assumed stable across versions, they're
re-verified.

## Invocation + metrics capture

```
claude -p "<task.md content>" --output-format json --dangerously-skip-permissions <condition flags>
```

Run inside the scratch dir. The JSON result gives, directly, most of what's needed:

- `duration_ms` -> time
- `num_turns` -> agentic effort (turn count)
- `usage.input_tokens` / `usage.output_tokens` / `usage.cache_creation_input_tokens` /
  `usage.cache_read_input_tokens` -> tokens
- `total_cost_usd` -> cost

Lines of code: diff the scratch dir's file(s) against the fixture's `before/` after the
run (added/removed/net). The same diff pass checks that `tests/` is untouched — if the
run modified the pinned tests, the tests-pass signal is meaningless and the run is marked
tainted (an agent making tests pass by editing them is a failure mode, not a pass).

### What each metric is (and isn't)

- **Wall-clock time** is descriptive only — it's dominated by API latency and queueing
  variance, so conditions are never compared on it. `num_turns` is the better effort
  proxy.
- **LOC delta is a behavioral signature, not a quality score.** Solidifier is expected to
  add lines and ponytail to remove them; the metric confirms each skill pushed output in
  its characteristic direction (a manipulation check) and shows what "both" does. Whether
  the delta was *good* is the judge's job.
- **Tokens/cost compare deployed cost fairly**: plugin conditions carry the skill
  content's token overhead by design — that overhead is part of the real cost of using
  the skill. Report totals per run; don't interpret the cache-creation vs cache-read
  split, which varies run-to-run for reasons unrelated to the conditions. Cost is only
  comparable because the model is pinned.
- **Tests pass/fail** is only valid when `tests/` is untouched (above), and only
  meaningful if the pinned tests pass on `before/` — verified once at fixture creation.

### Repetitions

Each fixture x condition cell runs **3 times** — single runs of a nondeterministic
process aren't data points. Report per-cell medians with ranges. The pilot's job includes
measuring this within-condition variance, which is what tells us whether 3 is enough and
how big the corpus needs to be.

## Judge rubric (fixed, applied identically across all 4 conditions)

Three axes, each scored 1-5 against written anchors pinned in the judge prompt (which
lives in the repo — the rubric text is versioned, not improvised per run). One-line axis
definitions aren't enough for an LLM judge to apply consistently; each axis needs
concrete anchors at least at 5, 3, and 1:

1. **SOLID compliance** — did it address the violation named in `task.md`, without
   introducing new ones? (5: the named violation is resolved and no new violations
   appear; 3: partially addressed, or fixed at the cost of a smaller new violation;
   1: violation untouched or the refactor made the design worse.)
2. **Restraint** — did it avoid over-engineering? (5: no abstractions beyond what the
   task requires; 3: one or two speculative touches — an unnecessary parameter, a
   premature extraction; 1: new interfaces/layers/patterns with a single implementation
   and no motivating requirement.) This is the axis where solidifier and ponytail's
   philosophies most directly interact.
3. **Contract stability** — did it touch public signatures it didn't need to? (5: all
   externally-visible signatures preserved unless the task required otherwise; 3: minor
   unforced signature churn; 1: gratuitous renames/reshapes of public surface.)

The exact anchor wording gets finalized when the judge prompt is written; the point is
that each score has a described behavior, not a vibe.

Judge mechanics:

- **Blind to condition.** The judge sees `task.md`, `before/`, and the unified diff —
  never the condition label and never the run transcript (the transcript names the active
  skill, which would unblind it). Blinding is imperfect — ponytail can leave `ponytail:`
  comments in output — noted as a limitation; artifacts are judged as-is, not edited.
- **Run 3 times per artifact**, pinned judge model and version, median score per axis.
  Cells where the three passes spread more than a point get flagged for human review.
- **Evidence required** — the judge must quote the specific code lines supporting each
  score, which makes scores auditable and discourages drive-by numbers.
- **No composite score.** The axes intentionally pull in opposite directions (SOLID
  compliance favors solidifier's instincts, restraint favors ponytail's) — collapsing
  them into one winner number would erase the actual question. Results are a per-axis
  profile per condition; the interesting cell is what "both" does on the restraint/SOLID
  tension.

Correctness is *not* judged qualitatively — it's the pinned-tests pass/fail signal from
`harness/static_checks.py`, kept separate from the LLM judge's more subjective scores.

## Reporting ties and noise

A difference smaller than the judge's own run-to-run spread on that cell is reported as
"no detectable difference" — that's a valid, publishable outcome of a comparison, not a
failure of the benchmark. The aggregate table says it explicitly rather than letting a
0.2-point gap masquerade as a result.

## Pilot

Before growing the fixture corpus, validate the full pipeline (preflight probes -> run ->
judge -> static checks -> aggregate) end-to-end on a single real pilot fixture, all 4
conditions x 3 repetitions. The pilot validates plumbing and measures variance; it
supports **no conclusions about the skills** — one fixture generalizes to nothing, and
any 4-way comparison drawn from it would be noise. Conclusions wait for the corpus:
target 10-15 fixtures, analyzed as per-fixture paired comparisons (which condition scored
higher *on this fixture*, and does the direction hold across fixtures) rather than pooled
means — consistency of direction across a dozen paired fixtures is the strongest claim
this corpus size can support.

## Related

- [[Repos/SkillBench/planning/PLAN_MAIN|PLAN_MAIN]]
- [[Repos/SkillBench/planning/TODO|TODO]]
