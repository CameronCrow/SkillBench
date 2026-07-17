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

Claude Code's CLI flags give real isolation here, not prompt-level toggling:

| Condition | Flags |
|---|---|
| baseline | `--safe-mode` (disables all customizations: CLAUDE.md, skills, plugins, hooks) |
| solidifier only | `--setting-sources project,local --plugin-dir <solidifier-clone>` (excludes the user-scope config where ponytail's marketplace registration lives; loads solidifier session-only) |
| ponytail only | default setting sources (user scope loads ponytail normally), no `--plugin-dir` |
| both | default setting sources + `--plugin-dir <solidifier-clone>` |

`solidifier` is cloned once into a local cache (`.cache/solidifier/`, gitignored) since it
ships as a marketplace-installable plugin — `--plugin-dir` can point straight at the clone,
no per-run install/uninstall needed.

Each fixture x condition run happens in its own scratch copy of `before/` (a fresh temp
dir) so runs never interfere with each other or with the fixture's canonical copy.

## Invocation + metrics capture

```
claude -p "<task.md content>" --output-format json --dangerously-skip-permissions <condition flags>
```

Run inside the scratch dir. The JSON result gives, directly, everything needed for the
tokens/time metrics:

- `duration_ms` -> time
- `usage.input_tokens` / `usage.output_tokens` / `usage.cache_creation_input_tokens` /
  `usage.cache_read_input_tokens` -> tokens
- `total_cost_usd` -> cost

Lines of code: diff the scratch dir's file(s) against the fixture's `before/` after the
run (added/removed/net).

## Judge rubric (fixed, applied identically across all 4 conditions)

1. **SOLID compliance** — did it address the violation named in `task.md`, without
   introducing new ones?
2. **Restraint** — did it avoid over-engineering (new abstractions beyond what's needed)?
   This is the axis where solidifier and ponytail's philosophies most directly interact.
3. **Contract stability** — did it touch public signatures it didn't need to?

Correctness is *not* judged qualitatively — it's the pinned-tests pass/fail signal from
`harness/static_checks.py`, kept separate from the LLM judge's more subjective scores.

## Pilot

Before growing the fixture corpus, validate the full pipeline (run -> judge -> static
checks -> aggregate) end-to-end on a single real pilot fixture.

## Related

- [[Repos/SkillBench/planning/PLAN_MAIN|PLAN_MAIN]]
- [[Repos/SkillBench/planning/TODO|TODO]]
