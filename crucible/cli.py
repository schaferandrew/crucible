#!/usr/bin/env python3
"""Crucible CLI entry point.

Usage:
    crucible run G2 --model openrouter/moonshotai/kimi-k2.6
    crucible score 20260829_040024
    crucible report --all
"""
from __future__ import annotations
import sys
from pathlib import Path

from crucible import runner, scorer, reporter, eval_runner


def _get_version() -> str:
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if pyproject.exists():
        for line in pyproject.read_text().splitlines():
            if line.startswith("version"):
                return line.split("=")[1].strip().strip('"')
    return "dev"


def _print_help() -> None:
    print(f"""crucible {_get_version()} - Personal AI benchmark gauntlet

Usage:
  crucible <command> [args...]

Commands:
  run      Run benchmark test(s) with an agent (opencode or pool)
  score    Auto-score a completed run (deterministic graders first, then optional LLM judge or interactive)
  report   Generate a comparison report across runs
  eval     Batch-score multiple runs against their rubrics

Test suites:
  coding (C1, C1b, C2, C2b, C3, C4, C4b, C5, C6)
  writing (W1a, W1b, W1c, W2, W2b)
  everyday (E1-E3), reasoning (G1-G3), home (H1-H4), all

Examples:
  # Single test with an OpenRouter model
  crucible run C1 --model openrouter/moonshotai/kimi-k2.6

  # Whole coding suite with a local ollama model
  crucible run coding --model ollama/qwen3:30b-a3b --timeout 300

  # Run through the Poolside agent instead of opencode
  crucible run C1 --agent pool

  # Watch a test live in the opencode TUI
  crucible run C2b --model openrouter/anthropic/claude-sonnet-4 --watch

  # Score a run (deterministic first, then interactive menu for remaining)
  crucible score 20260829_040024

  # Score with LLM judge (default model)
  crucible score 20260829_040024 --judge

  # Score with a specific judge model
  crucible score 20260829_040024 --judge openrouter/deepseek/deepseek-v4-flash

  # Compare specific runs, or report everything
  crucible report run1 run2 run3
  crucible report --all --output results.md

Options:
  -h, --help     Show this help and exit
  -v, --version  Show version and exit

Run 'crucible <command> -h' for command-specific options.
""")


def main():
    if len(sys.argv) < 2:
        _print_help()
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd in ("-h", "--help", "help"):
        _print_help()
        sys.exit(0)

    if cmd in ("--version", "-v"):
        print(f"crucible {_get_version()}")
        sys.exit(0)

    rest = sys.argv[2:]

    # Patch sys.argv so the subcommand's argparse sees only its own args
    sys.argv = [f"crucible {cmd}"] + rest

    if cmd == "run":
        runner.main()
    elif cmd == "score":
        scorer.main()
    elif cmd == "report":
        reporter.main()
    elif cmd == "eval":
        eval_runner.main()
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: crucible <run|score|report|eval> [args...]")
        print("Try 'crucible --help' for details.")
        sys.exit(1)


if __name__ == "__main__":
    main()
