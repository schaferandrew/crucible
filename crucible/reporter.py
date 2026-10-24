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

from crucible.scorer import RUNS_DIR, find_run_dir


def load_run(run_id: str) -> dict | None:
    """{"meta": ..., "results": ... | None}, or None if the run is unknown."""
    try:
        run_dir = find_run_dir(run_id)
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    results_path = run_dir / "results.json"
    results = json.loads(results_path.read_text(encoding="utf-8")) if results_path.exists() else None
    return {"meta": meta, "results": results}


def _scores(run: dict | None) -> dict:
    return ((run or {}).get("results") or {}).get("scores") or {}


def _summary_row(run_id: str, run: dict | None) -> str:
    if run is None:
        return f"| {run_id} | ? | ? | ? | ? |"
    meta = run["meta"]
    overall = _scores(run).get("_overall")
    score = f"{overall}/10" if overall is not None else "N/A"
    return (f"| {run_id} | {meta.get('test_id', '?')} | {meta.get('model', '?')} "
            f"| {meta.get('elapsed_time', '?')}s | {score} |")


def _breakdown(run_id: str, scores: dict) -> list[str]:
    lines = [f"## {run_id}", ""]
    lines += [f"- {criterion}: {score}" for criterion, score in scores.items()
              if not criterion.startswith("_")]
    if "_overall" in scores:
        lines.append(f"\n**Overall: {scores['_overall']}/10**")
    return lines + [""]


def generate_report(run_ids: list[str]) -> str:
    runs = {run_id: load_run(run_id) for run_id in run_ids}
    lines = [
        "# Crucible Benchmark Report",
        f"Generated: {datetime.now().isoformat()}",
        "",
        "| Run | Test | Model | Elapsed | Score |",
        "|-----|------|-------|---------|-------|",
        *(_summary_row(run_id, run) for run_id, run in runs.items()),
        "",
    ]
    for run_id, run in runs.items():
        if _scores(run):
            lines += _breakdown(run_id, _scores(run))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate benchmark report")
    parser.add_argument("run_ids", nargs="*", help="Run IDs to include (full path or leaf name)")
    parser.add_argument("--all", action="store_true", help="Include all scored runs")
    parser.add_argument("--output", "-o", help="Output file (default: print to stdout)")
    args = parser.parse_args()

    run_ids = set(args.run_ids)
    if args.all:  # every run directory that has been scored
        run_ids |= {str(p.parent.relative_to(RUNS_DIR)) for p in RUNS_DIR.rglob("results.json")}
    if not run_ids:
        print("No runs specified. Use run IDs or --all")
        sys.exit(1)

    report = generate_report(sorted(run_ids))
    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"Report saved to {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
