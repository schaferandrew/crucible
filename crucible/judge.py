"""`crucible judge`: save an AI judge's rubric score for a run as agent_results.json.

The judge (an agent following judge_instructions.md) reads the test and the
run, then hands its per-criterion scores to this command, which validates them
against the rubric and records where the number came from: judge model, judge
prompt version, rubric version and the test version the run used. Agent scores
live next to, never inside, the human results.json.

Usage:
    crucible judge <run_dir> <payload.json> [--judge-model claude-opus-5-5]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from crucible import checks, runrecord, versioning, workspace
from crucible.scorer import overall_score

# Bump when judge_instructions.md changes in a way that could move scores
JUDGE_PROMPT_VERSION = 3  # 2: hidden graders for Forge tests; 3: web graders run from apps/web
DEFAULT_JUDGE_MODEL = "claude-opus-5-5"
RESULTS_FILENAME = "agent_results.json"

CAVEAT = ("Agent score: an AI judge read the prompt, rubric and run output and scored it. "
          "It is a rough signal, not a precise eval, and has not been checked by a human.")


class JudgeError(ValueError):
    pass


def save_agent_score(run_dir: Path, payload: dict, judge_model: str = DEFAULT_JUDGE_MODEL) -> dict:
    """Validate a judge's payload against the run's rubric and write agent_results.json."""
    meta = runrecord.read(run_dir)
    if not meta:
        raise JudgeError(f"{run_dir} has no run record (runs from before 3.0.0 need `crucible migrate`)")
    prompt_def = workspace.load_task(meta["task"]["id"])

    # A score only means something against the content the run actually saw
    run_version = meta["task"].get("version")
    if run_version is not None and run_version != prompt_def.get("version"):
        raise JudgeError(f"run used {meta['task']['id']} v{run_version}, but the task is now "
                         f"v{prompt_def.get('version')}; rerun instead of re-scoring")

    max_scores = {item["criterion"]: item["max_score"] for item in prompt_def.get("rubric", [])}
    criteria = payload.get("criteria") or {}
    unknown, missing = set(criteria) - set(max_scores), set(max_scores) - set(criteria)
    if unknown or missing:
        raise JudgeError(f"criterion mismatch; unknown: {sorted(unknown)}, missing: {sorted(missing)}")
    for name, item in criteria.items():
        if not 0 <= item["score"] <= max_scores[name]:
            raise JudgeError(f"{name}: score {item['score']} outside 0..{max_scores[name]}")

    scores = {name: item["score"] for name, item in criteria.items()}
    notes = {name: item.get("note", "") for name, item in criteria.items()}

    # Criteria bound to a programmatic check are scored by the check, not the judge
    results = {r["id"]: r for r in checks.check_results(run_dir, prompt_def)}
    for item in prompt_def.get("rubric", []):
        result = results.get(item.get("check"))
        if result is not None:
            scores[item["criterion"]] = item["max_score"] if result["passed"] else 0
            notes[item["criterion"]] = f"Programmatic check {result['id']}: {'pass' if result['passed'] else 'fail'} ({result['detail']})"
    overall = overall_score(scores, prompt_def.get("rubric", []))
    cap = payload.get("score_cap")
    if cap is not None and overall is not None:
        overall = min(overall, float(cap))

    results = {
        "run_path": meta["run_path"],
        "task_id": meta["task"]["id"],
        "scorer": {"type": "agent", "model": judge_model, "prompt_version": JUDGE_PROMPT_VERSION},
        "caveat": CAVEAT,
        "test_version": prompt_def.get("version"),
        "rubric_version": prompt_def.get("rubric_version"),
        "rubric_hash": versioning.rubric_hash(prompt_def),
        "scores": {**scores, "_overall": overall},
        "notes": notes,
        "checks": list(results.values()),
        "score_cap": cap,
        "summary": payload.get("summary", ""),
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }
    (run_dir / RESULTS_FILENAME).write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(prog="crucible judge", description=__doc__.splitlines()[0])
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("payload", type=Path, help="JSON file with criteria, score_cap and summary")
    parser.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    args = parser.parse_args()
    try:
        results = save_agent_score(args.run_dir.resolve(),
                                   json.loads(args.payload.read_text(encoding="utf-8")), args.judge_model)
    except (JudgeError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"Not saved: {exc}")
        sys.exit(1)
    print(f"{results['task_id']}: {results['scores']['_overall']}/10 -> {args.run_dir / RESULTS_FILENAME}")


if __name__ == "__main__":
    main()
