#!/usr/bin/env python3
"""Simple benchmark runner using opencode CLI directly.

Usage:
    crucible run C1 --model openrouter/moonshotai/kimi-k2.6
    crucible run all --model openrouter/moonshotai/kimi-k2.6
    crucible run C1 --model ollama/qwen3:30b-a3b --watch
    crucible run coding --model openrouter/moonshotai/kimi-k2.6

Options:
    --model      Model to use (default from opencode config if not set)
    --watch      Open opencode TUI to observe
    --timeout    Timeout in seconds (default 600)
    --output     Output directory for runs (default ./runs)
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = REPO_ROOT / "prompts"
FIXTURES_DIR = REPO_ROOT / "fixtures"
REPOS_DIR = REPO_ROOT / "repos"


def load_prompt(test_id: str) -> dict:
    path = PROMPTS_DIR / f"{test_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    with open(path) as f:
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


def run_single(test_id: str, model: str | None, watch: bool, timeout: int, output_dir: Path) -> str:
    """Run a single test. Returns run_id."""
    prompt_def = load_prompt(test_id)
    prompt_text = prompt_def["prompt"]

    # Create run directory: runs/<model>/<category>/<test_id>/<timestamp>
    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    model_slug = (model or "default").replace("/", "_").replace(":", "_")
    category = prompt_def.get("category", "uncategorized")
    run_id = f"{model_slug}/{category}/{test_id}/{now}"
    run_dir = output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Opencode title must be a flat unique string
    opencode_title = f"{now}_{test_id}_{model_slug}"

    # Setup workspace
    workspace = setup_workspace(run_dir, prompt_def)

    # Write prompt to workspace
    prompt_file = workspace / "prompt.txt"
    prompt_file.write_text(prompt_text)
    # Also save in run_dir for reference
    (run_dir / "prompt.txt").write_text(prompt_text)

    # Use absolute paths
    prompt_file_abs = str(prompt_file.resolve())
    workspace_abs = str(workspace.resolve())

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
    (run_dir / "command.sh").write_text("#!/bin/bash\n" + " ".join(cmd) + "\n")

    started_at = datetime.now(timezone.utc).isoformat()
    start_time = time.time()

    try:
        result = subprocess.run(
            cmd,
            capture_output=not watch,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        print(f"[TIMEOUT] Test {test_id} timed out after {timeout}s")
        result = exc
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] By user.")
        raise

    ended_at = datetime.now(timezone.utc).isoformat()
    elapsed = time.time() - start_time

    # Write stdout/stderr
    stdout_path = run_dir / "stdout.txt"
    stderr_path = run_dir / "stderr.txt"

    def safe_decode(data):
        if data is None:
            return ""
        if isinstance(data, bytes):
            return data.decode("utf-8", errors="replace")
        return str(data)

    if isinstance(result, subprocess.TimeoutExpired):
        stdout_path.write_text(safe_decode(result.stdout))
        stderr_path.write_text(safe_decode(result.stderr))
    else:
        stdout_path.write_text(safe_decode(result.stdout))
        stderr_path.write_text(safe_decode(result.stderr))

    # Try to export session
    try:
        export = subprocess.run(
            ["opencode", "export", opencode_title, "--sanitize"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        session_path = run_dir / "session.json"
        try:
            data = json.loads(export.stdout)
            session_path.write_text(json.dumps(data, indent=2))
        except json.JSONDecodeError:
            session_path.write_text(export.stdout)
    except Exception as e:
        print(f"  Warning: could not export session: {e}")

    # Save metadata
    meta = {
        "run_id": run_id,
        "test_id": test_id,
        "model": model,
        "watch": watch,
        "started_at": started_at,
        "ended_at": ended_at,
        "elapsed_time": round(elapsed, 2),
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    print(f"\n[COMPLETE] {run_id}")
    print(f"  Elapsed: {elapsed:.1f}s")
    print(f"  Output: {run_dir}")
    print(f"  To score: python3 score.py {run_id}")

    return run_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AI benchmark tests via opencode")
    parser.add_argument("test", help="Test ID (e.g. C1) or suite (coding, writing, everyday, reasoning, home, all)")
    parser.add_argument("--model", help="Model to use (e.g. openrouter/moonshotai/kimi-k2.6)")
    parser.add_argument("--watch", action="store_true", help="Open opencode TUI")
    parser.add_argument("--timeout", type=int, default=600, help="Timeout in seconds")
    parser.add_argument("--output", type=Path, default=Path("runs"), help="Output directory")
    args = parser.parse_args()

    suites = {
        "coding": ["C1", "C1b", "C2", "C2b", "C3", "C4", "C4b", "C5", "C6"],
        "writing": ["W1a", "W1b", "W1c", "W2", "W2b"],
        "everyday": ["E1", "E2", "E3"],
        "reasoning": ["G1", "G2", "G3"],
        "home": ["H1", "H2", "H3", "H4"],
    }

    if args.test == "all":
        tests = sorted([p.stem for p in PROMPTS_DIR.glob("*.yaml")])
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
            rid = run_single(test_id, args.model, args.watch, args.timeout, args.output)
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


if __name__ == "__main__":
    main()
