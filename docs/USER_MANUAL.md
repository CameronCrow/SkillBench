---
type: reference
tags: [repo/SkillBench]
up: "[[Repos/SkillBench/docs/DOCS_MAIN|DOCS_MAIN]]"
---
# USER MANUAL

How to run a SkillBench benchmark end-to-end. The harness is pure-stdlib
Python (3.11+); the only other requirements are `git`, the `claude` CLI, and
`node` on PATH (ponytail's hooks silently no-op without node — the
engagement detector will catch it, but the runs would be wasted).

## One-time setup (on the machine with the plugins)

1. **Vendor the pinned plugins** into `.cache/` (gitignored):

   ```sh
   python -m harness.vendor \
     --solidifier-ref <commit-sha-or-tag> \
     --ponytail-source <path-to-ponytail-in-your-marketplace-cache> \
     --ponytail-version <its-version-string>
   ```

   This clones solidifier from GitHub at the pinned ref and copies your
   local ponytail, recording both pins (commit SHA / version + tree hash) in
   `.cache/vendor.json`. Every run embeds that manifest in its metadata.

2. **Preflight** — verify each condition's actual skill visibility:

   ```sh
   python -m harness.preflight --model <pinned-model>
   ```

   If a user-scope customization leaks into the probes, add
   `--scratch-config` (points `CLAUDE_CONFIG_DIR` at a throwaway dir) and
   then pass the same flag to every `harness.run` invocation. Re-run
   preflight after every CLI upgrade — `run.py` refuses to score runs if the
   stamp's CLI version doesn't match the installed one.

3. **Create a fixture** — see `fixtures/README.md` for the schema and
   checklist.

## Running a benchmark

```sh
# all 4 conditions x 3 reps on one fixture
python -m harness.run --fixture fixtures/<slug> --model <pinned-model>

# judge every rep (blind, 3 passes each, median)
python -m harness.judge --run results/<run-id> --judge-model <pinned-model>

# report
python -m harness.aggregate --run results/<run-id>
```

`harness.run` is resumable: re-running the same `--run-id` skips completed
reps. Output lands in `results/<run-id>/<fixture>/<condition>/rep-N/`
(transcript, result, after/ copy, diff, metrics) with `report.md` and
`summary.json` at the run root after aggregation.

## Reading the report

- Judge scores are a **per-axis profile** (SOLID compliance, restraint,
  contract stability) — deliberately no composite score.
- Pairwise gaps within the judge's own spread are printed as **"no
  detectable difference"** — a valid outcome.
- Reps where the intended skill never engaged, or where the run edited the
  pinned tests (**tainted**), are excluded from the quality comparison but
  reported (trigger rate / taint count).
- A single-fixture run is stamped as **pilot — variance measurement only**;
  it supports no conclusions about the skills.

## Related

- [[Repos/SkillBench/docs/DOCS_MAIN|DOCS_MAIN]]
