---
type: reference
tags: [repo/SkillBench]
up: "[[SkillBench]]"
---
# Planning

## Current State

Harness implemented in Python (stdlib only, 3.11+): `harness/{vendor,preflight,run,
static_checks,judge,aggregate}.py` plus the pinned judge rubric (`harness/rubric.md`)
and the fixture schema (`fixtures/README.md`). Smoke-tested on a synthetic fixture;
not yet run against the live CLI. Remaining for Phase 1, on the desktop that has the
plugins: vendor solidifier + ponytail (`python -m harness.vendor`), run preflight,
create the pilot fixture, run the pilot end-to-end — see `docs/USER_MANUAL.md` for
the exact steps. Phase 1 (harness + pilot fixture) in progress —
see [[Repos/SkillBench/planning/PHASE_1|PHASE_1]] for the design: 4-condition comparison
(baseline/solidifier/ponytail/both), symmetric isolation (identical flags every
condition, only the `--plugin-dir` set varies, both plugins vendored at pinned versions),
preflight probes that verify each condition's actual skill visibility, 3 repetitions per
cell, an anchored 1-5 judge rubric applied blind with 3 judge passes per artifact, and
the metrics captured (judge profile, pinned tests with a tamper guard, tokens/cost,
num_turns, LOC delta as a behavioral signature). Design revised 2026-07-17: the original
asymmetric flag scheme (`--safe-mode` baseline, default setting sources for ponytail)
compared a clean-room solidifier against ponytail-plus-the-entire-live-user-environment,
and ponytail's persisted mode state made "default" runs non-reproducible — see PHASE_1
for the full rationale.

## Related

- [[Repos/SkillBench/planning/PHASE_1|PHASE_1]]
- [[Repos/SkillBench/planning/TODO|TODO]]
- [[SkillBench]]
