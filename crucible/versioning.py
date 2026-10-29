"""Task versions and content hashes: what keeps scores comparable.

A task's *content* is everything the model sees or works on: the prompt text,
whether it gets tools, the seeded repo, fixtures and mock MCP data. Its
*rubric* is everything the scorer uses. They version separately:

  content changed -> bump `version`        -> old runs are not comparable (rerun)
  rubric changed  -> bump `rubric_version` -> re-score stored outputs (no rerun)

tasks/versions.lock.json records the hashes each declared version was cut
from. `crucible versions` checks the lock (CI runs the same check) and `--update`
rewrites it after a deliberate bump. Suites pin these hashes (crucible/suites.py).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


from crucible import workspace

LOCK_PATH = workspace.TASKS_DIR / "versions.lock.json"

# Prompt fields that change what the model does vs. how the run is graded
CONTENT_FIELDS = ("prompt", "needs_tools", "repo", "fixtures", "mcp_servers")
RUBRIC_FIELDS = ("rubric", "critical_failure", "hidden_answer", "auto_grade")

# Hidden acceptance tests the judge runs; never copied into a workspace
GRADERS_DIR = workspace.REPO_ROOT / "graders"

# Files behind a declared MCP server whose data the model reads
MCP_SERVER_DATA = {
    "mock-data": [workspace.FIXTURES_DIR / "mock-mcp-server", workspace.FIXTURES_DIR / "mock-data"],
    # "mock-calendar:<dataset>": the server, plus the dataset it serves (added in content_hash)
    "mock-calendar": [workspace.REPO_ROOT / "crucible" / "mcp_servers" / "calendar_server.py"],
}

# Never part of a seeded repo's content (installed or generated on the fly)
SKIP_DIRS = {".git", "node_modules", ".next", "__pycache__", "dist", ".venv"}


def _sha(*parts: bytes) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(len(part).to_bytes(8, "big"))
        digest.update(part)
    return digest.hexdigest()[:16]


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")


def _tree_bytes(path: Path) -> list[bytes]:
    """Relative paths and contents of every file under path, CRLF-normalized for cross-OS stability."""
    if not path.exists():
        return [b"<missing>", path.name.encode()]
    # Sorted by path parts, so the order (and the hash) never depends on how a filesystem compares names
    files = [path] if path.is_file() else sorted(
        (p for p in path.rglob("*") if p.is_file() and not SKIP_DIRS.intersection(p.relative_to(path).parts)),
        key=lambda p: p.relative_to(path).parts)
    parts = []
    for f in files:
        rel = f.name if path.is_file() else f.relative_to(path).as_posix()
        parts += [rel.encode(), f.read_bytes().replace(b"\r\n", b"\n")]
    return parts


def content_hash(prompt_def: dict) -> str:
    parts = [_canonical({k: prompt_def.get(k) for k in CONTENT_FIELDS})]
    repo = prompt_def.get("repo")
    if repo:
        parts += _tree_bytes(workspace.REPOS_DIR / repo)
    for name in workspace.fixture_names(prompt_def):
        parts += _tree_bytes(workspace.FIXTURES_DIR / name)
    for server in prompt_def.get("mcp_servers") or []:
        name, _, dataset = server.partition(":")
        paths = list(MCP_SERVER_DATA.get(server) or MCP_SERVER_DATA.get(name, []))
        if name == "mock-calendar" and dataset:
            paths.append(workspace.FIXTURES_DIR / "mock-calendar" / f"{dataset}.json")
        for path in paths:
            parts += _tree_bytes(path)
    return _sha(*parts)


def rubric_hash(prompt_def: dict) -> str:
    parts = [_canonical({k: prompt_def.get(k) for k in RUBRIC_FIELDS})]
    # Hidden grader tests are part of how a run is scored, so editing one is a rubric change. The
    # folder's name is the task's ID, which isn't hashed: renaming a task never changes its hashes.
    grader = prompt_def.get("grader")
    if grader:
        parts += _tree_bytes(GRADERS_DIR / grader)
    # Programmatic checks score criteria too; hashed only when present so other tests' hashes hold
    if prompt_def.get("checks"):
        parts.append(_canonical({"checks": prompt_def["checks"]}))
    if prompt_def.get("scoring"):
        parts.append(_canonical({"scoring": prompt_def["scoring"]}))
    return _sha(*parts)


def prompt_text_hash(text: str) -> str:
    """Hash of the prompt text alone; matches a run's saved prompt.txt to a version.

    Trailing whitespace is ignored: the direct harness strips it when it inlines fixtures.
    """
    return _sha(text.replace("\r\n", "\n").rstrip().encode("utf-8"))


def task_identity(prompt_def: dict) -> dict:
    """What a run or score records about the test it used."""
    return {
        "version": prompt_def.get("version"),
        "rubric_version": prompt_def.get("rubric_version"),
        "content_hash": content_hash(prompt_def),
        "rubric_hash": rubric_hash(prompt_def),
        "tier": prompt_def.get("tier"),
        "status": prompt_def.get("status"),
    }


# --------------------------------------------------------------------------
# Lock file
# --------------------------------------------------------------------------

def compute_lock() -> dict:
    lock = {}
    for task_id in workspace.all_task_ids():
        prompt_def = workspace.load_task(task_id)
        lock[task_id] = {
            "version": prompt_def.get("version"),
            "content_hash": content_hash(prompt_def),
            "prompt_hash": prompt_text_hash(prompt_def.get("prompt", "")),
            "rubric_version": prompt_def.get("rubric_version"),
            "rubric_hash": rubric_hash(prompt_def),
        }
    return lock


def read_lock() -> dict:
    return json.loads(LOCK_PATH.read_text(encoding="utf-8")) if LOCK_PATH.exists() else {}


def check_lock(current: dict | None = None, locked: dict | None = None) -> list[str]:
    """Problems that would let a score change meaning silently; [] when the lock is clean."""
    current = compute_lock() if current is None else current
    locked = read_lock() if locked is None else locked
    problems = []
    for task_id, now in current.items():
        then = locked.get(task_id)
        if then is None:
            problems.append(f"{task_id}: not in the lock; run `crucible versions --update`")
            continue
        for kind, version_key in (("content", "version"), ("rubric", "rubric_version")):
            changed = now[f"{kind}_hash"] != then[f"{kind}_hash"]
            bumped = now[version_key] != then[version_key]
            if changed and not bumped:
                problems.append(f"{task_id}: {kind} changed but {version_key} is still {now[version_key]}; "
                                f"bump {version_key} in tasks/{task_id}.yaml, then `crucible versions --update`")
            elif bumped and not changed:
                problems.append(f"{task_id}: {version_key} bumped to {now[version_key]} without a {kind} change")
            elif bumped and changed:
                problems.append(f"{task_id}: {version_key} bumped; run `crucible versions --update` to record it")
    for task_id in locked.keys() - current.keys():
        problems.append(f"{task_id}: in the lock but its task file is gone; retire it with status: retired instead")
    return problems


def write_lock() -> None:
    LOCK_PATH.write_text(json.dumps(compute_lock(), indent=2) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(prog="crucible versions",
                                     description="Check task versions against the lock, or update it")
    parser.add_argument("--update", action="store_true", help="Rewrite tasks/versions.lock.json from the current tasks")
    args = parser.parse_args()

    if args.update:
        write_lock()
        print(f"Updated {LOCK_PATH}")
    problems = check_lock()
    for problem in problems:
        print(f"  {problem}")
    if problems:
        print("See docs/versioning.md#task-versions")
        sys.exit(1)
    print(f"Lock is clean ({len(read_lock())} tasks).")


if __name__ == "__main__":
    main()
