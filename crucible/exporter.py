"""`crucible export --format 2`: flatten runs into one bundle file, the format the live dashboard reads
until it switches to format 3 (`crucible publish`, docs/bundle-format.md).

Format 2 is frozen: tasks are listed by their pre-3.0.0 test IDs (a task's first alias), runs by
their legacy run_id (or run path, for runs made since), so the dashboard keeps working unchanged.

Scores are only comparable on the same task content and rubric, so every run carries the version
it used, and a score counts (`counts: true`) only when that version and rubric version match the
current task and the task is active. Timed-out runs still count: running out of time is a result.
The page decides how to aggregate; this file never averages anything. Unknown values stay null, never 0.

Usage:
    crucible export --format 2 --out ../schaferandrew.github.io/_data/crucible/ironwood.json
    crucible export --format 2 --models openrouter_qwen_qwen3.8-27b --out crucible.json
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from crucible import checks, hardware, runrecord, suites, workspace
from crucible.agents import AGENTS
from crucible.judge import CAVEAT as AGENT_CAVEAT
from crucible.taxonomy import AREAS, CATEGORY_WEIGHTS, MODE_HARNESSES, MODE_LABELS, MODES, TIERS, mode_for

FORMAT_VERSION = 2  # 2: test IDs by area prefix, chat/agentic modes; frozen since 3.0.0
METRIC_KEYS = ["tests_passed", "tests_failed", "tool_calls", "tokens_in", "tokens_out",
               "model_responses", "ttft_s", "response_time_avg_s", "cost_usd"]


def _first_sentence(text: str) -> str:
    text = " ".join(text.split())
    match = re.match(r"(.+?[.?!])(\s|$)", text)
    return match.group(1) if match else text


def _read_json(path: Path) -> dict | None:
    return runrecord.read_json(path)


def legacy_id(prompt_def: dict) -> str:
    """The ID a task had before 3.0.0 (its first alias), which format 2 keeps using."""
    return (prompt_def.get("aliases") or [prompt_def["id"]])[0]


def export_tests() -> list[dict]:
    tests = []
    for p in sorted((workspace.load_task(t) for t in workspace.all_task_ids()), key=legacy_id):
        if p.get("status") == "retired":
            continue  # never run or scored; leaving it out also leaves out its runs
        tests.append({
            "id": legacy_id(p), "slug": p["id"], "name": p.get("name"), "mode": mode_for(p), "area": p.get("area"),
            "category": p.get("category"),
            "tier": p.get("tier"), "status": p.get("status"), "version": p.get("version"),
            "rubric_version": p.get("rubric_version"), "needs_tools": bool(p.get("needs_tools", True)),
            "summary": _first_sentence(p.get("prompt", "")),
            "prompt": (p.get("prompt") or "").strip(),
            "scoring": "checks" if checks.fully_checked(p) else "judge",
            "rules": [c.get("rule", c["type"]) for c in p.get("checks") or []],
        })
    return tests


def _score(path: Path, rubric_version: int | None) -> tuple[float | None, dict]:
    """A judge's or person's 0-10 overall when it was scored against the current rubric version."""
    results = _read_json(path)
    if not results:
        return None, {}
    overall = (results.get("scores") or {}).get("_overall")
    if results.get("rubric_version") != rubric_version:
        return None, {"stale_rubric": results.get("rubric_version")}
    return (overall if isinstance(overall, (int, float)) else None), results


def _check_score(run_dir: Path, rubric_version: int | None) -> tuple[float | None, dict | None]:
    """The checks or hidden-tests score record at the current rubric version."""
    record = next((r for r in reversed(runrecord.scores(run_dir)) if r.get("rubric_version") == rubric_version
                   and r.get("method") in ("checks", "hidden_tests")), None)
    if not record:
        return None, None
    score = record.get("score")
    return (score if isinstance(score, (int, float)) else None), record


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
    """One run in format 2; `tests` is keyed by task slug."""
    meta = runrecord.read(run_dir)
    # An invalid run's environment was broken (e.g. a stale server), not a model failure
    if not meta or meta["task"].get("id") not in tests or runrecord.invalid(run_dir, meta):
        return None
    test = tests[meta["task"]["id"]]
    harness = meta["harness"].get("id")
    # Each mode has its own harnesses (chat: direct; agentic: opencode, pi); a run through any
    # other harness, including the retired pool, isn't comparable and stays out of the export
    if harness not in MODE_HARNESSES[test["mode"]]:
        return None
    local = meta.get("local") or {}
    metrics = meta.get("metrics") or {}
    env = local.get("environment") or {}
    machine, inference = env.get("machine") or {}, env.get("inference") or {}
    outcome, model = meta.get("outcome") or {}, meta.get("model") or {}
    test_version = meta["task"].get("version")
    provenance = meta.get("provenance") or {}
    # A run migrated from before 3.0.0 exports the 2.4.0 fields it recorded then (null before 2.4.0)
    legacy = local.get("legacy_meta")

    human, _ = _score(run_dir / "results.json", test["rubric_version"])
    automatic, record = _check_score(run_dir, test["rubric_version"])
    agent, agent_results = _score(run_dir / "agent_results.json", test["rubric_version"])
    current = test_version is not None and test_version == test["version"]
    return {
        "run_id": meta.get("legacy_run_id") or meta.get("run_path"),
        "test_id": test["id"],
        "test_version": test_version,
        "harness": harness,
        "harness_version": env.get("harness_version"),
        "model": model.get("id"),
        # Each reasoning level is its own model on the dashboard; "default" leaves it to the model
        "reasoning": (model.get("reasoning") or {}).get("requested") or "default",
        "reasoning_chars": (_read_json(run_dir / "direct-response.json") or {}).get("reasoning_chars"),
        "started_at": meta.get("started_at"),
        "status": outcome.get("harness_status"),
        "outcome": outcome.get("status"),
        "timed_out": outcome.get("timed_out"),
        "elapsed_s": meta.get("elapsed_s"),
        "score": human if current else None,
        "agent_score": agent if current else None,
        # Deterministic score for tasks scored entirely by programmatic checks or hidden tests
        "check_score": automatic if current else None,
        "agent_summary": agent_results.get("summary"),
        "judge": agent_results.get("scorer"),
        "checks": local.get("checks"),
        # What the run produced and what the automatic tests found, for the dashboard's detail view
        "output": _clip(checks.final_answer(run_dir)),
        "criteria": runrecord.criteria(record) if current else None,
        "hidden_tests": _hidden_tests(run_dir),
        # Whether this run belongs in aggregates under the current task set
        "counts": current and test["status"] == "active",
        "hardware": _hardware(machine, inference),
        "inference": {k: inference.get(k) for k in ("provider", "local", "same_machine", "served_via",
                                                     "device", "quantization", "context_length")} if inference else None,
        **{key: metrics.get(key) for key in METRIC_KEYS},
        "run_uuid": meta.get("run_uuid"),
        **({key: legacy.get(key) for key in ("provenance", "model_variant", "hardware_key", "endpoint")} if legacy else {
            "provenance": {k: provenance.get(k) for k in ("crucible_version", "crucible_commit", "crucible_dirty", "machine_id")},
            "model_variant": {"publisher": model.get("publisher"), "format": model.get("format"), "quant": model.get("quant"),
                              "reasoning_resolved": (model.get("reasoning") or {}).get("resolved")},
            "hardware_key": (meta.get("hardware") or {}).get("key"),
            "endpoint": {k: (meta.get("endpoint") or {}).get(k) for k in ("upstream", "resolved_model")},
        }),
    }


def export(runs_dir: Path, models: list[str] | None = None) -> dict:
    runrecord.require_migrated(runs_dir)
    tests = export_tests()
    by_slug = {t["slug"]: t for t in tests}
    model_dirs = [runs_dir / m for m in models] if models else sorted(p for p in runs_dir.iterdir() if p.is_dir())
    runs = [run for d in model_dirs for run_dir in sorted(m.parent for m in d.glob("*/*/meta.json"))
            if (run := export_run(run_dir, by_slug)) is not None]
    # A model that never completed a single task has nothing to show
    finished = {r["model"] for r in runs if r.get("outcome") == "completed" or
                (r.get("outcome") is None and r.get("status") == "COMPLETE")}
    runs = [r for r in runs if r["model"] in finished]
    runs.sort(key=lambda r: (r["model"] or "", r["test_id"], r["harness"] or "", r["started_at"] or ""))
    suite = suites.latest()
    return {
        "format_version": FORMAT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "release": ({"release": suite.get("from_release") or suite["suite"], "created": suite.get("cut_at"),
                     "judge": suite.get("judge")} if suite else None),
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
    parser.add_argument("--format", type=int, choices=[2], default=2,
                        help="Bundle format: 2, the single file the dashboard reads until it switches to format 3 "
                             "(format 3 is written by `crucible publish`)")
    parser.add_argument("--runs", type=Path, default=Path("runs"), help="Runs directory (default: runs)")
    parser.add_argument("--models", nargs="*", help="Model directory names under runs/ (default: all)")
    parser.add_argument("--out", type=Path, required=True, help="Output JSON path")
    args = parser.parse_args()
    data = export(args.runs, args.models)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # Plain UTF-8, not \\u escapes: Jekyll parses data files with a YAML parser that rejects escaped emoji
    args.out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    counted = sum(r["counts"] for r in data["runs"])
    print(f"Wrote {len(data['runs'])} runs ({counted} count toward scores) to {args.out}")


if __name__ == "__main__":
    main()
