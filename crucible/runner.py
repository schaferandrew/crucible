#!/usr/bin/env python3
"""Simple benchmark runner using opencode or pool CLI directly.

Usage:
    crucible run C1 --model openrouter/moonshotai/kimi-k2.6
    crucible run all --model openrouter/moonshotai/kimi-k2.6
    crucible run C1 --model ollama/qwen3:30b-a3b --watch
    crucible run coding --model openrouter/moonshotai/kimi-k2.6
    crucible run C1 --agent pool

Options:
    --provider, -p   Provider (ollama, openrouter)
    --model, -m      Model name (e.g. qwen3.5:9b-mlx) or provider/model
    --agent          Agent to use: opencode (default) or pool (Poolside)
    --watch          Open opencode TUI to observe
    --timeout        Timeout in seconds (default 600)
    --output         Output directory for runs (default ./runs)
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
from typing import Any

import yaml

from crucible import direct_runner, scorer
from crucible.selector import select_from_list
from crucible.taxonomy import derive_suites, validate_category


REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = REPO_ROOT / "prompts"
FIXTURES_DIR = REPO_ROOT / "fixtures"
REPOS_DIR = REPO_ROOT / "repos"


def resolve_model(provider: str | None, model: str | None) -> str | None:
    """Resolve final model string from provider/model inputs."""
    # Case 1: Both provided -> combine (unless model already carries the prefix,
    # e.g. --provider ollama --model ollama/laguna... -> don't double it)
    if provider and model:
        if model.startswith(f"{provider}/"):
            return model
        return f"{provider}/{model}"

    # Case 2: Only model provided -> auto-detect provider from prefix or fuzzy match
    if model and not provider:
        if "/" in model:  # Already has provider prefix
            return model

        # Fuzzy match across providers
        matches = direct_runner.find_model_matches(model)
        if not matches:
            print(f"Model '{model}' not found on any provider.")
            sys.exit(1)
        if len(matches) == 1:
            return matches[0]

        # Multiple matches -> show combined selector
        selected = select_from_list(matches, f"Model '{model}' found on multiple providers:")
        if selected is None:
            print("Cancelled.")
            sys.exit(0)
        return selected

    # Case 3: Only provider provided -> interactive model selection for that provider
    if provider and not model:
        if provider == "ollama":
            models = direct_runner.fetch_ollama_models()
            if not models:
                print("No ollama models found. Run 'ollama pull <model>' first.")
                sys.exit(1)
            model_items = [f"ollama/{m}" for m in models]
            selected = select_from_list(model_items, f"Select {provider} model:")
            if selected is None:
                print("Cancelled.")
                sys.exit(0)
            return selected
        elif provider == "lmstudio":
            models = direct_runner.fetch_lmstudio_models()
            if not models:
                print("No LM Studio models found. Start LM Studio and load a model first.")
                sys.exit(1)
            model_items = [f"lmstudio/{m}" for m in models]
            selected = select_from_list(model_items, f"Select {provider} model:")
            if selected is None:
                print("Cancelled.")
                sys.exit(0)
            return selected
        elif provider == "openrouter":
            models = direct_runner.fetch_openrouter_models()
            if not models:
                print("No openrouter models found (check OPENROUTER_API_KEY).")
                sys.exit(1)
            model_items = [f"openrouter/{m}" for m in models]
            selected = select_from_list(model_items, f"Select {provider} model:")
            if selected is None:
                print("Cancelled.")
                sys.exit(0)
            return selected
        else:
            print(f"Unknown provider: {provider}")
            sys.exit(1)

    # Case 4: Neither provided -> None (use opencode default)
    return None


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
    """Create workspace and copy fixtures/repos."""
    workspace = run_dir / "workspace"
    ensure_clean_dir(workspace)

    # Copy repo if specified
    repo_name = prompt_def.get("repo")
    if repo_name:
        src = REPOS_DIR / repo_name
        if src.exists():
            if src.is_dir():
                # Copy directory contents
                for item in src.iterdir():
                    if item.is_dir():
                        shutil.copytree(item, workspace / item.name)
                    else:
                        shutil.copy2(item, workspace / item.name)
            else:
                shutil.copy2(src, workspace)

    # Copy fixtures
    fixtures = prompt_def.get("fixtures", [])
    if isinstance(fixtures, str):
        fixtures = [fixtures]
    for fixture_name in fixtures:
        src = FIXTURES_DIR / fixture_name
        if src.exists():
            if src.is_dir():
                shutil.copytree(src, workspace / src.name)
            else:
                shutil.copy2(src, workspace)
        else:
            print(f"  Warning: fixture not found: {src}")

    # Install deps if needed
    if (workspace / "package.json").exists():
        print("  Installing npm dependencies...")
        subprocess.run(["npm", "install"], cwd=workspace, capture_output=True, text=True)
    elif (workspace / "requirements.txt").exists():
        print("  Installing pip dependencies...")
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
                        cwd=workspace, capture_output=True, text=True)

    return workspace


def run_headless_logged(cmd: list[str], run_dir: Path, timeout: int, test_id: str,
                        env: dict | None = None) -> dict:
    """Run a headless command, streaming output live to stdout.txt/stderr.txt.

    Streams instead of buffering so progress can be observed (tail -f) while the
    test runs. Kills the whole process group on timeout/interrupt so agent child
    processes are never orphaned.
    """
    stdout_path = run_dir / "stdout.txt"
    stderr_path = run_dir / "stderr.txt"

    with open(stdout_path, "w", encoding="utf-8") as out_f, \
         open(stderr_path, "w", encoding="utf-8") as err_f:
        proc = subprocess.Popen(
            cmd,
            stdout=out_f,
            stderr=err_f,
            env=env,
            start_new_session=True,
        )
        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            print(f"[TIMEOUT] Test {test_id} timed out after {timeout}s")
            _kill_process_group(proc)
        except KeyboardInterrupt:
            print("\n[INTERRUPTED] Killing agent process group...")
            _kill_process_group(proc)
            raise

    return {"returncode": proc.returncode, "timed_out": timed_out}


def split_pool_output(run_dir: Path) -> None:
    """Convert pool's NLJSON stdout into session.json + a human transcript.

    NLJSON event types: assistantMessage {message}, toolCall {name, args},
    toolCallResult {result}. Leaves stdout.txt untouched if parsing fails.
    """
    stdout_path = run_dir / "stdout.txt"
    try:
        events = [json.loads(line) for line in stdout_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (json.JSONDecodeError, OSError):
        return
    if not events or not all(isinstance(e, dict) and "type" in e for e in events):
        return

    (run_dir / "session.json").write_text(json.dumps(events, indent=2), encoding="utf-8")

    lines = []
    for e in events:
        t = e.get("type")
        if t == "assistantMessage":
            lines.append(f"⏺ {e.get('message', '')}")
        elif t == "toolCall":
            name = e.get("name", "?")
            args = e.get("args") or {}
            summary = ", ".join(f"{k}={str(v)[:60]}" for k, v in list(args.items())[:3])
            lines.append(f"⏺ {name}({summary})")
        elif t == "toolCallResult":
            result = str(e.get("result", "")).strip()
            if result:
                lines.append(f"  ⎿ {result[:200]}")
    stdout_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def count_tool_calls(session_path: Path) -> int | None:
    """Count tool invocations in a session file, whatever its exact schema."""
    try:
        data = json.loads(session_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    def walk(node) -> int:
        if isinstance(node, dict):
            n = 1 if str(node.get("type", "")).startswith("tool") and "Call" in str(node.get("type", "")) else 0
            return n + sum(walk(v) for v in node.values())
        if isinstance(node, list):
            return sum(walk(v) for v in node)
        return 0

    return walk(data)


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


def should_run_direct(agent: str, needs_tools: bool, model: str | None) -> bool:
    """Decide whether a test may bypass the agent and call the provider API directly.

    Tool-requiring tests must NEVER run directly: direct mode is only allowed
    when the prompt explicitly declares needs_tools: false and the model is on
    a direct-capable provider (ollama, openrouter, lmstudio).
    """
    return bool(
        agent == "opencode"
        and not needs_tools
        and model
        and model.startswith(("ollama/", "openrouter/", "lmstudio/"))
    )


def _run_direct(test_id: str, run_id: str, run_dir: Path, prompt_def: dict,
                prompt_text: str, model: str, timeout: int, watch: bool) -> str:
    """Text-only run straight against the provider API — no agent, no workspace."""
    print(f"\n{'='*60}")
    print(f"Test: {test_id}")
    print(f"Agent: direct (API call, no tool use)")
    print(f"Model: {model}")
    print(f"Run ID: {run_id}")
    print(f"{'='*60}\n")

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
        stdout_text = direct_runner.run_direct(
            full_prompt,
            model,
            [],
            FIXTURES_DIR,
            timeout,
        )
    except Exception as e:
        stderr_text = f"Direct runner error: {e}"

    ended_at = datetime.now(timezone.utc).isoformat()
    elapsed = time.time() - start_time

    (run_dir / "stdout.txt").write_text(stdout_text, encoding="utf-8")
    (run_dir / "stderr.txt").write_text(stderr_text, encoding="utf-8")

    meta = {
        "run_id": run_id,
        "test_id": test_id,
        "agent": "direct",
        "model": model,
        "watch": watch,
        "started_at": started_at,
        "ended_at": ended_at,
        "elapsed_time": round(elapsed, 2),
        "returncode": 0 if not stderr_text else 1,
        "timed_out": False,
        "metrics": extract_metrics(run_dir),
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    if stderr_text:
        print(f"\n[ERROR] {run_id}")
        print(f"  Elapsed: {elapsed:.1f}s")
        print(f"  Output: {run_dir}")
        print(f"  Error: {stderr_text[:200]}")
        return run_id

    print(f"\n[COMPLETE] {run_id}")
    print(f"  Elapsed: {elapsed:.1f}s")
    print(f"  Output: {run_dir}")
    print(f"  To score: crucible score {run_id}")
    return run_id


def run_single(test_id: str, model: str | None, watch: bool, timeout: int,
               output_dir: Path, agent: str = "opencode") -> str:
    """Run a single test. Returns run_id."""
    prompt_def = load_prompt(test_id)
    prompt_text = prompt_def["prompt"]

    # Fail loudly on a category missing from the taxonomy registry
    validate_category(prompt_def.get("category"))

    # Create run directory: runs/<model_slug>/<category>/<test_id>/<timestamp>
    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    model_slug = (model or "default").replace("/", "_").replace(":", "_")
    category = prompt_def.get("category", "uncategorized")
    run_id = f"{model_slug}/{category}/{test_id}/{now}"
    run_dir = output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Opencode title must be a flat unique string
    opencode_title = f"{now}_{test_id}_{model_slug}"

    needs_tools = prompt_def.get("needs_tools", True)
    direct_mode = should_run_direct(agent, needs_tools, model)

    # Direct runs are text-only: no workspace, just the API call
    if direct_mode:
        (run_dir / "prompt.txt").write_text(prompt_text, encoding="utf-8")
        return _run_direct(test_id, run_id, run_dir, prompt_def, prompt_text,
                           model, timeout, watch)

    # Setup workspace
    workspace = setup_workspace(run_dir, prompt_def)

    # Write prompt to workspace
    prompt_file = workspace / "prompt.txt"
    prompt_file.write_text(prompt_text, encoding="utf-8")
    # Also save in run_dir for reference
    (run_dir / "prompt.txt").write_text(prompt_text, encoding="utf-8")

    # Use absolute paths
    prompt_file_abs = str(prompt_file.resolve())
    workspace_abs = str(workspace.resolve())

    if agent == "pool":
        print(f"\n{'='*60}")
        print(f"Test: {test_id}")
        print(f"Agent: pool (Poolside)")
        print(f"Model: {model or 'default'}")
        print(f"Run ID: {run_id}")
        print(f"Workspace: {workspace}")
        print(f"{'='*60}\n")

        started_at = datetime.now(timezone.utc).isoformat()
        start_time = time.time()

        # pool exec runs in standalone mode against pool.api_url; the model must
        # be selected via POOLSIDE_STANDALONE_MODEL (settings.yaml has no key for
        # it, and standalone defaults to pool's tenant model name). The
        # standalone API expects a bare model name, so strip any provider
        # prefix (pool/laguna... or ollama/laguna... -> laguna...).
        env = os.environ.copy()
        standalone_model = model.rsplit("/", 1)[-1] if model else None
        if standalone_model and standalone_model != "pool":
            env["POOLSIDE_STANDALONE_MODEL"] = standalone_model

        cmd = [
            "pool", "exec",
            "-f", prompt_file_abs,
            "-d", workspace_abs,
            "--unsafe-auto-allow",
        ]
        if watch:
            # Interactive TUI in the workspace with the benchmark prompt
            # pre-queued (auto-sent once the session is ready). Output goes to
            # the TUI; nothing is captured.
            cmd = ["pool", "-C", workspace_abs]
            if standalone_model:
                cmd.extend(["-m", standalone_model])
            cmd.extend(["-q", prompt_text])
            (run_dir / "command.sh").write_text("#!/bin/bash\n" + " ".join(cmd) + "\n", encoding="utf-8")
            print(f"Command: {' '.join(cmd)}\n")
            proc = subprocess.Popen(cmd, start_new_session=True)
            timed_out = False
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                print(f"\n[TIMEOUT] Test {test_id} timed out after {timeout}s")
                _kill_process_group(proc)
            except KeyboardInterrupt:
                print("\n[INTERRUPTED] Killing agent process group...")
                _kill_process_group(proc)
                raise
            result = {"returncode": proc.returncode, "timed_out": timed_out}
        else:
            cmd.extend(["-o", "json"])
            (run_dir / "command.sh").write_text("#!/bin/bash\n" + " ".join(cmd) + "\n", encoding="utf-8")
            result = run_headless_logged(cmd, run_dir, timeout, test_id, env=env)

            # stdout.txt holds NLJSON events; split into machine-readable
            # session.json and a human-readable transcript.
            split_pool_output(run_dir)

        ended_at = datetime.now(timezone.utc).isoformat()
        elapsed = time.time() - start_time

        meta = {
            "run_id": run_id,
            "test_id": test_id,
            "agent": agent,
            "model": model,
            "watch": watch,
            "started_at": started_at,
            "ended_at": ended_at,
            "elapsed_time": round(elapsed, 2),
            "returncode": result["returncode"],
            "timed_out": result["timed_out"],
            "metrics": extract_metrics(run_dir),
        }
        (run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        if result["timed_out"]:
            status = "TIMEOUT"
        elif result["returncode"] == 0:
            status = "COMPLETE"
        elif result["returncode"] == 4:
            status = "TASK FAILED (agent could not complete)"
        else:
            status = f"ERROR (exit {result['returncode']})"

        print(f"\n[{status}] {run_id}")
        print(f"  Elapsed: {elapsed:.1f}s")
        print(f"  Output: {run_dir}")
        if status not in ("COMPLETE",):
            stderr_tail = (run_dir / "stderr.txt").read_text(encoding="utf-8", errors="replace").strip().splitlines()
            if stderr_tail:
                print(f"  Error: {stderr_tail[-1][:200]}")
        if status != "TIMEOUT":
            print(f"  To score: crucible score {run_id}")

        return run_id

    # Build opencode command
    if watch:
        # Full TUI mode: opencode <workspace_dir> --prompt "..." --auto -m model
        cmd = [
            "opencode",
            workspace_abs,
            "--prompt",
            prompt_text,
            "--auto",
        ]
        if model:
            cmd.extend(["-m", model])
    else:
        # Headless mode: opencode run
        cmd = [
            "opencode",
            "run",
            "Complete the benchmark task described in the attached prompt.txt file.",
            "--file",
            prompt_file_abs,
            "--dir",
            workspace_abs,
            "--title",
            opencode_title,
            "--auto",
        ]
        if model:
            cmd.extend(["-m", model])

    print(f"\n{'='*60}")
    print(f"Test: {test_id}")
    print(f"Model: {model or 'default'}")
    print(f"Run ID: {run_id}")
    print(f"Workspace: {workspace}")
    print(f"Command: {' '.join(cmd)}")
    print(f"{'='*60}\n")

    # Save command
    (run_dir / "command.sh").write_text("#!/bin/bash\n" + " ".join(cmd) + "\n", encoding="utf-8")

    started_at = datetime.now(timezone.utc).isoformat()
    start_time = time.time()

    if watch:
        # TUI runs print to the terminal and are not captured.
        try:
            result = subprocess.run(cmd, timeout=timeout)
            run_result = {"returncode": result.returncode, "timed_out": False}
        except subprocess.TimeoutExpired:
            print(f"[TIMEOUT] Test {test_id} timed out after {timeout}s")
            run_result = {"returncode": None, "timed_out": True}
        except KeyboardInterrupt:
            print("\n[INTERRUPTED] By user.")
            raise
    else:
        run_result = run_headless_logged(cmd, run_dir, timeout, test_id)

    ended_at = datetime.now(timezone.utc).isoformat()
    elapsed = time.time() - start_time

    # Headless output is already streamed to stdout.txt/stderr.txt; watch mode
    # printed to the terminal instead, so capture nothing.
    if watch:
        (run_dir / "stdout.txt").write_text("", encoding="utf-8")
        (run_dir / "stderr.txt").write_text("", encoding="utf-8")

    # Export session (opencode only): sessions live in the workspace's
    # project-scoped DB, so list/export must run with cwd=workspace and use the
    # real session ID resolved from the known session title.
    if agent == "opencode" and not watch:
        try:
            listing = subprocess.run(
                ["opencode", "session", "list", "--format", "json"],
                cwd=workspace_abs,
                capture_output=True,
                text=True,
                timeout=30,
            )
            sid = None
            for entry in json.loads(listing.stdout or "[]"):
                if entry.get("title") == opencode_title:
                    sid = entry.get("id")
                    break
            if sid:
                export = subprocess.run(
                    ["opencode", "export", sid, "--sanitize"],
                    cwd=workspace_abs,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                try:
                    data = json.loads(export.stdout)
                    (run_dir / "session.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
                except json.JSONDecodeError:
                    print("  Warning: session export was not valid JSON; skipping session.json")
            else:
                print("  Warning: session not found; skipping session.json")
        except Exception as e:
            print(f"  Warning: could not export session: {e}")

    # Save metadata
    meta = {
        "run_id": run_id,
        "test_id": test_id,
        "agent": agent,
        "model": model,
        "watch": watch,
        "started_at": started_at,
        "ended_at": ended_at,
        "elapsed_time": round(elapsed, 2),
        "returncode": run_result["returncode"],
        "timed_out": run_result["timed_out"],
        "metrics": extract_metrics(run_dir),
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    status = "TIMEOUT" if run_result["timed_out"] else "COMPLETE"
    print(f"\n[{status}] {run_id}")
    print(f"  Elapsed: {elapsed:.1f}s")
    print(f"  Output: {run_dir}")
    print(f"  To score: crucible score {run_id}")

    return run_id


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="crucible run",
        description="Run AI benchmark tests via an agent (opencode or pool)",
    )
    parser.add_argument("test", help="Test ID (e.g. C1) or suite (coding, writing, everyday, reasoning, home, all)")
    parser.add_argument("--provider", "-p", help="Model provider (ollama, openrouter, lmstudio)")
    parser.add_argument("--model", "-m", help="Model name (e.g. qwen3.5:9b-mlx) or provider/model")
    parser.add_argument("--agent", choices=["opencode", "pool"], default="opencode",
                        help="Agent that executes the test (default: opencode)")
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
            rid = run_single(test_id, args.model, args.watch, args.timeout, args.output, args.agent)
            run_ids.append(rid)
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
