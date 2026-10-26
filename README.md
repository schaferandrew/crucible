# Crucible: Personal AI Benchmark Gauntlet

A personal benchmark suite for AI models on real-world tasks: writing, math, geography, history, general knowledge, coding, research and everyday tasks on your own data. Built to answer "how good is this local model at the things I actually do?", with cloud models as a reference.

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

Agentic tests also need an agent harness on PATH (chat tests don't):

```bash
npm install -g opencode-ai                                      # opencode (the default)
npm install -g --ignore-scripts @earendil-works/pi-coding-agent # pi
```

## Providers

Models are named `provider/model`. Crucible talks to three providers itself, for chat tests and model lists:

| Provider | Model names | Setup |
|---|---|---|
| LM Studio | `lmstudio/qwen/qwen3.5-9b` | Start LM Studio's local server (default `http://127.0.0.1:1234/v1`; override with `LMSTUDIO_BASE_URL`). Models served over **LM Link** from another machine work the same way, and runs record that the weights were remote. |
| Ollama | `ollama/qwen3:30b-a3b` | Run Ollama (default `http://localhost:11434`; override with `OLLAMA_BASE_URL`). |
| OpenRouter | `openrouter/moonshotai/kimi-k2.6` | Set `OPENROUTER_API_KEY`. Billed cost is read from the key's usage, so don't share the key with other jobs while a run is going. |

Agentic tests hand the model name to the harness, so anything the harness supports also works there, such as opencode's own `opencode/<model>` free models.

For local models on agentic tests, load the model with **at least 32k context**: crucible refuses the run otherwise, because agents compact or fail with less.

## Running tests

### The easy way: just run it

```bash
uv run crucible run
```

With no arguments, `crucible run` asks what to run, one question at a time:

1. **Which model?** A type-to-filter picker over every provider's live model list (OpenRouter, LM Studio, Ollama, fetched when it opens), with models loaded in LM Studio and models you've run before at the top. Type words to narrow it (`kimi k3`), ↑/↓ to move, Tab to complete, Enter to pick; a full `provider/model` that isn't listed works too. `--provider lmstudio` or a bare `--model qwen3.5` opens the same picker, narrowed.
2. **What to run?** Everything, Chat tests, Agentic tests, or individual tests (type IDs, with completion).
3. **Which area and tier?** For a section, narrow to an area (Writing, Coding, ...) and a tier (Spark, Temper, Forge), or keep them all.
4. **Which agent harness?** Only asked when agentic tests are included: opencode or pi.
5. **Watch?** Only offered for three or fewer agentic tests (see watch mode below).
6. **Skip what's already done?** When some tests already have a run of their current version for this model.

Menus take arrow keys, the number next to an option, or its first letter (press it again for the next match), then Enter; yes/no questions are `y`/`n`. They're drawn with prompt_toolkit. Where a menu can't be drawn the questions fall back to typed numbers, and say why. Before starting, the wizard prints the plan and the one-line command that repeats it without the questions.

### The same thing with flags

Any flag answers its question; give a test and a model and nothing is asked.

```bash
crucible run chat --model lmstudio/qwen/qwen3.5-9b                  # every chat test
crucible run agentic --tier spark --model lmstudio/qwen/qwen3.5-9b  # agentic Spark tests, with opencode
crucible run coding --agent pi --model ollama/qwen3:30b-a3b         # one area, with pi
crucible run WRIT-2 MATH-4 MATH-3 --model openrouter/moonshotai/kimi-k2.6       # individual tests
crucible run all --model lmstudio/qwen/qwen3.5-9b --skip-done       # resume a full suite
```

Selectors add up (`WRIT-2 MATH-4`), filters narrow (`chat --tier spark`, `--area math`). A selector is a test ID, a section (`chat`, `agentic`), an area, a tier or `all`.

| Flag | Meaning |
|---|---|
| `--model`, `-m` | `provider/model`, or a bare name to look up across providers (`--provider` narrows it) |
| `--mode`, `--area`, `--tier` | Filters |
| `--agent` | Harness for agentic tests: `opencode` (default) or `pi`. Chat tests always use `direct`. |
| `--timeout` | Seconds per test. Default by tier: Spark 5 min, Temper 15 min, Forge 20 min. No test runs longer than 20 minutes, so a runaway agent can't burn tokens for an hour. |
| `--allow-long` | Lift the 20-minute safety cap |
| `--skip-done` | Skip tests this model already ran on their current version |
| `--watch` | Open the agent's TUI instead of running headless |

### How tests are organized

Every test sits on three axes:

- **Section** (mode): **Chat** tests are one API call with no tools and always run with `direct`. **Agentic** tests run in an agent harness (opencode or pi) with tools and a workspace. The two are never mixed: not in a run, not in a score, not on the dashboard. A test is agentic when its YAML says `needs_tools: true`.
- **Area**: what the test covers, declared as `area:` in its YAML. Every test ID is its area's four letters, a hyphen and a number (`CODE-11`, `WRIT-2b`), and crucible refuses a test whose ID and area disagree:

  | Section | Area | Prefix | Covers |
  |---|---|---|---|
  | Chat | `writing` | WRIT | Proofreading, voice, constrained writing |
  | Chat | `math` | MATH | Everyday money math to competition problems, logic |
  | Chat | `geography` | GEOG | Capitals, borders, trick questions |
  | Chat | `history` | HIST | Chronology, fact-checking, anachronisms |
  | Chat | `general` | KNOW | Knowledge questions, explanations, home repair, summarizing supplied news |
  | Agentic | `coding` | CODE | Real repos: build, debug, browser, Forge monorepo tasks |
  | Agentic | `research` | RSCH | Live information: today's news, weather |
  | Agentic | `everyday` | TASK | Tasks on your own data: calendars, email, morning briefs |
- **Tier**: how hard it is (details in [test-tiers.md](test-tiers.md)). `spark` is the basics, a pass/fail gate; `temper` is everyday work, the headline score; `forge` is work you'd normally need a frontier model for. Tiers are scored separately, never blended.

Older IDs (C11, W2b, E4, and the three-letter COD11, WRI2b round) were renamed on 2026-10-26; [docs/test-id-map.json](docs/test-id-map.json) maps each old ID to its new one.

Each prompt also declares a finer scoring **category** (`coding_build`, `writing`, `math`, ...) that sets its weight within a tier and the run directory layout: `runs/<model_slug>/<category>/<test_id>/<timestamp>/`.

### What a suite does when things break

A full suite runs chat tests first, then agentic tests, area by area with the easiest tier first. After each agentic test it stops any dev server the agent left listening in its workspace. If two runs in a row fail before the model produced anything (or are refused, for example because the model isn't loaded), the suite stops with `SETUP PROBLEM` instead of burning through the rest: fix the setup and rerun with `--skip-done`.

Every run records an **outcome** in `meta.json`, before any scoring:

| Outcome | Meaning | Counts? |
|---|---|---|
| `completed` | Finished cleanly with an answer | yes, then scored |
| `failed` | Exited with an error after the model produced output | yes, as the model's failure |
| `no_answer` | The model produced tokens but never an answer | yes, as the model's failure |
| `timeout` | Hit the time limit | yes |
| `harness_error` | Exited before the model produced anything | no: marked invalid, rerun when the setup is fixed |

Scoring then climbs a ladder: did it complete, did it pass the programmatic checks or hidden tests, and (optionally) what a human or AI judge thinks.

### Watch mode

```bash
crucible run CODE-2b --model openrouter/moonshotai/kimi-k2.6 --watch
crucible run CODE-1 --agent pi --model ollama/qwen3:30b-a3b --watch
```

Watch mode opens the agent's TUI in the workspace so you can see the model work (pi sends the task itself). Quit the TUI when it's done (`/quit` for pi, `Ctrl+C` for opencode) and the run finalizes. Watch runs are recorded and scoreable like headless ones, but use headless runs for scores you'll compare: they're reproducible and nobody has to quit a TUI. Watch is for debugging and for seeing how a model works.

### Harness notes

- **opencode** runs headless with `opencode run`; its session is exported into the run directory. Each run gets its own opencode data directory, so parallel runs don't fight over opencode's database.
- **pi** runs with `--no-extensions` plus crucible's per-run extension, and writes its session into the run directory, so `~/.pi/agent` is never modified. `ollama/` and `lmstudio/` models are registered with pi for the run; anything else is handed to pi as-is with its usual API-key env vars.
- **direct** streams one completion from the provider and records tokens, time to first token and cost.

### Test versions
Prompts also declare `version`, `rubric_version` and `status` (`provisional`, `active` or `retired`). Each run records the version it used, so scores only compare within a version:

- Changing a prompt, its repo or its fixtures means bumping `version`; older runs stop counting until rerun.
- Changing only the rubric means bumping `rubric_version` and re-scoring the stored outputs.

`prompts/versions.lock.json` records the hashes each version was cut from, and CI fails on an undeclared change:
```bash
crucible versions                     # check the lock
crucible versions --update            # after a deliberate bump
crucible versions --release 2026.12   # pin active tests into releases/2026.12.yaml
crucible versions --backfill runs     # stamp older runs with the version they used
```

## Scoring

Scoring happens automatically at the end of every run; `crucible run` never asks you to grade anything.

- **Programmatic checks** run on the model's final answer (or a file it was asked to write) for chat tests and some agentic ones. See Programmatic checks below.
- **Hidden acceptance tests** run for Forge coding tests: test files the model never sees are copied into its finished workspace, run with vitest, and removed again. Each rubric criterion is the share of its hidden tests that pass, plus whether the repo's own tests still pass, whether the contract suite was left untouched (modifying it caps the score at 4), and whether the model's own new tests catch the bug: they must pass on its fix and at least one must fail on the seeded code. Results go to `grader_results.json` in the run directory.
- A test whose every criterion is a check or hidden tests gets its score on the spot, in `check_results.json`: points earned over points available, scaled to 0–10.

`crucible checks` reruns both on stored runs (after a rule or grader changes); `--no-hidden` skips the slower hidden tests.

Tests that still need judgment (explanations, advice, research briefs) aren't scored automatically yet. **Review** by a person (`crucible score`) or an AI judge (`crucible judge`) is a future feature that needs more infrastructure; it's never part of a run, and existing judge scores are shown as rough signals.

### Workspace isolation
Agents work in `~/.crucible/workspaces/<run>` (override with `CRUCIBLE_WORKSPACES`), outside this checkout, linked from the run's `workspace/` and moved back into the run directory when the run ends. Each workspace is also its own git repository, with the seeded state as its first commit. Inside the checkout, an agent searching upward would find the hidden graders, every rubric and other models' runs.

After every run, crucible scans the transcript for paths inside this checkout. If the agent reached any, the run's `meta.json` gets `leaks` and `invalid`, and `crucible export` leaves the run out.

### Programmatic checks
Tests can declare deterministic checks that run on the model's final answer (its last reply, never tool output) after every run:

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

`grounded_numbers` passes only when every figure in the answer appears in the prompt's own source material, which catches invented or altered numbers in summaries (KNOW-4). A rubric criterion with `check:` is scored by that check: full marks on a pass, zero on a fail, overriding any judge. When every criterion has a check (all writing tests do), the run is scored with no judge at all. The result goes to `check_results.json` next to the run, together with the exact text that was checked, so it can be audited.

```bash
crucible checks                        # re-run checks on existing runs (after editing rules)
crucible checks --doc docs/checks.md   # regenerate the list of every test's rules
```

[docs/checks.md](docs/checks.md) lists every rule each test enforces. Automatic scores (checks and hidden tests) win over a person's or the judge's.

### Review (future)
`crucible judge <run_dir> <payload.json>` saves an AI judge's per-criterion scores (following [crucible/judge_instructions.md](crucible/judge_instructions.md)) to `agent_results.json`, and `crucible score <run>` records a person's in `results.json`. Both exist for the tests that can't be scored automatically yet, but aren't part of the normal workflow; automatic scores (checks and hidden tests) always win, then a person's, then the judge's.

### Publishing results

The portfolio's Crucible page reads every `*.json` file in its `_data/crucible/` folder. Each is a **results bundle** (schema: [crucible/schemas/results.schema.json](crucible/schemas/results.schema.json)), one per machine, and the page merges them: runs by `run_id`, newest bundle wins, and the test list from the newest bundle.

```bash
crucible publish                         # this machine's runs -> ../schaferandrew.github.io/_data/crucible/<machine>.json
crucible publish --to <folder>           # write somewhere else (or set CRUCIBLE_PUBLISH_DIR)
crucible publish --check <bundle.json>   # validate a bundle, e.g. one made on another machine
crucible export --out <file.json>        # the same data without the checks or the machine name
```

To add results from another machine, run `crucible publish --to <folder>` there and drop the file into `_data/crucible/` (copy it, or upload it on GitHub). A run's score counts only when it matches the current test and rubric versions. Claude Code users can say "publish my Crucible results": the repo ships a skill for it (`.claude/skills/publish-results/`).

Runs that shouldn't be published live in `runs-archive/`: bad-day runs (incomplete, invalid, harness errors) and models with no scored run. `crucible export` and `crucible publish` read `runs/` only; move a folder back to restore it.

## Reports

Compare multiple runs:
```bash
crucible report run1 run2 run3
crucible report --all --output results.md
```

## Adding an agent harness

`crucible/runner.py` is the only orchestrator and never branches on which harness it is running: per test it loads the prompt, asks the agent `check()`, creates the run directory (plus `workspace/` if the agent uses one), calls `agent.run(ctx)`, writes `meta.json` and prints the result. Everything harness-specific lives in one module under `crucible/agents/`:

1. Create `crucible/agents/<name>.py` with a subclass of `Agent` (`crucible/agents/base.py`):
   - `name`, `label`, `executable` (CLI that must be on PATH) + `install_hint`, optionally `default_model`
   - **CLI harnesses** implement `launch(ctx)` → `Launch(cmd, cwd, env)` for headless or watch (`ctx.watch`) mode, and `collect(ctx)` to turn what the harness left behind into `session.json` / `stdout.txt` (use `crucible.session.write_normalized` for the shared event format). The default `run()` handles the rest: `command.sh`, headless logging or the TUI, timeouts and tree-kill.
   - **Non-CLI harnesses** (like `direct`) override `run(ctx)` instead, and may set `uses_workspace = False`.
   - optional: `validate(model, prompt_def)` (API keys, unsupported tests), `prepare(ctx)` (setup/teardown around the run), `token_usage(run_dir)`, `response_timings(run_dir)`, `status(result)`
2. Add an instance to `AGENTS` in `crucible/agents/__init__.py`.

`--agent <name>`, preflight checks, install hints, metrics and the console summary then work automatically. Use `crucible/procs.py` conventions for portability: single-line arguments, prompt passed as a file, per-run config in env vars.

## Developing

```bash
python -m pip install -e . pytest
python -m pytest            # unit + end-to-end tests (pi's runs when `pi` is on PATH)
```
CI (`.github/workflows/tests.yml`) runs the suite on Linux and macOS with pi installed. Crucible supports macOS and Linux only.

## Structure

- `prompts/` — Benchmark prompt definitions (YAML with rubrics)
- `fixtures/` — Test data (calendar JSON, writing samples, etc.)
- `repos/` — Seeded buggy repositories for coding tests
- `runs/` — Output directory for test results
- `crucible/cli.py` — CLI entry point (`run` / `score` / `judge` / `checks` / `versions` / `export` / `report`)
- `crucible/runner.py` — `crucible run`: per-test orchestration and the suite loop
- `crucible/plan.py` — What a run will do: test selection, order, harness and time limit per test
- `crucible/wizard.py` — The questions `crucible run` asks when it isn't given a test
- `crucible/taxonomy.py` — Sections (chat, agentic), areas, tiers and categories
- `crucible/agents/` — One module per harness: `opencode.py`, `pi.py` (+ `pi_extension.ts`), `direct.py`
- `crucible/workspace.py` — Prompts, run directories, workspace setup, fixtures
- `crucible/models.py` / `crucible/providers.py` — Model resolution; provider table (list models, stream completions)
- `crucible/metrics.py` — Metrics in `meta.json` (tests, tool calls, tokens, latency, cost)
- `crucible/cost.py` — Run cost: billed OpenRouter usage or the agent's own estimate
- `crucible/mcp_servers/` — MCP servers crucible ships to agents (`web_server.py`: `web_fetch`, `web_search`; `calendar_server.py`: mock calendar for A1-A3)
- `crucible/console.py` — What `crucible run` prints
- `crucible/procs.py` — Process launch and tree-kill (macOS, Linux)
- `crucible/session.py` — Normalized session events, transcript, tool-call counting
- `crucible/scorer.py` — Interactive scoring (`score_run`)
- `crucible/reporter.py` — Comparison report generator

## How It Works

1. `crucible run` builds a plan (`crucible/plan.py`): which tests, in what order, with which harness and time limit.
2. For each agentic test it creates a workspace in `~/.crucible/workspaces/<run>` (see Workspace isolation), copying in the seeded repo or fixtures; repos in this checkout are never mutated.
3. Headless, it runs `opencode run` / `pi -p` with the prompt attached as a file; chat tests are one streamed API call. In watch mode it opens the agent's TUI with the prompt pre-loaded.
4. The run directory gets `prompt.txt`, `stdout.txt`, `stderr.txt`, `session.json` (when the harness has one) and `meta.json` (outcome, metrics, test version, machine and inference details).
5. Programmatic checks and hidden tests score the run straight away when the test has them; the rest wait for review (a future feature).
6. `crucible publish` turns everything into the results bundle the dashboard reads.

## Mock MCP Server

Tests that need email / calendar / news / weather data declare the mock MCP server in their prompt YAML:

```yaml
mcp_servers:
  - mock-data
```

The server (`fixtures/mock-mcp-server/mock_server.py`, stdio JSON-RPC) serves fixture data from `fixtures/mock-data/` (`emails.json`, `calendar.json`, `news.json`, `weather.json`) via four tools: `get_emails`, `get_calendar_events`, `get_news`, `get_weather`.

**Wiring is per-run and self-contained — nothing goes in global agent configs:**
- **opencode**: the runner injects `OPENCODE_CONFIG_CONTENT` into the spawned process only
- **pi**: pi has no MCP support, so crucible's per-run pi extension (`crucible/agents/pi_extension.ts`, loaded with `-e`) spawns the declared MCP servers and registers their tools as native pi tools; config arrives via the `CRUCIBLE_PI_CONFIG` env var

This makes fresh machines work with zero manual setup: install the repo, run the test, the mock server is wired up and torn down automatically.

### Latency

`meta.json` also records `ttft_s` (time to first token of the first model response, from request sent), `ttft_avg_s`, `response_time_avg_s` and `model_responses`, and the per-test terminal summary prints them. Each harness reports only what it actually measures:
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

### Calendar scheduling tests (A1-A3)

The `agentic` suite (`crucible run agentic`) tests tool use against a mock calendar MCP server (`crucible/mcp_servers/calendar_server.py`) that imitates the Google Calendar MCP servers people really use, so models meet the tools and data shapes they will meet in practice:

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

A dataset fixes "now" (so tests never depend on the real date), the calendars and their events. Working hours are not exposed by the tools (nor by the real ones), and the prompts only say the meeting is for work: inferring business hours (9 to 5 in each person's own time zone, found in `list_calendars`) is part of the test.

| Test | Dataset | Task |
|------|---------|------|
| A1 | `spark` | "Am I free at 3:30?" One calendar; an event ends at exactly 3:30. |
| A2 | `pair` | An hour with Jamie this week: read my events, then Jamie's busy blocks. My declined and "free" events look busy. |
| A3 | `forge` | An hour for a team of 16 in two weeks: holiday, out-of-office, a New York teammate, non-team calendars to leave out, declined and "free" decoys. |

Each prompt's YAML comments hold the ground truth, and `free_starts()` in the server computes it for tests and graders. The datasets are regenerated with `python fixtures/mock-calendar/build.py`, which re-checks them against that oracle.

Caveat: harnesses may put the real current date in the model's context, which disagrees with the dataset's "now". The tests expect the model to ask the calendar for the time.

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
