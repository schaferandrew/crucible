#!/usr/bin/env python3
"""Interactive scoring for benchmark runs.

Usage:
    crucible score <run_id>
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from crucible import versioning
from crucible.taxonomy import validate_category
from crucible.workspace import REPO_ROOT, load_prompt

RUNS_DIR = REPO_ROOT / "runs"
MAX_DISPLAY_CHARS = 3000


def find_run_dir(run_id_or_path: str, runs_dir: Path = RUNS_DIR) -> Path:
    """Resolve a run identifier to its directory.

    Accepts an absolute path, a path relative to runs/ (optionally starting
    with 'runs/'), or just the timestamp leaf, which is searched for.
    """
    candidate = Path(run_id_or_path)
    if candidate.is_absolute() and candidate.is_dir():
        return candidate
    if candidate.parts[:1] == (runs_dir.name,):
        candidate = Path(*candidate.parts[1:])
    if (runs_dir / candidate).is_dir():
        return runs_dir / candidate
    match = next((m for m in runs_dir.rglob(candidate.name) if m.is_dir()), None)
    if match is None:
        raise FileNotFoundError(f"Run not found: {run_id_or_path}")
    return match


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _session_model_output(session_path: Path) -> str | None:
    """The model's reply text from session.json (opencode export or normalized events)."""
    data = _read_json(session_path) if session_path.exists() else {}
    if isinstance(data, dict):  # opencode export (1.x parts or 2.x content)
        from crucible.agents.opencode import message_texts
        texts = message_texts(data)
    else:  # normalized events (see crucible.session)
        texts = [e["message"] for e in data
                 if e.get("type") == "assistantMessage" and e.get("message")]
    return "\n\n".join(texts) or None


def _model_output(run_dir: Path) -> str:
    """stdout.txt, falling back to the session transcript (watch runs)."""
    stdout = run_dir / "stdout.txt"
    text = stdout.read_text(encoding="utf-8") if stdout.exists() else ""
    if text.strip():
        return text
    fallback = _session_model_output(run_dir / "session.json")
    return f"{fallback}\n\n[captured from session.json — watch run]" if fallback else "[No stdout captured]"


def _print_section(title: str, text: str) -> None:
    print(f"\n{'─'*60}\n{title}\n{'─'*60}")
    for line in text.strip().splitlines():
        print(f"  {line}")


def _ask_score(max_score: float) -> float | None:
    """A score in [0, max_score], or None when skipped (Enter / closed input)."""
    while True:
        try:
            raw = input(f"  Score (0-{max_score}): ").strip()
        except EOFError:
            print("  Input closed; skipping this criterion.")
            return None
        if raw == "":
            print("  Skipped.")
            return None
        try:
            value = float(raw)
        except ValueError:
            print("  Please enter a number.")
            continue
        if 0 <= value <= max_score:
            return value
        print(f"  Must be between 0 and {max_score}.")


def _raw_metrics(meta: dict) -> dict:
    """Metrics auto-extracted by the runner, plus derived success flags."""
    return {
        "user_interventions": 0,
        **(meta.get("metrics") or {}),
        "final_success": meta.get("timed_out") is not True and meta.get("returncode") in (0, None),
    }


def score_interactive(test_id: str, run_dir: Path, meta: dict | None = None) -> dict:
    """Show prompt, reference answer and model output; collect rubric scores."""
    prompt = load_prompt(test_id)
    validate_category(prompt.get("category"))
    prompt_path = run_dir / "prompt.txt"
    prompt_text = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else prompt["prompt"]
    output = _model_output(run_dir)
    if len(output) > MAX_DISPLAY_CHARS:
        output = output[:MAX_DISPLAY_CHARS] + "\n... [truncated, see stdout.txt for full output]"

    print(f"\n{'='*60}\nScoring {test_id}\n{'='*60}")
    _print_section("PROMPT:", prompt_text)
    if prompt.get("hidden_answer"):
        _print_section("HIDDEN ANSWER (for reference):", str(prompt["hidden_answer"]))
    _print_section("MODEL OUTPUT:", output)

    print(f"\n{'='*60}\nRUBRIC\n{'='*60}")
    if prompt.get("critical_failure"):
        print(f"[CRITICAL FAILURE] {prompt['critical_failure']}\n")
    scores = {}
    for item in prompt.get("rubric", []):
        print(f"\n{item['criterion']} (max {item['max_score']})\n  {item['description']}")
        value = _ask_score(item["max_score"])
        if value is not None:
            scores[item["criterion"]] = value

    print(f"\n{'='*60}\nRaw metrics (auto-extracted where possible)\n{'='*60}")
    raw = _raw_metrics(meta if meta is not None else _read_json(run_dir / "meta.json"))
    for key, value in raw.items():
        print(f"  {key}: {value}")
    scores["_raw_metrics_manual"] = raw
    return scores


def overall_score(scores: dict, rubric: list[dict]) -> float | None:
    """Plain mean of criterion scores normalized to 0-10.

    Category sweep weights (taxonomy.CATEGORY_WEIGHTS) are NOT applied here;
    they only make sense when aggregating a full sweep across categories.
    """
    max_scores = {item["criterion"]: item["max_score"] for item in rubric}
    normalized = [scores[c] / m * 10 for c, m in max_scores.items() if c in scores]
    return round(sum(normalized) / len(normalized), 2) if normalized else None


def score_run(run_dir: Path) -> Path:
    """Score one run interactively and save results.json; returns its path."""
    meta = _read_json(run_dir / "meta.json")
    # Layout is .../<test_id>/<timestamp>/ for runs that predate meta.json
    test_id = meta.get("test_id") or run_dir.parent.name
    prompt_def = load_prompt(test_id)
    # A rubric score only means something against the content the run actually saw
    run_version = (meta.get("test") or {}).get("version")
    if run_version is not None and run_version != prompt_def.get("version"):
        raise SystemExit(f"{test_id}: this run used v{run_version}, but the prompt is now "
                         f"v{prompt_def.get('version')}; rerun instead of re-scoring")
    scores = score_interactive(test_id, run_dir, meta)
    overall = overall_score(scores, prompt_def.get("rubric", []))
    if overall is not None:
        scores["_overall"] = overall

    results_path = run_dir / "results.json"
    results_path.write_text(json.dumps({
        "run_id": meta.get("run_id") or run_dir.name,
        "test_id": test_id,
        "scorer": {"type": "human"},
        "test_version": prompt_def.get("version"),
        "rubric_version": prompt_def.get("rubric_version"),
        "rubric_hash": versioning.rubric_hash(prompt_def),
        "scores": scores,
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2), encoding="utf-8")
    print(f"\n[COMPLETE] Results saved to {results_path}")
    return results_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Score a benchmark run")
    parser.add_argument("run_id", help="Run ID (model/category/test/timestamp), its timestamp, or a path")
    args = parser.parse_args()
    try:
        run_dir = find_run_dir(args.run_id)
    except FileNotFoundError as e:
        print(e)
        sys.exit(1)
    score_run(run_dir)


if __name__ == "__main__":
    main()
