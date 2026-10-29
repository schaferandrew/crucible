"""`crucible export`: flatten runs into one JSON file for publishing (e.g. the portfolio's Crucible page).

Scores are only comparable on the same test content and rubric, so every run
carries the test version it used, and a score counts (`counts: true`) only
when that version and rubric version match the current prompt and the test is
active. Timed-out runs still count: running out of time is a result. The page decides how to aggregate; this file
never averages anything. Unknown values stay null, never 0.

Usage:
    crucible export --out ../schaferandrew.github.io/_data/crucible.json
    crucible export --models openrouter_qwen_qwen3.8-27b lmstudio_google_gemma-4-26b-a4b-qat --out crucible.json
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from crucible import checks, hardware, versioning, workspace
from crucible.agents import AGENTS
from crucible.judge import CAVEAT as AGENT_CAVEAT
from crucible.taxonomy import AREAS, CATEGORY_WEIGHTS, MODE_HARNESSES, MODE_LABELS, MODES, TIERS, mode_for

FORMAT_VERSION = 2  # 2: test IDs by area prefix, chat/agentic modes
METRIC_KEYS = ["tests_passed", "tests_failed", "tool_calls", "tokens_in", "tokens_out",
               "model_responses", "ttft_s", "response_time_avg_s", "cost_usd"]


def _first_sentence(text: str) -> str:
    text = " ".join(text.split())
    match = re.match(r"(.+?[.?!])(\s|$)", text)
    return match.group(1) if match else text


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def export_tests() -> list[dict]:
    tests = []
    for test_id in workspace.all_test_ids():
        p = workspace.load_prompt(test_id)
        if p.get("status") == "retired":
            continue  # never run or scored; leaving it out also leaves out its runs
        tests.append({
            "id": test_id, "name": p.get("name"), "mode": mode_for(p), "area": p.get("area"), "category": p.get("category"),
            "tier": p.get("tier"), "status": p.get("status"), "version": p.get("version"),
            "rubric_version": p.get("rubric_version"), "needs_tools": bool(p.get("needs_tools", True)),
            "summary": _first_sentence(p.get("prompt", "")),
            "prompt": (p.get("prompt") or "").strip(),
            "scoring": "checks" if checks.fully_checked(p) else "judge",
            "rules": [c.get("rule", c["type"]) for c in p.get("checks") or []],
        })
    return tests


def _score(path: Path, rubric_version: int | None) -> tuple[float | None, dict]:
    """The file's 0-10 overall when it was scored against the current rubric version."""
    results = _read_json(path)
    if not results:
        return None, {}
    overall = (results.get("scores") or {}).get("_overall")
    if results.get("rubric_version") != rubric_version:
        return None, {"stale_rubric": results.get("rubric_version")}
    return (overall if isinstance(overall, (int, float)) else None), results


OUTPUT_LIMIT = 6000


CONTROL = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clip(text: str | None, limit: int = OUTPUT_LIMIT) -> str | None:
    # Terminal colour codes and control characters don't belong on a web page
    text = CONTROL.sub("", text or "").strip()
    if not text:
        return None
    return text if len(text) <= limit else text[:limit].rstrip() + f"\n\n[... {len(text) - limit:,} more characters in the run folder]"


def _hidden_tests(run_dir: Path) -> dict | None:
    """The hidden acceptance tests' results, trimmed for the dashboard."""
    record = _read_json(run_dir / "grader_results.json")
    if not record:
        return None
    return {
        "tests": [{"group": t["group"], "name": t["name"], "passed": t["passed"],
                   "error": (t.get("error") or "").splitlines()[0][:200] if t.get("error") else None}
                  for t in record.get("tests", [])],
        "existing": (record.get("existing") or {}).get("passed"),
        "contract_unchanged": record.get("contract_unchanged"),
        "regression": (record.get("regression") or {}).get("detail"),
        "regression_passed": (record.get("regression") or {}).get("passed"),
        "error": record.get("error"),
    }


def _hardware(machine: dict, inference: dict) -> dict | None:
    """The machine that ran inference: this one, or the LM Link device that served the model.

    Hostname is the machine's short name (e.g. Ironwood); never the endpoint address. A cloud
    run has none: the machine that sent the request didn't run the model.
    """
    if inference.get("local") is False:
        return None
    return hardware.serving(machine, inference)


def export_run(run_dir: Path, tests: dict[str, dict]) -> dict | None:
    meta = _read_json(run_dir / "meta.json")
    # meta["invalid"] marks a run whose environment was broken (e.g. a stale server), not a model failure
    if not meta or meta.get("test_id") not in tests or meta.get("invalid"):
        return None
    test = tests[meta["test_id"]]
    # Each mode has its own harnesses (chat: direct; agentic: opencode, pi); a run through any
    # other harness, including the retired pool, isn't comparable and stays out of the export
    if meta.get("agent") not in MODE_HARNESSES[test["mode"]]:
        return None
    metrics = meta.get("metrics") or {}
    env = meta.get("environment") or {}
    machine, inference = env.get("machine") or {}, env.get("inference") or {}
    test_version = (meta.get("test") or {}).get("version")

    human, _ = _score(run_dir / "results.json", test["rubric_version"])
    automatic, automatic_results = _score(run_dir / "check_results.json", test["rubric_version"])
    agent, agent_results = _score(run_dir / "agent_results.json", test["rubric_version"])
    current = test_version is not None and test_version == test["version"]
    return {
        "run_id": meta.get("run_id"),
        "test_id": meta["test_id"],
        "test_version": test_version,
        "harness": meta.get("agent"),
        "harness_version": env.get("harness_version"),
        "model": meta.get("model"),
        # Each reasoning level is its own model on the dashboard; "default" leaves it to the model
        "reasoning": meta.get("reasoning") or "default",
        "reasoning_chars": (_read_json(run_dir / "direct-response.json") or {}).get("reasoning_chars"),
        "started_at": meta.get("started_at"),
        "status": meta.get("status"),
        "outcome": meta.get("outcome"),
        "timed_out": meta.get("timed_out"),
        "elapsed_s": meta.get("elapsed_time"),
        "score": human if current else None,
        "agent_score": agent if current else None,
        # Deterministic score for tests scored entirely by programmatic checks
        "check_score": automatic if current else None,
        "agent_summary": agent_results.get("summary"),
        "judge": agent_results.get("scorer"),
        "checks": meta.get("checks"),
        # What the run produced and what the automatic tests found, for the dashboard's detail view
        "output": _clip(checks.final_answer(run_dir)),
        "criteria": automatic_results.get("criteria") if current else None,
        "hidden_tests": _hidden_tests(run_dir),
        # Whether this run belongs in aggregates under the current test set
        "counts": current and test["status"] == "active",
        "hardware": _hardware(machine, inference),
        "inference": {k: inference.get(k) for k in ("provider", "local", "same_machine", "served_via",
                                                     "device", "quantization", "context_length")} if inference else None,
        **{key: metrics.get(key) for key in METRIC_KEYS},
        # Recorded from 2.4.0 on; older runs export null
        "run_uuid": meta.get("run_uuid"),
        "provenance": meta.get("provenance"),
        "model_variant": meta.get("model_variant"),
        "hardware_key": meta.get("hardware_key"),
        "endpoint": meta.get("endpoint"),
    }


def export(runs_dir: Path, models: list[str] | None = None) -> dict:
    tests = export_tests()
    by_id = {t["id"]: t for t in tests}
    model_dirs = [runs_dir / m for m in models] if models else sorted(p for p in runs_dir.iterdir() if p.is_dir())
    runs = [run for d in model_dirs for run_dir in sorted(d.glob("*/*/*"))
            if (run := export_run(run_dir, by_id)) is not None]
    # A model that never completed a single test has nothing to show
    finished = {r["model"] for r in runs if r.get("outcome") == "completed" or
                (r.get("outcome") is None and r.get("status") == "COMPLETE")}
    runs = [r for r in runs if r["model"] in finished]
    runs.sort(key=lambda r: (r["model"] or "", r["test_id"], r["harness"] or "", r["started_at"] or ""))
    release = versioning.latest_release()
    return {
        "format_version": FORMAT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "release": {k: release[k] for k in ("release", "created", "judge")} if release else None,
        "agent_score_caveat": AGENT_CAVEAT,
        "harnesses": list(AGENTS),
        "modes": [{"id": m, "label": MODE_LABELS[m], "harnesses": list(MODE_HARNESSES[m]),
                   "areas": [{"id": a, "label": label} for a, label in AREAS[m].items()]} for m in MODES],
        "tiers": list(TIERS),
        "category_weights": CATEGORY_WEIGHTS,
        "tests": tests,
        "runs": runs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="crucible export", description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=Path, default=Path("runs"), help="Runs directory (default: runs)")
    parser.add_argument("--models", nargs="*", help="Model directory names under runs/ (default: all)")
    parser.add_argument("--out", type=Path, required=True, help="Output JSON path")
    args = parser.parse_args()
    data = export(args.runs, args.models)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    counted = sum(r["counts"] for r in data["runs"])
    print(f"Wrote {len(data['runs'])} runs ({counted} count toward scores) to {args.out}")


if __name__ == "__main__":
    main()
