# Crucible: Personal AI Benchmark Gauntlet

A lightweight, personal benchmark suite for evaluating AI models on real-world tasks: coding, writing, reasoning, everyday knowledge, and home maintenance.

## macOS Quick Start

### Option A: standard venv

```bash
cd /path/to/crucible
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install pyyaml
python -m pip install -e .
```

### Option B: uv (recommended for macOS)

```bash
cd /path/to/crucible
uv venv
source .venv/bin/activate
uv pip install --upgrade pip
uv pip install pyyaml
uv pip install -e .
```

If you prefer a global install without a venv:

```bash
pip3 install pyyaml
pip3 install -e .
```

Then verify the CLI works:

```bash
crucible --help
```

> If `crucible` is not on PATH, use `python3 -m crucible.cli ...` instead.

## Windows Quick Start

From PowerShell in the repo root:

```powershell
cd C:\Users\Andrew\Development\crucible
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install pyyaml
python -m pip install -e .
```

Then verify the CLI works:

```powershell
crucible --help
```

If PowerShell blocks script execution, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## Running with LM Studio locally (Windows)

If you are using LM Studio with the OpenAI-compatible local server at `http://127.0.0.1:1234`, you can run the direct API path without `opencode`:

```powershell
crucible run G2 --provider lmstudio --model openai/gpt-oss-20b --timeout 180
```

You can also specify the model by full provider/name format:

```powershell
crucible run E2 --model lmstudio/openai/gpt-oss-20b --timeout 180
```

This project has a direct runner for `lmstudio/...` models and does not require `opencode` for the no-tools benchmark cases.

## Quick Start

1. **Clone the repo**:
```bash
git clone <repo-url> crucible
cd crucible
```

2. **Install Python dependencies**:
```bash
pip3 install pyyaml
```

3. **Install crucible CLI** (optional, for `crucible run|score|report`):
```bash
pip3 install -e .
```

> **macOS note:** `pip3 install -e .` installs the `crucible` script to `~/Library/Python/3.9/bin/`, which is not on PATH by default. Add this to your `~/.zshrc` (or `~/.bash_profile`):
> ```bash
> export PATH="$HOME/Library/Python/3.9/bin:$PATH"
> ```
> Then reload: `source ~/.zshrc`. Alternatively, use `python3 -m crucible.cli run ...` without modifying PATH.

4. **Install an agent**: [opencode](https://opencode.ai) (default) and/or [pi](https://pi.dev):
```bash
npm install -g opencode-ai
npm install -g --ignore-scripts @earendil-works/pi-coding-agent
```
> **Windows + pi:** pi's `bash` tool needs a bash shell — install [Git for Windows](https://git-scm.com/download/win) (pi finds Git Bash automatically).

## Running Tests

### Single Test
```bash
crucible run C1 --model openrouter/moonshotai/kimi-k2.6
```

### With the Poolside agent (pool)
```bash
crucible run C1 --agent pool                                 # tenant mode (logged-in Poolside model)
crucible run C1 --agent pool --model ollama/laguna-xs-2.1:nvfp4
crucible run C1 --agent pool --model openrouter/deepseek/deepseek-v4-flash
```
Without a model, pool runs in tenant mode (recorded as model `pool`). `ollama/` and `openrouter/` models run pool in standalone mode; the model is passed to pool as a bare name.

### With the pi agent instead of opencode
```bash
crucible run C1 --agent pi --model openrouter/moonshotai/kimi-k2.6
crucible run C1 --agent pi --model ollama/qwen3:30b-a3b
crucible run C1 --agent pi --model lmstudio/openai/gpt-oss-20b
crucible run C1 --agent pi                                   # pi's own default model
```
Models use the same `provider/model` strings as opencode. `ollama/` and `lmstudio/` models are registered with pi for the run (honouring `OLLAMA_BASE_URL` / `LMSTUDIO_BASE_URL`); anything else (`openrouter/...`, `anthropic/...`, ...) is handed to pi as-is and uses pi's usual API-key env vars (e.g. `OPENROUTER_API_KEY`).

Runs are hermetic: pi is launched with `--no-extensions` plus crucible's own per-run extension, and its session is written into the run directory, so `~/.pi/agent` is never modified.

### Full Suite
```bash
crucible run all --model openrouter/moonshotai/kimi-k2.6
```

### With Ollama (local)
```bash
crucible run G2 --model ollama/qwen3:30b-a3b
```

### Watch Mode (opens the agent TUI with the prompt pre-loaded)
```bash
crucible run C2b --model openrouter/moonshotai/kimi-k2.6 --watch
crucible run C1 --agent pi --model ollama/qwen3:30b-a3b --watch
crucible run C1 --agent pool --watch
```
This opens the agent's TUI in the workspace directory so you can observe the model working in real time (pi and pool auto-send the task). Quit the TUI when the task completes (`/quit` for pi and pool, `Ctrl+C` for opencode) — the run finalizes after the TUI exits.

Watch runs are fully scoreable: pi writes its session into the run directory (`--session-dir`), from which crucible builds `session.json` + a readable `stdout.txt` transcript, pool's is rebuilt from its trajectory record, and opencode exports its session, so tool calls and output text are captured in both modes. pi has no tool-approval prompts and pool watch runs auto-approve (`--mode always-allow`, matching headless `--unsafe-auto-allow`), so unattended runs never stall on permission prompts.

> **Note:** driving a TUI from a headless shell (synthetic pty) is unreliable for teardown — watch mode is designed for a human terminal. For unattended automation, use headless mode.

*Alternative: Use `python3 -m crucible.cli ...` if `crucible` is not on PATH.*

### Suite Categories
Suites are derived from test-ID prefixes: `C`→coding, `W`→writing, `E`→everyday, `G`→reasoning, `H`→home.

- `coding`: C1, C1b, C2, C2b, C3, C4, C4b, C5, C6
- `writing`: W1a, W1b, W1c, W2, W2b
- `everyday`: E1-E4
- `reasoning`: G1-G3
- `home`: H1-H4
- `all`: Everything

Each prompt also declares a scoring **category** (`coding_build`, `coding_debug`, `coding_repo`, `browser_tool`, `everyday`, `reasoning`, `structured_data`, `long_agent`, `home_maintenance`, `writing`) used for run directory layout and sweep aggregation. Run paths are `runs/<model_slug>/<category>/<test_id>/<timestamp>/`.

## Scoring

After a run completes, crucible offers to score it right away (`Would you like to score ... now? [y/N]`). You can also score later:
```bash
crucible score <RUN_ID>
```

`RUN_ID` can be either:
- The **full path** (e.g. `openrouter_moonshotai_kimi-k2.6/everyday/E2/20260829_040024`)
- Just the **timestamp leaf** (e.g. `20260829_040024`) — it will be found recursively

Example:
```bash
crucible score 20260829_040024
crucible score openrouter_moonshotai_kimi-k2.6/everyday/E2/20260829_040024
```

The interactive CLI walks you through each rubric criterion and saves results to `runs/<MODEL>/<CATEGORY>/<TEST>/<TIMESTAMP>/results.json`.

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
   - optional: `validate(model, prompt_def)` (API keys, unsupported tests), `prepare(ctx)` (setup/teardown around the run, e.g. pool's settings.yaml), `token_usage(run_dir)`, `response_timings(run_dir)`, `status(result)`
2. Add an instance to `AGENTS` in `crucible/agents/__init__.py`.

`--agent <name>`, preflight checks, install hints, metrics and the console summary then work automatically. Use `crucible/procs.py` conventions for portability: single-line arguments, prompt passed as a file, per-run config in env vars.

## Developing

```bash
python -m pip install -e . pytest
python -m pytest            # unit + end-to-end tests (pi's runs when `pi` is on PATH; pool's uses a stand-in CLI)
```
CI (`.github/workflows/tests.yml`) runs the suite on Linux, macOS and Windows with pi installed.

## Structure

- `prompts/` — Benchmark prompt definitions (YAML with rubrics)
- `fixtures/` — Test data (calendar JSON, writing samples, etc.)
- `repos/` — Seeded buggy repositories for coding tests
- `runs/` — Output directory for test results
- `crucible/cli.py` — CLI entry point (`run` / `score` / `report`)
- `crucible/runner.py` — `crucible run`: per-test orchestration and the suite loop
- `crucible/agents/` — One module per harness: `opencode.py`, `pi.py` (+ `pi_extension.ts`), `pool.py`, `direct.py`
- `crucible/workspace.py` — Prompts, run directories, workspace setup, fixtures
- `crucible/models.py` / `crucible/providers.py` — Model resolution; provider table (list models, stream completions)
- `crucible/metrics.py` — Metrics in `meta.json` (tests, tool calls, tokens, latency)
- `crucible/console.py` — What `crucible run` prints
- `crucible/procs.py` — Cross-platform process launch / tree-kill (macOS, Linux, Windows)
- `crucible/session.py` — Normalized session events, transcript, tool-call counting
- `crucible/scorer.py` — Interactive scoring (`score_run`)
- `crucible/reporter.py` — Comparison report generator

## How It Works

1. The runner creates a workspace in `runs/<MODEL>/<CATEGORY>/<TEST_ID>/<TIMESTAMP>/workspace/` by invoking `crucible run`
2. For coding tests, it copies the seeded repo into the workspace (repos are never mutated)
3. For reasoning tests, it copies fixtures (e.g., `calendar-fixture.json`)
4. In headless mode, it invokes `opencode run` / `pi -p` with the prompt attached as a file. In watch mode, it opens the agent's TUI in the workspace with the prompt pre-loaded.
5. Results are saved: `stdout.txt`, `stderr.txt`, `session.json` (if available), `meta.json`
6. You score manually with `crucible score` (automated graders planned for select tests)

## Model Aliases

Any model your opencode installation supports works. Common examples:
- `openrouter/moonshotai/kimi-k2.6`
- `openrouter/anthropic/claude-sonnet-4`
- `openrouter/openai/gpt-5`
- `ollama/qwen3:30b-a3b`
- `ollama/llama3.1:8b`

## Timeout

Default timeout is 600 seconds (10 minutes) per test. Override with `--timeout`:
```bash
crucible run C1 --model openrouter/moonshotai/kimi-k2.6 --timeout 300
```

## Mock MCP Server

Tests that need email / calendar / news / weather data declare the mock MCP server in their prompt YAML:

```yaml
mcp_servers:
  - mock-data
```

The server (`fixtures/mock-mcp-server/mock_server.py`, stdio JSON-RPC) serves fixture data from `fixtures/mock-data/` (`emails.json`, `calendar.json`, `news.json`, `weather.json`) via four tools: `get_emails`, `get_calendar_events`, `get_news`, `get_weather`.

**Wiring is per-run and self-contained — nothing goes in global agent configs:**
- **opencode**: the runner injects `OPENCODE_CONFIG_CONTENT` into the spawned process only
- **pool**: pool has no per-launch MCP config, so the harness adds the entry to `~/.config/poolside/settings.yaml` for the run and removes it afterwards, even on timeout or Ctrl+C (a pre-existing entry is left untouched)
- **pi**: pi has no MCP support, so crucible's per-run pi extension (`crucible/agents/pi_extension.ts`, loaded with `-e`) spawns the declared MCP servers and registers their tools as native pi tools; config arrives via the `CRUCIBLE_PI_CONFIG` env var

This makes fresh machines work with zero manual setup: install the repo, run the test, the mock server is wired up and torn down automatically.

### Latency

`meta.json` also records `ttft_s` (time to first token of the first model response, from request sent), `ttft_avg_s`, `response_time_avg_s` and `model_responses`, and the per-test terminal summary prints them. Each harness reports only what it actually measures:
- **pi**: exact, timestamped inside pi by crucible's extension (headless and `--watch`)
- **direct**: exact, from the streamed provider response (direct runs also record token usage)
- **opencode**: per-response duration from its session export; no token-level timestamps, so TTFT is empty
- **pool**: per-response duration from its trajectory record (inference start/end); its trajectory has no first-token event, so TTFT is empty

### Token usage

`meta.json` records `tokens_in` / `tokens_out` per run (from opencode's session export, pi's session file, or pool's trajectory record). Caveats: opencode's `tokens_out` includes reasoning tokens; pi's `tokens_in` includes cache reads/writes; pool's `tokens_in` may include cached input.

### Verified MCP permutations (E4)

All combinations below ran against the mock MCP server; "✓" means the mock tools were invoked and the briefing ended with the Spanish paragraph.

| Agent   | Mode     | Model                                   | Run (20260903_*) | Result | tokens in/out |
|---------|----------|------------------------------------------|------------------|--------|---------------|
| pool    | headless | tenant default (laguna-xs-2.1:nvfp4)     | 131513           | ✓      | 12513 / 925   |
| pool    | headless | openrouter/deepseek/deepseek-v4-flash    | 032355           | ✓      | 12833 / 1027  |
| pool    | headless | openrouter/moonshotai/kimi-k2.6          | 030425           | ✓      | n/a (pre-fix) |
| pool    | headless | ollama/laguna-xs-2.1:nvfp4               | 033147           | ✓      | 25533 / 740   |
| opencode| headless | openrouter/anthropic/claude-sonnet-4.5   | 010917           | ✓      | n/a (pre-fix) |
| opencode| headless | openrouter/deepseek/deepseek-v4-flash    | 032424           | ✓      | n/a (run pre-dated token capture wiring) |
| pool    | watch    | ollama/laguna-xs-2.1:nvfp4               | 033631           | ✓      | 29207 / 776   |
| pool    | watch    | openrouter/deepseek/deepseek-v4-flash    | 040603           | ✓ *    | 14584 / 1209  |
| opencode| watch    | openrouter/deepseek/deepseek-v4-flash    | 041420           | ✓      | n/a (run pre-dated token capture wiring) |

\* Task completed and verified via pool's ACP log; artifacts were exported from the trajectory record after a synthetic-pty teardown. (Rows predate the harness refactor.)

pi runs are covered end-to-end by `tests/test_pi_integration.py`, which drives the real pi CLI against a scripted OpenAI-compatible model (`tests/fake_openai.py`) through the mock MCP server, on Linux, macOS and Windows in CI.

### Pitfalls learned

- **Rubrics must live in a top-level `rubric:` key**, never inside `prompt:` — otherwise the agent sees the eval criteria (fixed for E4; all prompts scanned).
- **Stale global `crucible` install**: an editable install pointing at a different checkout silently runs old code (symptom: "MCP not available" despite everything else working). Check with `pip show crucible | grep -i editable`.
- **Pool watch without auto-approve stalls**: the TUI blocks on tool-approval prompts; the harness passes `--mode always-allow` in watch mode.
- **Pool has no per-launch MCP flag**: only settings.yaml; hence the add/remove-around-the-run approach (`PoolAgent.prepare`).
- **Pool trajectory location** (as `pool config` prints it): `~/Library/Application Support/poolside/trajectories` on macOS, `%LOCALAPPDATA%\poolside\trajectories` on Windows, `$XDG_STATE_HOME` (default `~/.local/state`)`/poolside/trajectories` on Linux. Set `CRUCIBLE_POOL_TRAJECTORIES_DIR` to override.
- **Pool MCP schema**: `settings.yaml` entries need `command` as a single string plus `args` (pool 1.0.16 rejects a list-valued `command`).
- **Windows argument mangling**: npm CLIs are `.cmd` shims on Windows and cmd.exe truncates multi-line arguments, so prompts are always attached as `prompt.txt` (never passed inline) and per-run config travels in env vars.
