"""`crucible task`: list the tasks, or show one.

    crucible task list [--all]
    crucible task show react-lead-form      (or an earlier ID: CODE-16)
"""
from __future__ import annotations

import argparse
import sys

from crucible import plan as planner
from crucible import workspace
from crucible.taxonomy import AREAS, MODE_LABELS, MODES, mode_for


def main() -> None:
    parser = argparse.ArgumentParser(prog="crucible task", description="List the tasks, or show one")
    sub = parser.add_subparsers(dest="command", required=True)
    ls = sub.add_parser("list", help="Every task by mode and area")
    ls.add_argument("--all", action="store_true", help="Include retired tasks")
    show = sub.add_parser("show", help="One task's details and prompt")
    show.add_argument("task", help="Its slug or an earlier ID")
    args = parser.parse_args()

    if args.command == "show":
        try:
            slug, alias = workspace.resolve(args.task)
        except KeyError:
            sys.exit(f"No task {args.task}")
        if alias:
            print(f"Note: {alias} is now {slug}")
        p = workspace.load_task(slug)
        for label, value in (("Task", f"{slug} ({p.get('name')})"), ("Formerly", ", ".join(p.get("aliases") or []) or "-"),
                             ("Mode", MODE_LABELS[mode_for(p)]), ("Area", p.get("area")), ("Category", p.get("category")),
                             ("Tier", p.get("tier")), ("Status", p.get("status")),
                             ("Version", f"{p.get('version')} (rubric {p.get('rubric_version')})")):
            print(f"{label + ':':<10} {value}")
        print(f"\n{(p.get('prompt') or '').strip()}")
        return

    prompts = planner.all_prompts()
    for mode in MODES:
        print(MODE_LABELS[mode])
        for area, label in AREAS[mode].items():
            ids = planner.sort_tasks([t for t, p in prompts.items() if p.get("area") == area
                                      and (args.all or p.get("status") != "retired")], prompts)
            if not ids:
                continue
            print(f"  {label}")
            for t in ids:
                p = prompts[t]
                print(f"    {t:<32} {p.get('tier'):<7} {p.get('status'):<12} {p.get('name')}"
                      f"  (formerly {', '.join(p.get('aliases') or [])})")
