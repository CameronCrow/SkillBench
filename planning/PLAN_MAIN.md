---
type: reference
tags: [repo/SkillBench]
up: "[[SkillBench]]"
---
# Planning

## Current State

Repo scaffolded from PROJECT_TEMPLATE. Phase 1 (harness + pilot fixture) in progress —
see [[Repos/SkillBench/planning/PHASE_1|PHASE_1]] for the design: 4-condition comparison
(baseline/solidifier/ponytail/both), symmetric isolation (identical flags every
condition, only the `--plugin-dir` set varies, both plugins vendored at pinned versions),
preflight probes that verify each condition's actual skill visibility, an anchored 1-5
judge rubric applied blind, and the metrics captured (judge profile, pinned tests with a
tamper guard, tokens/cost, num_turns, LOC delta as a behavioral signature). Scope revised
2026-07-20 to fit a usage budget (~75% of one subscription session window): two pinned
models (sonnet + opus) as a second grid axis, 1 rep per cell (was 3), 1 Sonnet judge pass
per artifact (was 3), corpus capped at 3 fixtures (was 10-15), harness cost cap on
cumulative `total_cost_usd` with Sonnet cells scheduled before Opus — results are
direction-consistency claims only, no per-cell gap sizes. Design revised 2026-07-17: the original
asymmetric flag scheme (`--safe-mode` baseline, default setting sources for ponytail)
compared a clean-room solidifier against ponytail-plus-the-entire-live-user-environment,
and ponytail's persisted mode state made "default" runs non-reproducible — see PHASE_1
for the full rationale.

## Related

- [[Repos/SkillBench/planning/PHASE_1|PHASE_1]]
- [[Repos/SkillBench/planning/TODO|TODO]]
- [[SkillBench]]
