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

from crucible import runner, scorer, reporter


def _get_version() -> str:
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if pyproject.exists():
        for line in pyproject.read_text().splitlines():
            if line.startswith("version"):
                return line.split("=")[1].strip().strip('"')
    return "dev"


def main():
    if len(sys.argv) < 2:
        print("Usage: crucible <run|score|report> [args...]")
        sys.exit(1)

    cmd = sys.argv[1]

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
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: crucible <run|score|report> [args...]")
        sys.exit(1)


if __name__ == "__main__":
    main()
