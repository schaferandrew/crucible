# Changelog

Crucible's own releases: the tool people install. What changed in the benchmark itself (which tasks
are scored, at which versions) is in [SUITE_CHANGELOG.md](SUITE_CHANGELOG.md).

Crucible follows [semantic versioning](https://semver.org). The stable surface is the CLI and its
flags, the task YAML format, check and grader formats, harness names, the run record and bundle
formats, and the identity rules (the slug format, `run_uuid`). An incompatible change to any of them
is a new major version; new features, check types, harnesses and CLI or dashboard improvements are
minor; fixes that change no behavior anyone relies on are patches. Which tasks exist, and their
slugs, tiers and weights, are suite data, not part of this surface. Every change to `crucible/`,
`pyproject.toml` or `tests/` is a release, and CI checks it bumps the version and adds its entry
here ([docs/versioning.md](docs/versioning.md)).

## 3.3.0 (2026-10-29)

The engine pieces for Suite v2's second wave of converted tasks: Python graders, checks that read what an
app recorded rather than what the model says, and `items` kinds that read a whole document or a written JSON file.

### Added

- **Python graders (`runner: pytest` in grader.yaml):** an isolated grader can run hidden pytest files
  (the grader folder's `test_*.py`, with any other `*.py` there as support code) against the model's
  artifacts in a fresh copy, starting from an empty folder for a `repo: null` task. Each test's group is
  its class's docstring. `own_tests: <folder>` adds one test to the pool: the model's own tests in that
  folder (pytest, else unittest) run and pass. pytest comes from the running Python, else `uv run --with pytest`.
- New check types `audit_log` and `workspace_unchanged`, for scoring a task from what the app recorded rather
  than what the model says. `audit_log` reads a hash-chained JSONL log in the workspace (a line that was
  edited, dropped or hand-written voids the log) and requires events in order, with values shared across
  steps (`$name`) and events that must not follow. `workspace_unchanged` compares paths with the seeded
  commit (git), optionally requiring that the app was used. Both fail an empty answer like every check.
- Isolated graders: the model's own tests may be JavaScript (`.test.js`, `.spec.mjs`, ...) and
  `regression_tests` / `artifacts` accept `.` (the whole repo); before, a repo-root test folder never matched.
- **`items` check, whole-document kinds** (use with `header: null`): `sections` (one item per `#` heading, present and
  in order), `language` (Spanish or not, by function-word share), `mention` (titles from `fixtures/mock-data`
  mentioned in the reply) and `json` (ops on a JSON file: `parses`, `listed`, `listed_by_day`, `count`, `all_valid`, `each_nonempty`,
  `no_conflict`, `no_outside`; the right slots are computed from a fixture calendar). Block kinds (`pattern`,
  `each`, `count`, `distinct`, `language`) take `section:` to read one heading's lines, and `top_level: true` to
  count only outermost list items.
- **`grounded_numbers` `sources:`:** fixture files whose numbers the answer may quote (timestamps count; whole hours
  also as 24-hour times).
- `add-task/validate.py` takes `files:` per case for tasks whose checks read a written file.

## 3.2.0 (2026-10-29)

The engine pieces for Suite v2's first wave of converted tasks: more ways for the `items` check to read
an answer block, checks for cited prose, calendar answers and the agent's tool calls, and caps on a
per-test grader's core requirement.

### Added

- **`cited_paragraphs` check:** scores a prose answer by the numbered sources its paragraphs cite
  (`[S1, S2]`, `(S3; S4)`, `[S9 opinion]`): a source cited in exactly one paragraph (optionally together
  with named others and no strangers), cited as opinion, or not cited at all; patterns required or
  forbidden in the paragraphs citing given sources; patterns forbidden anywhere. One item per entry,
  equal weight, like `items`.
- **`items` check, whole-block kinds:** `pattern` (a regex is found in the block, or with `absent: true`
  is not; `part: name` searches only the entries' names), `each` (every entry matches), `count`
  (exactly `expect`, or `min`/`max` entries), `distinct` (no name twice) and `subset` (every entry's name
  is in another block, `source:`), for answers that are an email, a paragraph or a list rather than short
  values. A check can set `multiline: true` so blank lines don't end its block. An empty block fails
  every such item.
- **`items` check, for per-item rescoring of chat tasks:** `header: null` (no header line; the reply's own
  labelled lines are the block), `key` as a list of accepted labels (`[Türkiye, Turkey]`), a `name_set`
  kind (one item per name that must be on a labelled line and not on the lines in `not_in`), and `find`
  (read the line that names an event, with aliases, instead of a numbered label; for scoring a year per
  event whatever order the lines are in).
- **`time_options` check:** scores an `OPTIONS:` block of `YYYY-MM-DD HH:MM <time zone>` lines against a
  mock-calendar dataset. The ground-truth start times are computed from the dataset (`free_starts()`),
  not listed in the task. Item kinds: `in_set` (every option a distinct valid start), `count`,
  `includes_any` (a valid option matching a weekday, date or time), `not_before_now`, `avoid` (dates and
  date ranges) and `latest_end`. Zones are read by name (`CDT`, `Central`, `America/Chicago`) or offset.
- **`tool_calls` check:** scores what the agent did, from the run's `session.json` (pi and opencode
  formats) rather than its reply: a tool was called, and for `get_freebusy` with `covers`, every
  calendar of a dataset's team was named. `checks.session_tool_calls()` and a `tool_calls=` argument to
  `run_checks()` expose the calls.
- **`cap_if_failed` on a per-test criterion:** under `scoring: per_test`, a test criterion (not only the
  `existing` and `contract_unchanged` gates) can carry `cap_if_failed`. Its tests keep their points, and
  when any one of them fails the score is capped. cursor-pagination caps cursor correctness at 6.

### Changed

- **Mock calendar data is part of a task's content hash.** `mock-calendar:<dataset>` hashes the dataset
  JSON and the server (`calendar_server.py`), so editing either shows up as drift in `crucible versions`
  (it was not hashed before). Only the three calendar tasks are affected.
- An empty answer fails every item of every item-scoring check (`items`, `cited_paragraphs`,
  `time_options`, `tool_calls`) through one code path, so each keeps its item count in the score record.

## 3.1.0 (2026-10-29)

Scoring fixes and the first converted tasks for Suite v2: empty answers score 0, answer blocks
can score detection tasks, and isolated graders handle workspaces monorepos with caps instead of free
points.

### Added

- **`items` check:** a `line_set` kind (each numbered line in `of` listed in the block or left out, one
  item per line, for detection tasks with accurate controls) and a `year` normalizer (every year in the
  value must be an expected one, so "18 June 1815" is 1815 and "1812 or 1815" fails). A value written as
  `wrong → right` (or `->`, `=>`) is scored on what follows the arrow, and block lines may be labelled
  `Line 4`, `Claim 4` or `Sentence 4` as well as `4`.
- **Isolated graders for npm workspaces monorepos.** A `grader.yaml` can now declare `lockfile` (a
  lockfile kept with the grader, for a seeded repo that has none), `test_roots` (which folder each
  hidden test file runs in, e.g. `apps/api`), `existing_tests` (folders whose seeded tests must
  still pass on the model's source), `unchanged` (files the model must leave as seeded) and
  `regression_tests` (the model's own new tests must pass on its fix and catch the bug on the
  seeded code, scored as one more test in the pool). The
  install is cached per workspace manifest, and the workspace's own package links resolve to the
  model's source in the grading copy, not to the cache.
- **Caps under per-test scoring.** With `scoring: per_test`, the `existing` and `contract_unchanged`
  criteria are caps (`cap_if_failed`), never points: they pass on the seeded repo, so a run that
  changes nothing no longer earns them, and the score record lists them under `capped_at`, not as
  criteria.

### Fixed

- **An empty answer scores 0.** Every check type now fails an empty or whitespace-only answer (or an
  empty `file:`), with the detail "no answer to check". Before, `list_items` checks with `distinct` or
  `each_matches` passed on a list of 0 items, so a run that timed out with no output earned points:
  4.0 on novel-character-names, 2.0 on names-for-one-character. Those two tasks get a rubric bump so
  their stored runs are rescored; no other stored score changes.
- An `items` check with no answer block (or no answer) now reports every item it would have scored,
  each letter of a `letter_set` and each pair of an `ordering` included, so the item total is the same
  whether or not the block was found.

## 3.0.0 (2026-10-29)

Tests become tasks with permanent slugs, runs get a permanent identity and a new layout, and results
publish as one file per run. **No score changed:** every task keeps its content, rubric and versions,
and every stored score is carried over as it was. Runs from earlier versions must be migrated once
with `crucible migrate` (try `--dry-run` first) before any other command reads them.

### Breaking

- **Task IDs are slugs.** `CODE-16` is now `react-lead-form`: every task has a kebab-case `id`, a
  `name` and its earlier IDs as `aliases`. Old IDs still work on the command line and print the new
  name; [docs/task-id-map.json](docs/task-id-map.json) maps every earlier ID (including the 0.x ones,
  `C11` → `CODE-11` → `editorial-review-workflow`) in one lookup.
- **Task files** moved from `prompts/<ID>.yaml` to `tasks/<slug>.yaml`; the key `test_id:` is now
  `id:`. The version lock is `tasks/versions.lock.json`, keyed by slug. Graders moved from
  `graders/<tier>/<ID>/` to `graders/<slug>/`, and `grader:` names the slug.
- **"Task" everywhere:** the CLI, menus, help and output say task; `crucible checks --test` is
  `--task`; `crucible grader <task>`. New: `crucible task list` and `crucible task show <task>`.
- **Run layout:** new runs are written to `runs/<model>/<task>/<timestamp>/` (no category folder).
- **`meta.json` is the run record** ([docs/data-model.md](docs/data-model.md)): `run_uuid`, `run_path`,
  `task {id, version, rubric_version, content_hash, rubric_hash, alias}`, `harness`, `model` (base,
  publisher, format, quant, reasoning requested and resolved, variant key), `endpoint` (local or
  cloud, provider, upstream), `hardware` (null for cloud runs), `outcome`, `metrics`, `provenance`,
  and `local` for what is never published. The 2.4.0 fields `model_variant`, `hardware_key` and
  `endpoint` moved into `model`, `hardware` and `endpoint`.
- **Scores are score records**, `scores/r<rubric_version>.<method>.json` in the run folder, with the
  raw counts (`passed`, `total`, `unit`) and the normalized score; `check_results.json` is no longer
  written. Invalidations after the fact are status records (`status.json`, `crucible status <run>
  --invalid REASON`).
- **Bundle format 3** ([docs/bundle-format.md](docs/bundle-format.md)): `crucible publish` writes a
  catalog per suite and one file per run, score record and status record under `_data/crucible/`,
  and outputs outside `_data`. It is additive and idempotent, keyed by `run_uuid`, validates every
  file, and `crucible publish --check <dir>` validates a folder and recomputes content hashes. It no
  longer writes `<machine>.json`; `crucible export --format 2` still writes that single-file bundle
  for the live dashboard until it switches.
- **Suites replace releases.** `releases/2026.11.yaml` is gone; `suites/v1.yaml` pins the active
  tasks as the dashboard scored them on 2026-10-28 (the release is kept inside it for the record).
  `crucible versions --release` and `--backfill` are removed; use `crucible suite` and
  `crucible migrate`.
- **Taxonomy is suite data:** areas, categories, weights, tiers and statuses moved from
  `crucible/taxonomy.py` to `tasks/taxonomy.yaml`. The area prefixes (`WRIT`, `CODE`, ...) are gone.
- Changing a grader task's rubric hash: the hash no longer includes the grader folder's path (it held
  the old ID). The six grader tasks' `rubric_hash` values changed once, one to one; no version moved.

### Added

- **`crucible migrate [--dry-run] [--runs DIR] [--machine NAME]`** moves runs from before 3.0.0 into
  the new layout and record: it mints a permanent legacy `run_uuid` (UUIDv5 of the recorded hostname
  and the old `run_id`) into every run before anything moves, rewrites `meta.json` (the old one is
  kept under `local.legacy_meta`), fills publisher and format where the model key implies them, drops
  cloud runs' hardware, and turns `check_results.json` into a score record at the rubric version it
  was scored under, copying the score. Running it twice changes nothing.
  `crucible migrate --bundle FILE --to DIR` converts a published format-2 bundle into records, with
  the same UUIDs.
- **`crucible suite list | verify | cut | patch`**: `cut v3 --promote … --retire …` makes tasks active
  or retired and pins the lock into `suites/v3.yaml`; `patch` pins rubric fixes into `v3.1` and
  rescores stored runs; `verify` checks the current suite still holds. Suite membership is derived
  from task versions, never stored on runs. `SUITE_CHANGELOG.md` records each suite.
- **Two release tracks** in CI (`python -m crucible.ci`): tool changes need a version bump and a
  changelog entry; task changes need a SUITE_CHANGELOG entry, a clean lock and a suite that holds;
  suite files are never edited.
- Docs: [versioning](docs/versioning.md), [scoring](docs/scoring.md), [data model](docs/data-model.md),
  [bundle format](docs/bundle-format.md); `docs/test-tiers.md` is now `docs/task-tiers.md`; the README
  documents the `items` check.
- Skills: `calibrate-task`, `cut-suite`, and `publish-results` updated for format 3.

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
