# SkillBench

A harness for benchmarking Claude Code skills/plugins on real refactor tasks — how much
does a given skill actually change the output, and is the change good?

## Problem

Skills like `solidifier` (SOLID-principle refactoring) and `ponytail` (anti-over-engineering)
each carry a strong opinion about how Claude should refactor code. It's easy to install a
skill and *feel* like it helps; it's harder to know whether it actually produces better
diffs, and whether two skills with opposing instincts (a "make it more correct" nudge vs.
a "keep it minimal" nudge) reinforce or fight each other when both are active.

## Seed case

The first benchmark run compares four conditions on the same real-world refactor fixtures:

1. **baseline** — no skill active
2. **solidifier** — SOLID-refactor skill active
3. **ponytail** — anti-over-engineering skill active
4. **both** — solidifier + ponytail together

See `planning/PHASE_1.md` for the full design (fixture schema, condition isolation
mechanics, metrics captured).

## Metrics captured per fixture x condition

Each fixture x condition cell runs 3 times (single runs of a nondeterministic process
aren't data points); per-cell medians are reported with ranges.

- **Judge rubric** — SOLID compliance, restraint (no gratuitous abstraction), contract
  stability, each scored 1-5 against written anchors by an LLM judge that is blind to
  condition and runs 3x per artifact (median). No composite score — the axes pull in
  opposite directions on purpose, so results are a per-axis profile.
- **Verification** — pinned tests still pass in the refactored copy, with a guard that
  the run didn't modify the tests themselves.
- **Tokens** — input/output/cache tokens and USD cost, from the `claude -p --output-format
  json` usage block. Compared as totals (deployed cost, skill overhead included); the
  cache-creation/cache-read split is not interpreted.
- **Effort** — `num_turns` per run. Wall-clock duration is recorded but descriptive only
  (it's dominated by API latency variance).
- **Lines of code** — added/removed/net diff size vs. the original fixture. A behavioral
  signature (did each skill push output in its characteristic direction), not a quality
  score.
- **Skill engagement** — whether the intended skill actually fired during the run
  (solidifier is model-invoked, not always-on); runs where it didn't count toward a
  trigger rate and are excluded from the quality comparison.

Differences smaller than the judge's own run-to-run spread are reported as "no detectable
difference" — a valid outcome, not a failure.

## Vision

A reusable harness, not a one-off — the same `harness/` scripts should work for
benchmarking any future skill against any future fixture corpus, not just this seed
comparison.

## Open questions

- Which repos supply fixtures beyond the first candidates, and does the 10-15 fixture
  target hold once the pilot's variance numbers are in?
- Are 3 repetitions per cell enough, given the within-condition variance the pilot
  measures?
- How often does solidifier actually trigger on neutral task phrasing — and if the
  trigger rate is low, is that a finding about the skill or a prompt-shaping problem?

(Two earlier open questions are now settled in the design: judge self-consistency — the
judge runs 3x per artifact with median scoring; and isolation durability across CLI
versions — the preflight probe re-verifies flag behavior empirically after every
upgrade instead of assuming it.)

## Current State

See `planning/PLAN_MAIN.md`.

## Related

- [[SkillBench]]
- solidifier: https://github.com/FernandoJRR/solidifier
- ponytail: Claude Code marketplace plugin (anti-over-engineering)
