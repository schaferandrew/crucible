# Changelog

Crucible follows [semantic versioning](https://semver.org). The stable surface is the
test IDs, the chat/agentic sections, the harness names, the CLI and the results bundle
format (`crucible/schemas/results.schema.json`): an incompatible change to any of them is
a new major version. New tests, test version bumps, new areas and dashboard or CLI
improvements are minor releases; fixes that change no behavior anyone relies on are patches.
Every change that lands on `main` is a release (see [AGENTS.md](AGENTS.md)), and CI checks
that a pull request touching the code or tests bumps the version and adds its entry here.

## 2.1.0 (2026-10-26)

### Added

- **Evals area (`EVAL-1` to `EVAL-3`, chat).** Tests whether a model can grade an agent's
  response: it sees the task, the criteria and the response, reasons, and ends with
  `GRADE: <0-10>`. A new `grade_closeness` check scores the grade against a hidden reference
  grade, with points following a bell curve in the distance (full for an exact match, 64% two
  points off, 6% five off). The reasoning is kept with the run's output. The tests are `active`.

## 2.0.0 (2026-10-26)

### Breaking

- **Chat runs refuse a too-small context.** On a local server, chat tests now need a 32k
  loaded context (8k with `--reasoning off`), as agentic tests already did. Runs that used
  to start on an 8k context (and could only fill it reasoning) are refused.
- **`--reasoning` only takes the levels a model accepts.** LM Studio models report theirs
  (qwen3.5 and Gemma 4: `off`; gpt-oss: `low`, `medium`, `high`), and a level a model
  doesn't take, or any level for a model that doesn't reason, is refused.

### Added

- **`context_limit` outcome** for a response that filled the model's context: invalid when
  the loaded context was below the minimum (a setup problem), counted otherwise (a runaway,
  such as a thinking loop). Providers record why each response ended.
- **The reasoning question** in `crucible run` appears only for models that reason, with only
  their levels, read from LM Studio's `/api/v1/models`, OpenRouter's supported parameters or
  Ollama's capabilities.
- **LM Link device detection:** runs record which machine actually served the model (from
  `lms ps` and `lms link status`), and the export reports that machine's hardware.
- **`AGENTS.md` and `CLAUDE.md`** with the rules for coding agents, and a `release-notes` CI
  check that every pull request touching the code or tests carries a version bump and a
  changelog entry.

### Changed

- **MATH-4** (the seating logic puzzle) is scored by checks instead of a judge: the prompt
  asks for the full seating and an `ANSWER:` line (test version 2; older runs stop counting).

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
