#!/usr/bin/env python3
"""`crucible run`: run benchmark tests through an agent harness.

Usage:
    crucible run C1 --model openrouter/moonshotai/kimi-k2.6
    crucible run coding --model openrouter/moonshotai/kimi-k2.6
    crucible run C1 --model ollama/qwen3:30b-a3b --watch
    crucible run C1 --agent pi --model ollama/qwen3:30b-a3b
    crucible run C1 --agent pool                          # Poolside tenant mode
    crucible run E1 --agent direct --model openrouter/z-ai/glm-5.3-flash

Flow per test: load prompt -> agent.check() -> new run dir (+ workspace) ->
agent.run() -> meta.json -> console summary. Everything harness-specific lives
in crucible/agents/; this module never branches on which agent it is.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from crucible import console, scorer, workspace
from crucible.agents import AGENTS, DEFAULT_AGENT, Agent, RunContext
from crucible.agents.base import available_mcp_servers
from crucible.cost import BilledCost
from crucible.metrics import extract_metrics
from crucible.models import resolve_model
from crucible.taxonomy import derive_suites, validate_category


class RunRefused(Exception):
    """A test cannot run with this agent/model (e.g. missing CLI or API key)."""


# --------------------------------------------------------------------------
# One test
# --------------------------------------------------------------------------

def _build_context(agent: Agent, test_id: str, prompt_def: dict, model: str | None,
                   watch: bool, timeout: int, output_dir: Path) -> RunContext:
    """Create the run dir (and workspace, if the agent uses one) with prompt.txt."""
    run = workspace.new_run_dir(output_dir, test_id, model, prompt_def)
    prompt_file = run.path / "prompt.txt"
    prompt_file.write_text(prompt_def["prompt"], encoding="utf-8")

    work_dir = workspace.setup_workspace(run.path, prompt_def) if agent.uses_workspace else None
    if work_dir:
        # Agents read the prompt from inside their working directory
        prompt_file = work_dir / "prompt.txt"
        prompt_file.write_text(prompt_def["prompt"], encoding="utf-8")

    return RunContext(
        test_id=test_id, run_id=run.run_id, run_dir=run.path, prompt_file=prompt_file,
        model=model, watch=watch, timeout=timeout, title=run.title, workspace=work_dir,
        mcp_servers=list(prompt_def.get("mcp_servers") or []),
        fixtures=workspace.fixture_names(prompt_def),
    )


def _write_meta(ctx: RunContext, agent: Agent, result: dict,
                started_at: str, elapsed: float, billed_usd: float | None = None) -> dict:
    # Every run dir has the same shape, even when the TUI printed to the terminal
    for name in ("stdout.txt", "stderr.txt"):
        (ctx.run_dir / name).touch()
    meta = {
        "run_id": ctx.run_id,
        "test_id": ctx.test_id,
        "agent": agent.name,
        "model": ctx.model,
        "watch": ctx.watch,
        "platform": sys.platform,
        "started_at": started_at,
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_time": round(elapsed, 2),
        "returncode": result["returncode"],
        "timed_out": result["timed_out"],
        "status": agent.status(result),
        # What the model could reach: tool access shapes scores (e.g. E6)
        "tools": {
            "builtin_web": agent.builtin_web_tools,
            "mcp_servers": available_mcp_servers(ctx.mcp_servers),
        },
        "metrics": extract_metrics(ctx.run_dir, agent, billed_usd),
    }
    (ctx.run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def run_single(test_id: str, model: str | None, watch: bool, timeout: int,
               output_dir: Path, agent_name: str = DEFAULT_AGENT) -> str:
    """Run one test end to end; returns its run_id. Raises RunRefused."""
    prompt_def = workspace.load_prompt(test_id)
    validate_category(prompt_def.get("category"))
    agent = AGENTS[agent_name]
    problem = agent.check(model, prompt_def)
    if problem:
        raise RunRefused(problem)

    ctx = _build_context(agent, test_id, prompt_def, model, watch, timeout, output_dir)
    console.print_header(f"{agent.label} run", [
        ("Test", test_id),
        ("Model", model or "agent default"),
        ("Run ID", ctx.run_id),
        *([("Workspace", ctx.workspace)] if ctx.workspace else []),
    ])

    started_at = datetime.now(timezone.utc).isoformat()
    start = time.time()
    with BilledCost(model) as bill:
        result = agent.run(ctx)
    elapsed = time.time() - start
    meta = _write_meta(ctx, agent, result, started_at, elapsed, bill.usd)
    console.print_result(meta, ctx.run_dir)
    return ctx.run_id


def _read_meta(run_dir: Path) -> dict:
    try:
        return json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


# --------------------------------------------------------------------------
# After the suite: score, retry or discard
# --------------------------------------------------------------------------

def _ask(question: str) -> str:
    try:
        return input(question).strip().lower()
    except EOFError:
        return ""


def _close_the_loop(run_id: str | None, args: argparse.Namespace) -> None:
    """Offer to score a successful run; offer retry/discard for a failed one."""
    while run_id:
        run_dir = args.output / run_id
        meta = _read_meta(run_dir)
        status = meta.get("status", "ERROR (no meta recorded)")
        if status == "COMPLETE":
            if _ask(f"\nWould you like to score {run_id} now? [y/N] ") in ("y", "yes"):
                print()
                scorer.score_run(run_dir)
            return
        answer = _ask(f"\nRun {status}: {run_id}\n[d]iscard it, [r]etry it, or Enter to leave it? ")
        if answer == "d":
            shutil.rmtree(run_dir, ignore_errors=True)
            print(f"  Discarded {run_id}")
            return
        if answer != "r" or not meta.get("test_id"):
            return
        print()
        run_id = _try_run(meta["test_id"], args)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _tests_for(selector: str) -> list[str]:
    """A test ID, a suite name (prefix-derived: C->coding, ...), or 'all'."""
    all_tests = workspace.all_test_ids()
    suites = {"all": all_tests, **derive_suites(all_tests)}
    return suites.get(selector, [selector])


def _try_run(test_id: str, args: argparse.Namespace) -> str | None:
    """run_single, reporting (not raising) a refused run."""
    try:
        return run_single(test_id, args.model, args.watch, args.timeout, args.output, args.agent)
    except RunRefused as exc:
        print(f"[SKIPPED] {test_id}: {exc}")
        return None


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="crucible run",
        description=f"Run AI benchmark tests via an agent harness ({', '.join(AGENTS)})",
    )
    parser.add_argument("test", help="Test ID (e.g. C1) or suite (coding, writing, everyday, reasoning, home, all)")
    parser.add_argument("--provider", "-p", help="Model provider (ollama, openrouter, lmstudio)")
    parser.add_argument("--model", "-m", help="Model name (e.g. qwen3.5:9b-mlx) or provider/model")
    parser.add_argument("--agent", choices=list(AGENTS), default=DEFAULT_AGENT,
                        help=f"Harness that executes the test (default: {DEFAULT_AGENT}). "
                             "'direct' calls the provider API without an agent — "
                             "only for needs_tools: false prompts")
    parser.add_argument("--watch", action="store_true", help="Open the agent TUI with the prompt pre-loaded")
    parser.add_argument("--timeout", type=int, default=600, help="Timeout in seconds")
    parser.add_argument("--output", type=Path, default=Path("runs"), help="Output directory")
    args = parser.parse_args()

    args.model = resolve_model(args.provider, args.model) or AGENTS[args.agent].default_model
    known = set(workspace.all_test_ids())
    tests = _tests_for(args.test)

    run_ids = []
    for i, test_id in enumerate(tests, 1):
        if test_id not in known:
            print(f"Skipping unknown test: {test_id}")
            continue
        if len(tests) > 1:
            print(f"\n[{i}/{len(tests)}] {test_id}")
        try:
            run_id = _try_run(test_id, args)
        except KeyboardInterrupt:
            print("\nStopped by user.")
            break
        except Exception as e:
            print(f"Error running {test_id}: {e}")
            continue
        if run_id:
            run_ids.append(run_id)

    summary = []
    for run_id in run_ids:
        meta = _read_meta(args.output / run_id)
        summary.append((meta.get("status", "?"), meta.get("elapsed_time"), run_id))
    console.print_suite_summary(summary)

    # Interactive sessions only, so scripted/headless invocations never block
    if run_ids and sys.stdin.isatty():
        for run_id in run_ids:
            _close_the_loop(run_id, args)
    if not run_ids:
        sys.exit(1)


if __name__ == "__main__":
    main()
