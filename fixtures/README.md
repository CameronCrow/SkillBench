# Fixtures

Hand-picked real files from repos Cameron owns — not synthetic snippets —
stripped of anything sensitive. Verify the pinned tests pass on `before/` at
creation time; the tests-pass metric is meaningless otherwise.

## Schema

```
fixtures/<slug>/
  before/         extracted source file(s) + any minimal supporting context
                  (interfaces, a sibling file) needed for the task to make sense
  tests/          pinned tests (from the source repo if they exist, else
                  hand-written characterization tests) — must still pass
                  post-refactor, and must never be edited by a run
  task.md         the refactor ask, phrased like solidifier's own examples
                  ("Review X for SOLID violations", "clean up this switch
                  statement"). NEVER names either skill — whether neutral
                  phrasing engages a skill is part of what's being measured.
  fixture.json    metadata (below)
```

## fixture.json

```json
{
  "source_repo": "irl-core",
  "source_ref": "<commit the files were extracted at>",
  "language": "python",
  "test_cmd": "python -m pytest tests/ -q"
}
```

`test_cmd` is required — the harness is language-agnostic and only knows how
to run this command. It executes with the scratch root as the working
directory, where `before/`'s files sit at the root and the pinned tests are
in `tests/`. Lay out `before/` and write `test_cmd` accordingly, and make
sure whatever toolchain it needs is installed on the machine running the
benchmark. Gotcha: the scratch root is the cwd but nothing puts it on the
import path — `python -m pytest tests/` handles this (`-m` prepends cwd),
but a bare `python tests/test_x.py` needs `PYTHONPATH=. ` in front.

Checklist for a new fixture:

1. Extract the file(s) into `before/` at the paths `test_cmd` expects.
2. Pin tests into `tests/`; run `test_cmd` against a scratch copy and
   confirm it passes on the untouched `before/`.
3. Write a neutral `task.md` naming a concrete violation/cleanup target.
4. Fill `fixture.json` with the source pin and `test_cmd`.
