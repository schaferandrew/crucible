#!/usr/bin/env python3
"""Crucible CLI entry point.

Usage:
    crucible run
    crucible run CODE-11 --model openrouter/moonshotai/kimi-k2.6
    crucible publish
"""
from __future__ import annotations
import sys
from pathlib import Path

from crucible import bundle, checks, exporter, judge, reporter, runner, scorer, versioning


def _get_version() -> str:
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if pyproject.exists():
        for line in pyproject.read_text(encoding="utf-8").splitlines():
            if line.startswith("version"):
                return line.split("=")[1].strip().strip('"')
    return "dev"


def _print_help() -> None:
    print(f"""crucible {_get_version()} - Personal AI benchmark gauntlet

Usage:
  crucible <command> [args...]

Commands:
  run      Run tests. With no arguments it asks what to run; scoring happens automatically
  checks   Re-run programmatic checks and hidden tests on existing runs; --doc PATH writes the rules doc
  versions Check test versions against the lock; --update, --release NAME, --backfill runs
  publish  Write this machine's results into the portfolio's data folder (validated)
  export   Flatten runs into one JSON file
  report   Generate a comparison report across runs

Not ready yet (review needs more infrastructure; never part of a run):
  score    Review a run by hand against its rubric
  judge    Save an AI judge's review of a run

Sections, areas and tiers:
  chat     writing (WRIT), math (MATH), geography (GEOG), history (HIST), general knowledge (KNOW)
  agentic  coding (CODE), research (RSCH), everyday tasks (TASK)
  tiers    spark (the basics, a gate), temper (everyday work, the headline), forge (frontier-level)

Examples:
  crucible run                                              # asks what to run
  crucible run chat --model lmstudio/qwen/qwen3.5-9b         # every chat test
  crucible run coding --tier forge --agent pi --model ollama/qwen3:30b-a3b
  crucible run CODE-2b --model openrouter/moonshotai/kimi-k2.6 --watch
  crucible publish                                          # update the dashboard data

Options:
  -h, --help     Show this help and exit
  -v, --version  Show version and exit

Run 'crucible <command> -h' for command-specific options.
""")



COMMANDS = {
    "run": runner.main, "score": scorer.main, "report": reporter.main,
    "judge": judge.main, "versions": versioning.main, "export": exporter.main, "publish": bundle.main, "checks": checks.main,
}


def main():
    cmd, rest = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else (None, [])
    if cmd in (None, "-h", "--help", "help"):
        _print_help()
        sys.exit(0 if cmd else 1)
    if cmd in ("-v", "--version"):
        print(f"crucible {_get_version()}")
        sys.exit(0)
    if cmd not in COMMANDS:
        print(f"Unknown command: {cmd}")
        print(f"Usage: crucible <{'|'.join(COMMANDS)}> [args...]")
        print("Try 'crucible --help' for details.")
        sys.exit(1)

    # The subcommand's argparse sees only its own args
    sys.argv = [f"crucible {cmd}", *rest]
    COMMANDS[cmd]()

if __name__ == "__main__":
    main()
