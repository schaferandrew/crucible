#!/usr/bin/env python3
"""Benchmark runner: routes tests to an agent (opencode, pool) or direct API.

Usage:
    crucible run C1 --model openrouter/moonshotai/kimi-k2.6
    crucible run coding --model openrouter/moonshotai/kimi-k2.6
    crucible run C1 --model ollama/qwen3:30b-a3b --watch
    crucible run C1 --agent pool                          # tenant mode
    crucible run C1 --agent pool --model ollama/laguna... # standalone vs ollama
    crucible run E1 --model openrouter/z-ai/glm-5.3-flash # direct (no tools)

Options:
    --provider, -p   Model provider (ollama, openrouter, lmstudio)
    --model, -m      Model name or provider/model
    --agent          Agent that executes the test: opencode (default) or pool
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
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from crucible import direct_runner, scorer
from crucible.selector import select_from_list
from crucible.taxonomy import derive_suites, validate_category


REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = REPO_ROOT / "prompts"
FIXTURES_DIR = REPO_ROOT / "fixtures"
REPOS_DIR = REPO_ROOT / "repos"

# Event type names for tool invocations in session captures
TOOL_CALL_TYPES = {"tool", "toolCall"}  # opencode export, pool NLJSON

OPENROUTER_API = "https://openrouter.ai/api/v1"


# --------------------------------------------------------------------------
# Model resolution
# --------------------------------------------------------------------------

# provider -> (fetch models, hint when none found)
PROVIDER_CATALOG = {
    "ollama": (
        direct_runner.fetch_ollama_models,
        "No ollama models found. Run 'ollama pull <model>' first.",
    ),
    "lmstudio": (
        direct_runner.fetch_lmstudio_models,
        "No LM Studio models found. Start LM Studio and load a model first.",
    ),
    "openrouter": (
        direct_runner.fetch_openrouter_models,
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
        fetch_models, none_hint = PROVIDER_CATALOG[provider]
        models = fetch_models()
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

    if (workspace / "package.json").exists():
        print("  Installing npm dependencies...")
        subprocess.run(["npm", "install"], cwd=workspace, capture_output=True, text=True)
    elif (workspace / "requirements.txt").exists():
        print("  Installing pip dependencies...")
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
                       cwd=workspace, capture_output=True, text=True)

    return workspace


# --------------------------------------------------------------------------
# Subprocess execution
# --------------------------------------------------------------------------

def _kill_process_group(proc: subprocess.Popen, grace: int = 10) -> None:
    """SIGTERM the process group, escalating to SIGKILL if it lingers."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=grace)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass


def _wait_with_cleanup(proc: subprocess.Popen, timeout: int, test_id: str) -> dict:
    """Wait for proc, killing the process group on timeout/interrupt/shutdown.

    The finally block is a safety net for every exit path (e.g. SIGTERM while
    SIGINT is ignored in backgrounded shells) so agents are never orphaned.
    """
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        print(f"[TIMEOUT] Test {test_id} timed out after {timeout}s")
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Killing agent process group...")
        raise
    finally:
        if proc.poll() is None:
            _kill_process_group(proc)
    return {"returncode": proc.returncode, "timed_out": timed_out}


def run_headless_logged(cmd: list[str], run_dir: Path, timeout: int, test_id: str,
                        env: dict | None = None) -> dict:
    """Run a command headless, streaming output live to stdout.txt/stderr.txt.

    Streams instead of buffering so progress can be observed (tail -f) while
    the test runs.
    """
    with open(run_dir / "stdout.txt", "w", encoding="utf-8") as out_f, \
         open(run_dir / "stderr.txt", "w", encoding="utf-8") as err_f:
        proc = subprocess.Popen(
            cmd,
            stdout=out_f,
            stderr=err_f,
            env=env,
            start_new_session=True,
        )
        return _wait_with_cleanup(proc, timeout, test_id)


def _run_tui(cmd: list[str], timeout: int, test_id: str, env: dict | None = None) -> dict:
    """Run an agent TUI interactively; output goes to the terminal, uncaptured."""
    proc = subprocess.Popen(cmd, env=env, start_new_session=True)
    return _wait_with_cleanup(proc, timeout, test_id)


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
                  result: dict, status: str) -> None:
    """Write meta.json and print the closing status block."""
    elapsed = time.time() - start_time

    # Watch mode prints to the terminal; still leave empty artifacts behind so
    # every run directory has the same shape.
    if watch:
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
        "started_at": started_at,
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_time": round(elapsed, 2),
        "returncode": result["returncode"],
        "timed_out": result["timed_out"],
        "metrics": extract_metrics(run_dir),
    })

    print(f"\n[{status}] {run_id}")
    print(f"  Elapsed: {elapsed:.1f}s")
    print(f"  Output: {run_dir}")
    if status != "COMPLETE":
        stderr_tail = (run_dir / "stderr.txt").read_text(
            encoding="utf-8", errors="replace").strip().splitlines()
        if stderr_tail:
            print(f"  Error: {stderr_tail[-1][:200]}")
    if status not in ("TIMEOUT", "ERROR"):
        print(f"  To score: crucible score {run_id}")


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

def count_tool_calls(session_path: Path) -> int | None:
    """Count tool invocations in a session file (opencode and pool schemas)."""
    try:
        data = json.loads(session_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    count = 0
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if node.get("type") in TOOL_CALL_TYPES:
                count += 1
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return count


def extract_metrics(run_dir: Path) -> dict:
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

    return {
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,
        "tool_calls": tool_calls,
    }


def split_pool_output(run_dir: Path) -> None:
    """Convert pool's NLJSON stdout into session.json + a human transcript.

    NLJSON event types: assistantMessage {message}, toolCall {name, args},
    toolCallResult {result}. A truncated trailing line (e.g. after a timeout)
    is dropped; stdout.txt is left untouched when nothing parses.
    """
    stdout_path = run_dir / "stdout.txt"
    try:
        raw_lines = stdout_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    events = []
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            break  # incomplete tail — keep the complete prefix
        if isinstance(event, dict) and "type" in event:
            events.append(event)
    if not events:
        return

    (run_dir / "session.json").write_text(json.dumps(events, indent=2), encoding="utf-8")

    lines = []
    for e in events:
        t = e.get("type")
        if t == "assistantMessage":
            lines.append(f"⏺ {e.get('message', '')}")
        elif t == "toolCall":
            args = e.get("args") or {}
            summary = ", ".join(f"{k}={str(v)[:60]}" for k, v in list(args.items())[:3])
            lines.append(f"⏺ {e.get('name', '?')}({summary})")
        elif t == "toolCallResult":
            result = str(e.get("result", "")).strip()
            if result:
                lines.append(f"  ⎿ {result[:200]}")
    stdout_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
# Agents
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


def _pool_config(model: str | None) -> tuple[dict, list[str], str | None]:
    """Build the env/cmd adjustments for pool's standalone vs tenant modes.

    - no model          -> tenant mode (logged-in Poolside managed model)
    - ollama/<model>    -> standalone against pool.api_url (local ollama)
    - openrouter/<v>/<m>-> standalone against OpenRouter. The --api-url flag
      gets blocked by Cloudflare bot detection, but the
      POOLSIDE_STANDALONE_BASE_URL env var works.
    """
    env = os.environ.copy()
    extra_flags: list[str] = []
    standalone_model = None

    if model and model.startswith("openrouter/"):
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise SystemExit("OPENROUTER_API_KEY required for openrouter-backed pool runs")
        env["POOLSIDE_API_KEY"] = api_key
        env["POOLSIDE_STANDALONE_BASE_URL"] = OPENROUTER_API
        env["POOLSIDE_STANDALONE_MODEL"] = standalone_model = model.split("/", 1)[1]
        extra_flags = ["--sandbox", "disabled"]
    elif model and model != "pool":
        standalone_model = model.rsplit("/", 1)[-1]
        env["POOLSIDE_STANDALONE_MODEL"] = standalone_model

    return env, extra_flags, standalone_model


def _run_pool(test_id: str, run_id: str, run_dir: Path, prompt_text: str,
              model: str | None, watch: bool, timeout: int,
              prompt_file_abs: str, workspace_abs: str) -> str:
    _print_header("Pool (Poolside) run", [
        ("Test", test_id),
        ("Model", model or "tenant default"),
        ("Run ID", run_id),
        ("Workspace", run_dir / "workspace"),
    ])

    started_at = datetime.now(timezone.utc).isoformat()
    start_time = time.time()
    env, extra_flags, standalone_model = _pool_config(model)

    if watch:
        # TUI in the workspace, prompt pre-queued (auto-sent when ready)
        cmd = ["pool", "-C", workspace_abs]
        if standalone_model:
            cmd.extend(["-m", standalone_model])
        cmd.extend(["-q", prompt_text])
        print(f"Command: {' '.join(cmd)}\n")
        (run_dir / "command.sh").write_text("#!/bin/bash\n" + " ".join(cmd) + "\n", encoding="utf-8")
        result = _run_tui(cmd, timeout, test_id, env=env)
    else:
        cmd = [
            "pool", "exec",
            "-f", prompt_file_abs,
            "-d", workspace_abs,
            "--unsafe-auto-allow",
            *extra_flags,
            "-o", "json",
        ]
        (run_dir / "command.sh").write_text("#!/bin/bash\n" + " ".join(cmd) + "\n", encoding="utf-8")
        result = run_headless_logged(cmd, run_dir, timeout, test_id, env=env)
        # stdout.txt holds NLJSON events; split into session.json + transcript
        split_pool_output(run_dir)

    if result["timed_out"]:
        status = "TIMEOUT"
    elif result["returncode"] == 0:
        status = "COMPLETE"
    elif result["returncode"] == 4:
        status = "TASK FAILED (agent could not complete)"
    else:
        status = f"ERROR (exit {result['returncode']})"

    _finalize_run(run_dir, run_id, test_id, "pool", model, watch,
                  started_at, start_time, result, status)
    return run_id


def _run_opencode(test_id: str, run_id: str, run_dir: Path, prompt_text: str,
                  model: str | None, watch: bool, timeout: int,
                  prompt_file_abs: str, workspace_abs: str, title: str) -> str:
    _print_header("OpenCode run", [
        ("Test", test_id),
        ("Model", model or "default"),
        ("Run ID", run_id),
        ("Workspace", run_dir / "workspace"),
    ])

    started_at = datetime.now(timezone.utc).isoformat()
    start_time = time.time()

    if watch:
        cmd = ["opencode", workspace_abs, "--prompt", prompt_text, "--auto"]
        if model:
            cmd.extend(["-m", model])
        print(f"Command: {' '.join(cmd)}\n")
        (run_dir / "command.sh").write_text("#!/bin/bash\n" + " ".join(cmd) + "\n", encoding="utf-8")
        result = _run_tui(cmd, timeout, test_id)
    else:
        cmd = [
            "opencode", "run",
            "Complete the benchmark task described in the attached prompt.txt file.",
            "--file", prompt_file_abs,
            "--dir", workspace_abs,
            "--title", title,
            "--auto",
        ]
        if model:
            cmd.extend(["-m", model])
        (run_dir / "command.sh").write_text("#!/bin/bash\n" + " ".join(cmd) + "\n", encoding="utf-8")
        result = run_headless_logged(cmd, run_dir, timeout, test_id)

    if not watch:
        _export_opencode_session(workspace_abs, title, run_dir)

    if result["timed_out"]:
        status = "TIMEOUT"
    elif result["returncode"] == 0:
        status = "COMPLETE"
    else:
        status = f"ERROR (exit {result['returncode']})"

    _finalize_run(run_dir, run_id, test_id, "opencode", model, watch,
                  started_at, start_time, result, status)
    return run_id


def _export_opencode_session(workspace_abs: str, title: str, run_dir: Path) -> None:
    """Export the run's opencode session transcript to session.json.

    Sessions live in the workspace's project-scoped DB, so list/export must run
    with cwd=workspace and use the real session ID resolved from the title.
    """
    try:
        listing = subprocess.run(
            ["opencode", "session", "list", "--format", "json"],
            cwd=workspace_abs, capture_output=True, text=True, timeout=30,
        )
        sid = next((e.get("id") for e in json.loads(listing.stdout or "[]")
                    if e.get("title") == title), None)
        if not sid:
            print("  Warning: session not found; skipping session.json")
            return
        export = subprocess.run(
            ["opencode", "export", sid, "--sanitize"],
            cwd=workspace_abs, capture_output=True, text=True, timeout=60,
        )
        (run_dir / "session.json").write_text(
            json.dumps(json.loads(export.stdout), indent=2), encoding="utf-8")
    except json.JSONDecodeError:
        print("  Warning: session export was not valid JSON; skipping session.json")
    except Exception as e:
        print(f"  Warning: could not export session: {e}")


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------

def run_single(test_id: str, model: str | None, watch: bool, timeout: int,
               output_dir: Path, agent: str = "opencode") -> str:
    """Run a single test. Returns run_id."""
    prompt_def = load_prompt(test_id)
    validate_category(prompt_def.get("category"))

    needs_tools = prompt_def.get("needs_tools", True)

    if agent == "direct":
        if needs_tools:
            print(f"[ERROR] Test {test_id} requires tool access; refusing to run it directly. "
                  f"Use --agent opencode or --agent pool.")
            sys.exit(1)
        if not model or not model.startswith(tuple(PROVIDER_CATALOG)):
            print("[ERROR] Direct mode needs a model on a direct-capable provider "
                  "(ollama/, openrouter/, lmstudio/).")
            sys.exit(1)

    if agent == "pool" and model and model.startswith("openrouter/") \
            and not os.environ.get("OPENROUTER_API_KEY"):
        print("[ERROR] OPENROUTER_API_KEY required for openrouter-backed pool runs")
        sys.exit(1)

    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    model_slug = (model or "default").replace("/", "_").replace(":", "_")
    category = prompt_def.get("category", "uncategorized")
    run_id = f"{model_slug}/{category}/{test_id}/{now}"
    run_dir = output_dir / run_id
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

    if agent == "pool":
        return _run_pool(test_id, run_id, run_dir, prompt_text, model, watch,
                         timeout, str(prompt_file.resolve()), str(workspace.resolve()))
    return _run_opencode(test_id, run_id, run_dir, prompt_text, model, watch,
                         timeout, str(prompt_file.resolve()), str(workspace.resolve()),
                         title=f"{now}_{test_id}_{model_slug}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="crucible run",
        description="Run AI benchmark tests via an agent (opencode or pool) or direct API",
    )
    parser.add_argument("test", help="Test ID (e.g. C1) or suite (coding, writing, everyday, reasoning, home, all)")
    parser.add_argument("--provider", "-p", help="Model provider (ollama, openrouter, lmstudio)")
    parser.add_argument("--model", "-m", help="Model name (e.g. qwen3.5:9b-mlx) or provider/model")
    parser.add_argument("--agent", choices=["opencode", "pool", "direct"], default="opencode",
                        help="Agent that executes the test (default: opencode). "
                             "'direct' calls the provider API without an agent — "
                             "only for needs_tools: false prompts")
    parser.add_argument("--watch", action="store_true", help="Open the agent TUI (opencode or pool) with the prompt pre-loaded")
    parser.add_argument("--timeout", type=int, default=600, help="Timeout in seconds")
    parser.add_argument("--output", type=Path, default=Path("runs"), help="Output directory")
    args = parser.parse_args()

    # Resolve model from provider/model args; pool names its own model
    args.model = resolve_model(args.provider, args.model)
    if args.model is None and args.agent == "pool":
        args.model = "pool"

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

    # Close the loop: offer to score right away (interactive sessions only, so
    # scripted/headless invocations are never blocked on a prompt).
    if run_ids and sys.stdin.isatty():
        for rid in run_ids:
            try:
                answer = input(f"\nWould you like to score {rid} now? [y/N] ").strip().lower()
            except EOFError:
                break
            if answer in ("y", "yes"):
                print()
                sys.argv = ["crucible score", rid]
                scorer.main()


if __name__ == "__main__":
    main()
