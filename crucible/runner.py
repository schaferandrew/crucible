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

from crucible import (checks, console, environment, graders, origin, provenance, providers, runrecord, scorer,
                      versioning, workspace)
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

def _build_context(agent: Agent, task_id: str, prompt_def: dict, model: str | None,
                   watch: bool, timeout: int, output_dir: Path, reasoning: str = "default") -> RunContext:
    """Create the run dir (and workspace, if the agent uses one) with prompt.txt."""
    run = workspace.new_run_dir(output_dir, task_id, model, reasoning)
    prompt_file = run.path / "prompt.txt"
    prompt_file.write_text(prompt_def["prompt"], encoding="utf-8")

    work_dir = workspace.setup_workspace(run.path, prompt_def) if agent.uses_workspace else None
    if work_dir:
        # Agents read the prompt from inside their working directory
        prompt_file = work_dir / "prompt.txt"
        prompt_file.write_text(prompt_def["prompt"], encoding="utf-8")

    return RunContext(
        task_id=task_id, run_path=run.run_path, run_dir=run.path, prompt_file=prompt_file,
        model=model, watch=watch, timeout=timeout, title=run.title, workspace=work_dir,
        mcp_servers=list(prompt_def.get("mcp_servers") or []),
        fixtures=workspace.fixture_names(prompt_def), reasoning=reasoning, run_uuid=run.run_uuid,
    )


# Agent harnesses send a system prompt plus tool definitions on every turn (opencode's is ~10k
# tokens); below this the agent can't even start, so the run would measure the setup, not the model.
MIN_AGENT_CONTEXT = 32_768


# A chat test is one prompt and one answer, but a thinking model can reason for thousands of
# tokens first: with too little context it fills the window and never answers.
MIN_CHAT_CONTEXT = 32_768
MIN_CHAT_CONTEXT_NO_REASONING = 8_192


def min_context(agent: Agent, reasoning: str = "default") -> int:
    if agent.uses_workspace:
        return MIN_AGENT_CONTEXT
    return MIN_CHAT_CONTEXT_NO_REASONING if reasoning == "off" else MIN_CHAT_CONTEXT


def _context_problem(agent: Agent, model: str | None, reasoning: str = "default") -> str | None:
    """Refuse runs on a local server whose loaded context is too small for the run to finish."""
    loaded = environment.inference(model).get("context_length")
    need = min_context(agent, reasoning)
    if loaded is None or loaded >= need:
        return None
    why = ("agent harnesses need" if agent.uses_workspace
           else f"chat tests with reasoning {reasoning} need" if reasoning != "default" else "chat tests with reasoning on need")
    return (f"{model} is loaded with a {loaded:,}-token context; {why} at least {need:,}. "
            "Reload it with a larger context (LM Studio: model settings > Context Length)"
            + ("" if agent.uses_workspace or reasoning == "off" else ", or run with --reasoning off") + ".")


def _write_meta(ctx: RunContext, agent: Agent, prompt_def: dict, result: dict,
                started_at: str, elapsed: float, billed_usd: float | None = None) -> dict:
    """The run record (see crucible/runrecord.py and docs/data-model.md)."""
    # Every run dir has the same shape, even when the TUI printed to the terminal
    for name in ("stdout.txt", "stderr.txt"):
        (ctx.run_dir / name).touch()
    env = environment.capture(ctx.model, agent.executable)
    inference = env["inference"]
    identity = versioning.task_identity(prompt_def)
    meta = {
        "record": "run", "format_version": runrecord.FORMAT_VERSION,
        "run_uuid": ctx.run_uuid,
        "run_path": ctx.run_path,
        "legacy_run_id": None,
        "started_at": started_at,
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_s": round(elapsed, 2),
        # Which task content and rubric this run used: scores only compare within a version
        "task": {"id": prompt_def["id"], "version": identity["version"], "rubric_version": identity["rubric_version"],
                 "content_hash": identity["content_hash"], "rubric_hash": identity["rubric_hash"], "alias": None},
        "harness": {"id": agent.name, "version": env.get("harness_version")},
        # The weights as a variant (who converted them, into what format and quant) and the reasoning
        # level they ran at; each level is its own model on the dashboard
        "model": {**runrecord.model_record(ctx.model, ctx.reasoning,
                                           environment.reasoning_resolved(ctx.model, ctx.reasoning), inference),
                  # Who trained the weights, from the file or server itself (never a lookup table)
                  "origin": origin.capture(ctx.model, inference, providers.openrouter_model_if_fetched(
                      (ctx.model or "").partition("/")[2]))},
        "endpoint": runrecord.endpoint_record(ctx.model, inference, environment.endpoint(ctx.model, ctx.run_dir)),
        # The device that ran the weights; cloud runs have none
        "hardware": runrecord.hardware_record(ctx.model, env.get("machine"), inference),
        "outcome": {"status": None, "harness_status": agent.status(result), "returncode": result["returncode"],
                    "timed_out": result["timed_out"], "invalid": None, "leaks": []},
        "metrics": {**extract_metrics(ctx.run_dir, agent, billed_usd),
                    "reasoning_chars": (runrecord.read_json(ctx.run_dir / "direct-response.json") or {}).get("reasoning_chars")},
        "output_ref": None,
        # Which crucible produced this run, from which checkout, on which machine
        "provenance": {**runrecord.null_provenance(), **provenance.capture(),
                       "machine_label": (env.get("machine") or {}).get("hostname"), "source": "crucible-run"},
        # Stays on this machine: never published
        "local": {
            # Captured after the run, when a local server has the model loaded
            "environment": env,
            # What the model could reach: tool access shapes scores (e.g. weather-vs-normal)
            "tools": {"builtin_web": agent.builtin_web_tools, "mcp_servers": available_mcp_servers(ctx.mcp_servers)},
            "watch": ctx.watch,
            "platform": sys.platform,
        },
    }
    _save_meta(ctx.run_dir, meta)
    return meta


def _save_meta(run_dir: Path, meta: dict) -> None:
    runrecord.write_json(run_dir / "meta.json", meta)


def run_single(task_id: str, model: str | None, watch: bool, timeout: int,
               output_dir: Path, agent_name: str = DEFAULT_AGENT, reasoning: str = "default") -> str:
    """Run one test end to end; returns its run_path. Raises RunRefused."""
    prompt_def = workspace.load_task(task_id)
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
    problem = agent.check(model, prompt_def, reasoning) or _context_problem(agent, model, reasoning)
    if problem:
        raise RunRefused(problem)

    ctx = _build_context(agent, task_id, prompt_def, model, watch, timeout, output_dir, reasoning)
    console.print_header(f"{agent.label} run", [
        ("Test", task_id),
        ("Model", model or "agent default"),
        *([("Reasoning", reasoning)] if reasoning != "default" else []),
        ("Run", ctx.run_path),
        *([("Workspace", ctx.workspace)] if ctx.workspace else []),
    ])

    started_at = datetime.now(timezone.utc).isoformat()
    start = time.time()
    try:
        with BilledCost(model) as bill:
            result = agent.run(ctx)
    except KeyboardInterrupt:
        _discard(ctx.run_dir)
        raise
    elapsed = time.time() - start
    meta = _write_meta(ctx, agent, prompt_def, result, started_at, elapsed, bill.usd)
    _record_outcome(ctx, meta)
    _record_checks(ctx, prompt_def, meta)
    _flag_leaks(ctx, meta)
    workspace.finalize_workspace(ctx.run_dir)
    console.print_result(meta, ctx.run_dir)
    return ctx.run_path


def _discard(run_dir: Path) -> None:
    """Remove a run that was stopped before it finished, and its workspace outside the checkout."""
    link = run_dir / "workspace"
    if link.is_symlink():
        shutil.rmtree(link.resolve(), ignore_errors=True)
    shutil.rmtree(run_dir, ignore_errors=True)
    for parent in run_dir.parents:  # folders the run left empty
        if parent.name == "runs" or not parent.is_dir() or any(parent.iterdir()):
            break
        parent.rmdir()
    print(f"\n  Discarded the unfinished run ({run_dir.name}); nothing was recorded.")


def classify_outcome(meta: dict, run_dir: Path) -> str:
    """What happened, before any scoring.

    harness_error: the agent exited before the model produced anything (no responses, no
                   tokens, no answer); a setup failure, not the model's, so the run is invalid
    timeout:       hit the time limit (counts: running out of time is a result)
    no_answer:     the model produced tokens but never an answer (counts against the model)
    context_limit: the response stopped because it filled the model's context; invalid when the
                   loaded context was below the minimum (a setup problem), otherwise a runaway
                   that counts against the model
    failed:        exited with an error after the model produced output (counts; worth a look)
    completed:     finished cleanly with an answer
    """
    metrics = meta.get("metrics") or {}
    outcome = meta.get("outcome") or {}
    produced = bool(metrics.get("model_responses") or metrics.get("tokens_out") or metrics.get("tool_calls"))
    answer = checks.final_answer(run_dir).strip()
    if outcome.get("timed_out"):
        return "timeout"
    if hit_context_limit(meta, run_dir):
        return "context_limit"
    if outcome.get("returncode") not in (0, None):
        return "failed" if (produced or answer) else "harness_error"
    return "completed" if answer else ("no_answer" if produced else "harness_error")


def hit_context_limit(meta: dict, run_dir: Path) -> bool:
    """The response stopped because the context filled: the provider says so (finish_reason
    "length"), or the tokens used reached the loaded context (for runs recorded before that)."""
    try:
        response = json.loads((run_dir / "direct-response.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False  # only direct runs record how their response ended
    if response.get("finish_reason") == "length":
        return True
    loaded = (meta.get("model") or {}).get("context_loaded")
    used = (response.get("tokens_in") or 0) + (response.get("tokens_out") or 0)
    return bool(loaded) and used >= 0.97 * loaded


def context_limit_is_setup(meta: dict) -> int | None:
    """The loaded context, when it was below what this run needed (so the stop wasn't the model's fault)."""
    loaded = (meta.get("model") or {}).get("context_loaded")
    reasoning = ((meta.get("model") or {}).get("reasoning") or {}).get("requested")
    need = (MIN_CHAT_CONTEXT_NO_REASONING if reasoning == "off" else MIN_CHAT_CONTEXT) \
        if (meta.get("harness") or {}).get("id") == "direct" else MIN_AGENT_CONTEXT
    return loaded if loaded and loaded < need else None


def _record_outcome(ctx: RunContext, meta: dict) -> None:
    outcome = meta["outcome"]
    outcome["status"] = classify_outcome(meta, ctx.run_dir)
    if outcome["status"] == "context_limit":
        small = context_limit_is_setup(meta)
        if small:
            outcome["invalid"] = {"reason": f"Ran out of context: loaded with only {small:,} tokens, which the model filled "
                                         "before it could finish. A setup problem, not the model's; rerun with more context.",
                               "marked_at": datetime.now(timezone.utc).isoformat()}
            print(f"  [INVALID] filled its {small:,}-token context before finishing; rerun with more context")
        else:
            print("  [CONTEXT LIMIT] the model filled its whole context without finishing (a runaway); this counts")
    if outcome["status"] == "harness_error":
        outcome["invalid"] = {"reason": "Harness error: the agent exited before the model produced anything.",
                              "marked_at": datetime.now(timezone.utc).isoformat()}
        print("  [INVALID] harness error: the model never produced anything; rerun when the setup is fixed")
    _save_meta(ctx.run_dir, meta)


def _record_checks(ctx: RunContext, prompt_def: dict, meta: dict) -> None:
    """Run the prompt's programmatic checks and hidden tests, and score the run when that's all it needs."""
    results = checks.check_results(ctx.run_dir, prompt_def)
    grader = None
    if prompt_def.get("grader") and meta["outcome"]["status"] not in ("harness_error",):
        print("  Running the hidden acceptance tests...")
        grader = graders.run(ctx.run_dir, prompt_def)
    if not results and not grader:
        return
    if results:
        meta["local"]["checks"] = results
        _save_meta(ctx.run_dir, meta)
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
    meta["outcome"]["leaks"] = leaks
    meta["outcome"]["invalid"] = {"reason": "Contaminated: the agent read files in crucible's checkout outside its "
                                            "workspace (see leaks).", "marked_at": datetime.now(timezone.utc).isoformat()}
    _save_meta(ctx.run_dir, meta)
    print(f"  [INVALID] agent reached crucible's own files: {', '.join(leaks[:3])}")


def _read_meta(run_dir: Path) -> dict:
    return runrecord.read(run_dir)


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
    run_paths, setup_failures = [], 0
    total = len(plan.steps)
    for mode, steps in plan.groups():
        if len(plan.groups()) > 1:
            print(f"\n=== {MODE_LABELS[mode]} tests ({len(steps)}) ===")
        for step in steps:
            i = plan.steps.index(step) + 1
            if total > 1:
                print(f"\n[{i}/{total}] {step.task_id}  ({step.area}, {step.tier}, {step.harness})")
            try:
                run_path = run_single(step.task_id, plan.model, watch, step.timeout, output_dir, step.harness,
                                    plan.reasoning)
            except RunRefused as exc:
                print(f"[SKIPPED] {step.task_id}: {exc}")
                run_path = None
            except KeyboardInterrupt:
                print("\nStopped by user.")
                return run_paths
            outcome = (_read_meta(output_dir / run_path).get("outcome") or {}).get("status") if run_path else "refused"
            if run_path:
                run_paths.append(run_path)
                if step.mode == "agentic":
                    _stop_workspace_servers(output_dir / run_path)
            # Two in a row means the model or harness isn't reachable: stop, don't burn the suite
            setup_failures = setup_failures + 1 if outcome in ("harness_error", "refused") else 0
            if setup_failures >= 2 and total > 2:
                print("\nSETUP PROBLEM: two runs in a row failed before the model produced anything "
                      "(or were refused). Fix the setup, then rerun with --skip-done to pick up where this stopped.")
                return run_paths
    return run_paths


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
    parser.add_argument("--reasoning", choices=["default", "off", "low", "medium", "high"],
                        help="Reasoning (thinking) level; each level is recorded as its own model (default: the model's own)")
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
        plan = planner.build(args.model, tests, args.agent, args.timeout, args.skip_done, args.output, args.allow_long,
                             args.reasoning or "default")
        if args.timeout and args.timeout > planner.MAX_TIMEOUT and not args.allow_long:
            print(f"Time limit capped at {planner.MAX_TIMEOUT // 60} minutes per test (pass --allow-long to lift it).")
        for line in planner.describe(plan):
            print(line)
    problem = planner.reasoning_problem(plan)
    if not problem and plan.reasoning != "default":
        from crucible.reasoning import levels
        allowed = levels(plan.model)
        if allowed == ("default",):
            problem = f"{plan.model} doesn't reason, so there's no reasoning level to set; drop --reasoning."
        elif allowed and plan.reasoning not in allowed:
            problem = (f"{plan.model} doesn't take reasoning {plan.reasoning}; it accepts: "
                       f"{', '.join(level for level in allowed if level != 'default')} (or the default).")
    if problem:
        print(problem)
        return
    if args.watch and not any(s.mode == "agentic" for s in plan.steps):
        print("Note: --watch opens an agent's TUI, so it only applies to agentic tests; "
              "chat tests show a live progress line instead.")
    run_paths = run_plan(plan, args.watch, args.output)

    summary = []
    for run_path in run_paths:
        meta = _read_meta(args.output / run_path)
        summary.append(((meta.get("outcome") or {}).get("harness_status", "?"), meta.get("elapsed_s"), run_path))
    console.print_suite_summary(summary)
