#!/usr/bin/env python3
"""Batch evaluation runner — auto-score multiple runs at once.

Usage:
    crucible eval <run_id> [<run_id> ...] [--auto] [--judge MODEL] [--output FILE]
    crucible eval --all --auto --judge ollama/qwen3:14b --output eval_summary.json

This command is a thin wrapper around the same auto-scoring pipeline used by
`crucible score --auto --judge`, but applies it to many runs and writes a
consolidated summary. It is the entry point for the "run the eval with ollama"
workflow.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from crucible.scorer import auto_score, find_run_dir, load_prompt, _compute_overall


def discover_scored_runs() -> list[str]:
    """Find all run directories under runs/ that have a meta.json."""
    runs_dir = Path(__file__).resolve().parent.parent / "runs"
    run_ids = []
    for meta_path in sorted(runs_dir.rglob("meta.json")):
        run_dir = meta_path.parent
        rel = str(run_dir.relative_to(runs_dir))
        run_ids.append(rel)
    return run_ids


def score_run(run_id: str, auto: bool, judge_model: str | None) -> dict:
    """Auto-score a single run. Returns a summary dict."""
    try:
        run_dir = find_run_dir(run_id)
    except FileNotFoundError as e:
        return {"run_id": run_id, "error": str(e)}

    meta_path = run_dir / "meta.json"
    meta = {}
    if meta_path.exists():
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    test_id = meta.get("test_id")

    if not test_id:
        return {"run_id": run_id, "error": "Could not determine test_id"}

    prompt_def = load_prompt(test_id)
    result = auto_score(test_id, prompt_def, run_dir, judge_model)

    if result is None:
        return {
            "run_id": run_id,
            "test_id": test_id,
            "status": "no_automated_grader",
        }

    scores, provenance = result
    overall = _compute_overall(scores, prompt_def)
    if overall is not None:
        scores["_overall"] = overall

    # Save results.json alongside the run (same format as crucible score --auto)
    results = {
        "run_id": run_id,
        "test_id": test_id,
        "scores": scores,
        "auto_graded": True,
        "provenance": {
            "deterministic_criteria": provenance["deterministic"],
            "llm_judge_criteria": provenance["llm_judge"],
            "judge_model": judge_model,
        },
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }
    results_path = run_dir / "results.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    return {
        "run_id": run_id,
        "test_id": test_id,
        "overall": overall,
        "deterministic_criteria": provenance["deterministic"],
        "llm_judge_criteria": provenance["llm_judge"],
        "un_scored": scores.get("_un_scored_criteria", []),
    }


def generate_summary(summaries: list[dict]) -> str:
    """Generate a markdown summary table."""
    lines = [
        "# Crucible Eval Summary",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "| Run | Test | Overall | Deterministic | LLM Judge | Unscored |",
        "|-----|------|---------|---------------|-----------|----------|",
    ]
    for s in summaries:
        if s.get("error"):
            lines.append(f"| {s['run_id']} | ? | ERROR | — | — | — |")
            continue
        overall = s.get("overall", "N/A")
        overall_str = f"{overall}/10" if overall is not None else "N/A"
        det = ", ".join(s.get("deterministic_criteria", [])) or "—"
        judge = ", ".join(s.get("llm_judge_criteria", [])) or "—"
        unscored = ", ".join(s.get("un_scored", [])) or "—"
        lines.append(f"| {s['run_id']} | {s.get('test_id','?')} | {overall_str} | {det} | {judge} | {unscored} |")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="crucible eval",
        description="Batch auto-score multiple benchmark runs",
    )
    parser.add_argument("run_ids", nargs="*", help="Run IDs to auto-score")
    parser.add_argument("--all", action="store_true",
                        help="Score all runs that have a meta.json")
    parser.add_argument("--auto", action="store_true",
                        help="Use deterministic auto-graders where available")
    parser.add_argument("--judge", metavar="MODEL",
                        help="LLM judge model (e.g. ollama/qwen3:14b or openrouter/deepseek/deepseek-v4-flash)")
    parser.add_argument("--output", "-o", help="Output file (markdown summary; .json for JSON)")
    args = parser.parse_args()

    if not args.auto and not args.judge:
        print("Error: specify --auto, --judge MODEL, or both.")
        sys.exit(1)

    if args.all:
        run_ids = discover_scored_runs()
    else:
        run_ids = args.run_ids

    if not run_ids:
        print("No runs specified. Use run IDs, --all, or both.")
        sys.exit(1)

    print(f"Evaluating {len(run_ids)} run(s)...")
    if args.judge:
        print(f"  LLM judge: {args.judge}")

    summaries = []
    for i, run_id in enumerate(run_ids, 1):
        print(f"\n[{i}/{len(run_ids)}] Scoring {run_id}...")
        summary = score_run(run_id, args.auto, args.judge)
        summaries.append(summary)
        if summary.get("overall") is not None:
            print(f"  → Overall: {summary['overall']}/10")
        elif summary.get("status"):
            print(f"  → {summary['status']}")
        elif summary.get("error"):
            print(f"  → Error: {summary['error']}")

    # Write summary
    if args.output:
        output_path = Path(args.output)
        if output_path.suffix == ".json":
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump({"generated_at": datetime.now(timezone.utc).isoformat(),
                           "runs": summaries}, f, indent=2)
        else:
            output_path.write_text(generate_summary(summaries), encoding="utf-8")
        print(f"\nSummary saved to {output_path}")
    else:
        print("\n" + "=" * 60)
        print(generate_summary(summaries))


if __name__ == "__main__":
    main()
