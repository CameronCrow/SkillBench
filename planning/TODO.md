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
- [x] Preflight probe - per-condition skill/plugin visibility check, asserted before any
      scored run (fallback: scratch `CLAUDE_CONFIG_DIR` if user scope leaks)
- [x] `harness/run.py` - condition orchestration + `claude -p` invocation: 3 reps per
      cell, pinned `--model`, `PONYTAIL_DEFAULT_MODE=full` for ponytail runs, records
      CLI version / model / `num_turns`, detects from the transcript whether the
      intended skill actually fired
- [x] `harness/judge.py` - anchored 1-5 rubric, blind to condition (task + before +
      diff only), 3 passes per artifact with median, evidence quotes required
- [x] `harness/static_checks.py` - pinned tests + LOC delta + tests-untouched tamper
      guard
- [x] `harness/aggregate.py` - per-axis profile across the 4 conditions, per-fixture
      paired comparisons, "no detectable difference" reported when a gap is within
      judge noise

Checked items are code-complete and smoke-tested (diff/taint/judge-parse/aggregate
paths exercised on a synthetic fixture); their first run against the live `claude`
CLI is part of the pilot, which is also where the fixture-schema item's pilot
fixture gets created (schema itself: `fixtures/README.md`).
- [ ] Pilot fixture run end-to-end: probes + all 4 conditions x 3 reps (plumbing +
      variance measurement only - no skill conclusions from one fixture)

## Related

- [[Repos/SkillBench/planning/PLAN_MAIN|PLAN_MAIN]]
- [[Repos/SkillBench/planning/PHASE_1|PHASE_1]]
- [[SkillBench]]
