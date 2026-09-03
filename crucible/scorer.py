#!/usr/bin/env python3
"""Auto + interactive scoring for benchmark runs.

Usage:
    crucible score <run_id>                # deterministic first, then menu
    crucible score <run_id> --judge        # deterministic + LLM judge (default model)
    crucible score <run_id> --judge ollama/qwen3:14b
    crucible score <run_id> --interactive  # deterministic + human scoring
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from crucible import graders, llm_judge
from crucible.taxonomy import validate_category

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = REPO_ROOT / "prompts"
RUNS_DIR = REPO_ROOT / "runs"

# Default LLM judge model — well-suited to the M1 Pro 32GB target machine.
DEFAULT_JUDGE_MODEL = "ollama/qwen3:14b"

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


def _session_model_output(session_path: Path) -> str | None:
    """Extract the model's reply from a session capture (opencode or pool)."""
    try:
        data = json.loads(session_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    texts = []
    if isinstance(data, dict):  # opencode export: messages -> parts -> text
        for msg in data.get("messages", []):
            if msg.get("info", {}).get("role") not in (None, "assistant"):
                continue
            for part in msg.get("parts", []):
                if part.get("type") == "text" and part.get("text"):
                    texts.append(part["text"])
    elif isinstance(data, list):  # pool NLJSON events
        for event in data:
            if event.get("type") == "assistantMessage" and event.get("message"):
                texts.append(event["message"])
    return "\n\n".join(texts) if texts else None


def score_interactive(test_id: str, run_dir: Path) -> dict:
    """Present rubric and collect scores interactively."""
    prompt = load_prompt(test_id)
    validate_category(prompt.get("category"))
    rubric = prompt.get("rubric", [])
    critical = prompt.get("critical_failure")

    # Model output: stdout.txt first; watch runs capture nothing there, so fall
    # back to the session transcript.
    stdout_path = run_dir / "stdout.txt"
    prompt_path = run_dir / "prompt.txt"
    model_output = stdout_path.read_text(encoding="utf-8") if stdout_path.exists() else ""
    if not model_output.strip():
        session_path = run_dir / "session.json"
        if session_path.exists():
            fallback = _session_model_output(session_path)
            if fallback:
                model_output = f"{fallback}\n\n[captured from session.json — watch run]"
    if not model_output.strip():
        model_output = "[No stdout captured]"
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


# --------------------------------------------------------------------------
# Auto-grading (deterministic + LLM judge)
# --------------------------------------------------------------------------

def _extract_raw_metrics(run_dir: Path) -> dict:
    """Extract raw metrics from meta.json for scoring provenance."""
    meta_path = run_dir / "meta.json"
    if meta_path.exists():
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        extracted = meta.get("metrics") or {}
        timed_out = meta.get("timed_out")
        returncode = meta.get("returncode")
        final_success = (timed_out is not True) and (returncode in (0, None))
        return {
            "user_interventions": 0,
            "tool_calls": extracted.get("tool_calls"),
            "tests_passed": extracted.get("tests_passed"),
            "tests_failed": extracted.get("tests_failed"),
            "final_success": final_success,
            "estimated_cost_usd": None,
        }
    return {
        "user_interventions": 0,
        "tool_calls": 0,
        "tests_passed": 0,
        "tests_failed": 0,
        "final_success": True,
        "estimated_cost_usd": 0.0,
    }


def auto_score(test_id: str, prompt_def: dict, run_dir: Path,
               judge_model: str | None = None) -> tuple[dict, dict] | None:
    """Automatically score a run using deterministic graders + optional LLM judge.

    Returns (scores, provenance) where scores maps criterion→score and
    provenance records what method produced each criterion. Returns None
    if no automated grading is possible at all.
    """
    model_output = graders.get_model_output(run_dir)
    scores: dict[str, float] = {}
    provenance: dict[str, list[str]] = {"deterministic": [], "llm_judge": []}

    # 1. Try deterministic grader
    if graders.has_grader(test_id):
        grader = graders.get_grader(test_id)
        det_scores = grader(prompt_def, run_dir, model_output)
        scores.update(det_scores)
        provenance["deterministic"] = list(det_scores.keys())
        print(f"\n  [auto] Deterministic grader scored {len(det_scores)} criterion/criteria.")

    # 2. If LLM judge requested, judge remaining criteria
    if judge_model:
        judge = llm_judge.LLMJudge(judge_model)
        remaining = {
            item["criterion"] for item in prompt_def.get("rubric", [])
        } - set(scores.keys())
        if remaining:
            print(f"  [judge] Sending {len(remaining)} un-graded criterion/criteria to {judge_model}...")
            llm_scores = judge.judge(prompt_def, model_output, skip=set(scores.keys()))
            scores.update(llm_scores)
            provenance["llm_judge"] = list(llm_scores.keys())
            print(f"  [judge] LLM judge scored {len(llm_scores)} criterion/criteria.")
        else:
            print("  [judge] All criteria already scored deterministically; skipping LLM judge.")

    if not scores:
        return None

    # Record raw metrics
    scores["_raw_metrics_auto"] = _extract_raw_metrics(run_dir)

    # Track coverage for transparency
    all_criteria = {item["criterion"] for item in prompt_def.get("rubric", [])}
    scored = set(scores.keys()) & all_criteria
    scores["_un_scored_criteria"] = sorted(all_criteria - scored)

    return scores, provenance


def _compute_overall(scores: dict, prompt_def: dict) -> float | None:
    """Compute per-run overall score as a plain mean of normalized criterion scores (0–10).

    Category sweep weights (taxonomy.CATEGORY_WEIGHTS) are NOT applied here —
    they only make sense when aggregating a full sweep across categories.
    """
    rubric = {item["criterion"]: item["max_score"] for item in prompt_def.get("rubric", [])}
    normalized = []
    for criterion, score in scores.items():
        if not criterion.startswith("_") and criterion in rubric:
            normalized.append(score / rubric[criterion] * 10)
    if not normalized:
        return None
    return round(sum(normalized) / len(normalized), 2)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def _save_results(run_id: str, test_id: str, scores: dict,
                 auto_graded: bool, provenance: dict, run_dir: Path) -> None:
    """Persist scores to results.json in the run directory."""
    overall = _compute_overall(scores, load_prompt(test_id))
    if overall is not None:
        scores["_overall"] = overall

    results = {
        "run_id": run_id,
        "test_id": test_id,
        "scores": scores,
        "auto_graded": auto_graded,
        "provenance": provenance,
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }
    results_path = run_dir / "results.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\n[COMPLETE] Results saved to {results_path}")
    if scores.get("_overall") is not None:
        print(f"  Overall: {scores['_overall']}/10")


def _score_remaining_interactive(prompt: dict, already_scored: set[str]) -> dict[str, float]:
    """Interactively score only rubric criteria not in *already_scored*."""
    scores: dict[str, float] = {}
    rubric = prompt.get("rubric", [])
    for item in rubric:
        criterion = item["criterion"]
        if criterion in already_scored:
            continue
        max_score = item["max_score"]
        description = item.get("description", "")
        print(f"\n{criterion} (max {max_score})")
        print(f"  {description}")
        while True:
            try:
                raw = input(f"  Score (0-{max_score}): ").strip()
            except EOFError:
                print("  Input closed; skipping this criterion.")
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
    return scores


def _score_menu(remaining: list[str]) -> str | None:
    """Present the post-auto menu and return user choice: 'judge', 'interactive', or None."""
    print(f"\n  Remaining criteria: {', '.join(remaining)}")
    print("\nOptions:")
    print("  [s] Save — keep deterministic scores only")
    print("  [j] Judge — run LLM judge for remaining criteria")
    print("  [j MODEL] Judge with a specific model (e.g. j openrouter/deepseek/deepseek-v4-flash)")
    print("  [i] Interactive — manually score remaining criteria")
    try:
        choice = input("\nChoice [s/j/i] (default s): ").strip().lower()
    except EOFError:
        print()
        return None
    if not choice or choice == "s":
        return None
    if choice.startswith("j"):
        model = choice[1:].strip()
        return f"judge:{model}" if model else "judge"
    if choice == "i":
        return "interactive"
    print(f"  Unknown choice '{choice}'; saving deterministic scores only.")
    return None


def _run_judge_for_remaining(prompt: dict, run_dir: Path, scores: dict,
                             judge_model: str) -> tuple[dict[str, float], dict[str, list[str]]]:
    """Run the LLM judge for criteria not yet scored. Returns (scores, provenance)."""
    model_output = graders.get_model_output(run_dir)
    all_criteria = {item["criterion"] for item in prompt.get("rubric", [])}
    already_scored = {k for k in scores if k in all_criteria}
    judge = llm_judge.LLMJudge(judge_model)
    llm_scores = judge.judge(prompt, model_output, skip=already_scored)
    prov = {"deterministic": [], "llm_judge": list(llm_scores.keys()), "judge_model": judge_model}
    return llm_scores, prov


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="crucible score",
        description="Score a benchmark run (deterministic auto-grader runs first, "
                    "then optional LLM judge or interactive)",
    )
    parser.add_argument("run_id", help="Run ID to score")
    parser.add_argument("--judge", nargs="?", const=DEFAULT_JUDGE_MODEL, default=None,
                        metavar="MODEL",
                        help=f"Use an LLM judge for un-graded criteria "
                             f"(default model: {DEFAULT_JUDGE_MODEL})")
    parser.add_argument("--interactive", action="store_true",
                        help="Enable interactive human scoring for criteria not auto-scored")
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
        parts = run_dir.parts
        test_id = None
        for i in range(len(parts) - 1, -1, -1):
            part = parts[i]
            if len(part) <= 4 and part[0].isalpha() and part[1:].replace('b','').replace('c','').replace('a','').isdigit():
                test_id = part
                break
        if not test_id and len(parts) >= 2:
            test_id = parts[-2]

    if not test_id:
        print("Could not determine test_id")
        sys.exit(1)

    prompt = load_prompt(test_id)

    # ---- Step 1: Always run deterministic grading first ----
    result = auto_score(test_id, prompt, run_dir, judge_model=None)
    scores: dict[str, float] = {}
    provenance: dict = {"deterministic": [], "llm_judge": [], "judge_model": None}
    auto_graded = True

    if result is not None:
        scores, det_prov = result
        provenance["deterministic"] = det_prov["deterministic"]
        print(f"\n  [auto] Deterministic grader scored {len(provenance['deterministic'])} criterion/criteria.")

        all_criteria = {item["criterion"] for item in prompt.get("rubric", [])}
        remaining = sorted(all_criteria - {k for k in scores if k in all_criteria})

        # ---- Step 2: Decide on judge / interactive ----
        if args.judge:
            judge_model = args.judge
            llm_scores, judge_prov = _run_judge_for_remaining(
                prompt, run_dir, scores, judge_model)
            scores.update(llm_scores)
            provenance["llm_judge"] = judge_prov["llm_judge"]
            provenance["judge_model"] = judge_model
        elif args.interactive:
            if remaining:
                print(f"\n  Interactive scoring for: {', '.join(remaining)}")
                remaining_scores = _score_remaining_interactive(prompt, set(scores.keys()))
                scores.update(remaining_scores)
        elif remaining:
            choice = _score_menu(remaining)
            if choice is None:
                pass  # save deterministic only
            elif choice == "interactive":
                remaining_scores = _score_remaining_interactive(prompt, set(scores.keys()))
                scores.update(remaining_scores)
            elif choice.startswith("judge:"):
                judge_model = choice[5:].strip() or DEFAULT_JUDGE_MODEL
                llm_scores, judge_prov = _run_judge_for_remaining(
                    prompt, run_dir, scores, judge_model)
                scores.update(llm_scores)
                provenance["llm_judge"] = judge_prov["llm_judge"]
                provenance["judge_model"] = judge_model
            elif choice == "judge":
                llm_scores, judge_prov = _run_judge_for_remaining(
                    prompt, run_dir, scores, DEFAULT_JUDGE_MODEL)
                scores.update(llm_scores)
                provenance["llm_judge"] = judge_prov["llm_judge"]
                provenance["judge_model"] = DEFAULT_JUDGE_MODEL
    else:
        # No deterministic grader for this test
        print(f"  No deterministic grader available for {test_id}.")
        if args.judge:
            judge_model = args.judge
            llm_scores, judge_prov = _run_judge_for_remaining(prompt, run_dir, {}, judge_model)
            scores.update(llm_scores)
            provenance["llm_judge"] = judge_prov["llm_judge"]
            provenance["judge_model"] = judge_model
        elif args.interactive:
            scores = score_interactive(test_id, run_dir)
            auto_graded = False
        else:
            # Menu for the no-grader case
            all_criteria = [item["criterion"] for item in prompt.get("rubric", [])]
            choice = _score_menu(all_criteria)
            if choice is None:
                print("  No scores to save.")
                return
            elif choice == "interactive":
                scores = score_interactive(test_id, run_dir)
                auto_graded = False
            elif choice.startswith("judge:"):
                judge_model = choice[5:].strip() or DEFAULT_JUDGE_MODEL
                llm_scores, judge_prov = _run_judge_for_remaining(prompt, run_dir, {}, judge_model)
                scores.update(llm_scores)
                provenance["llm_judge"] = judge_prov["llm_judge"]
                provenance["judge_model"] = judge_model
            elif choice == "judge":
                llm_scores, judge_prov = _run_judge_for_remaining(
                    prompt, run_dir, {}, DEFAULT_JUDGE_MODEL)
                scores.update(llm_scores)
                provenance["llm_judge"] = judge_prov["llm_judge"]
                provenance["judge_model"] = DEFAULT_JUDGE_MODEL

    if not scores:
        print("  No scores produced; nothing to save.")
        return

    _save_results(args.run_id, test_id, scores, auto_graded, provenance, run_dir)


if __name__ == "__main__":
    main()
