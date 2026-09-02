#!/usr/bin/env python3
"""Generate comparison reports across benchmark runs.

Usage:
    crucible report run1 run2 run3
    crucible report --all --output results.md
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "runs"


def find_run_dir(run_id_or_path: str) -> Path | None:
    """Resolve a run identifier to a directory path."""
    candidate = Path(run_id_or_path)
    if candidate.is_absolute() and candidate.is_dir():
        return candidate
    parts = candidate.parts
    if parts and parts[0] == RUNS_DIR.name:
        candidate = Path(*parts[1:]) if len(parts) > 1 else RUNS_DIR

    direct = RUNS_DIR / candidate
    if direct.exists() and direct.is_dir():
        return direct

    for match in RUNS_DIR.rglob(candidate.name if candidate.name else run_id_or_path):
        if match.is_dir():
            return match

    return None


def load_run(run_id: str) -> dict | None:
    run_dir = find_run_dir(run_id)
    if not run_dir:
        return None
    
    meta_path = run_dir / "meta.json"
    results_path = run_dir / "results.json"

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
    parser.add_argument("run_ids", nargs="*", help="Run IDs to include (full path or leaf name)")
    parser.add_argument("--all", action="store_true", help="Include all scored runs")
    parser.add_argument("--output", "-o", help="Output file (default: print to stdout)")
    args = parser.parse_args()

    run_ids = args.run_ids or []
    
    if args.all:
        # Discover all directories that have results.json
        all_runs = []
        for path in RUNS_DIR.rglob("results.json"):
            # Relative path from RUNS_DIR, parent is the run dir
            rel = str(path.parent.relative_to(RUNS_DIR))
            all_runs.append(rel)
        run_ids = sorted(set(run_ids + all_runs))

    if not run_ids:
        print("No runs specified. Use run IDs or --all")
        sys.exit(1)

    report = generate_report(run_ids)

    if args.output:
        Path(args.output).write_text(report)
        print(f"Report saved to {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
