---
name: cut-suite
description: Cut a new Crucible suite (promote and retire tasks) or a suite patch (pin rubric fixes and rescore). Use only when the user explicitly asks to cut, release or patch a suite.
---

# Cut or patch a suite

Suites say which tasks are scored, at which version and rubric version, with which weights
([docs/versioning.md](../../../docs/versioning.md#suites)). Only `crucible suite cut` makes a task active,
and only `crucible suite patch` publishes rubric fixes to a suite. **Do this only when the user asks**, and
as its own PR.

## Which one

- **Patch** (`v2` → `v2.1`): only `rubric_version`s changed since the latest suite (check and grader fixes).
  Stored runs are rescored; nothing needs a rerun.
- **Cut** (`v2` → `v3`): anything else: promoting or retiring tasks, a task `version` bump, tier, category,
  area or weight changes, slug renames, gate or coverage thresholds.

## Checks before

```bash
pgrep -fl "crucible run"           # nothing running in this checkout
uv run crucible versions           # the lock is clean
uv run crucible suite verify       # the current suite holds
uv run crucible suite list
```

For each task to promote, confirm the promotion criteria and show the user the evidence:
- runs from at least one small local, one mid-size and one frontier model (the `calibrate-task` skill),
- scores that aren't all equal,
- for a grader task, `uv run crucible grader <task>` passes (the cut runs it again),
- its checks were validated against a reference answer (10), an empty answer (0) and real wrong answers.

`SUITE_CHANGELOG.md` must say what's changing under `## Unreleased`, for someone reading the leaderboard:
what was added, retired or fixed, and whether old runs were rescored, kept or stop counting. Write it with
the user if it's empty; the cut refuses without it.

## Cutting

```bash
uv run crucible suite cut v3 --promote <task>... --retire <task>...
uv run crucible suite patch                      # rescoring runs/ unless --no-rescore
```

The cut sets `status:` in the task files, writes `suites/v3.yaml` from the lock and moves `## Unreleased`
under `## Suite v3 (<date>)`. Then:

```bash
uv run crucible versions && uv run crucible suite verify
uv run --with pytest python -m pytest -q tests
```

Commit the task files, the new suite file and SUITE_CHANGELOG.md together, on a branch, and open the PR only
when the user says so. A task-only PR needs no Crucible version bump. Never edit an existing
`suites/*.yaml`; if a cut was wrong, cut the next one.

After it merges, publishing (the `publish-results` skill) writes the new suite's catalog.
