# C: Crucible 3.0.0 (outline; refined after A1 merges)

One Opus session, one writer: it touches nearly every file.

- Task slugs and `aliases` from the audit's ID map (section 2); `prompts/` → `tasks/`,
  `test_id` → `id`, "task" in the CLI, menus, help, docs; aliases accepted with a notice.
- Graders move to `graders/<slug>/`; run layout `runs/<model>/<task>/<timestamp>/`.
- `crucible migrate`: legacy UUIDs (uuid5 of machine + pre-rename `run_id`) written first, then
  renames and moves; score records split from `check_results.json` / `grader_results.json`.
- Bundle format 3 (section 3): catalog per suite, run / score / status records, one file per run
  (D6); additive, idempotent `crucible publish`; raw + normalized scores.
- Suites: `suites/v1.yaml` from `releases/2026.11.yaml`, `crucible suite cut | patch | verify`,
  `SUITE_CHANGELOG.md`, `tasks/taxonomy.yaml`.
- Two-track CI and the AGENTS.md / CLAUDE.md rules (section 5); `docs/versioning.md`,
  `scoring.md`, `data-model.md`, `bundle-format.md`; skills `calibrate-task`, `cut-suite`,
  updated `publish-results`.
- Afterwards (Haiku): verify the ID map was applied everywhere, regenerate generated docs.
