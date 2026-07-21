# Judge instructions

You are judging one refactoring attempt. You are given the task that was assigned, the
original source files, and the unified diff the attempt produced. Judge the diff as-is.

Score three axes, each 1-5, against the anchors below. For each axis you MUST quote the
specific lines from the diff (or note their absence) that justify the score. Do not
guess at intent; judge only what the diff shows.

## Axis 1 — SOLID compliance

Did the change address the design problems in the target file without introducing new
ones?

- **5** — Real design violations in the target file are resolved (or the diff correctly
  concludes no change was warranted, when the file was already sound); no new violations
  appear.
- **3** — Partially addressed: a genuine violation is improved but incompletely, or
  fixed at the cost of a smaller new violation.
- **1** — Violations untouched, or the refactor made the design worse (new coupling,
  duplicated logic, responsibilities more tangled than before).

## Axis 2 — Restraint

Did the change avoid over-engineering?

- **5** — No abstractions beyond what the task requires; every new construct has a
  concrete, present justification visible in the code.
- **3** — One or two speculative touches: an unnecessary parameter, a premature
  extraction, a helper with one call site that clarifies nothing.
- **1** — New interfaces, layers, registries, or patterns with a single implementation
  and no motivating requirement in the diff.

## Axis 3 — Contract stability

Did the change avoid touching public surface it didn't need to?

- **5** — All externally-visible names and signatures (module-level functions, class
  names, their parameters) preserved, unless the task required otherwise.
- **3** — Minor unforced churn: a renamed public function, a reordered or added
  parameter without need.
- **1** — Gratuitous renames or reshapes of the public surface.

## Output format

Respond with ONLY a JSON object, no prose before or after:

```json
{
  "solid":     {"score": <1-5>, "evidence": "<quoted lines + one-sentence reason>"},
  "restraint": {"score": <1-5>, "evidence": "<quoted lines + one-sentence reason>"},
  "contract":  {"score": <1-5>, "evidence": "<quoted lines + one-sentence reason>"}
}
```
