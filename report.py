#!/usr/bin/env python3
"""Generate comparison reports across benchmark runs.

Usage:
    python3 report.py run1 run2 run3
    python3 report.py --output results.md run1 run2
"""
from __future__ import annotations
import argparse
import json
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
RUNS_DIR = REPO_ROOT / "runs"


def load_run(run_id: str) -> dict | None:
    meta_path = RUNS_DIR / run_id / "meta.json"
    results_path = RUNS_DIR / run_id / "results.json"

    if not meta_path.exists():
        return None

    data = {}
    with open(meta_path) as f:
        data["meta"] = json.load(f)

    if results_path.exists():
        with open(results_path) as f:
            data["results"] = json.load(f)
    else:
        data["results"] = None

    return data


def generate_report(run_ids: list[str]) -> str:
    lines = [
        "# Crucible Benchmark Report",
        f"Generated: {datetime.now().isoformat()}",
        "",
    ]

    # Header
    lines.append("| Run | Test | Model | Elapsed | Score |")
    lines.append("|-----|------|-------|---------|-------|")

    for rid in run_ids:
        data = load_run(rid)
        if not data:
            lines.append(f"| {rid} | ? | ? | ? | ? |")
            continue

        meta = data["meta"]
        test_id = meta.get("test_id", "?")
        model = meta.get("model", "?")
        elapsed = meta.get("elapsed_time", "?")

        score = "N/A"
        if data.get("results") and data["results"].get("scores"):
            scores = data["results"]["scores"]
            if "_overall" in scores:
                score = f"{scores['_overall']}/10"

        lines.append(f"| {rid} | {test_id} | {model} | {elapsed}s | {score} |")

    lines.append("")

    # Detailed breakdown for scored runs
    for rid in run_ids:
        data = load_run(rid)
        if not data or not data.get("results"):
            continue

        results = data["results"]
        scores = results.get("scores", {})
        if not scores:
            continue

        lines.append(f"## {rid}")
        lines.append("")

        for criterion, score in scores.items():
            if not criterion.startswith("_"):
                lines.append(f"- {criterion}: {score}")

        if "_overall" in scores:
            lines.append(f"\n**Overall: {scores['_overall']}/10**")

        lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate benchmark report")
    parser.add_argument("run_ids", nargs="+", help="Run IDs to include")
    parser.add_argument("--output", "-o", help="Output file (default: print to stdout)")
    args = parser.parse_args()

    report = generate_report(args.run_ids)

    if args.output:
        Path(args.output).write_text(report)
        print(f"Report saved to {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
