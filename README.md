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

4. **Ensure opencode is installed and configured** with your model provider (e.g., OpenRouter).

## Running Tests

### Single Test
```bash
crucible run C1 --model openrouter/moonshotai/kimi-k2.6
```

### Full Suite
```bash
crucible run all --model openrouter/moonshotai/kimi-k2.6
```

### With Ollama (local)
```bash
crucible run G2 --model ollama/qwen3:30b-a3b
```

### Watch Mode (opens full TUI)
```bash
crucible run C2b --model openrouter/moonshotai/kimi-k2.6 --watch
```
This opens the interactive opencode TUI in the workspace directory so you can observe the model working in real time. Press `q` or `Ctrl+C` to exit when done. In watch mode, output streams live to the terminal and is not captured to `stdout.txt`.

*Alternative: Use `python3 -m crucible.cli ...` if `crucible` is not on PATH.*

### Suite Categories
- `coding`: C1, C1b, C2, C2b, C3, C4, C4b, C5, C6
- `writing`: W1a, W1b, W1c, W2, W2b
- `everyday`: E1-E3
- `reasoning`: G1-G3
- `home`: H1-H4
- `all`: Everything

## Scoring

After a run completes, score it interactively:
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

## Structure

- `prompts/` — Benchmark prompt definitions (YAML with rubrics)
- `fixtures/` — Test data (calendar JSON, writing samples, etc.)
- `repos/` — Seeded buggy repositories for coding tests
- `runs/` — Output directory for test results
- `crucible/cli.py` — CLI entry point
- `crucible/runner.py` — Main runner module
- `crucible/scorer.py` — Interactive scoring module
- `crucible/reporter.py` — Comparison report generator

## How It Works

1. The runner creates a workspace in `runs/<MODEL>/<CATEGORY>/<TEST_ID>/<TIMESTAMP>/workspace/` by invoking `crucible run`
2. For coding tests, it copies the seeded repo into the workspace (repos are never mutated)
3. For reasoning tests, it copies fixtures (e.g., `calendar-fixture.json`)
4. In headless mode, it invokes `opencode run` with the prompt attached as a file. In watch mode, it opens the opencode TUI in the workspace with the prompt pre-loaded.
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
