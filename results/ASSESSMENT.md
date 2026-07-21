---
type: reference
tags: [repo/SkillBench]
up: "[[SkillBench]]"
---
# Pilot assessment — solidifier vs ponytail vs baseline vs both

**Run 2026-07-20 · 1 fixture · 4 conditions x 2 models x 1 rep · $14.40 total
(runs $10.81 + judging $3.59) · commits `ab0e547`, `e0bf585`**

## Setup

Fixture `neutral-text`: `llt/emit/neutral_text.py` from LLT (~300-line IL-to-AB
neutral-text emitter with real refactoring surface) plus four sibling modules and 46
pinned characterization tests. One task, identical for every cell, phrased like
solidifier's own trigger examples without naming either plugin:

> Review `llt/emit/neutral_text.py` for SOLID violations and refactor it accordingly.
> Do not change observable behavior: the tests in `tests/` must continue to pass, and
> the files under `tests/` must not be modified.

Pinned: solidifier @ `71fd5a9`, ponytail 4.7.0 (`PONYTAIL_DEFAULT_MODE=full`), CLI
2.1.216, `claude-sonnet-5` and `claude-opus-4-8`, Sonnet judge. Preflight probes passed
for all four conditions (isolation mechanics in `planning/PHASE_1.md`). Every plugin
cell's skill verifiably engaged — solidifier via an explicit `Skill` tool call in the
transcript, ponytail via its SessionStart hook banner; in the `both` cells the two
engaged together.

## Results

| condition | model | tests | turns | cost $ | LOC net | SOLID | restraint | contract |
|---|---|---|---|---|---|---|---|---|
| baseline | opus | pass | 14 | 1.86 | +96 | 5 | 4 | 5 |
| solidifier | opus | pass | 14 | 1.60 | +59 | 5 | 5 | 5 |
| ponytail | opus | pass | 7 | 1.35 | +74 | 4 | 5 | 5 |
| both | opus | pass | 11 | 1.40 | +53 | 5 | 5 | 5 |
| baseline | sonnet | pass | 14 | 1.29 | +137 | 5 | 4 | 5 |
| solidifier | sonnet | pass | 23 | 1.33 | +78 | 4 | 3 | 5 |
| ponytail | sonnet | pass | 10 | 0.83 | +82 | 4 | 4 | 5 |
| both | sonnet | pass | 11 | 1.16 | +113 | 4 | 4 | 5 |

All eight cells: pinned tests pass, `tests/` untouched (no tamper), contract stability 5.

## Findings

1. **The plugins changed cost and diff size, not judge-measurable quality.** Every cell
   produced a competent, behavior-preserving refactor. Judge axes barely separate the
   conditions; the mechanical signals do. Ponytail is the consistent efficiency lever:
   cheapest cell on both models ($0.83 / $1.35), half of baseline's turns on Opus.

2. **Solidifier's restraint language dominates its SOLID checklist.** Its diffs were
   among the smallest (+59 / +78 net), pure flat-function decomposition — no classes,
   no patterns. The un-plugined Opus baseline did the most speculative architecture
   (a `_LeafContext` class plus a chain-of-responsibility handler scheme). Both plugins
   mostly functioned as a leash on the model's own instinct to pattern-build.

3. **The `both` condition composes; it doesn't conflict.** Ponytail's injected ruleset
   did not stop the model invoking solidifier. On Opus, `both` produced the leanest
   diff of all eight cells (+53) at mid cost; both `both` cells did the same
   flat-helper decomposition shape as the single-plugin runs.

4. **Meta-finding (the most decision-relevant one): single-pass judge scores are noise
   at this scale.** A harness bug (a spurious scaffold-file deletion in every diff)
   forced a full re-judge of identical artifacts; scores moved 1–2 points and
   *direction vs baseline flipped* for several cells between the two passes
   (`judgments.contaminated.jsonl` kept as the evidence). Any conclusion resting on a
   1-point judge gap on this corpus is unsupportable; only tests/turns/cost/LOC are
   trustworthy signals at one fixture x one rep x one pass.

5. **Model beats plugin as a quality lever.** Opus's baseline already behaved with
   restraint; Sonnet over-built with or without ponytail. The plugins moved *how* the
   work happened far more than they moved its quality on either model.

## Verdict

On this task shape, ponytail bought the same (judge-indistinguishable) quality at
roughly 35% lower cost and half the turns — worth running on efficiency grounds alone.
Solidifier added nothing on top of that here, and `both` is a reasonable default if the
leanest diffs are the goal. **These are one-fixture directions, not conclusions**: the
review-shaped task on already-decent code gave restraint-focused plugins little to
prevent.

## What would change the picture

- 2 more fixtures (~$7 each all-in) to test direction consistency — including at least
  one task that *invites* over-building ("add support for X"), which stresses
  ponytail's actual thesis harder than a review-shaped ask.
- 3 judge passes with medians before trusting any judge-axis claim (finding 4).
- Blinding caveat noted in the plan stands: ponytail can leave `ponytail:` comments in
  output (none appeared in these eight diffs).
