#!/usr/bin/env python3
"""Interactive scoring for benchmark runs.

Usage:
    python3 score.py <run_id>
    python3 score.py <run_id> --auto
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent
PROMPTS_DIR = REPO_ROOT / "prompts"
RUNS_DIR = REPO_ROOT / "runs"


def load_prompt(test_id: str) -> dict:
    with open(PROMPTS_DIR / f"{test_id}.yaml") as f:
        return yaml.safe_load(f)


def score_interactive(test_id: str, run_dir: Path) -> dict:
    """Present rubric and collect scores interactively."""
    prompt = load_prompt(test_id)
    rubric = prompt.get("rubric", [])
    critical = prompt.get("critical_failure")

    # Load model output for context
    stdout_path = run_dir / "stdout.txt"
    prompt_path = run_dir / "prompt.txt"
    model_output = stdout_path.read_text() if stdout_path.exists() else "[No stdout captured]"
    prompt_text = prompt_path.read_text() if prompt_path.exists() else prompt.get("prompt", "[Prompt not found]")
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
            raw = input(f"  Score (0-{max_score}): ").strip()
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

    # Raw metrics
    print(f"\n{'='*60}")
    print("Raw metrics (press Enter to skip)")
    print(f"{'='*60}")
    extras = {
        "user_interventions": 0,
        "tool_calls": 0,
        "tests_passed": None,
        "tests_failed": None,
        "final_success": None,
        "estimated_cost_usd": None,
    }
    for key in extras:
        raw = input(f"  {key}: ").strip()
        if raw:
            try:
                if "." in raw:
                    extras[key] = float(raw)
                else:
                    extras[key] = int(raw)
            except ValueError:
                if raw.lower() in ("true", "yes"):
                    extras[key] = True
                elif raw.lower() in ("false", "no"):
                    extras[key] = False
                else:
                    extras[key] = raw

    scores["_raw_metrics_manual"] = extras
    return scores


def main() -> None:
    parser = argparse.ArgumentParser(description="Score a benchmark run")
    parser.add_argument("run_id", help="Run ID to score")
    parser.add_argument("--auto", action="store_true", help="Run auto-grader if available")
    args = parser.parse_args()

    run_dir = RUNS_DIR / args.run_id
    if not run_dir.exists():
        print(f"Run not found: {run_dir}")
        sys.exit(1)

    # Load meta to get test_id
    meta_path = run_dir / "meta.json"
    if meta_path.exists():
        with open(meta_path) as f:
            meta = json.load(f)
        test_id = meta.get("test_id")
    else:
        # Try to extract from run_id
        test_id = args.run_id.split("_")[1]

    if not test_id:
        print("Could not determine test_id")
        sys.exit(1)

    # Run auto-grader
    if args.auto:
        print("Auto-grader not yet implemented in this version.")

    # Interactive scoring
    scores = score_interactive(test_id, run_dir)

    # Calculate weighted score
    weights = {
        "coding_build": 0.10,
        "coding_debug": 0.10,
        "coding_repo": 0.15,
        "browser_tool": 0.10,
        "writing": 0.10,
        "everyday": 0.10,
        "reasoning": 0.10,
        "structured_data": 0.10,
        "long_agent": 0.05,
        "home_maintenance": 0.10,
    }

    prompt = load_prompt(test_id)
    category = prompt.get("category", "")

    total = 0.0
    count = 0
    for criterion, score in scores.items():
        if not criterion.startswith("_"):
            # Use max score from rubric for weighted calc
            for item in prompt.get("rubric", []):
                if item["criterion"] == criterion:
                    normalized = score / item["max_score"] * 10  # 0-10 scale
                    total += normalized * weights.get(category, 0.1)
                    count += 1
                    break

    if count > 0:
        scores["_overall"] = round(total, 2)

    # Save
    results = {
        "run_id": args.run_id,
        "test_id": test_id,
        "scores": scores,
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }

    results_path = run_dir / "results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n[COMPLETE] Results saved to {results_path}")


if __name__ == "__main__":
    import sys
    from datetime import datetime, timezone
    main()
