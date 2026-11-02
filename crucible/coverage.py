#!/usr/bin/env python3
"""`crucible coverage`: report task coverage per variant for the active suite.

Shows one line per variant (base, publisher, format, quant, reasoning, where, harness)
with tasks done and missing, counted the way the dashboard counts them (task version
pinned, invalid and withdrawn runs excluded), plus the exact `crucible run ... --skip-done`
command that fills each gap.

Usage:
    crucible coverage [--runs DIR] [--suite SUITE] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from crucible import runrecord, suites, tasks


def _variant_key(run: dict) -> str:
    """Build a variant key from a run record."""
    model = run.get("model", {})
    endpoint = run.get("endpoint", {})
    harness = run.get("harness", {})
    
    base = model.get("base") or ""
    publisher = model.get("publisher") or ""
    fmt = model.get("format") or ""
    quant = model.get("quant") or ""
    reasoning = (model.get("reasoning") or {}).get("resolved") or (model.get("reasoning") or {}).get("requested") or ""
    where = endpoint.get("where") or ""
    harness_id = harness.get("id") or ""
    
    # Normalize for grouping
    return "|".join([base, publisher, fmt or "-", quant or "-", reasoning or "-", where or "-", harness_id or "-"])


def _model_id(run: dict) -> str:
    """Get the model ID from a run."""
    return run.get("model", {}).get("id") or ""


def _task_key(run: dict) -> str:
    """Get the task key from a run."""
    task = run.get("task", {})
    return f"{task.get('id')}:{task.get('version')}" if task.get("id") and task.get("version") else ""


def _is_valid(run: dict, run_dir: Path) -> bool:
    """Check if a run is valid (not invalid or withdrawn)."""
    # Check outcome
    outcome = run.get("outcome", {})
    if outcome.get("invalid"):
        return False
    
    # Check status records
    status_file = run_dir / "status.json"
    if status_file.exists():
        try:
            statuses = json.loads(status_file.read_text())
            for status in statuses:
                if status.get("invalid") or status.get("withdrawn"):
                    return False
                if status.get("valid") is True:
                    # Valid overrides previous invalid/withdrawn
                    return True
        except (json.JSONDecodeError, OSError):
            pass
    
    return True


def _load_run(run_dir: Path) -> dict | None:
    """Load a run record from a directory."""
    meta_path = run_dir / "meta.json"
    if not meta_path.exists():
        return None
    try:
        data = json.loads(meta_path.read_text())
        if data.get("record") == "run":
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _find_run_dirs(runs_dir: Path) -> list[Path]:
    """Find all run directories."""
    run_dirs = []
    
    # Check both old and new formats
    for pattern in ["*/*/*/", "*/*/*/*/"]:
        for dirpath in runs_dir.glob(pattern):
            if (dirpath / "meta.json").exists():
                run_dirs.append(dirpath)
    
    return sorted(set(run_dirs))


def coverage(runs_dir: Path, suite_name: str | None = None, json_output: bool = False) -> dict | None:
    """Compute coverage per variant.
    
    Returns:
        A dict with suite info and variants, or None if no runs found.
    """
    # Get the active suite
    if suite_name:
        suite = suites.load_suite(suite_name)
    else:
        suite = suites.active_suite()
    
    if not suite:
        print("No active suite found")
        return None
    
    # Get all tasks in the suite
    suite_tasks = set()
    for task_id in suite.get("tasks", []):
        task = tasks.get(task_id)
        if task:
            suite_tasks.add(f"{task_id}:{task.get('version', 1)}")
    
    if not suite_tasks:
        print("No tasks in suite")
        return None
    
    # Find all run directories
    run_dirs = _find_run_dirs(runs_dir)
    
    if not run_dirs:
        print(f"No runs found in {runs_dir}")
        return None
    
    # Group runs by variant
    variants = defaultdict(list)
    for run_dir in run_dirs:
        run = _load_run(run_dir)
        if not run:
            continue
        
        # Check if valid
        if not _is_valid(run, run_dir):
            continue
        
        # Get variant key
        vkey = _variant_key(run)
        variants[vkey].append(run)
    
    if not variants:
        print("No valid runs found")
        return None
    
    # Build result
    result = {
        "suite": suite_name or suite.get("id", "unknown"),
        "total_tasks": len(suite_tasks),
        "variants": []
    }
    
    # For each variant, count tasks done and missing
    for vkey, runs in sorted(variants.items()):
        parts = vkey.split("|")
        base = parts[0] if len(parts) > 0 else ""
        publisher = parts[1] if len(parts) > 1 else ""
        fmt = parts[2] if len(parts) > 2 and parts[2] != "-" else None
        quant = parts[3] if len(parts) > 3 and parts[3] != "-" else None
        reasoning = parts[4] if len(parts) > 4 and parts[4] != "-" else "default"
        where = parts[5] if len(parts) > 5 and parts[5] != "-" else ""
        harness_id = parts[6] if len(parts) > 6 and parts[6] != "-" else ""
        
        # Count tasks done
        tasks_done = set()
        for run in runs:
            task_key = _task_key(run)
            if task_key in suite_tasks:
                tasks_done.add(task_key)
        
        # Find missing tasks
        tasks_missing = sorted([tk for tk in suite_tasks if tk not in tasks_done])
        
        # Build skip-done command
        missing_task_ids = [tk.split(":")[0] for tk in tasks_missing]
        if missing_task_ids:
            # Try to reconstruct the model ID from one of the runs
            model_id = _model_id(runs[0]) if runs else ""
            
            # Build command
            cmd_parts = ["crucible", "run"]
            cmd_parts.extend(missing_task_ids)
            if model_id:
                cmd_parts.extend(["--model", model_id])
            if reasoning != "default":
                cmd_parts.extend(["--reasoning", reasoning])
            cmd_parts.append("--skip-done")
            
            command = " ".join(cmd_parts)
        else:
            command = ""
        
        result["variants"].append({
            "base": base,
            "publisher": publisher if publisher else None,
            "format": fmt,
            "quant": quant,
            "reasoning": reasoning,
            "where": where if where else None,
            "harness": harness_id if harness_id else None,
            "tasks_done": len(tasks_done),
            "tasks_missing": len(tasks_missing),
            "missing_task_ids": [tk.split(":")[0] for tk in tasks_missing],
            "command": command
        })
    
    return result


def main():
    parser = argparse.ArgumentParser(prog="crucible coverage", description=coverage.__doc__)
    parser.add_argument("--runs", type=Path, default=Path("runs"),
                        help="Directory containing run records (default: runs)")
    parser.add_argument("--suite", type=str, default=None,
                        help="Suite ID to use (default: active suite)")
    parser.add_argument("--json", action="store_true",
                        help="Output in JSON format")
    args = parser.parse_args()
    
    runs_dir = args.runs
    if not runs_dir.is_absolute():
        runs_dir = Path.cwd() / runs_dir
    
    if not runs_dir.exists():
        print(f"Error: {runs_dir} does not exist")
        sys.exit(1)
    
    result = coverage(runs_dir, args.suite, args.json)
    
    if result is None:
        sys.exit(1)
    
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        # Human-readable output
        print(f"Suite: {result['suite']}")
        print(f"Total tasks: {result['total_tasks']}")
        print(f"Variants: {len(result['variants'])}")
        print()
        
        for variant in result["variants"]:
            base = variant["base"]
            pub = variant["publisher"] or "-"
            fmt = variant["format"] or "-"
            quant = variant["quant"] or "-"
            reasoning = variant["reasoning"]
            where = variant["where"] or "-"
            harness = variant["harness"] or "-"
            
            done = variant["tasks_done"]
            missing = variant["tasks_missing"]
            total = result["total_tasks"]
            
            # Build variant description
            parts = []
            if base:
                parts.append(base)
            if pub != "-":
                parts.append(f"publisher={pub}")
            if fmt != "-":
                parts.append(f"format={fmt}")
            if quant != "-":
                parts.append(f"quant={quant}")
            if reasoning != "default":
                parts.append(f"reasoning={reasoning}")
            if where != "-":
                parts.append(f"where={where}")
            if harness != "-":
                parts.append(f"harness={harness}")
            
            variant_desc = ", ".join(parts)
            
            # Progress bar
            pct = (done / total * 100) if total > 0 else 0
            bar_width = 40
            filled = int(pct / 100 * bar_width)
            bar = "█" * filled + "░" * (bar_width - filled)
            
            print(f"{variant_desc:80} [{bar}] {done}/{total} ({pct:.1f}%)")
            
            if missing > 0:
                missing_ids = ", ".join(variant["missing_task_ids"][:5])
                if len(variant["missing_task_ids"]) > 5:
                    missing_ids += f" ... ({missing} total)"
                print(f"  Missing: {missing_ids}")
                if variant["command"]:
                    print(f"  Command: {variant['command']}")
            print()


if __name__ == "__main__":
    main()
