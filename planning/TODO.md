---
type: reference
tags: [repo/SkillBench]
up: "[[SkillBench]]"
---
# TODO

## Phase 1 - Harness + pilot fixture

- [ ] Fixture schema + one real pilot fixture (verify pinned tests pass on `before/` at
      creation)
- [ ] Vendor pinned plugins into `.cache/`: solidifier clone at a recorded commit SHA,
      ponytail copy at a recorded version; record both in the run metadata
- [ ] Preflight probe - per-condition skill/plugin visibility check, asserted before any
      scored run (fallback: scratch `CLAUDE_CONFIG_DIR` if user scope leaks)
- [ ] `harness/run.py` - condition orchestration + `claude -p` invocation: 1 rep per
      cell across 2 pinned models (sonnet + opus), Sonnet cells before Opus cells,
      cumulative `total_cost_usd` cost cap that stops launching new cells when hit,
      `PONYTAIL_DEFAULT_MODE=full` for ponytail runs, records CLI version / model /
      `num_turns`, detects from the transcript whether the intended skill actually fired
- [ ] `harness/judge.py` - anchored 1-5 rubric, blind to condition (task + before +
      diff only), 1 pass per artifact with a pinned Sonnet judge, evidence quotes
      required
- [ ] `harness/static_checks.py` - pinned tests + LOC delta + tests-untouched tamper
      guard
- [ ] `harness/aggregate.py` - per-axis profile across the 4 conditions x 2 models,
      per-fixture paired comparisons reported as direction-only (single rep + single
      judge pass = no noise floor to score gaps against)
- [ ] Pilot fixture run end-to-end: probes + all 4 conditions x 2 models x 1 rep
      (plumbing validation - no skill conclusions from one fixture)

## Related

- [[Repos/SkillBench/planning/PLAN_MAIN|PLAN_MAIN]]
- [[Repos/SkillBench/planning/PHASE_1|PHASE_1]]
- [[SkillBench]]
