# Crucible: Personal AI Benchmark Gauntlet

A personal benchmark suite for AI models on real-world tasks: writing, math, geography, history, general knowledge, grading other models' answers, coding, research and everyday tasks on your own data. Built to answer "how good is this local model at the things I actually do?", with cloud models as a reference.

Releases and what changed in each: [CHANGELOG.md](CHANGELOG.md) for the tool, [SUITE_CHANGELOG.md](SUITE_CHANGELOG.md) for the benchmark itself (which tasks are scored, at which versions). How the two are versioned: [docs/versioning.md](docs/versioning.md). Crucible 3.0.0 renamed every task to a slug (CODE-16 is now `react-lead-form`); [docs/task-id-map.json](docs/task-id-map.json) maps every earlier ID, and old IDs still work on the command line.

## Install

Crucible needs Python 3.9+ and [uv](https://docs.astral.sh/uv/) (or plain pip).

```bash
git clone https://github.com/schaferandrew/crucible
cd crucible
uv sync                      # creates .venv with crucible and its dependencies
uv run crucible --help
```

To have `crucible` on your PATH everywhere (instead of `uv run crucible`), install it as a uv tool; it keeps its own environment, so its dependencies are always there:

```bash
uv tool install --editable .
```

If an older `pip install -e .` left a `crucible` on your PATH (check with `which crucible`), remove it first with `pip uninstall crucible`, or it may run without its dependencies (for example, menus that fall back to typed numbers).

Without uv: `python -m venv .venv`, `source .venv/bin/activate`, then `pip install -e .` and run `crucible --help`.

Agentic tasks also need an agent harness on PATH (chat tasks don't):

```bash
npm install -g opencode-ai                                      # opencode (the default)
npm install -g --ignore-scripts @earendil-works/pi-coding-agent # pi
```

## Providers

Models are named `provider/model`. Crucible talks to three providers itself, for chat tasks and model lists:

| Provider | Model names | Setup |
|---|---|---|
| LM Studio | `lmstudio/qwen/qwen3.5-9b` | Start LM Studio's local server (default `http://127.0.0.1:1234/v1`; override with `LMSTUDIO_BASE_URL`). Models served over **LM Link** from another machine work the same way, and runs record that the weights were remote. |
| Ollama | `ollama/qwen3:30b-a3b` | Run Ollama (default `http://localhost:11434`; override with `OLLAMA_BASE_URL`). |
| OpenRouter | `openrouter/moonshotai/kimi-k2.6` | Set `OPENROUTER_API_KEY`. Billed cost is read from the key's usage, so don't share the key with other jobs while a run is going. |

Agentic tasks hand the model name to the harness, so anything the harness supports also works there, such as opencode's own `opencode/<model>` free models.

Load local models with **at least 32k context** (8k is enough for chat tasks with `--reasoning off`); crucible refuses the run otherwise. Agents compact or fail with less, and a thinking model can reason for thousands of tokens before it answers, filling a small context with no answer at all.

## Running tasks

### The easy way: just run it

```bash
uv run crucible run
```

With no arguments, `crucible run` asks what to run, one question at a time:

1. **Which model?** A type-to-filter picker over every provider's live model list (OpenRouter, LM Studio, Ollama, fetched when it opens), with models loaded in LM Studio and models you've run before at the top. Type words to narrow it (`kimi k3`), ↑/↓ to move, Tab to complete, Enter to pick; a full `provider/model` that isn't listed works too. `--provider lmstudio` or a bare `--model qwen3.5` opens the same picker, narrowed.
2. **What to run?** Everything, Chat tasks, Agentic tasks, or individual tasks (type slugs, with completion).
3. **Which area and tier?** For a section, narrow to an area (Writing, Coding, ...) and a tier (Spark, Temper, Forge), or keep them all.
4. **Which agent harness?** Only asked when agentic tests are included: opencode or pi.
5. **Watch?** Only offered for three or fewer agentic tests (see watch mode below).
6. **Skip what's already done?** When some tests already have a run of their current version for this model.

Menus take arrow keys, the number next to an option, or its first letter (press it again for the next match), then Enter; yes/no questions are `y`/`n`. They're drawn with prompt_toolkit. Where a menu can't be drawn the questions fall back to typed numbers, and say why. Before starting, the wizard prints the plan and the one-line command that repeats it without the questions.

### The same thing with flags

Any flag answers its question; give a task and a model and nothing is asked.

```bash
crucible run chat --model lmstudio/qwen/qwen3.5-9b                  # every chat task
crucible run agentic --tier spark --model lmstudio/qwen/qwen3.5-9b  # agentic Spark tasks, with opencode
crucible run coding --agent pi --model ollama/qwen3:30b-a3b         # one area, with pi
crucible run seating-logic-puzzle competition-math --model openrouter/moonshotai/kimi-k2.6   # individual tasks
crucible run all --model lmstudio/qwen/qwen3.5-9b --skip-done       # resume a full sweep
crucible task list                                                  # every task, with its tier and status
```

Selectors add up (`seating-logic-puzzle competition-math`), filters narrow (`chat --tier spark`, `--area math`). A selector is a task slug, an earlier ID (`MATH-4` works and prints its new name), a section (`chat`, `agentic`), an area, a tier or `all`.

| Flag | Meaning |
|---|---|
| `--model`, `-m` | `provider/model`, or a bare name to look up across providers (`--provider` narrows it) |
| `--mode`, `--area`, `--tier` | Filters |
| `--agent` | Harness for agentic tasks: `opencode` (default) or `pi`. Chat tasks always use `direct`. |
| `--timeout` | Seconds per task. Default by tier: Spark 5 min, Temper 15 min, Forge 20 min. No task runs longer than 20 minutes, so a runaway agent can't burn tokens for an hour. |
| `--allow-long` | Lift the 20-minute safety cap |
| `--skip-done` | Skip tasks this model already ran on their current version |
| `--watch` | Open the agent's TUI instead of running headless |
| `--reasoning` | Reasoning (thinking) level: `default` (the model's own), `off`, `low`, `medium`, `high`. Each level is recorded as its own model, in its own run folder (`<model>@reasoning-off`), and shows as its own row on the dashboard. Chat tasks send it to the provider; agentic tasks need pi (`--thinking`), since opencode can't set it per run. |

### How tasks are organized

Every task is `tasks/<slug>.yaml`, with an `id` (a kebab-case slug that says what the task is,
`react-lead-form`), a `name` ("React lead form") and its earlier IDs as `aliases`. It sits on three axes:

- **Section** (mode): **Chat** tasks are one API call with no tools and always run with `direct`. **Agentic** tasks run in an agent harness (opencode or pi) with tools and a workspace. The two are never mixed: not in a run, not in a score, not on the dashboard. A task is agentic when its YAML says `needs_tools: true`.
- **Area**: what the task covers, declared as `area:` in its YAML (the old IDs' prefix is in brackets):

  | Section | Area | Covers |
  |---|---|---|
  | Chat | `writing` (WRIT) | Proofreading, voice, constrained writing |
  | Chat | `math` (MATH) | Everyday money math to competition problems, logic |
  | Chat | `geography` (GEOG) | Capitals, borders, trick questions |
  | Chat | `history` (HIST) | Chronology, fact-checking, anachronisms |
  | Chat | `general` (KNOW) | Knowledge questions, explanations, home repair, summarizing supplied news |
  | Chat | `evals` (EVAL) | Grading an agent's response against criteria (see [Evals](#evals)) |
  | Agentic | `coding` (CODE) | Real repos: build, debug, browser, Forge monorepo tasks |
  | Agentic | `research` (RSCH) | Live information: today's news, weather |
  | Agentic | `everyday` (TASK) | Tasks on your own data: calendars, email, morning briefs |
- **Tier**: how hard it is (details in [docs/task-tiers.md](docs/task-tiers.md)). `spark` is the basics, a pass/fail gate; `temper` is everyday work, the headline score; `forge` is work you'd normally need a frontier model for. Tiers are scored separately, never blended.

Each task also declares a finer scoring **category** (`coding_build`, `writing`, `math`, ...) that sets its weight within a tier. Areas, categories, weights and tiers are suite data in [tasks/taxonomy.yaml](tasks/taxonomy.yaml), not code.

Runs are written to `runs/<model_slug>/<task>/<timestamp>/`, and `meta.json` there is the run record ([docs/data-model.md](docs/data-model.md)). Runs from before 3.0.0 are moved into this layout by `crucible migrate` (try `--dry-run` first).

### What a sweep does when things break

A full sweep runs chat tasks first, then agentic tasks, area by area with the easiest tier first. After each agentic task it stops any dev server the agent left listening in its workspace. If two runs in a row fail before the model produced anything (or are refused, for example because the model isn't loaded), the sweep stops with `SETUP PROBLEM` instead of burning through the rest: fix the setup and rerun with `--skip-done`.

Every run records an **outcome** in `meta.json` (`outcome.status`), before any scoring:

| Outcome | Meaning | Counts? |
|---|---|---|
| `completed` | Finished cleanly with an answer | yes, then scored |
| `failed` | Exited with an error after the model produced output | yes, as the model's failure |
| `no_answer` | The model produced tokens but never an answer | yes, as the model's failure |
| `timeout` | Hit the time limit | yes |
| `context_limit` | The response filled the model's whole context before finishing | no, when the loaded context was below the minimum (a setup problem); yes otherwise (a runaway, like a thinking loop) |
| `harness_error` | Exited before the model produced anything | no: marked invalid, rerun when the setup is fixed |

Scoring then climbs a ladder: did it complete, did it pass the programmatic checks or hidden tests, and (optionally) what a human or AI judge thinks.

### Reasoning levels

Thinking models (Qwen 3.5, gpt-oss, DeepSeek...) can spend minutes reasoning before they answer, so the same weights with thinking off and on are benchmarked as separate models, the way Artificial Analysis lists "(Reasoning)" and "(Non-reasoning)" rows. `crucible run` asks for the level only when the model reasons, and offers only the levels it accepts. LM Studio's `/api/v1/models` lists each model's reasoning options (qwen3.5 and Gemma 4: off or on; gpt-oss: low, medium or high), even for models that aren't loaded; a loaded model with no reasoning info (some community MLX conversions) is asked a one-line question instead. OpenRouter lists `reasoning` among a model's supported parameters, and Ollama reports a `thinking` capability. When it can't be told, the run uses the model's default. `--reasoning` is refused for a level the model doesn't accept, when that's known. Every run records its level:

| Provider | How the level is sent |
|---|---|
| LM Studio | `reasoning_effort` (`none` turns thinking off) |
| OpenRouter | `reasoning: {effort}`, or `{enabled: false}` for off |
| Ollama | `think` (`false` for off) |
| pi (agentic) | `--thinking <level>` |

While a chat task streams, a live line shows how long the model has been thinking and how much it has written, so a long think doesn't look like a hang. The reasoning is saved to `reasoning.txt` in the run folder, apart from the answer that checks and the dashboard see. Press Ctrl+C to stop a task: the unfinished run folder is discarded, so nothing half-done is recorded.

### Watch mode

```bash
crucible run navbar-hamburger-menu --model openrouter/moonshotai/kimi-k2.6 --watch
crucible run interest-calculator-cli --agent pi --model ollama/qwen3:30b-a3b --watch
```

Watch mode opens the agent's TUI in the workspace so you can see the model work (pi sends the task itself). Quit the TUI when it's done (`/quit` for pi, `Ctrl+C` for opencode) and the run finalizes. Watch runs are recorded and scoreable like headless ones, but use headless runs for scores you'll compare: they're reproducible and nobody has to quit a TUI. Watch is for debugging and for seeing how a model works.

### Harness notes

- **opencode** runs headless with `opencode run`; its session is exported into the run directory. Each run gets its own opencode data directory, so parallel runs don't fight over opencode's database.
- **pi** runs with `--no-extensions` plus crucible's per-run extension, and writes its session into the run directory, so `~/.pi/agent` is never modified. `ollama/` and `lmstudio/` models are registered with pi for the run; anything else is handed to pi as-is with its usual API-key env vars.
- **direct** streams one completion from the provider and records tokens, time to first token and cost.

### Task versions and suites
Tasks declare `version`, `rubric_version` and `status` (`provisional`, `active` or `retired`). Each run records the version it used, so scores only compare within a version:

- Changing a task's prompt, its repo or its fixtures means bumping `version`; older runs stop counting until rerun.
- Changing only the rubric, checks or grader means bumping `rubric_version` and re-scoring the stored outputs.

`tasks/versions.lock.json` records the hashes each version was cut from, and CI fails on an undeclared change. A **suite** (`suites/v1.yaml`) pins which tasks are scored, at which versions, with which weights; a run counts in every suite that pins its task at the version it ran. New tasks start provisional and only `crucible suite cut` makes them active. The rules: [docs/versioning.md](docs/versioning.md).

```bash
crucible versions                     # check the lock
crucible versions --update            # after a deliberate bump
crucible suite verify                 # the current suite still holds
crucible suite cut v2 --promote river-haiku-banned-words   # a new suite (only when asked)
crucible suite patch                  # pin rubric fixes and rescore stored runs
```

## Scoring

Scoring happens automatically at the end of every run; `crucible run` never asks you to grade anything.

- **Programmatic checks** run on the model's final answer (or a file it was asked to write) for chat tasks and some agentic ones. See Programmatic checks below.
- **Hidden acceptance tests** run for Forge coding tasks: test files the model never sees are copied into its finished workspace, run with vitest, and removed again. Each rubric criterion is the share of its hidden tests that pass, plus whether the repo's own tests still pass, whether the contract suite was left untouched (modifying it caps the score at 4), and whether the model's own new tests catch the bug: they must pass on its fix and at least one must fail on the seeded code. Results go to `grader_results.json` in the run directory.
- A task whose every criterion is a check or hidden tests gets its score on the spot, as a **score record** in the run's `scores/` folder (`r<rubric_version>.checks.json` or `.hidden_tests.json`): what was counted (`raw`), points earned over points available scaled to 0–10, and every item's result. A rescore under a new rubric version adds a record and never edits the run ([docs/scoring.md](docs/scoring.md)).

- **Isolated graders** (CODE-16) go further: the hidden tests run in a fresh copy of the seeded repo that takes only the source paths the grader lists (`artifacts` in its `grader.yaml`) from the model's workspace, with the seeded package.json, lockfile, config and a cached `npm ci` install. With `scoring: per_test` every hidden test weighs the same: the score is tests passed / all tests × 10, so a task can have any number of tests. `crucible grader <task>` checks the grader against its oracle: the reference solution must score 10, the seeded repo 0, and each calibration fixture (a partial solution) inside its declared range.

`crucible checks` reruns both on stored runs (after a rule or grader changes); `--no-hidden` skips the slower hidden tests.

Tasks that still need judgment (explanations, advice, research briefs) aren't scored automatically yet. **Review** by a person (`crucible score`) or an AI judge (`crucible judge`) is a future feature that needs more infrastructure; it's never part of a run, and existing judge scores are shown as rough signals.

### Workspace isolation
Agents work in `~/.crucible/workspaces/<run>` (override with `CRUCIBLE_WORKSPACES`), outside this checkout, linked from the run's `workspace/` and moved back into the run directory when the run ends. Each workspace is also its own git repository, with the seeded state as its first commit. Inside the checkout, an agent searching upward would find the hidden graders, every rubric and other models' runs.

After every run, crucible scans the transcript for paths inside this checkout. If the agent reached any, the run's `meta.json` records `outcome.leaks` and `outcome.invalid`, and the run never counts. To mark a run invalid after the fact (a stale server, say), `crucible status <run> --invalid REASON` appends a status record.

### Programmatic checks
Tasks can declare deterministic checks that run on the model's final answer (its last reply, never tool output) after every run:

```yaml
checks:
  - id: fixes_than
    type: required_patterns          # also: forbidden_patterns, non_empty, line_count, list_items, grounded_numbers
    patterns: ['louder than']
    rule: "Fixes 'louder then' to 'louder than'."   # plain English, shown on the dashboard
rubric:
  - criterion: "Fixes than"
    max_score: 2
    check: fixes_than                # this criterion is scored by the check
```

`grade_closeness` is the one check that earns partial credit; see [Evals](#evals). `grounded_numbers` passes only when every figure in the answer appears in the prompt's own source material, which catches invented or altered numbers in summaries (KNOW-4). A rubric criterion with `check:` is scored by that check: full marks on a pass, zero on a fail, overriding any judge. When every criterion has a check (all writing tasks do), the run is scored with no judge at all. The result is a score record in the run's `scores/` folder, together with the exact text that was checked, so it can be audited.

```bash
crucible checks                        # re-run checks on existing runs (after editing rules)
crucible checks --doc docs/checks.md   # regenerate the list of every task's rules
```

[docs/checks.md](docs/checks.md) lists every rule each task enforces.

#### Answer blocks and the `items` check
New and converted chat tasks score only a fixed **answer block** at the end of the reply, one item per line, with each expected item worth the same ([docs/scoring.md](docs/scoring.md#answer-blocks)). The `items` check reads the last block under `header`, tolerating case, `**bold**`, `#` heading marks, a missing colon and code fences, and scores each item on its own; the criterion earns the share of items that pass, and a missing block or an empty answer earns 0:

```yaml
checks:
  - id: answers
    type: items
    header: ANSWERS            # or a list of accepted headers
    normalize: number          # how values compare: number, money, name, line_number, datetime,
                               # letter_set, ordering (an item can override it)
    aliases: {Türkiye: [Turkey]}
    items:
      - {id: total, key: "Total", expect: "42.50", normalize: money}   # the line labelled "Total:"
      - {id: second, expect: "Canberra", normalize: name}              # no key: the item's position
      - {id: order, normalize: ordering, expect: [B, A, C]}            # every pair in order is one item
      - {id: flagged, normalize: letter_set, expect: [A, C], of: [A, B, C, D]}   # each letter: listed or left out
rubric:
  - criterion: "Answers"
    max_score: 10
    check: answers
``` Automatic scores (checks and hidden tests) win over a person's or the judge's.

### Evals
The `evals` area (`grade-palindrome-function`, `grade-two-sentence-summary`, `grade-binary-search-answer`, formerly EVAL-1 to EVAL-3) tests whether a model can **consistently and correctly grade an agent's response**. The prompt shows the model the task given to an agent, the criteria and the agent's response; the model reasons through the criteria and ends with a `GRADE: <0-10>` line. A `grade_closeness` check compares that grade with a hidden reference grade held in the task's `checks:` block (never in `prompt:`), and points follow a Gaussian (bell curve) in the distance:

```yaml
checks:
  - id: grade
    type: grade_closeness
    scale: [0, 10]       # valid grades
    actual_score: 7      # hidden reference grade
    width: 3             # width of the curve: the error at which 37% of points remain
rubric:
  - criterion: "Grade accuracy"
    max_score: 10
    check: grade
```

An exact match earns full points, and the penalty grows with the distance: a grade 1 off earns 89%, 2 off 64%, 3 off 37%, 5 off 6%. Small misses cost little and big ones cost a lot. `width` stretches or tightens the curve per task. A missing or out-of-range `GRADE:` line earns 0. Like every fully checked task, it is scored at the end of the run with no judge. The model's reasoning is the run's output: it is kept as `checked_text` in the score record and shown on the dashboard, next to what it graded and the reference grade. The cases span a near-perfect response, a mediocre one and a confidently wrong one; run them repeatedly to measure consistency.

### Review (future)
`crucible judge <run_dir> <payload.json>` saves an AI judge's per-criterion scores (following [crucible/judge_instructions.md](crucible/judge_instructions.md)) to `agent_results.json`, and `crucible score <run>` records a person's in `results.json`. Both exist for the tasks that can't be scored automatically yet, but aren't part of the normal workflow; automatic scores (checks and hidden tests) always win, then a person's, then the judge's.

### Publishing results

`crucible publish` adds this machine's results to the portfolio's `_data/crucible/` folder in **bundle format 3** ([docs/bundle-format.md](docs/bundle-format.md)): one file per run (`runs/<yyyy-mm>/<run_uuid>.json`), one per score record and status record, and one catalog per suite that holds every label, tier and weight the page shows. Full outputs go to `crucible-data/outputs/`, outside `_data`. Publishing only adds files, keyed by each run's permanent `run_uuid`, so publishing twice changes nothing and two machines never touch the same file; everything is validated before it's written.

```bash
crucible publish                         # this machine's runs -> ../schaferandrew.github.io/_data/crucible/
crucible publish --dry-run               # what would be added
crucible publish --to <folder>           # somewhere else (or set CRUCIBLE_PUBLISH_DIR)
crucible publish --check <folder>        # validate a folder and recompute every run's content hash
crucible export --format 2 --out <file>  # the single-file bundle the page reads until it switches to format 3
crucible migrate --bundle <file> --to <folder>   # convert another machine's format-2 bundle into records
```

Until the dashboard switches to format 3, the live page reads the format-2 file (`_data/crucible/ironwood.json`) written by `crucible export --format 2`, which keeps the pre-3.0.0 IDs. Claude Code users can say "publish my Crucible results": the repo ships a skill for it (`.claude/skills/publish-results/`).

Runs that shouldn't be published live in `runs-archive/`: bad-day runs (incomplete, invalid, harness errors) and models with no scored run. `crucible publish` and `crucible export` read `runs/` only; move a folder back to restore it.

## Reports

Compare multiple runs:
```bash
crucible report run1 run2 run3
crucible report --all --output results.md
```

## Adding an agent harness

`crucible/runner.py` is the only orchestrator and never branches on which harness it is running: per task it loads the task, asks the agent `check()`, creates the run directory (plus `workspace/` if the agent uses one), calls `agent.run(ctx)`, writes `meta.json` and prints the result. Everything harness-specific lives in one module under `crucible/agents/`:

1. Create `crucible/agents/<name>.py` with a subclass of `Agent` (`crucible/agents/base.py`):
   - `name`, `label`, `executable` (CLI that must be on PATH) + `install_hint`, optionally `default_model`
   - **CLI harnesses** implement `launch(ctx)` → `Launch(cmd, cwd, env)` for headless or watch (`ctx.watch`) mode, and `collect(ctx)` to turn what the harness left behind into `session.json` / `stdout.txt` (use `crucible.session.write_normalized` for the shared event format). The default `run()` handles the rest: `command.sh`, headless logging or the TUI, timeouts and tree-kill.
   - **Non-CLI harnesses** (like `direct`) override `run(ctx)` instead, and may set `uses_workspace = False`.
   - optional: `validate(model, prompt_def)` (API keys, unsupported tasks), `prepare(ctx)` (setup/teardown around the run), `token_usage(run_dir)`, `response_timings(run_dir)`, `status(result)`
2. Add an instance to `AGENTS` in `crucible/agents/__init__.py`.

`--agent <name>`, preflight checks, install hints, metrics and the console summary then work automatically. Use `crucible/procs.py` conventions for portability: single-line arguments, prompt passed as a file, per-run config in env vars.

## Developing

```bash
python -m pip install -e . pytest
python -m pytest            # unit + end-to-end tests (pi's runs when `pi` is on PATH)
```
CI (`.github/workflows/tests.yml`) runs the suite on Linux and macOS with pi installed. Crucible supports macOS and Linux only.

## Structure

- `tasks/` — Benchmark task definitions (YAML with rubrics), `taxonomy.yaml` and the version lock
- `suites/` — Suite pins, written by `crucible suite`
- `graders/` — Hidden acceptance tests, one folder per task
- `fixtures/` — Test data (calendar JSON, writing samples, etc.)
- `repos/` — Seeded buggy repositories for coding tasks
- `runs/` — Run results: `<model>/<task>/<timestamp>/`
- `crucible/cli.py` — CLI entry point (`run` / `score` / `judge` / `checks` / `versions` / `export` / `report`)
- `crucible/runner.py` — `crucible run`: per-task orchestration and the sweep loop
- `crucible/runrecord.py` — The run record, score records and status records
- `crucible/migrate.py` — `crucible migrate`: runs from before 3.0.0
- `crucible/suites.py` — `crucible suite`: cut, patch, verify
- `crucible/bundle.py` — `crucible publish`: bundle format 3
- `crucible/plan.py` — What a run will do: task selection, order, harness and time limit per task
- `crucible/wizard.py` — The questions `crucible run` asks when it isn't given a task
- `crucible/taxonomy.py` — Sections (chat, agentic), areas, tiers and categories
- `crucible/agents/` — One module per harness: `opencode.py`, `pi.py` (+ `pi_extension.ts`), `direct.py`
- `crucible/workspace.py` — Prompts, run directories, workspace setup, fixtures
- `crucible/models.py` / `crucible/providers.py` — Model resolution; provider table (list models, stream completions)
- `crucible/metrics.py` — Metrics in `meta.json` (tests, tool calls, tokens, latency, cost)
- `crucible/cost.py` — Run cost: billed OpenRouter usage or the agent's own estimate
- `crucible/mcp_servers/` — MCP servers crucible ships to agents (`web_server.py`: `web_fetch`, `web_search`; `calendar_server.py`: mock calendar for TASK-4 to TASK-6)
- `crucible/console.py` — What `crucible run` prints
- `crucible/procs.py` — Process launch and tree-kill (macOS, Linux)
- `crucible/session.py` — Normalized session events, transcript, tool-call counting
- `crucible/scorer.py` — Interactive scoring (`score_run`)
- `crucible/reporter.py` — Comparison report generator

## How It Works

1. `crucible run` builds a plan (`crucible/plan.py`): which tasks, in what order, with which harness and time limit.
2. For each agentic task it creates a workspace in `~/.crucible/workspaces/<run>` (see Workspace isolation), copying in the seeded repo or fixtures; repos in this checkout are never mutated.
3. Headless, it runs `opencode run` / `pi -p` with the prompt attached as a file; chat tasks are one streamed API call. In watch mode it opens the agent's TUI with the prompt pre-loaded.
4. The run directory gets `prompt.txt`, `stdout.txt`, `stderr.txt`, `session.json` (when the harness has one) and `meta.json`, the run record (task version, model variant, endpoint, hardware, outcome, metrics, provenance).
5. Programmatic checks and hidden tests score the run straight away when the task has them, as a score record; the rest wait for review (a future feature).
6. `crucible publish` turns everything into the results bundle the dashboard reads.

## Mock MCP Server

Tasks that need email / calendar / news / weather data declare the mock MCP server in their task YAML:

```yaml
mcp_servers:
  - mock-data
```

The server (`fixtures/mock-mcp-server/mock_server.py`, stdio JSON-RPC) serves fixture data from `fixtures/mock-data/` (`emails.json`, `calendar.json`, `news.json`, `weather.json`) via four tools: `get_emails`, `get_calendar_events`, `get_news`, `get_weather`.

**Wiring is per-run and self-contained — nothing goes in global agent configs:**
- **opencode**: the runner injects `OPENCODE_CONFIG_CONTENT` into the spawned process only
- **pi**: pi has no MCP support, so crucible's per-run pi extension (`crucible/agents/pi_extension.ts`, loaded with `-e`) spawns the declared MCP servers and registers their tools as native pi tools; config arrives via the `CRUCIBLE_PI_CONFIG` env var

This makes fresh machines work with zero manual setup: install the repo, run the task, the mock server is wired up and torn down automatically.

### Latency

`meta.json` also records `ttft_s` (time to first token of the first model response, from request sent), `ttft_avg_s`, `response_time_avg_s` and `model_responses`, and the per-task terminal summary prints them. Each harness reports only what it actually measures:
- **pi**: exact, timestamped inside pi by crucible's extension (headless and `--watch`)
- **direct**: exact, from the streamed provider response (direct runs also record token usage)
- **opencode**: per-response duration from its session export; no token-level timestamps, so TTFT is empty

### Token usage

`meta.json` records `tokens_in` / `tokens_out` per run (from opencode's session export, pi's session file). Caveats: opencode's `tokens_out` includes reasoning tokens; pi's `tokens_in` includes cache reads/writes.

### Cost

`meta.json` records `cost_usd` and `cost_source`, best source first:
- **`openrouter_billed`**: for `openrouter/...` models, the billed usage of `OPENROUTER_API_KEY` read before and after the run (`GET /api/v1/key`), so it is real spend for any agent. It is only clean when nothing else spends on that key during the run, so give an LLM judge its own key. Usage can lag a few seconds, so a run that reads $0 is re-checked for up to ~8s.
- **`<agent>_estimate`**: the agent's own figure from its session record (pi's `usage.cost.total`, opencode's `messages[].info.cost`), priced from the agent's built-in price list rather than a bill. Local models (ollama, LM Studio) read $0.

Both are `null` when unknown.

### Web tools (RSCH-2)

RSCH-2 and RSCH-2b declare crucible's web MCP server (`mcp_servers: [web]`, `crucible/mcp_servers/web_server.py`), so every agent gets the same `web_fetch` tool (HTTP GET; HTML reduced to text) rather than whatever its harness ships. `web_search` (Brave Search API) is offered only when `BRAVE_SEARCH_API_KEY` is set. `meta.json` records `tools.mcp_servers` and `tools.builtin_web` (opencode still has its own `webfetch`), so you can see what each run could reach.

### Calendar scheduling tasks (formerly TASK-4 to TASK-6)

Three everyday tasks (`crucible run everyday` runs them with the other everyday tasks) test tool use against a mock calendar MCP server (`crucible/mcp_servers/calendar_server.py`) that imitates the Google Calendar MCP servers people really use, so models meet the tools and data shapes they will meet in practice:

| Tool | Real-world counterpart |
|------|------------------------|
| `list_calendars` | calendar list: `id` (email), `summary`, `description`, `timeZone`, `accessRole` |
| `list_events` | `events.list`: `calendarId`, `startTime`, `endTime`, `timeZone`, `fullText`, `eventType`, `orderBy`, paging |
| `get_event`, `search_events` | `events.get`; keyword search of the primary calendar |
| `get_freebusy` | `freebusy.query`: busy blocks per calendar, no details |
| `get_current_time` | offered by community servers; the dataset's "now" |

Events are Google Event resources (`start`/`end` as `{dateTime, timeZone}` or `{date}`, `status`, `transparency`, `eventType`, `attendees[].responseStatus`). As in real life, colleagues share free/busy only: `list_events` on their calendar fails with 403 and `get_freebusy` is how you see them, while your own calendar is read as events. Declined events, transparent ("free") events and out-of-office time behave as Google does. Like the real servers, nothing finds a time several people share; there is no `suggest_time`, and the model intersects calendars itself.

A prompt picks its world with a dataset suffix:

```yaml
mcp_servers:
  - mock-calendar:forge     # fixtures/mock-calendar/forge.json
```

A dataset fixes "now" (so tests never depend on the real date), the calendars and their events. Working hours are not exposed by the tools (nor by the real ones), and the prompts only say the meeting is for work: inferring business hours (9 to 5 in each person's own time zone, found in `list_calendars`) is part of the task.

| Task | Dataset | What it asks |
|------|---------|------|
| TASK-4 | `spark` | "Am I free at 3:30?" One calendar; an event ends at exactly 3:30. |
| TASK-5 | `pair` | An hour with Jamie this week: read my events, then Jamie's busy blocks. My declined and "free" events look busy. |
| TASK-6 | `forge` | An hour for a team of 16 in two weeks: holiday, out-of-office, a New York teammate, non-team calendars to leave out, declined and "free" decoys. |

The tasks end with an `ANSWER:` or `OPTIONS:` block and are scored by checks. The right answers are not written down anywhere in a task: the `time_options` check computes them from the dataset with `free_starts()` in the server. The datasets are regenerated with `python graders/mock-calendar/build.py` (kept under `graders/`, never in `fixtures/`, because it holds the ground truth), which re-checks them against that oracle.

**The file-based sibling.** `two-calendar-slots-json` (TASK-1) is the one calendar task that does *not* use the MCP server, on purpose. It hands the model `calendar-fixture.json` and asks for `slots.json`, so it measures the scheduling logic alone: interval arithmetic, the 9-5 and half-hour grid, window and weekend edges, and an exhaustive per-day list of valid slots. The MCP tasks above measure tool use: finding and calling the tools, grounding "now", reading free/busy, and handling real-world ambiguity. Read the two together: a model that passes TASK-1 but fails TASK-5 or TASK-6 can schedule but struggles with tools; one that fails both can't schedule.

Caveat: harnesses may put the real current date in the model's context, which disagrees with the dataset's "now". The tasks expect the model to ask the calendar for the time.

### Verified MCP permutations (TASK-2)

All combinations below ran against the mock MCP server; "✓" means the mock tools were invoked and the briefing ended with the Spanish paragraph.

| Agent   | Mode     | Model                                   | Run (20260903_*) | Result | tokens in/out |
|---------|----------|------------------------------------------|------------------|--------|---------------|
| opencode| headless | openrouter/anthropic/claude-sonnet-4.5   | 010917           | ✓      | n/a (pre-fix) |
| opencode| headless | openrouter/deepseek/deepseek-v4-flash    | 032424           | ✓      | n/a (run pre-dated token capture wiring) |
| opencode| watch    | openrouter/deepseek/deepseek-v4-flash    | 041420           | ✓      | n/a (run pre-dated token capture wiring) |

pi runs are covered end-to-end by `tests/test_pi_integration.py`, which drives the real pi CLI against a scripted OpenAI-compatible model (`tests/fake_openai.py`) through the mock MCP server, on Linux and macOS in CI.

### Pitfalls learned

- **Rubrics must live in a top-level `rubric:` key**, never inside `prompt:` — otherwise the agent sees the eval criteria (fixed for TASK-2; all prompts scanned).
- **Stale global `crucible` install**: an editable install pointing at a different checkout silently runs old code (symptom: "MCP not available" despite everything else working). Check with `pip show crucible | grep -i editable`.
