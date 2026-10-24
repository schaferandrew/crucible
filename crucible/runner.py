#!/usr/bin/env python3
"""Benchmark runner: routes tests to an agent (opencode, pi) or direct API.

Usage:
    crucible run C1 --model openrouter/moonshotai/kimi-k2.6
    crucible run coding --model openrouter/moonshotai/kimi-k2.6
    crucible run C1 --model ollama/qwen3:30b-a3b --watch
    crucible run C1 --agent pi --model openrouter/moonshotai/kimi-k2.6
    crucible run C1 --agent pi --model ollama/qwen3:30b-a3b
    crucible run E1 --agent direct --model openrouter/z-ai/glm-5.3-flash

Options:
    --provider, -p   Model provider (ollama, openrouter, lmstudio)
    --model, -m      Model name or provider/model
    --agent          opencode (default), pi, or direct (no tools)
    --watch          Open the agent TUI with the prompt pre-loaded
    --timeout        Timeout in seconds (default 600)
    --output         Output directory for runs (default ./runs)

Every run writes to runs/<model_slug>/<category>/<test_id>/<timestamp>/:
    prompt.txt, stdout.txt, stderr.txt, command.sh, meta.json and, when the
    agent supports it, session.json.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from crucible import direct_runner, procs, scorer
from crucible.agents import AGENTS, DEFAULT_AGENT, Agent, RunContext
from crucible.selector import select_from_list
from crucible.session import count_tool_calls
from crucible.taxonomy import derive_suites, validate_category


REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = REPO_ROOT / "prompts"
FIXTURES_DIR = REPO_ROOT / "fixtures"
REPOS_DIR = REPO_ROOT / "repos"


# --------------------------------------------------------------------------
# Model resolution
# --------------------------------------------------------------------------

# provider -> (direct_runner fetch function name, hint when none found).
# Looked up by name at call time so tests can patch direct_runner.
PROVIDER_CATALOG = {
    "ollama": (
        "fetch_ollama_models",
        "No ollama models found. Run 'ollama pull <model>' first.",
    ),
    "lmstudio": (
        "fetch_lmstudio_models",
        "No LM Studio models found. Start LM Studio and load a model first.",
    ),
    "openrouter": (
        "fetch_openrouter_models",
        "No openrouter models found (check OPENROUTER_API_KEY).",
    ),
}


def resolve_model(provider: str | None, model: str | None) -> str | None:
    """Resolve the final provider/model string from CLI args."""
    if provider and model:
        # Don't double the prefix when the model already carries it
        return model if model.startswith(f"{provider}/") else f"{provider}/{model}"

    if model:  # model only: use as-is when prefixed, else fuzzy-match
        if "/" in model:
            return model
        matches = direct_runner.find_model_matches(model)
        if not matches:
            print(f"Model '{model}' not found on any provider.")
            sys.exit(1)
        if len(matches) == 1:
            return matches[0]
        selected = select_from_list(matches, f"Model '{model}' found on multiple providers:")
        if selected is None:
            print("Cancelled.")
            sys.exit(0)
        return selected

    if provider:  # provider only: interactive selection for that provider
        if provider not in PROVIDER_CATALOG:
            print(f"Unknown provider: {provider}")
            sys.exit(1)
        fetch_name, none_hint = PROVIDER_CATALOG[provider]
        models = getattr(direct_runner, fetch_name)()
        if not models:
            print(none_hint)
            sys.exit(1)
        selected = select_from_list([f"{provider}/{m}" for m in models],
                                    f"Select {provider} model:")
        if selected is None:
            print("Cancelled.")
            sys.exit(0)
        return selected

    return None  # neither: agent default


# --------------------------------------------------------------------------
# Workspace / prompt loading
# --------------------------------------------------------------------------

def load_prompt(test_id: str) -> dict:
    path = PROMPTS_DIR / f"{test_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def setup_workspace(run_dir: Path, prompt_def: dict) -> Path:
    """Create the run workspace and copy in any repo/fixture files."""
    workspace = run_dir / "workspace"
    ensure_clean_dir(workspace)

    repo_name = prompt_def.get("repo")
    if repo_name:
        src = REPOS_DIR / repo_name
        if src.is_dir():
            for item in src.iterdir():
                if item.is_dir():
                    shutil.copytree(item, workspace / item.name)
                else:
                    shutil.copy2(item, workspace / item.name)
        elif src.exists():
            shutil.copy2(src, workspace)

    fixtures = prompt_def.get("fixtures", [])
    if isinstance(fixtures, str):
        fixtures = [fixtures]
    for fixture_name in fixtures:
        src = FIXTURES_DIR / fixture_name
        if src.is_dir():
            shutil.copytree(src, workspace / src.name)
        elif src.exists():
            shutil.copy2(src, workspace)
        else:
            print(f"  Warning: fixture not found: {src}")

    _install_dependencies(workspace)
    return workspace


def _install_dependencies(workspace: Path) -> None:
    """Install a seeded repo's dependencies so the agent starts from a working tree."""
    if (workspace / "package.json").exists():
        print("  Installing npm dependencies...")
        try:
            subprocess.run([procs.resolve_executable("npm"), "install"],
                           cwd=workspace, capture_output=True, text=True)
        except FileNotFoundError:
            print("  Warning: npm not found on PATH; skipping npm install")
    elif (workspace / "requirements.txt").exists():
        print("  Installing pip dependencies...")
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
                       cwd=workspace, capture_output=True, text=True)


# --------------------------------------------------------------------------
# Run bookkeeping
# --------------------------------------------------------------------------

def _print_header(title: str, rows: list[tuple[str, str]]) -> None:
    print(f"\n{'='*60}")
    print(title)
    for label, value in rows:
        print(f"{label}: {value}")
    print(f"{'='*60}\n")


def _write_meta(run_dir: Path, meta: dict) -> None:
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _finalize_run(run_dir: Path, run_id: str, test_id: str, agent: str,
                  model: str | None, watch: bool, started_at: str, start_time: float,
                  result: dict, status: str, agent_impl: Agent | None = None) -> None:
    """Write meta.json and print the closing status block."""
    elapsed = time.time() - start_time

    # Watch mode prints to the terminal; still leave empty artifacts behind so
    # every run directory has the same shape.
    for name in ("stdout.txt", "stderr.txt"):
        path = run_dir / name
        if not path.exists():
            path.write_text("", encoding="utf-8")

    _write_meta(run_dir, {
        "run_id": run_id,
        "test_id": test_id,
        "agent": agent,
        "model": model,
        "watch": watch,
        "platform": sys.platform,
        "started_at": started_at,
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_time": round(elapsed, 2),
        "returncode": result["returncode"],
        "timed_out": result["timed_out"],
        "metrics": extract_metrics(run_dir, agent_impl),
    })

    print(f"\n[{status}] {run_id}")
    print(f"  Elapsed: {elapsed:.1f}s")
    print(f"  Output: {run_dir}")
    if status != "COMPLETE":
        stderr_tail = (run_dir / "stderr.txt").read_text(
            encoding="utf-8", errors="replace").strip().splitlines()
        if stderr_tail:
            print(f"  Error: {stderr_tail[-1][:200]}")
    if not status.startswith(("TIMEOUT", "ERROR")):
        print(f"  To score: crucible score {run_id}")


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

def extract_metrics(run_dir: Path, agent: Agent | None = None) -> dict:
    """Best-effort raw metrics from run artifacts; None when unknown."""
    stdout_path = run_dir / "stdout.txt"
    tests_passed = tests_failed = None
    if stdout_path.exists():
        text = stdout_path.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"(\d+) passed", text)
        tests_passed = int(m.group(1)) if m else None
        m = re.search(r"(\d+) failed", text)
        tests_failed = int(m.group(1)) if m else None
        if tests_failed == 0 and tests_passed is None:
            tests_passed = 0

    session_path = run_dir / "session.json"
    tool_calls = count_tool_calls(session_path) if session_path.exists() else None

    # Token usage comes from each agent's own session record; output tokens
    # include reasoning tokens.
    usage = agent.token_usage(run_dir) if agent else None
    tokens_in, tokens_out = usage if usage else (None, None)

    return {
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,
        "tool_calls": tool_calls,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
    }


# --------------------------------------------------------------------------
# Routing
# --------------------------------------------------------------------------

def should_run_direct(agent: str, needs_tools: bool, model: str | None) -> bool:
    """Decide whether a test bypasses the agent and calls the provider API directly.

    Direct mode must be explicitly requested (--agent direct) and is only
    allowed when the prompt declares needs_tools: false and the model is on a
    direct-capable provider (ollama, openrouter, lmstudio). Tool-requiring
    tests can NEVER run directly.
    """
    return bool(
        agent == "direct"
        and not needs_tools
        and model
        and model.startswith(tuple(PROVIDER_CATALOG))
    )


# --------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------

def _run_direct(test_id: str, run_id: str, run_dir: Path, prompt_def: dict,
                prompt_text: str, model: str, timeout: int, watch: bool) -> str:
    """Text-only run straight against the provider API — no agent, no workspace."""
    _print_header("Direct API run (no tool use)", [
        ("Test", test_id),
        ("Model", model),
        ("Run ID", run_id),
    ])

    started_at = datetime.now(timezone.utc).isoformat()
    start_time = time.time()

    # Inline fixture contents into the prompt (direct mode has no file tools),
    # and record the exact prompt sent so runs are auditable.
    full_prompt = direct_runner._inline_fixtures(
        prompt_text, prompt_def.get("fixtures", []), FIXTURES_DIR)
    (run_dir / "prompt.txt").write_text(full_prompt, encoding="utf-8")

    stdout_text = ""
    stderr_text = ""
    try:
        stdout_text = direct_runner.run_direct(full_prompt, model, [], FIXTURES_DIR, timeout)
    except Exception as e:
        stderr_text = f"Direct runner error: {e}"

    (run_dir / "stdout.txt").write_text(stdout_text, encoding="utf-8")
    (run_dir / "stderr.txt").write_text(stderr_text, encoding="utf-8")

    _finalize_run(
        run_dir, run_id, test_id, "direct", model, False, started_at, start_time,
        result={"returncode": 0 if not stderr_text else 1, "timed_out": False},
        status="COMPLETE" if not stderr_text else "ERROR",
    )
    return run_id


def _run_agent(agent: Agent, ctx: RunContext) -> str:
    """Launch an agent headless (logged) or as a TUI (watch), then collect."""
    _print_header(f"{agent.label} run", [
        ("Test", ctx.test_id),
        ("Model", ctx.model or "agent default"),
        ("Run ID", ctx.run_id),
        ("Workspace", ctx.workspace),
    ])

    started_at = datetime.now(timezone.utc).isoformat()
    start_time = time.time()

    launch = agent.launch(ctx)
    env = {**os.environ, **launch.env}
    (ctx.run_dir / "command.sh").write_text(
        "#!/bin/bash\n" + procs.format_command(launch.cmd, launch.env) + "\n", encoding="utf-8")

    if ctx.watch:
        print(f"Command: {' '.join(launch.cmd)}\n")
        result = procs.run_interactive(launch.cmd, ctx.timeout, ctx.test_id,
                                       cwd=launch.cwd, env=env)
    else:
        result = procs.run_logged(launch.cmd, ctx.run_dir, ctx.timeout, ctx.test_id,
                                  cwd=launch.cwd, env=env)
    agent.collect(ctx)

    _finalize_run(ctx.run_dir, ctx.run_id, ctx.test_id, agent.name, ctx.model, ctx.watch,
                  started_at, start_time, result, agent.status(result), agent_impl=agent)
    return ctx.run_id


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------

def _preflight(agent_name: str, model: str | None, needs_tools: bool, test_id: str) -> None:
    """Exit with a clear message when the run cannot possibly work."""
    if agent_name == "direct":
        if needs_tools:
            print(f"[ERROR] Test {test_id} requires tool access; refusing to run it directly. "
                  f"Use --agent {' or --agent '.join(AGENTS)}.")
            sys.exit(1)
        if not model or not model.startswith(tuple(PROVIDER_CATALOG)):
            print("[ERROR] Direct mode needs a model on a direct-capable provider "
                  "(ollama/, openrouter/, lmstudio/).")
            sys.exit(1)
        return

    agent = AGENTS[agent_name]
    if shutil.which(agent.executable) is None:
        print(f"[ERROR] '{agent.executable}' not found on PATH. Install it with: {agent.install_hint}")
        sys.exit(1)
    error = agent.validate(model)
    if error:
        print(f"[ERROR] {error}")
        sys.exit(1)


def run_single(test_id: str, model: str | None, watch: bool, timeout: int,
               output_dir: Path, agent: str = DEFAULT_AGENT) -> str:
    """Run a single test. Returns run_id."""
    prompt_def = load_prompt(test_id)
    validate_category(prompt_def.get("category"))
    _preflight(agent, model, prompt_def.get("needs_tools", True), test_id)

    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    model_slug = re.sub(r'[/:\\<>"|?*]', "_", model or "default")
    category = prompt_def.get("category", "uncategorized")
    run_id = f"{model_slug}/{category}/{test_id}/{now}"
    run_dir = (output_dir / run_id).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    prompt_text = prompt_def["prompt"]

    # Direct runs are text-only: no workspace, just the API call
    if agent == "direct":
        (run_dir / "prompt.txt").write_text(prompt_text, encoding="utf-8")
        return _run_direct(test_id, run_id, run_dir, prompt_def, prompt_text,
                           model, timeout, watch)

    workspace = setup_workspace(run_dir, prompt_def)
    prompt_file = workspace / "prompt.txt"
    prompt_file.write_text(prompt_text, encoding="utf-8")
    (run_dir / "prompt.txt").write_text(prompt_text, encoding="utf-8")

    ctx = RunContext(
        test_id=test_id, run_id=run_id, run_dir=run_dir,
        workspace=workspace, prompt_file=prompt_file,
        model=model, watch=watch, timeout=timeout,
        title=f"{now}_{test_id}_{model_slug}",
        mcp_servers=list(prompt_def.get("mcp_servers") or []),
    )
    return _run_agent(AGENTS[agent], ctx)


def _meta_status(run_dir: Path) -> str:
    """Classify a finished run from its meta.json."""
    try:
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "ERROR (no meta recorded)"
    if meta.get("timed_out"):
        return "TIMEOUT"
    rc = meta.get("returncode")
    if rc == 0:
        return "COMPLETE"
    return f"ERROR (exit {rc})"


def _close_the_loop(run_id: str, args: argparse.Namespace) -> None:
    """Interactively score successful runs; failed runs can be retried or discarded."""
    while True:
        status = _meta_status(args.output / run_id)
        try:
            if status == "COMPLETE":
                answer = input(f"\nWould you like to score {run_id} now? [y/N] ").strip().lower()
                if answer in ("y", "yes"):
                    print()
                    sys.argv = ["crucible score", run_id]
                    scorer.main()
                return
            answer = input(
                f"\nRun {status}: {run_id}\n[d]iscard it, [r]etry it, or Enter to leave it? "
            ).strip().lower()
        except EOFError:
            return

        if answer == "d":
            shutil.rmtree(args.output / run_id, ignore_errors=True)
            print(f"  Discarded {run_id}")
            return
        if answer == "r":
            try:
                meta = json.loads((args.output / run_id / "meta.json").read_text(encoding="utf-8"))
                test_id = meta.get("test_id")
            except (OSError, json.JSONDecodeError):
                print("  Cannot retry: meta.json unreadable")
                return
            if not test_id:
                print("  Cannot retry: test_id unknown")
                return
            print()
            run_id = run_single(test_id, args.model, args.watch, args.timeout,
                                args.output, args.agent)
            continue
        return


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="crucible run",
        description="Run AI benchmark tests via an agent (opencode or pi) or direct API",
    )
    parser.add_argument("test", help="Test ID (e.g. C1) or suite (coding, writing, everyday, reasoning, home, all)")
    parser.add_argument("--provider", "-p", help="Model provider (ollama, openrouter, lmstudio)")
    parser.add_argument("--model", "-m", help="Model name (e.g. qwen3.5:9b-mlx) or provider/model")
    parser.add_argument("--agent", choices=[*AGENTS, "direct"], default=DEFAULT_AGENT,
                        help=f"Agent that executes the test (default: {DEFAULT_AGENT}). "
                             "'direct' calls the provider API without an agent — "
                             "only for needs_tools: false prompts")
    parser.add_argument("--watch", action="store_true", help="Open the agent TUI with the prompt pre-loaded")
    parser.add_argument("--timeout", type=int, default=600, help="Timeout in seconds")
    parser.add_argument("--output", type=Path, default=Path("runs"), help="Output directory")
    args = parser.parse_args()

    # Resolve model from provider/model args; None means the agent's default
    args.model = resolve_model(args.provider, args.model)

    # Suites are derived from test-ID prefixes (C->coding, W->writing, ...)
    all_tests = sorted(p.stem for p in PROMPTS_DIR.glob("*.yaml"))
    suites = derive_suites(all_tests)

    if args.test == "all":
        tests = all_tests
    elif args.test in suites:
        tests = suites[args.test]
    else:
        tests = [args.test]

    run_ids = []
    for test_id in tests:
        if not (PROMPTS_DIR / f"{test_id}.yaml").exists():
            print(f"Skipping unknown test: {test_id}")
            continue
        try:
            run_ids.append(run_single(test_id, args.model, args.watch, args.timeout,
                                      args.output, args.agent))
        except KeyboardInterrupt:
            print("\nStopped by user.")
            break
        except Exception as e:
            print(f"Error running {test_id}: {e}")

    print(f"\n{'='*60}")
    print(f"Completed {len(run_ids)} run(s)")
    for rid in run_ids:
        print(f"  {rid}")
    print(f"{'='*60}")

    # Close the loop: score successful runs, discard/retry failed ones.
    # Interactive sessions only, so scripted/headless invocations never block.
    if run_ids and sys.stdin.isatty():
        for rid in run_ids:
            _close_the_loop(rid, args)


if __name__ == "__main__":
    main()
