"""Test versions, content hashes, releases and backfill: what keeps scores comparable.

A test's *content* is everything the model sees or works on: the prompt text,
whether it gets tools, the seeded repo, fixtures and mock MCP data. Its
*rubric* is everything the scorer uses. They version separately:

  content changed -> bump `version`        -> old runs are not comparable (rerun)
  rubric changed  -> bump `rubric_version` -> re-score stored outputs (no rerun)

prompts/versions.lock.json records the hashes each declared version was cut
from. `crucible versions` checks the lock (CI runs the same check), `--update`
rewrites it after a deliberate bump, `--release NAME` pins the active tests
into releases/NAME.yaml, and `--backfill` stamps runs recorded before versions
existed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from crucible import workspace
from crucible.taxonomy import CATEGORY_WEIGHTS, TIERS

LOCK_PATH = workspace.PROMPTS_DIR / "versions.lock.json"
RELEASES_DIR = workspace.REPO_ROOT / "releases"

# Prompt fields that change what the model does vs. how the run is graded
CONTENT_FIELDS = ("prompt", "needs_tools", "repo", "fixtures", "mcp_servers")
RUBRIC_FIELDS = ("rubric", "critical_failure", "hidden_answer", "auto_grade")

# Hidden acceptance tests the judge runs; never copied into a workspace
GRADERS_DIR = workspace.REPO_ROOT / "graders"

# Files behind a declared MCP server whose data the model reads
MCP_SERVER_DATA = {
    "mock-data": [workspace.FIXTURES_DIR / "mock-mcp-server", workspace.FIXTURES_DIR / "mock-data"],
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
    files = [path] if path.is_file() else sorted(
        p for p in path.rglob("*") if p.is_file() and not SKIP_DIRS.intersection(p.relative_to(path).parts))
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
        for path in MCP_SERVER_DATA.get(server, []):
            parts += _tree_bytes(path)
    return _sha(*parts)


def rubric_hash(prompt_def: dict) -> str:
    parts = [_canonical({k: prompt_def.get(k) for k in RUBRIC_FIELDS})]
    # Hidden grader tests are part of how a run is scored, so editing one is a rubric change
    grader = prompt_def.get("grader")
    if grader:
        parts += [grader.encode(), *_tree_bytes(GRADERS_DIR / grader)]
    # Programmatic checks score criteria too; hashed only when present so other tests' hashes hold
    if prompt_def.get("checks"):
        parts.append(_canonical({"checks": prompt_def["checks"]}))
    return _sha(*parts)


def prompt_text_hash(text: str) -> str:
    """Hash of the prompt text alone; matches a run's saved prompt.txt to a version.

    Trailing whitespace is ignored: the direct harness strips it when it inlines fixtures.
    """
    return _sha(text.replace("\r\n", "\n").rstrip().encode("utf-8"))


def _sent_prompt_hashes(prompt_def: dict) -> set[str]:
    """Hashes of every form of the prompt a harness saves: as written, or with fixtures inlined (direct)."""
    text = prompt_def.get("prompt", "")
    return {prompt_text_hash(text),
            prompt_text_hash(workspace.inline_fixtures(text, workspace.fixture_names(prompt_def)))}


def test_identity(prompt_def: dict) -> dict:
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
    for test_id in workspace.all_test_ids():
        prompt_def = workspace.load_prompt(test_id)
        lock[test_id] = {
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
    for test_id, now in current.items():
        then = locked.get(test_id)
        if then is None:
            problems.append(f"{test_id}: not in the lock; run `crucible versions --update`")
            continue
        for kind, version_key in (("content", "version"), ("rubric", "rubric_version")):
            changed = now[f"{kind}_hash"] != then[f"{kind}_hash"]
            bumped = now[version_key] != then[version_key]
            if changed and not bumped:
                problems.append(f"{test_id}: {kind} changed but {version_key} is still {now[version_key]}; "
                                f"bump {version_key} in prompts/{test_id}.yaml, then `crucible versions --update`")
            elif bumped and not changed:
                problems.append(f"{test_id}: {version_key} bumped to {now[version_key]} without a {kind} change")
            elif bumped and changed:
                problems.append(f"{test_id}: {version_key} bumped; run `crucible versions --update` to record it")
    for test_id in locked.keys() - current.keys():
        problems.append(f"{test_id}: in the lock but its prompt is gone; retire it with status: retired instead")
    return problems


def write_lock() -> None:
    LOCK_PATH.write_text(json.dumps(compute_lock(), indent=2) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# Releases
# --------------------------------------------------------------------------

def build_release(name: str, judge_model: str, judge_prompt_version: int) -> dict:
    tests = []
    for test_id in workspace.all_test_ids():
        p = workspace.load_prompt(test_id)
        if p.get("status") != "active":
            continue
        tests.append({"id": test_id, "version": p["version"], "rubric_version": p["rubric_version"],
                      "tier": p["tier"], "category": p["category"]})
    return {
        "release": name,
        "created": datetime.now(timezone.utc).date().isoformat(),
        "judge": {"model": judge_model, "prompt_version": judge_prompt_version},
        "tiers": list(TIERS),
        "category_weights": CATEGORY_WEIGHTS,
        "tests": tests,
    }


def write_release(name: str, judge_model: str, judge_prompt_version: int) -> Path:
    RELEASES_DIR.mkdir(exist_ok=True)
    path = RELEASES_DIR / f"{name}.yaml"
    if path.exists():
        raise FileExistsError(f"{path} exists; releases are immutable, cut a new one")
    release = build_release(name, judge_model, judge_prompt_version)
    path.write_text(yaml.safe_dump(release, sort_keys=False), encoding="utf-8")
    return path


def latest_release() -> dict | None:
    paths = sorted(RELEASES_DIR.glob("*.yaml"))
    return yaml.safe_load(paths[-1].read_text(encoding="utf-8")) if paths else None


# --------------------------------------------------------------------------
# Backfill runs recorded before versioning
# --------------------------------------------------------------------------

def backfill_run(run_dir: Path, lock: dict) -> str:
    """Stamp meta.json and score files with the test version they used. Returns what happened."""
    meta_path = run_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if "test" in meta and not meta["test"].get("backfilled"):
        return "already versioned"
    locked = lock.get(meta.get("test_id"))
    prompt_txt = run_dir / "prompt.txt"
    if not locked or not prompt_txt.exists():
        return "skipped (unknown test or no prompt.txt)"

    # The lock describes the current prompts, so the current prompt's sent forms are that version's
    current = workspace.load_prompt(meta["test_id"])
    matches = (current.get("version") == locked["version"]
               and prompt_text_hash(prompt_txt.read_text(encoding="utf-8")) in _sent_prompt_hashes(current))
    meta["test"] = {
        "version": locked["version"] if matches else None,
        "rubric_version": None,
        "content_hash": None,  # repos and fixtures weren't recorded at run time
        "backfilled": True,
        "note": ("prompt.txt matches this version; repo and fixtures assumed unchanged"
                 if matches else "prompt.txt differs from every recorded version; not comparable"),
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    # Score files scored against today's rubric when they were written after the rubric was locked
    for name in ("results.json", "agent_results.json"):
        path = run_dir / name
        if not path.exists():
            continue
        scores = json.loads(path.read_text(encoding="utf-8"))
        if "rubric_version" not in scores:
            scores["rubric_version"] = locked["rubric_version"]
            scores["rubric_version_backfilled"] = True
            path.write_text(json.dumps(scores, indent=2) + "\n", encoding="utf-8")
    return f"v{locked['version']}" if matches else "prompt differs"


def backfill(runs_dir: Path) -> dict[str, int]:
    lock = read_lock() or compute_lock()
    counts: dict[str, int] = {}
    for meta_path in sorted(runs_dir.glob("*/*/*/*/meta.json")):
        outcome = backfill_run(meta_path.parent, lock)
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(prog="crucible versions",
                                     description="Check test versions against the lock, update it, cut a release or backfill runs")
    parser.add_argument("--update", action="store_true", help="Rewrite prompts/versions.lock.json from the current prompts")
    parser.add_argument("--release", metavar="NAME", help="Pin active tests into releases/NAME.yaml (e.g. 2026.11)")
    parser.add_argument("--judge-model", default="claude-opus-5-5", help="Agent judge for the release")
    parser.add_argument("--backfill", metavar="RUNS_DIR", type=Path, help="Stamp unversioned runs with their test version")
    args = parser.parse_args()

    if args.update:
        write_lock()
        print(f"Updated {LOCK_PATH}")
    problems = check_lock()
    for problem in problems:
        print(f"  {problem}")
    if problems:
        sys.exit(1)
    print(f"Lock is clean ({len(read_lock())} tests).")

    if args.release:
        from crucible.judge import JUDGE_PROMPT_VERSION
        print(f"Wrote {write_release(args.release, args.judge_model, JUDGE_PROMPT_VERSION)}")
    if args.backfill:
        for outcome, n in sorted(backfill(args.backfill).items()):
            print(f"  {n:4d}  {outcome}")


if __name__ == "__main__":
    main()
