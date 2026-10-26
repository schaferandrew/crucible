# Changelog

Crucible follows [semantic versioning](https://semver.org). The stable surface is the
test IDs, the chat/agentic sections, the harness names, the CLI and the results bundle
format (`crucible/schemas/results.schema.json`): an incompatible change to any of them is
a new major version. New tests, test version bumps, new areas and dashboard or CLI
improvements are minor releases.

## 1.0.0 (2026-10-26)

### Breaking

- **Test IDs renamed.** Every ID is now its area's four letters, a hyphen and a number
  (`C11` → `CODE-11`, `W2b` → `WRIT-2b`, `E4` → `TASK-2`). Run folders, the version lock and
  graders were migrated; [docs/test-id-map.json](docs/test-id-map.json) maps every earlier ID.
- **Chat and agentic tests are separate.** Chat tests always run with `direct` (one API
  call, no tools); agentic tests run with `opencode` or `pi`. Runs that mix them (a chat
  test through an agent harness) no longer count.
- **The `pool` harness is removed.**
- **Windows is no longer supported**; Crucible runs on macOS and Linux.
- **Results format 2.** `crucible export` and `crucible publish` write `format_version: 2`
  (sections, areas, outcomes, per-criterion scores, hidden-test results, output,
  reasoning level).
- **Reasoning level is part of a model's identity.** Runs at a non-default level live in
  `<model>@reasoning-<level>` folders and count as a separate model.

### Added

- **`crucible run` asks what to run** when it isn't given a test: the model (a
  type-to-filter picker over every provider's live model list), section, area, tier,
  harness and reasoning level. Menus take arrows, numbers or first letters; the plan ends
  with the one-line command that repeats it.
- **Areas**: writing, math, geography, history, general knowledge (chat); coding,
  research, everyday tasks (agentic).
- **New tests**: math, geography and history at all three tiers; a news aggregation
  accuracy test; calendar scheduling tests against a mock Google Calendar MCP server
  (`TASK-4` to `TASK-6`).
- **Automatic scoring.** Programmatic checks score chat tests on the spot, including
  `grounded_numbers` (every figure must come from the sources). Forge coding tests run
  hidden acceptance tests in the finished workspace, check that the repo's own suite
  still passes, that the contract suite is untouched (else the score is capped at 4), and
  that the model's new tests catch the bug on the seeded code.
- **`--reasoning off|low|medium|high`**, sent the way each provider understands it.
- **Run outcomes** (`completed`, `failed`, `no_answer`, `timeout`, `harness_error`);
  harness errors are marked invalid.
- **Safety**: every test stops at 20 minutes (`--allow-long` lifts it); a suite stops
  after two setup failures in a row and resumes with `--skip-done`; dev servers an agent
  leaves running are stopped; Ctrl+C discards the unfinished run.
- **Live progress** while a chat test streams, and the model's reasoning saved to
  `reasoning.txt`.
- **`crucible publish`** writes this machine's results bundle into the portfolio's data
  folder, validated against the schema; a `publish-results` skill documents the steps.
- Tiers (Spark, Temper, Forge), test versioning with a lock file and releases, workspace
  isolation with leak detection, run cost, shared web tools, and environment capture
  (hardware, quantization, LM Link).

### Changed

- The CLI never asks you to grade a run. Review by a person (`crucible score`) or an AI
  judge (`crucible judge`) is a future feature; automatic scores always win over them.
- Deterministic scores weight criteria by their points.

## 0.1.0

First version: `crucible run`, `score` and `report` with the opencode and direct
harnesses.
