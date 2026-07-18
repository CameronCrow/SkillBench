# SkillBench judge rubric (pinned)

This file is injected verbatim into the judge prompt by `harness/judge.py`.
It is versioned here so rubric changes are visible in git history — never
improvise anchors per run. Applied identically to every condition; the judge
never learns which condition produced the diff.

Score each axis 1–5 against the anchors below. 4 and 2 are for outputs that
fall clearly between adjacent anchors. Every score must be supported by
quoted evidence — specific lines from the diff (or a statement of what is
absent from it). Correctness is NOT judged here; a separate test suite
handles it.

## Axis 1 — SOLID compliance

Did the refactor address the violation named in the task, without
introducing new ones?

- **5** — The named violation is resolved, and no new SOLID violations
  appear anywhere in the changed code.
- **3** — The named violation is partially addressed, or fully fixed at the
  cost of introducing a smaller new violation.
- **1** — The named violation is untouched, or the refactor made the design
  worse than the original.

## Axis 2 — Restraint

Did the refactor avoid over-engineering? (Judge against what the task
requires, not against what a maximal design could justify.)

- **5** — No abstractions beyond what the task requires; every new
  construct is motivated by the stated ask.
- **3** — One or two speculative touches: an unnecessary parameter, a
  premature extraction, a helper generalized past its single caller.
- **1** — New interfaces, layers, or patterns with a single implementation
  and no motivating requirement in the task.

## Axis 3 — Contract stability

Did the refactor touch public signatures it didn't need to?

- **5** — All externally-visible signatures (names, parameters, return
  shapes of anything a caller outside these files could depend on) are
  preserved, unless the task explicitly required otherwise.
- **3** — Minor unforced signature churn: a rename or parameter reshuffle
  the task didn't ask for, limited in scope.
- **1** — Gratuitous renames or reshapes of the public surface throughout.

## Output format

Respond with a single JSON object and nothing else:

```json
{
  "solid_compliance": {"score": <1-5>, "evidence": ["<quoted lines>", "..."]},
  "restraint":        {"score": <1-5>, "evidence": ["..."]},
  "contract_stability": {"score": <1-5>, "evidence": ["..."]}
}
```
