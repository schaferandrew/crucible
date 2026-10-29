# Changelog

Crucible follows [semantic versioning](https://semver.org). The stable surface is the
test IDs, the chat/agentic sections, the harness names, the CLI and the results bundle
format (`crucible/schemas/results.schema.json`): an incompatible change to any of them is
a new major version. New tests, test version bumps, new areas and dashboard or CLI
improvements are minor releases; fixes that change no behavior anyone relies on are patches.
Every change that lands on `main` is a release (see [AGENTS.md](AGENTS.md)), and CI checks
that a pull request touching the code or tests bumps the version and adds its entry here.

## 2.4.0 (2026-10-29)

Groundwork for Suite v2. No score changes: every existing test scores exactly as in 2.3.0, and
runs recorded before this version export as before, with null in the new fields.

### Added

- **Every new run records its identity and provenance** in `meta.json`: a permanent `run_uuid`
  that survives renames and moves, and `provenance` with the Crucible version, the checkout's
  commit, whether `crucible/`, `prompts/`, `graders/`, `fixtures/` or `repos/` had uncommitted
  changes (so a run from an edited grader can be told apart), and a random `machine_id` minted
  once into `~/.crucible/machine.json` (never the hostname).
- **Model variant:** `model_variant` records who published the weights and their format
  (LM Studio's `gguf` or `mlx`; Ollama models are `gguf`, published by their namespace), the
  quantization, and `reasoning_resolved`, the level the model actually ran at (for `default`,
  what LM Studio reports as the model's default; null when it can't be told).
- **Cloud endpoint:** OpenRouter runs through `direct` record the upstream provider that served
  the request and the dated model it resolved to (`endpoint`), best effort; null when unknown.
- **Hardware key:** local runs record `hardware_key`, the device that ran the weights plus its
  memory (`m1-pro-32gb`, `rtx-5070-ti-16gb`, `2x-rtx-3090-24gb`, `cpu-ryzen-7-7700-32gb`).
- **`items` check and answer blocks** (not used by any test yet): scores only the fixed block an
  answer ends with (`ANSWERS:`, `ERRORS:`, ...; tolerant of case, bold, a missing colon and code
  fences; the last block wins), each expected item on its own, as the share of items passed.
  Normalizers: `number`, `money`, `name` (with aliases), `letter_set`, `line_number`, `datetime`
  and `ordering` (every pair in order). Per-item results are kept with the check's result.
- The results bundle carries the new run fields (`run_uuid`, `provenance`, `model_variant`,
  `hardware_key`, `endpoint`), all optional and nullable; the bundle format stays 2.
  `crucible publish` records the Crucible version that wrote the bundle (`source.crucible_version`).

### Changed

- Cloud runs export no hardware (`hardware: null`) instead of the machine that sent the request.

## 2.3.0 (2026-10-29)

### Added

- **CODE-16, React lead form (coding, temper, provisional).** A Next.js quote form that won't
  build (a Server Component with event handlers) and can't be typed into (no state), to be fixed
  and finished: required-field errors with `aria-invalid` and focus on the first error, and email
  that is accepted as people type it but saved strictly (trimmed, lowercased, invalid addresses
  never saved, whatever the client sends). 43 hidden tests in six levels that climb in difficulty.
- **Per-test scoring** (`scoring: per_test`): every hidden test weighs the same and the score is
  tests passed / all tests x 10, so a task can have any number of tests and never scores above 10.
  Each criterion shows the share of the 10 points its tests carry.
- **Isolated graders** (`grader.yaml` with `isolated: true`): hidden tests run in a fresh copy of
  the seeded repo that takes only the declared source paths from the model's workspace, so a model
  can't pass by editing package.json, the test config or node_modules. Dependencies are installed
  once per lockfile and cached in `~/.crucible/cache` (`CRUCIBLE_CACHE` overrides). A test that
  never runs, because its file fails to load, counts as failed.
- **`crucible grader <test>`** checks an isolated grader against its oracle: the reference
  solution must score 10, the seeded repo 0, and each calibration fixture (such as a form that
  submits but validates nothing) inside its declared range. `--write-expected` records the
  solution's test list.
- The results bundle lists each test's human-readable `name`, when it has one.

### Changed

- Seeded repos with a `package-lock.json` install with `npm ci`, so every run starts from the same
  dependency tree.

### Fixed

- pi runs no longer fail with "No API key found for lmstudio" when the user's `~/.pi/agent/auth.json`
  holds an empty stored key for that provider. Each run gets its own pi config directory, so only
  Crucible's provider settings apply.

## 2.2.0 (2026-10-26)

### Changed

- **KNOW-1** (fire truck color) is scored by checks instead of a judge: red is named, red is
  the first color named (variants afterward are fine), and the answer is a sentence or two
  (rubric version 2; existing runs are rescored, no rerun needed).
- `non_empty` checks accept `max_words`.

### Removed

- **Retired KNOW-2, KNOW-3 and KNOW-5 to KNOW-8** (enshittification, solar panels and the four
  home-repair questions). Open-ended explanations and advice need review to score, which is a
  future feature. Retired tests never run, never score, and are left out of the export with
  their runs; the prompts stay for when review exists.

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
