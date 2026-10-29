---
name: convert-grader
description: Convert a Crucible coding task (hidden tests in the model's workspace) to an isolated, per-test grader - artifacts, a reference solution, calibration fixtures, an oracle with seeded [0, 0], caps instead of free points, expected.json, rescoring the stored workspaces and checking the seeded repo for answer leaks. Use when asked to convert, fix or rewrite a coding task's grader (CODE-12 to 15), or when a coding task pays points for doing nothing.
---

# Convert a coding task to an isolated per-test grader

The old coding graders run their hidden tests inside the model's own workspace and pay points for things
the seeded repo already does ("existing tests still pass", "contract suite untouched"). gpt-oss-20b made
no changes to CODE-11 in 3 seconds and scored 2.0 (audit bug B3). An isolated, per-test grader fixes both:

- **Isolated:** the hidden tests run in a fresh copy of the seeded repo that takes only the source paths
  the model may change (`artifacts`). Its package.json, lockfile, test config and seeded tests stay as
  seeded, and node_modules is installed from the pinned lockfile.
- **Per test:** every hidden test weighs the same. The score is tests passed / all tests x 10.
- **Oracle:** `crucible grader <task>` grades the seeded repo (must score `[0, 0]`), the reference
  solution (`[10, 10]`) and each calibration fixture (its declared range). A grader isn't trusted until
  it passes.

Two worked examples: `react-lead-form` (formerly CODE-16, a single Next.js app) and
`editorial-review-workflow` (formerly CODE-11, an npm workspaces monorepo). Read both
`graders/<slug>/grader.yaml` files and `tasks/<slug>.yaml` before you start. The engine is
`crucible/graders.py`; its module docstring lists every `grader.yaml` key.

Touch only your task's files: `tasks/<slug>.yaml`, `graders/<slug>/`, its repo under `repos/` (only if
no other task shares it), `tasks/versions.lock.json` and a SUITE_CHANGELOG line. A grader that needs
something `graders.py` can't do is an engine change (a tool release, with tests and a CHANGELOG entry
under `## Unreleased`): stop and ask the orchestrating session first.

## 0. Before you start

- Copy `runs/` from the main checkout into your scratchpad (`cp -cR` clones on APFS, which is instant)
  and run `uv run crucible migrate --runs <copy>`. Work only on the copy; never touch the original.
- Note each stored run of the task: its old score (`scores/r<N>.hidden_tests.json`), task version
  (`meta.json` → `task.version`), and what it changed (`git -C workspace status --short`). Runs with
  no changes are the no-op runs that must end up at 0.
- `grep -n "^repo:" tasks/*.yaml`: is the repo shared? conduit-monorepo is shared by CODE-11 and
  CODE-12. Any file you add to a shared repo changes the other task's content hash, which forces it
  to a new version, and stored runs of a new version can't be rescored. So keep repo changes out of
  shared repos (see `lockfile` below).

## 1. grader.yaml

CODE-11's, annotated:

```yaml
isolated: true
# Source folders only. Tests, package.json files and configs stay as seeded, so the model can't
# weaken the seeded tests or change dependencies to pass.
artifacts: [apps/api/src, apps/web/src, packages/shared/src]
# conduit-monorepo has no lockfile and is shared with cursor-pagination, so the grader pins its own.
# Make it from the seeded package.json files: copy the repo somewhere, `npm install`, take package-lock.json.
lockfile: package-lock.json
# Where each hidden test file runs (vitest starts in that folder, the file goes in its test/hidden).
# First glob that matches wins; default ".". A web test would add "*.web.grader.test.tsx": apps/web.
test_roots:
  "*.grader.test.ts": apps/api
existing_tests: [apps/api, apps/web]                   # seeded tests that must still pass: the `existing` gate
unchanged: [apps/api/test/realworld.contract.test.ts]  # must be byte-for-byte as seeded: `contract_unchanged`
# The model's own new or changed tests (and the helpers it changed) must pass on its fix, and at least one
# must fail on the seeded source: one synthetic test in the pool, group `regression`
regression_tests: [apps/api, apps/web]
timeout: 600
oracle:
  solution: [10, 10]
  seeded: [0, 0]
  calibration:
    contract-only: [3, 5.5]         # the workflow as the contract spells it; nothing kept private
    direct-access-only: [4.5, 6.5]  # drafts 404 when opened, but leak through lists, tags, comments and edits
    breaks-existing-clients: [5, 5] # everything, but new articles default to drafts: capped at 5
```

Choosing `artifacts`: list every folder a correct solution has to touch, and nothing that grades the
model. Check the stored runs' `git status`: if a model's real fix lives somewhere you didn't list, either
list it or confirm the brief forbids it. In a workspaces monorepo the shared package is usually an
artifact: CODE-11's request schema lives in `packages/shared`, and zod strips an unknown `status` field
unless the model adds it there.

## 2. The rubric: per-test, with caps instead of free points

```yaml
scoring: per_test
rubric:
- criterion: Client contract
  hidden_tests: contract                          # a describe-group prefix
- criterion: Unapproved work stays private
  hidden_tests: 'rules: unapproved work stays private'
- criterion: Rules found, not given
  hidden_tests: 'rules: found in the brief'
- criterion: Regression tests
  hidden_tests: regression                        # one synthetic test: weighs 1/N, fails on an unchanged repo
- criterion: Existing tests still pass
  hidden_tests: existing
  cap_if_failed: 5                                # a cap, not points
- criterion: Contract suite untouched
  hidden_tests: contract_unchanged
  cap_if_failed: 4
```

- **Every hidden test must be picked by exactly one test criterion** (a describe-group prefix or a file
  name). `tests/test_graders.py::test_isolated_graders_are_complete` checks this.
- **Gates are caps.** `existing` and `contract_unchanged` pass on the seeded repo, so as points they pay
  for doing nothing. Under `per_test` they earn nothing; when they fail they cap the score. Give them
  `cap_if_failed` and no `max_score`.
- **A core requirement can cap too.** When a fixture that misses the task's point still scores high by tests
  (cursor-pagination's offset-cursor: 8.73, its cursors repeat under concurrent writes), give that test
  criterion `cap_if_failed`: its tests keep their points, and any one failing caps the score (6 there).
- **"Regression tests" is one test in the pool**, not points and not a cap: with `regression_tests` in
  grader.yaml the grader adds one synthetic result, "your new tests fail on the seeded code and pass on
  your fix". It weighs exactly one test, and an unchanged repo fails it (no new tests). A cap would punish
  too hard for one missing test. Any other criterion that isn't a hidden test has no place under
  `per_test`: drop it and say so in the SUITE_CHANGELOG entry. `max_score` is ignored, so leave it out.
- Remove `max_score` from the other criteria too. A criterion's weight is now its share of the tests,
  so **check the weights**: CODE-11's privacy criterion had 3 big tests out of 13. Splitting them into
  11 (one per way a draft can leak) gave it the weight it had in points.

## 3. Hidden tests: keep the intent, close the gaps

Keep every existing test's intent and name (renaming a test changes expected.json, which is fine during
a conversion but not after). Then look for what the old tests never checked:

- **Every test must fail on the seeded repo.** Easiest is a shared setup step that needs the feature: CODE-11's
  `draft()` helper asserts `status === "draft"`, so on the seeded repo every privacy test fails in
  `beforeEach`. A positive control ("the author still sees their draft") is fine as long as it needs the
  feature to set up.
- **One test per thing that can go wrong**, not one test looping over five endpoints. A per-test score
  should show which leak a model missed.
- **Under-tested criteria.** CODE-11 gained: own articles newest first and filtered by status; only the
  author submits; editing or deleting a hidden draft 404s (the brief's "not even that it exists" beats
  the RealWorld 403); no one rejects their own work; authors see the feedback in their own list.
- **Derive every new test from the prompt's words**, and don't test a call the brief leaves open. CODE-11
  doesn't test whether feedback survives resubmission, whether a non-author submitting gets 403 or 404 on
  an invisible draft, or whether a duplicate title's slug reveals a hidden draft.
- Test names must be the same on every run (no random values in `it()` titles). The oracle refuses names
  missing from expected.json.

## 4. Reference solution and calibration fixtures

- `solution/` is an overlay on the seeded repo: only the files a correct solution changes, at their repo
  paths. Build it in a scratch copy of the repo (`npm install`, write the fix, run the seeded tests and the
  hidden tests from the test root, `npx tsc -p <app>`), then copy the changed files in. It should
  implement the whole brief, the parts no hidden test checks included (CODE-11's web screens): it is the
  answer key a reviewer reads. With `regression_tests`, it needs its own test file that fails on the
  seeded code (CODE-11's `solution/apps/api/test/editorial.test.ts`), or it can't score 10.
- `calibration/<name>/` are **partial solutions with declared ranges**, at least two, each a realistic
  way to get it half right. Derive them from the solution with small, readable edits so the difference
  is the mistake and nothing else:
  - `contract-only`: the endpoints work, nothing is private (4.23)
  - `direct-access-only`: `GET /articles/:slug` 404s, but lists, tags, comments, favorites and edits
    still leak (5.38)
  - `breaks-existing-clients`: the full solution, except an article without a status becomes a draft.
    8.85 by tests alone, capped at 5 because the seeded contract suite fails. **Include one fixture like
    this: it proves the cap works.**
- Set each range around the score you get, wide enough to survive a small test change (±1) and narrow
  enough that fixtures don't overlap.

## 5. Record and check

```bash
uv run crucible grader <slug> --write-expected   # re-records expected.json from the solution (all must pass)
uv run crucible grader <slug>                    # the oracle: every case "ok"
uv run crucible versions --update                # rubric_version bumped; version only if prompt or repo changed
uv run --with pytest python -m pytest -q tests
```

- Bump `rubric_version`, not `version`, when only the grader and rubric change. `crucible checks` only
  rescores runs at the task's current `version`, so bumping `version` strands the stored runs.
- Re-run `--write-expected` after any change to the hidden tests, then re-run the oracle.

## 6. Rescore the stored workspaces

```bash
uv run crucible checks --runs <migrated copy> --task <slug>
```

That writes `scores/r<new>.hidden_tests.json` beside the old record in each run at the current version.
A run at an older task version is skipped: grade it directly (`graders.run(run_dir, prompt_def)` and
`checks.save_check_score`) and report it separately. Report old vs new for every run, and check:

- **every no-op run scores 0.** If one doesn't, a test passes on the seeded repo: fix the test.
- For each run that gained or lost, read which tests flipped (`grader_results.json`) and check they're
  earned. CODE-11: qwen3.5-9b's 2 passing tests come from its real partial implementation, and deepseek
  loses only the two self-review tests.
- `grader_results.json` → `regression` lists the model's test files and why they passed or failed.
- `grader_results.json` lists the artifacts taken, `existing`, `contract_unchanged` and errors. An error
  on every run usually means the install or a test root is wrong, not the models.

CODE-11, old (rubric 3) vs new (rubric 4):

| Run | Old | New | Tests |
|---|---|---|---|
| gemma-4-e4b (no-op) | 2.0 | 0.0 | 0/26 |
| gpt-oss-20b (no-op) | 2.0 | 0.0 | 0/26 |
| qwen3.5-9b | 2.43 | 0.77 | 2/26 |
| qwen3.6-35b-a3b | 4.96 | 4.62 | 12/26 |
| deepseek-v4.1-flash (task v2) | 9.33 | 9.23 | 24/26 |

The regression result agrees with the old grader on every run (qwen3.6 and deepseek pass it).

## 7. Check the seeded repo for answer leaks

The model sees the whole seeded repo. Grep it for the solution's key terms (CODE-11: review, editor,
draft, approve, reject, status, EDITORS) and read every hit. Comments, docs, CHANGELOGs, logs and test
names that state the fix or point at the bug are leaks. Fix those your task owns, and list the rest from
[the A2 report](../../../docs/v-next/plan/reports/A2-leak-scan.md) for your task. CODE-11's repo was
clean. Hidden graders, solutions and lockfiles live in `graders/`, which the workspace can't reach
(`runner.find_leaks` flags a transcript that read them).

## 8. Finish

- The task stays `status: provisional`. Never edit `suites/*.yaml`; cutting or patching a suite is its
  own job.
- SUITE_CHANGELOG `## Unreleased`: what changed for someone reading the leaderboard, including the
  old → new scores of the stored runs.
- Commit on your branch. Don't push. Report the oracle output, the test result, the rescoring table and
  anything you skipped.
