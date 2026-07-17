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

- **Judge rubric** — SOLID compliance, restraint (no gratuitous abstraction), contract
  stability, scored by an LLM judge against a fixed rubric.
- **Verification** — pinned tests still pass in the refactored copy.
- **Tokens** — input/output/cache tokens and USD cost, from the `claude -p --output-format
  json` usage block.
- **Time** — wall-clock duration of the run.
- **Lines of code** — added/removed/net diff size vs. the original fixture.

## Vision

A reusable harness, not a one-off — the same `harness/` scripts should work for
benchmarking any future skill against any future fixture corpus, not just this seed
comparison.

## Open questions

- How large should the fixture corpus grow past the initial pilot, and from which repos?
- Is CLI-flag-level isolation (`--safe-mode`, `--setting-sources`, `--plugin-dir`) durable
  across Claude Code versions, or does it need re-verifying periodically?
- Should the judge itself be run multiple times per fixture (self-consistency) given LLM
  judges are noisy?

## Current State

See `planning/PLAN_MAIN.md`.

## Related

- [[SkillBench]]
- solidifier: https://github.com/FernandoJRR/solidifier
- ponytail: Claude Code marketplace plugin (anti-over-engineering)
