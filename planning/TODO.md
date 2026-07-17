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
- [ ] `harness/run.py` - condition orchestration + `claude -p` invocation: 3 reps per
      cell, pinned `--model`, `PONYTAIL_DEFAULT_MODE=full` for ponytail runs, records
      CLI version / model / `num_turns`, detects from the transcript whether the
      intended skill actually fired
- [ ] `harness/judge.py` - anchored 1-5 rubric, blind to condition (task + before +
      diff only), 3 passes per artifact with median, evidence quotes required
- [ ] `harness/static_checks.py` - pinned tests + LOC delta + tests-untouched tamper
      guard
- [ ] `harness/aggregate.py` - per-axis profile across the 4 conditions, per-fixture
      paired comparisons, "no detectable difference" reported when a gap is within
      judge noise
- [ ] Pilot fixture run end-to-end: probes + all 4 conditions x 3 reps (plumbing +
      variance measurement only - no skill conclusions from one fixture)

## Related

- [[Repos/SkillBench/planning/PLAN_MAIN|PLAN_MAIN]]
- [[Repos/SkillBench/planning/PHASE_1|PHASE_1]]
- [[SkillBench]]
