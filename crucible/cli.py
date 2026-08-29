#!/usr/bin/env python3
"""Crucible CLI entry point.

Usage:
    crucible run G2 --model openrouter/moonshotai/kimi-k2.6
    crucible score 20260829_040024
    crucible report --all
"""
from __future__ import annotations
import sys

from crucible import runner, scorer, reporter


def main():
    if len(sys.argv) < 2:
        print("Usage: crucible <run|score|report> [args...]")
        sys.exit(1)

    cmd = sys.argv[1]
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
