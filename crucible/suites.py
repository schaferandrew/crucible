"""Suites: which tasks are scored, at which version and rubric version, with which weights.

A suite file (suites/v2.yaml, suites/v2.1.yaml) is a frozen pin, written only by `crucible suite cut`
(a new major: tasks promoted, retired or changed) or `crucible suite patch` (rubric fixes only, so
stored runs are rescored and nothing needs a rerun). Each file stands alone and is never edited.

A run records its task, not a suite: it counts in every suite that pins its task at the version it
ran, scored by the score record at that suite's rubric version. See docs/versioning.md.

    crucible suite list
    crucible suite verify
    crucible suite cut v3 --promote react-lead-form --retire nextjs-course
    crucible suite patch
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from crucible import versioning, workspace
from crucible.taxonomy import CATEGORY_WEIGHTS, SCORING_POLICY, TIER_INFO, TIERS

SUITES_DIR = workspace.REPO_ROOT / "suites"
CHANGELOG_PATH = workspace.REPO_ROOT / "SUITE_CHANGELOG.md"
NAME = re.compile(r"v(\d+)(?:\.(\d+))?")
RULES = "docs/versioning.md#suites"


def parse(name: str) -> tuple[int, int]:
    match = NAME.fullmatch(name)
    if not match:
        raise ValueError(f"'{name}' isn't a suite name (v2, v2.1)")
    return int(match.group(1)), int(match.group(2) or 0)


def names(suites_dir: Path | None = None) -> list[str]:
    """Every suite, oldest first."""
    folder = suites_dir or SUITES_DIR
    found = [p.stem for p in folder.glob("v*.yaml") if NAME.fullmatch(p.stem)]
    return sorted(found, key=parse)


def load(name: str, suites_dir: Path | None = None) -> dict:
    return yaml.safe_load(((suites_dir or SUITES_DIR) / f"{name}.yaml").read_text(encoding="utf-8"))


def latest(suites_dir: Path | None = None) -> dict | None:
    found = names(suites_dir)
    return load(found[-1], suites_dir) if found else None


def pins(suite: dict) -> dict[str, dict]:
    return {t["id"]: t for t in suite.get("tasks") or []}


def counts_in(task_id: str, version, suites_dir: Path | None = None) -> list[str]:
    """The suites a run of this task at this version counts in (derived; never stored on the run)."""
    return [n for n in names(suites_dir) if (pins(load(n, suites_dir)).get(task_id) or {}).get("version") == version]


# --------------------------------------------------------------------------
# Building a suite from the lock
# --------------------------------------------------------------------------

def build(name: str, cut_at: str, task_ids: list[str], lock: dict | None = None) -> dict:
    """A suite pinning these tasks at their locked versions, with today's tiers and weights."""
    lock = lock if lock is not None else versioning.read_lock()
    defs = {t: workspace.load_task(t) for t in task_ids}
    per_category: dict[str, int] = {}
    for p in defs.values():
        per_category[p["category"]] = per_category.get(p["category"], 0) + 1
    major, patch = parse(name)
    tasks = []
    for task_id in sorted(task_ids):
        p, locked = defs[task_id], lock[task_id]
        tasks.append({
            "id": task_id, "aliases": list(p.get("aliases") or []),
            "version": locked["version"], "rubric_version": locked["rubric_version"],
            "content_hash": locked["content_hash"], "rubric_hash": locked["rubric_hash"],
            "tier": p["tier"], "category": p["category"],
            # The category's weight split across its tasks in this suite
            "weight": round(CATEGORY_WEIGHTS[p["category"]] / per_category[p["category"]], 6),
        })
    return {
        "suite": name, "version": f"{major}.{patch}", "cut_at": cut_at,
        "scoring_policy": dict(SCORING_POLICY),
        "tiers": [{k: v for k, v in TIER_INFO[t].items() if k in ("id", "label", "role", "gate")} for t in TIERS],
        "category_weights": dict(CATEGORY_WEIGHTS),
        "tasks": tasks,
    }


def write(suite: dict, suites_dir: Path | None = None) -> Path:
    folder = suites_dir or SUITES_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{suite['suite']}.yaml"
    if path.exists():
        raise FileExistsError(f"{path} exists; suites are immutable, cut a new one ({RULES})")
    header = (f"# Suite {suite['suite']}: written by `crucible suite`, never edited by hand ({RULES}).\n")
    path.write_text(header + yaml.safe_dump(suite, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Verifying
# --------------------------------------------------------------------------

def verify(suite: dict | None = None, lock: dict | None = None, statuses: dict[str, str] | None = None) -> list[str]:
    """Problems with the latest suite against the tasks today; [] when it still holds.

    A pinned task's content and rubric may only change with a version bump (its runs then stop
    counting in this suite, or a patch rescores them); only a cut changes which tasks are active.
    """
    suite = suite if suite is not None else latest()
    if suite is None:
        return []
    lock = lock if lock is not None else versioning.read_lock()
    if statuses is None:
        statuses = {t: workspace.load_task(t).get("status") for t in workspace.all_task_ids()}
    problems = []
    pinned = pins(suite)
    for task_id, pin in pinned.items():
        now = lock.get(task_id)
        if now is None:
            problems.append(f"{task_id}: pinned in suite {suite['suite']} but not in the lock; tasks are retired, never deleted")
            continue
        for kind, version_key in (("content", "version"), ("rubric", "rubric_version")):
            if now[version_key] < pin[version_key]:
                problems.append(f"{task_id}: {version_key} {now[version_key]} is below the {pin[version_key]} "
                                f"suite {suite['suite']} pins")
            elif (now[version_key] == pin[version_key] and pin.get(f"{kind}_hash")
                  and now[f"{kind}_hash"] != pin[f"{kind}_hash"]):
                problems.append(f"{task_id}: {kind} changed since suite {suite['suite']} pinned it at "
                                f"{version_key} {pin[version_key]}; bump {version_key} ({RULES})")
    active = {t for t, status in statuses.items() if status == "active"}
    for task_id in sorted(active - set(pinned)):
        problems.append(f"{task_id}: active but not in suite {suite['suite']}; only `crucible suite cut` promotes a task "
                        f"(set it back to provisional, or cut a suite)")
    for task_id in sorted(set(pinned) - active):
        if task_id in statuses:
            problems.append(f"{task_id}: pinned in suite {suite['suite']} but {statuses[task_id]}; only `crucible suite cut` "
                            f"retires a task")
    return problems


# --------------------------------------------------------------------------
# Cutting and patching
# --------------------------------------------------------------------------

def set_status(task_id: str, status: str) -> None:
    """Rewrite a task file's `status:` line in place (the rest of the file is left as written)."""
    path = workspace.TASKS_DIR / f"{task_id}.yaml"
    text = path.read_text(encoding="utf-8")
    new, n = re.subn(r"(?m)^status: *\S+ *$", f"status: {status}", text, count=1)
    if n != 1:
        raise ValueError(f"{path} has no top-level `status:` line")
    path.write_text(new, encoding="utf-8")


def _unreleased(path: Path):
    text = path.read_text(encoding="utf-8")
    match = re.search(r"(?m)^## Unreleased[ \t]*\n(.*?)(?=^## |\Z)", text, re.S)
    if not match:
        raise ValueError(f"{path} has no `## Unreleased` section")
    if not match.group(1).strip():
        raise ValueError(f"Nothing under `## Unreleased` in {path}: say what changed before cutting a suite")
    return text, match


def release_changelog(name: str, date: str, path: Path | None = None) -> None:
    """Move what's under `## Unreleased` into a new `## Suite <name> (<date>)` section."""
    path = path or CHANGELOG_PATH
    text, match = _unreleased(path)
    body = match.group(1).strip()
    section = f"## Unreleased\n\n## Suite {name} ({date})\n\n{body}\n\n"
    path.write_text(text[:match.start()] + section + text[match.end():], encoding="utf-8")


def _grader_passes(task_id: str) -> bool:
    proc = subprocess.run([sys.executable, "-m", "crucible.cli", "grader", task_id], cwd=workspace.REPO_ROOT)
    return proc.returncode == 0


def cut(name: str, promote: list[str] = (), retire: list[str] = (), date: str | None = None,
        check_graders: bool = True, suites_dir: Path | None = None, changelog: Path | None = None) -> Path:
    """Promote and retire tasks, write suites/<name>.yaml from the lock and close the changelog section."""
    date = date or datetime.now(timezone.utc).date().isoformat()
    previous = names(suites_dir)
    expected = f"v{parse(previous[-1])[0] + 1}" if previous else "v1"
    if name != expected:
        raise ValueError(f"The next suite is {expected}, not {name} (a patch is `crucible suite patch`)")
    promote = [workspace.resolve(t)[0] for t in promote]
    retire = [workspace.resolve(t)[0] for t in retire]
    _unreleased(changelog or CHANGELOG_PATH)
    problems = versioning.check_lock()
    if problems:
        raise ValueError("The lock isn't clean; fix it first:\n  " + "\n  ".join(problems))
    for task_id in promote:
        p = workspace.load_task(task_id)
        if p.get("status") != "provisional":
            raise ValueError(f"{task_id} is {p.get('status')}, not provisional; only provisional tasks are promoted")
        if check_graders and p.get("grader") and not _grader_passes(task_id):
            raise ValueError(f"{task_id}: `crucible grader {task_id}` fails; a grader must pass its oracle before promotion")
    for task_id in retire:
        if workspace.load_task(task_id).get("status") == "retired":
            raise ValueError(f"{task_id} is already retired")
    for task_id in promote:
        set_status(task_id, "active")
    for task_id in retire:
        set_status(task_id, "retired")
    active = [t for t in workspace.all_task_ids() if workspace.load_task(t).get("status") == "active"]
    path = write(build(name, date, active), suites_dir)
    release_changelog(name, date, changelog)
    return path


def patch(date: str | None = None, suites_dir: Path | None = None, changelog: Path | None = None) -> tuple[Path, list[str]]:
    """Write the next patch of the latest suite when only rubric versions changed; returns it and the rescored tasks."""
    date = date or datetime.now(timezone.utc).date().isoformat()
    current = latest(suites_dir)
    if current is None:
        raise ValueError("No suite to patch; cut one first")
    problems = versioning.check_lock()
    if problems:
        raise ValueError("The lock isn't clean; fix it first:\n  " + "\n  ".join(problems))
    _unreleased(changelog or CHANGELOG_PATH)
    lock = versioning.read_lock()
    major, minor = parse(current["suite"])
    bumped = []
    for task_id, pin in pins(current).items():
        now = lock.get(task_id)
        if now is None or now["version"] != pin["version"] or now["content_hash"] != pin.get("content_hash", now["content_hash"]):
            raise ValueError(f"{task_id}: its content changed since suite {current['suite']}; that needs a new suite "
                             f"(`crucible suite cut v{major + 1}`), not a patch")
        if now["rubric_version"] != pin["rubric_version"]:
            bumped.append(task_id)
    if not bumped:
        raise ValueError(f"No rubric_version changed since suite {current['suite']}; nothing to patch")
    name = f"v{major}.{minor + 1}"
    suite = {**current, "suite": name, "version": f"{major}.{minor + 1}", "cut_at": date,
             "tasks": [{**pin, "rubric_version": lock[t]["rubric_version"], "rubric_hash": lock[t]["rubric_hash"]}
                       if t in bumped else pin for t, pin in pins(current).items()]}
    suite.pop("from_release", None)
    path = write(suite, suites_dir)
    release_changelog(name, date, changelog)
    return path, bumped


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(prog="crucible suite", description="Cut, patch, verify or list suites")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="Every suite and how many tasks it pins")
    sub.add_parser("verify", help="Check the latest suite still holds: pinned tasks unchanged unless bumped")
    c = sub.add_parser("cut", help="Cut a new suite major: promote and retire tasks, pin the lock")
    c.add_argument("name", help="The new suite, e.g. v2")
    c.add_argument("--promote", nargs="*", default=[], help="Provisional tasks to make active")
    c.add_argument("--retire", nargs="*", default=[], help="Tasks to retire")
    c.add_argument("--skip-grader-check", action="store_true", help="Don't run `crucible grader` on promoted tasks")
    p = sub.add_parser("patch", help="Pin rubric fixes into the next suite patch and rescore stored runs")
    p.add_argument("--runs", type=Path, default=Path("runs"))
    p.add_argument("--no-rescore", action="store_true", help="Write the suite file only")
    args = parser.parse_args()

    if args.command == "list":
        for n in names():
            s = load(n)
            print(f"  Suite {n:<6} cut {s.get('cut_at')}  {len(s.get('tasks') or [])} tasks")
        return
    if args.command == "verify":
        problems = verify()
        for problem in problems:
            print(f"  {problem}")
        if problems:
            sys.exit(1)
        current = latest()
        print(f"Suite {current['suite']} holds ({len(current['tasks'])} tasks)." if current else "No suites yet.")
        return
    try:
        if args.command == "cut":
            path = cut(args.name, args.promote, args.retire, check_graders=not args.skip_grader_check)
            print(f"Wrote {path}; run `crucible versions` and commit it with SUITE_CHANGELOG.md and the task files")
        else:
            path, bumped = patch()
            print(f"Wrote {path} (rubric fixes: {', '.join(bumped)})")
            if not args.no_rescore:
                from crucible import checks
                counts = checks.rescore(args.runs, bumped)
                print(f"Rescored {counts['checked'] + counts['graded']} runs into score records at the new rubric versions")
    except (ValueError, FileExistsError) as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
