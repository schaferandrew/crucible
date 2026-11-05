#!/usr/bin/env python3
"""`crucible coverage`: which suite tasks each model setup has finished, and the command that fills the gaps.

One line per model as run (model.id) and requested reasoning level, since that's what `crucible run
--skip-done` can fill. A task is done when a run of it counts the way the dashboard counts it: at the
suite's pinned task version, through a harness its mode allows, and not marked invalid or withdrawn.

Usage:
    crucible coverage [--runs DIR] [--suite NAME] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from crucible import runrecord, suites


def coverage(runs_dir: Path, suite: dict) -> dict:
    """{"suite", "total_tasks", "setups": [...]} for every model and reasoning level with a run in runs_dir."""
    from crucible.bundle import harness_problem
    pins = suites.pins(suite)
    setups: dict[tuple[str, str], dict] = {}
    for run_dir in runrecord.run_dirs(runs_dir):
        meta = runrecord.read(run_dir)
        if not meta:
            continue
        model = meta.get("model") or {}
        requested = (model.get("reasoning") or {}).get("requested") or "default"
        key = (model.get("id") or "", requested)
        setup = setups.setdefault(key, {
            "model": key[0], "reasoning": requested, "base": model.get("base"),
            "publisher": model.get("publisher"), "format": model.get("format"), "quant": model.get("quant"),
            "where": (meta.get("endpoint") or {}).get("where"), "harnesses": set(), "done": set()})
        task, harness = meta.get("task") or {}, (meta.get("harness") or {}).get("id")
        pin = pins.get(task.get("id"))
        if (pin and task.get("version") == pin.get("version") and not harness_problem(meta)
                and not runrecord.invalid(run_dir, meta)
                and (meta.get("outcome") or {}).get("status") != "harness_error"):
            setup["done"].add(task["id"])
            if harness and harness != "direct":
                setup["harnesses"].add(harness)
    rows = []
    for (model_id, reasoning), s in sorted(setups.items()):
        missing = sorted(t for t in pins if t not in s["done"])
        command = ""
        if missing:
            parts = ["crucible", "run", *missing, "--model", model_id]
            if reasoning != "default":
                parts += ["--reasoning", reasoning]
            if len(s["harnesses"]) == 1:
                parts += ["--agent", next(iter(s["harnesses"]))]
            command = " ".join(parts + ["--skip-done"])
        rows.append({**{k: v for k, v in s.items() if k not in ("done", "harnesses")},
                     "harnesses": sorted(s["harnesses"]), "tasks_done": len(s["done"]),
                     "tasks_missing": missing, "command": command})
    return {"suite": suite.get("suite"), "total_tasks": len(pins), "setups": rows}


def main() -> None:
    parser = argparse.ArgumentParser(prog="crucible coverage", description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=Path, default=Path("runs"), help="Run folders (default: runs)")
    parser.add_argument("--suite", help="Suite name, e.g. v4 (default: the latest)")
    parser.add_argument("--json", action="store_true", help="Print JSON")
    args = parser.parse_args()
    if not args.runs.is_dir():
        sys.exit(f"{args.runs} doesn't exist")
    runrecord.require_migrated(args.runs)
    suite = suites.load(args.suite) if args.suite else suites.latest()
    if not suite:
        sys.exit("No suite found")
    result = coverage(args.runs, suite)
    if args.json:
        print(json.dumps(result, indent=2))
        return
    total = result["total_tasks"]
    print(f"Suite {result['suite']}: {total} tasks, {len(result['setups'])} setups")
    for s in result["setups"]:
        label = " · ".join(filter(None, [s["model"], s["reasoning"] if s["reasoning"] != "default" else None,
                                         s["quant"], s["where"]]))
        print(f"\n{label}: {s['tasks_done']}/{total}")
        if s["command"]:
            print(f"  missing: {', '.join(s['tasks_missing'])}\n  {s['command']}")


if __name__ == "__main__":
    main()
