#!/usr/bin/env python3
"""`crucible run`: run benchmark tests through an agent harness.

Usage:
    crucible run CODE-1 --model openrouter/moonshotai/kimi-k2.6
    crucible run coding --model openrouter/moonshotai/kimi-k2.6
    crucible run CODE-1 --model ollama/qwen3:30b-a3b --watch
    crucible run CODE-1 --agent pi --model ollama/qwen3:30b-a3b
    crucible run RSCH-1 --agent direct --model openrouter/z-ai/glm-5.3-flash

Flow per test: load prompt -> agent.check() -> new run dir (+ workspace) ->
agent.run() -> meta.json -> console summary. Everything harness-specific lives
in crucible/agents/; this module never branches on which agent it is.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from crucible import checks, console, environment, graders, scorer, versioning, workspace
from crucible.agents import AGENTS, DEFAULT_AGENT, Agent, RunContext
from crucible.agents.base import available_mcp_servers
from crucible.cost import BilledCost
from crucible.metrics import extract_metrics
from crucible.models import resolve_model
from crucible import plan as planner
from crucible.taxonomy import (MODE_LABELS, harness_problem, validate_area, validate_category,
                               validate_status, validate_tier)


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


# Agent harnesses send a system prompt plus tool definitions on every turn (opencode's is ~10k
# tokens); below this the agent can't even start, so the run would measure the setup, not the model.
MIN_AGENT_CONTEXT = 32_768


def _context_problem(agent: Agent, model: str | None) -> str | None:
    """Refuse agent runs on a local server whose loaded context is too small to hold the agent."""
    if not agent.uses_workspace:
        return None
    loaded = environment.inference(model).get("context_length")
    if loaded is not None and loaded < MIN_AGENT_CONTEXT:
        return (f"{model} is loaded with a {loaded:,}-token context; agent harnesses need at least "
                f"{MIN_AGENT_CONTEXT:,}. Reload it with a larger context (LM Studio: model settings > Context Length).")
    return None


def _write_meta(ctx: RunContext, agent: Agent, prompt_def: dict, result: dict,
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
        # Which test content and rubric this run used: scores only compare within a version
        "test": versioning.test_identity(prompt_def),
        # Captured after the run, when a local server has the model loaded
        "environment": environment.capture(ctx.model, agent.executable),
        # What the model could reach: tool access shapes scores (e.g. RSCH-2)
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
    validate_tier(prompt_def.get("tier"))
    validate_status(prompt_def.get("status"))
    validate_area(prompt_def)
    if prompt_def["status"] == "retired":
        raise RunRefused("this test is retired")
    mismatch = harness_problem(prompt_def, agent_name)
    if mismatch:
        raise RunRefused(mismatch)
    agent = AGENTS[agent_name]
    problem = agent.check(model, prompt_def) or _context_problem(agent, model)
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
    meta = _write_meta(ctx, agent, prompt_def, result, started_at, elapsed, bill.usd)
    _record_outcome(ctx, meta)
    _record_checks(ctx, prompt_def, meta)
    _flag_leaks(ctx, meta)
    workspace.finalize_workspace(ctx.run_dir)
    console.print_result(meta, ctx.run_dir)
    return ctx.run_id


def classify_outcome(meta: dict, run_dir: Path) -> str:
    """What happened, before any scoring.

    harness_error: the agent exited before the model produced anything (no responses, no
                   tokens, no answer); a setup failure, not the model's, so the run is invalid
    timeout:       hit the time limit (counts: running out of time is a result)
    no_answer:     the model produced tokens but never an answer (counts against the model)
    failed:        exited with an error after the model produced output (counts; worth a look)
    completed:     finished cleanly with an answer
    """
    metrics = meta.get("metrics") or {}
    produced = bool(metrics.get("model_responses") or metrics.get("tokens_out") or metrics.get("tool_calls"))
    answer = checks.final_answer(run_dir).strip()
    if meta.get("timed_out"):
        return "timeout"
    if meta.get("returncode") not in (0, None):
        return "failed" if (produced or answer) else "harness_error"
    return "completed" if answer else ("no_answer" if produced else "harness_error")


def _record_outcome(ctx: RunContext, meta: dict) -> None:
    meta["outcome"] = classify_outcome(meta, ctx.run_dir)
    if meta["outcome"] == "harness_error":
        meta["invalid"] = {"reason": "Harness error: the agent exited before the model produced anything.",
                           "marked_at": datetime.now(timezone.utc).isoformat()}
        print("  [INVALID] harness error: the model never produced anything; rerun when the setup is fixed")
    (ctx.run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _record_checks(ctx: RunContext, prompt_def: dict, meta: dict) -> None:
    """Run the prompt's programmatic checks and hidden tests, and score the run when that's all it needs."""
    results = checks.check_results(ctx.run_dir, prompt_def)
    grader = None
    if prompt_def.get("grader") and meta.get("outcome") not in ("harness_error",):
        print("  Running the hidden acceptance tests...")
        grader = graders.run(ctx.run_dir, prompt_def)
    if not results and not grader:
        return
    if results:
        meta["checks"] = results
        (ctx.run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        for r in results:
            print(f"  check {r['id']}: {'PASS' if r['passed'] else 'FAIL'} ({r['detail']})")
    # Fully deterministic tests are scored on the spot: no judge, no human
    record = checks.save_check_score(ctx.run_dir, prompt_def, results, grader)
    if record:
        for c in record["criteria"]:
            print(f"  {c['criterion']}: {c['score']}/{c['max_score']} ({c['detail']})")
        capped = f", capped at {record['capped_at']}" if record.get("capped_at") is not None else ""
        print(f"  score: {record['scores']['_overall']}/10{capped}")


TRANSCRIPTS = ("stdout.txt", "stderr.txt", "session.json")


def find_leaks(run_dir: Path) -> list[str]:
    """Paths inside crucible's checkout that the agent touched, outside its own run directory.

    Agents work outside the checkout, so a crucible path in the transcript means the agent
    went looking: for graders, rubrics or other models' runs.
    """
    root = str(workspace.REPO_ROOT)
    own = str(run_dir.resolve())
    found: set[str] = set()
    for name in TRANSCRIPTS:
        path = run_dir / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace").replace(own, "<run>")
        for match in re.finditer(re.escape(root) + r"[^\s\"'`)\]>]*", text):
            found.add(match.group(0))
    return sorted(found)[:20]


def _flag_leaks(ctx: RunContext, meta: dict) -> None:
    leaks = find_leaks(ctx.run_dir)
    if not leaks:
        return
    meta["leaks"] = leaks
    meta["invalid"] = {"reason": "Contaminated: the agent read files in crucible's checkout outside its workspace "
                                 "(see leaks).", "marked_at": datetime.now(timezone.utc).isoformat()}
    (ctx.run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"  [INVALID] agent reached crucible's own files: {', '.join(leaks[:3])}")


def _read_meta(run_dir: Path) -> dict:
    try:
        return json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _stop_workspace_servers(run_dir: Path) -> None:
    """Stop dev servers an agent left listening in its workspace (macOS and Linux, via lsof)."""
    if not shutil.which("lsof"):
        return
    workspace_dir = str((run_dir / "workspace").resolve())
    out = subprocess.run(["lsof", "-nP", "-tiTCP", "-sTCP:LISTEN"], capture_output=True, text=True).stdout
    for pid in out.split():
        cwd = subprocess.run(["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"], capture_output=True, text=True).stdout
        if any(line[1:].startswith(workspace_dir) for line in cwd.splitlines() if line.startswith("n")):
            subprocess.run(["kill", pid], capture_output=True)
            print(f"  Stopped a server the agent left running (pid {pid})")


def run_plan(plan: planner.Plan, watch: bool, output_dir: Path) -> list[str]:
    """Run every step; stop early when the setup is broken rather than the model."""
    run_ids, setup_failures = [], 0
    total = len(plan.steps)
    for mode, steps in plan.groups():
        if len(plan.groups()) > 1:
            print(f"\n=== {MODE_LABELS[mode]} tests ({len(steps)}) ===")
        for step in steps:
            i = plan.steps.index(step) + 1
            if total > 1:
                print(f"\n[{i}/{total}] {step.test_id}  ({step.area}, {step.tier}, {step.harness})")
            try:
                run_id = run_single(step.test_id, plan.model, watch, step.timeout, output_dir, step.harness)
            except RunRefused as exc:
                print(f"[SKIPPED] {step.test_id}: {exc}")
                run_id = None
            except KeyboardInterrupt:
                print("\nStopped by user.")
                return run_ids
            outcome = _read_meta(output_dir / run_id).get("outcome") if run_id else "refused"
            if run_id:
                run_ids.append(run_id)
                if step.mode == "agentic":
                    _stop_workspace_servers(output_dir / run_id)
            # Two in a row means the model or harness isn't reachable: stop, don't burn the suite
            setup_failures = setup_failures + 1 if outcome in ("harness_error", "refused") else 0
            if setup_failures >= 2 and total > 2:
                print("\nSETUP PROBLEM: two runs in a row failed before the model produced anything "
                      "(or were refused). Fix the setup, then rerun with --skip-done to pick up where this stopped.")
                return run_ids
    return run_ids


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="crucible run",
        description="Run benchmark tests. With no test, asks what to run.",
        epilog="Chat tests always run with direct; agentic tests run with --agent (default opencode). "
               "Selectors add up (WRIT-2 MATH-4), filters narrow (chat --tier spark).",
    )
    parser.add_argument("test", nargs="*", help="Test IDs, a mode (chat, agentic), an area (writing, math, coding, "
                                                 "research, ...), a tier (spark, temper, forge) or 'all'")
    parser.add_argument("--mode", choices=list(planner.MODES), help="Only chat or only agentic tests")
    parser.add_argument("--area", help="Only this area")
    parser.add_argument("--tier", choices=list(planner.TIERS), help="Only this tier")
    parser.add_argument("--provider", "-p", help="Model provider (ollama, openrouter, lmstudio)")
    parser.add_argument("--model", "-m", help="Model name (e.g. qwen3.5:9b-mlx) or provider/model")
    parser.add_argument("--agent", choices=list(AGENTS),
                        help="Harness for agentic tests (default: opencode); chat tests always use direct")
    parser.add_argument("--watch", action="store_true", help="Open the agent TUI with the prompt pre-loaded")
    parser.add_argument("--timeout", type=int, help="Seconds per test (default by tier: spark 300, temper 900, forge 1200; "
                                                     "never more than 1200 unless --allow-long)")
    parser.add_argument("--allow-long", action="store_true", help="Lift the 20-minute safety cap on each test")
    parser.add_argument("--skip-done", action="store_true", help="Skip tests this model already ran on their current version")
    parser.add_argument("--output", type=Path, default=Path("runs"), help="Output directory")
    args = parser.parse_args()
    if args.provider or (args.model and "/" not in args.model):
        args.model = resolve_model(args.provider, args.model)
    if args.test and not args.model:
        args.model = AGENTS[args.agent or planner.DEFAULT_AGENTIC_HARNESS].default_model

    if not args.test or not args.model:
        from crucible.wizard import run_wizard
        answer = run_wizard(args)
        if not answer:
            return
        plan, extra = answer
        args.watch = extra["watch"]
    else:
        try:
            tests = planner.select(args.test, args.mode, args.area, args.tier)
        except ValueError as exc:
            parser.error(str(exc))
        plan = planner.build(args.model, tests, args.agent, args.timeout, args.skip_done, args.output, args.allow_long)
        if args.timeout and args.timeout > planner.MAX_TIMEOUT and not args.allow_long:
            print(f"Time limit capped at {planner.MAX_TIMEOUT // 60} minutes per test (pass --allow-long to lift it).")
        for line in planner.describe(plan):
            print(line)
    run_ids = run_plan(plan, args.watch, args.output)

    summary = []
    for run_id in run_ids:
        meta = _read_meta(args.output / run_id)
        summary.append((meta.get("status", "?"), meta.get("elapsed_time"), run_id))
    console.print_suite_summary(summary)
