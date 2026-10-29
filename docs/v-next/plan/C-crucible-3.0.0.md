# C: Crucible 3.0.0

**One Opus session, one writer:** it touches nearly every file, so nothing else edits crucible
while it runs. **Branch:** from the A1 branch (Crucible 2.4.0). Design references: audit
sections 2 (naming and the ID map), 3 (bundle contract), 5 (suite versioning and release
rules), 6 (run data model), 7 (agent rules and skills), and decisions D1 to D13 in section 8.

**Scoring must not change (D10).** 3.0.0 renames and restructures; every existing task keeps
its content and scoring. The bug fixes and task rewrites are package D, after this merges.

## Scope, in this order

1. **Task identity**
   - `docs/task-id-map.json` from audit section 2, chained through `docs/test-id-map.json` so
     every earlier ID resolves in one lookup.
   - `prompts/<ID>.yaml` → `tasks/<slug>.yaml`, `test_id:` → `id:`, `aliases: [<old ID>]`, and
     `name:` on every task.
   - Graders move to `graders/<slug>/`, with no tier folder.
   - Replace `validate_area`'s ID regex with the slug rules in section 2.
   - The version lock is re-keyed by slug. **Content and rubric hashes must not change:** exclude
     the ID fields from the hash, or prove the new hashes map one-to-one onto the old ones. No
     task gets a version bump from the rename.
2. **"Task" everywhere**
   - Change the CLI, menus, help text, console output and docs, per the surface table in
     section 2. "Hidden tests", unit tests and `npm test` keep their names.
   - Selectors accept slugs and old IDs; an old ID prints a one-line notice.
3. **Taxonomy as suite data:** areas, categories, weights and tiers move from `crucible/taxonomy.py`
   into `tasks/taxonomy.yaml`; code reads them from there.
4. **Run layout and record**
   - New runs are written to `runs/<model_slug>/<task>/<timestamp>/`.
   - `meta.json` follows the section 6 record, mapping A1's 2.4.0 fields.
   - Score records and status records are separate, append-only files next to the run.
   - Score records carry raw counts plus the normalized score.
5. **`crucible migrate [--dry-run] [--runs DIR]`**
   - Step one writes a legacy `run_uuid` into every `meta.json` that lacks one:
     uuid5 of the machine (`host:<hostname>`) and the pre-rename `run_id`.
   - Then it renames IDs, moves folders to the new layout, and splits `check_results.json` and
     `grader_results.json` into score records at their recorded rubric version.
   - It also backfills `publisher` and `format` where the model key implies them, and sets
     cloud runs' hardware to null.
   - `--bundle <file>` converts a published format-2 bundle into records.
   - It is idempotent: running it twice changes nothing.
6. **Bundle format 3 and publishing (D6)**
   - Write the catalog per suite and one file per run under `_data/crucible/runs/<yyyy-mm>/`.
     Score and status records go next to it; outputs go outside `_data`.
   - `crucible publish` is additive and idempotent, keyed by `run_uuid`.
   - `publish --check` validates a folder and recomputes content hashes.
   - Keep `crucible export --format 2` (the old single bundle) working until the site switches
     (step 8), so the live dashboard isn't stranded.
7. **Suites**
   - `suites/v1.yaml` from `releases/2026.11.yaml` (remove `releases/`), plus
     `crucible suite cut | patch | verify`.
   - `SUITE_CHANGELOG.md` with Suite v1 described and an `## Unreleased` section.
   - Suite membership is derived from task versions, not stored on runs.
8. **Release rules**
   - The two-track AGENTS.md and CLAUDE.md text and the CI job, both drafted in section 5.
   - Release notes go to `docs/versioning.md`, plus `docs/scoring.md`, `docs/data-model.md` and
     `docs/bundle-format.md`, written from audit sections 3, 5 and 6. `docs/test-tiers.md`
     becomes `docs/task-tiers.md`.
   - The README is updated, including the `items` check that A1 added.
9. **Skills:** `calibrate-task` and `cut-suite`, and an updated `publish-results` (section 7).
   `add-task` and `convert-grader` are written in package D, from its first two conversions.
10. **Release:** version 3.0.0, `uv lock`, and a `## 3.0.0` CHANGELOG entry under "Breaking" that
    lists every incompatible change and points to `crucible migrate`.

## Not in scope

- No task content or scoring changes: no rewrites, no empty-answer fix, no grader conversions, no
  retirements. All of that is package D.
- No portfolio changes and no model runs.

## Real data

`runs/` and `runs-archive/` are gitignored and hold real results that exist only on this
machine; your worktree has neither.
- Copy them from `/Users/schafer/Developer/crucible/` into your own scratch directory and
  develop and test `crucible migrate` only on that copy.
- Never modify the originals. Migrating the real folders is a separate step Andrew approves.

## Done when

- `uv run --with pytest python -m pytest -q tests` passes, with tests for:
  - the ID map, including chained old IDs
  - selectors accepting slugs and aliases
  - slug validation and lock hashes unchanged by the rename
  - `migrate` on a fixture tree: a dry run changes nothing, migrating twice changes nothing, and
    legacy UUIDs are stable
  - `publish` writing twice adds nothing the second time
  - `suite cut`, `patch` and `verify`
  - the CI script logic
- On your copy of `runs/`: after `crucible migrate`, every run has a `run_uuid`, and every
  run's score matches its pre-migration `check_score` (compare by legacy `run_id` through the ID
  map). Publishing the copy twice into a scratch folder gives identical trees, and
  `publish --check` passes.
- `crucible export --format 2` on the migrated copy reproduces today's bundle scores for the live
  site.
- `crucible versions` is clean, and `crucible suite verify` passes against `suites/v1.yaml`.
- Committed on your branch; not pushed. Report with test output, the score comparison, and
  every place you departed from the audit, with the reason.
