#!/usr/bin/env python3
"""Interactive scoring for benchmark runs.

Usage:
    crucible score <run_id>
    crucible score <run_id> --auto
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from crucible.taxonomy import validate_category

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = REPO_ROOT / "prompts"
RUNS_DIR = REPO_ROOT / "runs"


def load_prompt(test_id: str) -> dict:
    with open(PROMPTS_DIR / f"{test_id}.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def find_run_dir(run_id_or_path: str) -> Path:
    """Resolve a run identifier to a directory path.

    Accepts: a path relative to the repo root (optionally with a leading
    'runs/'), a path relative to runs/, or just the timestamp leaf, which is
    searched for recursively.
    """
    # Tolerate the common 'runs/...' form and absolute paths
    candidate = Path(run_id_or_path)
    if candidate.is_absolute() and candidate.is_dir():
        return candidate
    parts = candidate.parts
    if parts and parts[0] == RUNS_DIR.name:
        candidate = Path(*parts[1:]) if len(parts) > 1 else RUNS_DIR

    direct = RUNS_DIR / candidate
    if direct.exists() and direct.is_dir():
        return direct

    # Search recursively for a directory with this exact name
    for match in RUNS_DIR.rglob(candidate.name if candidate.name else run_id_or_path):
        if match.is_dir():
            return match

    raise FileNotFoundError(f"Run not found: {run_id_or_path}")


def score_interactive(test_id: str, run_dir: Path) -> dict:
    """Present rubric and collect scores interactively."""
    prompt = load_prompt(test_id)
    validate_category(prompt.get("category"))
    rubric = prompt.get("rubric", [])
    critical = prompt.get("critical_failure")

    # Load model output for context
    stdout_path = run_dir / "stdout.txt"
    prompt_path = run_dir / "prompt.txt"
    model_output = stdout_path.read_text(encoding="utf-8") if stdout_path.exists() else "[No stdout captured]"
    prompt_text = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else prompt.get("prompt", "[Prompt not found]")
    hidden_answer = prompt.get("hidden_answer")

    # Truncate long outputs for display
    MAX_OUT = 3000
    display_output = model_output if len(model_output) <= MAX_OUT else model_output[:MAX_OUT] + "\n... [truncated, see stdout.txt for full output]"

    print(f"\n{'='*60}")
    print(f"Scoring {test_id}")
    print(f"{'='*60}")

    # Show prompt
    print(f"\n{'─'*60}")
    print("PROMPT:")
    print(f"{'─'*60}")
    # Indent prompt for readability
    for line in prompt_text.strip().splitlines():
        print(f"  {line}")

    # Show hidden answer if present
    if hidden_answer:
        print(f"\n{'─'*60}")
        print("HIDDEN ANSWER (for reference):")
        print(f"{'─'*60}")
        print(f"  {hidden_answer}")

    # Show model output
    print(f"\n{'─'*60}")
    print("MODEL OUTPUT:")
    print(f"{'─'*60}")
    for line in display_output.strip().splitlines():
        print(f"  {line}")

    print(f"\n{'='*60}")
    print("RUBRIC")
    print(f"{'='*60}")
    if critical:
        print(f"[CRITICAL FAILURE] {critical}\n")

    scores = {}
    for item in rubric:
        criterion = item["criterion"]
        max_score = item["max_score"]
        description = item["description"]

        print(f"\n{criterion} (max {max_score})")
        print(f"  {description}")

        while True:
            try:
                raw = input(f"  Score (0-{max_score}): ").strip()
            except EOFError:
                print("  Input closed; skipping this criterion.")
                raw = ""
                break
            if raw == "":
                print("  Skipped.")
                break
            try:
                val = float(raw)
                if 0 <= val <= max_score:
                    scores[criterion] = val
                    break
                print(f"  Must be between 0 and {max_score}.")
            except ValueError:
                print("  Please enter a number.")

    # Raw metrics: prefer values auto-extracted by the runner into meta.json;
    # None means unknown rather than zero.
    print(f"\n{'='*60}")
    print("Raw metrics (auto-extracted where possible)")
    print(f"{'='*60}")
    meta = {}
    meta_path = run_dir / "meta.json"
    if meta_path.exists():
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    extracted = meta.get("metrics") or {}
    timed_out = meta.get("timed_out")
    returncode = meta.get("returncode")
    final_success = (timed_out is not True) and (returncode in (0, None))
    extras = {
        "user_interventions": 0,
        "tool_calls": extracted.get("tool_calls"),
        "tests_passed": extracted.get("tests_passed"),
        "tests_failed": extracted.get("tests_failed"),
        "final_success": final_success,
        "estimated_cost_usd": None,
    }
    for key, value in extras.items():
        print(f"  {key}: {value}")

    scores["_raw_metrics_manual"] = extras
    return scores


def main() -> None:
    parser = argparse.ArgumentParser(description="Score a benchmark run")
    parser.add_argument("run_id", help="Run ID to score (full path like model/category/test/timestamp, or just timestamp)")
    parser.add_argument("--auto", action="store_true", help="Run auto-grader if available")
    args = parser.parse_args()

    try:
        run_dir = find_run_dir(args.run_id)
    except FileNotFoundError as e:
        print(e)
        sys.exit(1)

    # Load meta to get test_id
    meta_path = run_dir / "meta.json"
    if meta_path.exists():
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        test_id = meta.get("test_id")
    else:
        # Try to extract from the second-to-last path component (test_id dir)
        parts = run_dir.parts
        # Walk up from leaf to find test_id
        test_id = None
        for i in range(len(parts) - 1, -1, -1):
            # Heuristic: test IDs are like E2, C1b, W1a
            part = parts[i]
            if len(part) <= 4 and part[0].isalpha() and part[1:].replace('b','').replace('c','').replace('a','').isdigit():
                test_id = part
                break
        if not test_id and len(parts) >= 2:
            test_id = parts[-2]

    if not test_id:
        print("Could not determine test_id")
        sys.exit(1)

    # Run auto-grader
    if args.auto:
        print("Auto-grader not yet implemented in this version.")

    # Interactive scoring
    scores = score_interactive(test_id, run_dir)

    # Per-run overall: plain mean of criterion scores normalized to 0-10.
    # Category sweep weights (taxonomy.CATEGORY_WEIGHTS) are NOT applied here —
    # they only make sense when aggregating a full sweep across categories.
    prompt = load_prompt(test_id)
    rubric = {item["criterion"]: item["max_score"] for item in prompt.get("rubric", [])}

    normalized = []
    for criterion, score in scores.items():
        if not criterion.startswith("_") and criterion in rubric:
            normalized.append(score / rubric[criterion] * 10)

    if normalized:
        scores["_overall"] = round(sum(normalized) / len(normalized), 2)

    # Save
    results = {
        "run_id": args.run_id,
        "test_id": test_id,
        "scores": scores,
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }

    results_path = run_dir / "results.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"\n[COMPLETE] Results saved to {results_path}")


if __name__ == "__main__":
    main()
