#!/usr/bin/env python3
"""Hidden acceptance tests for repo tests (Forge): run automatically after each run, and score it.

A task with `grader: <slug>` has hidden vitest files in graders/<slug>/ that the model never
sees. After the run they're copied into the finished workspace (`*.web.grader.test.tsx` into
apps/web/test/hidden, other `*.grader.test.ts` into apps/api/test/hidden), run, and removed again.
Alongside them the grader records whether the repo's own suite still passes, whether the contract
suite was left untouched, and whether the model's new tests catch the bug (pass on its code, fail on
the seeded code).

Rubric criteria bind to these results with `hidden_tests:`
  - a describe-group prefix ("contract", "finding 1") or a grader file name: the share of its tests
    that pass, times the criterion's points
  - `existing`: the repo's own tests all pass (hidden tests left out)
  - `contract_unchanged`: apps/api/test/realworld.contract.test.ts is as seeded
  - `regression`: the model added tests that pass on its code and at least one fails on the seeded code

A grader with a grader.yaml declaring `isolated: true` runs differently, closer to a verifier that
never trusts the workspace: the hidden tests run in a fresh copy of the seeded repo that takes only
the declared `artifacts` (source paths) from the model's workspace, so package.json, the lockfile,
the test config and node_modules (installed from the seeded lockfile, cached by its hash) stay as
seeded. expected.json lists every test the grader declares, recorded from the reference solution by
`crucible grader <test> --write-expected`, so a file that fails to load counts every one as failed.
An isolated grader.yaml can also declare:
  - `lockfile`: a lockfile in the grader folder to install from, for a seeded repo that has none
  - `test_roots`: {file glob: folder}, where each hidden test file runs (the first glob that matches;
    default "."), for a monorepo whose apps each have their own vitest setup
  - `existing_tests`: folders whose seeded tests must still pass on the model's artifacts (`existing`)
  - `unchanged`: files the model must leave as seeded (`contract_unchanged`)
  - `regression_tests`: folders where the model's own tests go. Its new or changed test files must pass
    on its fix and at least one must fail on the seeded code; that counts as one more test in the pool
    (group `regression`), so it weighs one test and fails on an unchanged repo
A grader.yaml with `runner: pytest` grades a Python task the same way, with pytest in the isolated copy:
the hidden tests are the grader folder's `test_*.py` files (any other `*.py` there is support code they
import), copied into `crucible_hidden/` of the grading copy and run from its root, so they can call the
model's code the way a user would (`python -m <package>`). A task with `repo: null` is seeded empty.
Each test's group is its class's docstring (first line), or its class name. `own_tests: <folder>` adds
one synthetic test (group `own tests`): the model's own tests in that folder (pytest, else unittest) run
and pass. `lockfile`, `test_roots`, `existing_tests`, `unchanged` and `regression_tests` are for vitest only.
Under `scoring: per_test` these two are caps (`cap_if_failed`), never points: they pass on the seeded
repo, so paying for them would pay for doing nothing. A test criterion can carry `cap_if_failed` too:
its tests still earn their points, and when any one of them fails the score is capped.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

from crucible.versioning import GRADERS_DIR
from crucible.workspace import REPOS_DIR

RESULTS_FILENAME = "grader_results.json"
CONFIG_FILENAME = "grader.yaml"
EXPECTED_FILENAME = "expected.json"
# Never copied from a seeded repo or a workspace into a grading copy
NOT_SOURCE = ("node_modules", ".next", ".git", "dist", "test-results")
CONTRACT = "apps/api/test/realworld.contract.test.ts"
SPECIAL = ("existing", "contract_unchanged", "regression")
# Pass on the seeded repo, so under per-test scoring they only cap
GATES = ("existing", "contract_unchanged")
TEST_FILE = re.compile(r"\.(test|spec)\.[cm]?[jt]sx?$")
OWN_TESTS = {"file": "own tests", "group": "own tests", "name": "your own tests run and pass"}
HIDDEN_DIR = "crucible_hidden"
REGRESSION_TEST = {"file": "regression", "group": "regression",
                   "name": "your new tests fail on the seeded code and pass on your fix"}
TEST_NAME = re.compile(r"""^\s*it\(\s*(["'`])(.+?)\1""", re.M)
# How long the model's own tests may run on the seeded code (see _isolated_regression)
SEEDED_TIMEOUT = 120

GROUP_NAME = re.compile(r"""^\s*describe\(\s*(["'`])(.+?)\1""", re.M)


def _run_group(cmd: list[str], cwd: Path, timeout: int, env: dict | None = None) -> subprocess.CompletedProcess:
    """subprocess.run in its own process group, killed whole on timeout (raising TimeoutExpired), so the
    workers a test runner spawns (vitest's, pytest-xdist's) never outlive it."""
    with subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          start_new_session=True) as proc:
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            proc.wait()
            raise
        finally:
            # Workers left behind by a runner that exited on its own
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def _run(cmd: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess:
    try:
        return _run_group(cmd, cwd, timeout)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return subprocess.CompletedProcess(cmd, 124, stdout, stderr + "\n[timed out]")


def _ensure_deps(workspace: Path) -> str | None:
    """Install the monorepo's dependencies when the agent never did; returns an error or None."""
    if (workspace / "node_modules").exists():
        return None
    result = _run(["npm", "install", "--no-audit", "--no-fund", "--loglevel=error"], workspace, 600)
    return None if result.returncode == 0 else f"npm install failed: {result.stderr.strip()[-300:]}"


def _vitest(app_dir: Path, args: list[str], timeout: int = 300) -> tuple[list[dict], str | None]:
    """[{file, group, name, passed, error}] from a vitest JSON report, or an error string."""
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.json"
        result = _run(["npx", "vitest", "run", *args, "--reporter=json", f"--outputFile={report}"], app_dir, timeout)
        if not report.exists():
            return [], (result.stderr or result.stdout).strip()[-400:] or f"vitest exited {result.returncode}"
        data = json.loads(report.read_text(encoding="utf-8"))
    tests, load_errors = [], []
    for suite in data.get("testResults", []):
        if not suite.get("assertionResults") and suite.get("status") == "failed":
            load_errors.append(f"{Path(suite.get('name', '')).name}: {(suite.get('message') or '').strip()[:300]}")
        for a in suite.get("assertionResults", []):
            tests.append({"file": Path(suite.get("name", "")).name, "group": " > ".join(a.get("ancestorTitles") or []),
                          "name": a.get("title"), "passed": a.get("status") == "passed",
                          "error": None if a.get("status") == "passed" else "; ".join(a.get("failureMessages") or [])[:300]})
    return tests, ("; ".join(load_errors) or None)


def _expected_tests(path: Path) -> list[dict]:
    """The tests a grader file declares, so a file that can't even load still counts as all failed."""
    text = path.read_text(encoding="utf-8")
    groups = [(m.start(), m.group(2)) for m in GROUP_NAME.finditer(text)]
    found = []
    for m in TEST_NAME.finditer(text):
        group = next((g for pos, g in reversed(groups) if pos < m.start()), "")
        found.append({"file": path.name, "group": group, "name": m.group(2), "passed": False, "error": None})
    return found


def _app_for(grader_file: Path) -> str:
    return "web" if ".web." in grader_file.name else "api"


def _seed_commit(workspace: Path) -> str | None:
    out = _run(["git", "rev-list", "--max-parents=0", "HEAD"], workspace, 30)
    return out.stdout.split()[0] if out.returncode == 0 and out.stdout.strip() else None


def _hidden_tests(workspace: Path, files: list[Path]) -> tuple[list[dict], list[str]]:
    tests, errors = [], []
    for app in ("api", "web"):
        mine = [f for f in files if _app_for(f) == app]
        if not mine:
            continue
        app_dir = workspace / "apps" / app
        hidden = app_dir / "test" / "hidden"
        hidden.mkdir(parents=True, exist_ok=True)
        try:
            for f in mine:
                shutil.copy2(f, hidden / f.name)
            found, error = _vitest(app_dir, ["test/hidden"])
        finally:
            shutil.rmtree(hidden, ignore_errors=True)
        ran = {(t["file"], t["name"]) for t in found}
        for f in mine:  # a file that failed to load: every test it declares fails
            found += [t for t in _expected_tests(f) if (t["file"], t["name"]) not in ran
                      and not any(r[0] == f.name for r in ran)]
        if error:
            errors.append(f"{app}: {error}")
        tests += found
    return tests, errors


def _existing_suite(workspace: Path) -> dict:
    """The repo's own tests (whatever the model left in place), hidden tests excluded."""
    results = {}
    for app in ("api", "web"):
        app_dir = workspace / "apps" / app
        if not (app_dir / "package.json").exists():
            continue
        tests, error = _vitest(app_dir, ["--exclude", "test/hidden/**"])
        results[app] = {"passed": sum(t["passed"] for t in tests), "failed": sum(not t["passed"] for t in tests),
                        "error": error}
    ok = bool(results) and all(r["failed"] == 0 and not r["error"] and r["passed"] for r in results.values())
    return {"passed": ok, "apps": results}


def _contract_unchanged(workspace: Path, seed: str | None) -> bool | None:
    if not seed or not (workspace / CONTRACT).exists():
        return None
    return _run(["git", "diff", "--quiet", seed, "--", CONTRACT], workspace, 30).returncode == 0


def _regression(workspace: Path, seed: str | None) -> dict:
    """Test files the model added or changed must pass on its code, and at least one must fail on the seed."""
    if not seed:
        return {"passed": False, "detail": "no seeded commit to compare against"}
    diff = _run(["git", "diff", "--name-only", seed, "--", "apps"], workspace, 30).stdout.split()
    untracked = _run(["git", "ls-files", "--others", "--exclude-standard", "--", "apps"], workspace, 30).stdout.split()
    changed = sorted({p for p in diff + untracked if re.search(r"\.test\.tsx?$", p) and "/hidden/" not in p
                      and p != CONTRACT and (workspace / p).exists()})
    if not changed:
        return {"passed": False, "detail": "no new or changed test files"}
    by_app: dict[str, list[str]] = {}
    for p in changed:
        by_app.setdefault(p.split("/")[1], []).append(p)
    after_ok, before_failed = True, False
    with tempfile.TemporaryDirectory() as tmp:
        seeded = Path(tmp) / "seeded"
        _run(["git", "worktree", "add", "--detach", str(seeded), seed], workspace, 60)
        try:
            for nm in workspace.glob("**/node_modules"):
                if "node_modules" in nm.relative_to(workspace).parts[:-1]:
                    continue
                target = seeded / nm.relative_to(workspace)
                if target.parent.exists() and not target.exists():
                    target.symlink_to(nm.resolve())
            for app, paths in by_app.items():
                rel = [str(Path(p).relative_to(f"apps/{app}")) for p in paths]
                after, _ = _vitest(workspace / "apps" / app, rel)
                after_ok &= bool(after) and all(t["passed"] for t in after)
                for p in paths:
                    (seeded / p).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(workspace / p, seeded / p)
                before, error = _vitest(seeded / "apps" / app, rel)
                before_failed |= bool(error) or any(not t["passed"] for t in before)
        finally:
            _run(["git", "worktree", "remove", "--force", str(seeded)], workspace, 60)
    return {"passed": after_ok and before_failed, "files": changed,
            "detail": ("pass on the fix and catch the bug on the seeded code" if after_ok and before_failed
                       else "don't pass on the fix" if not after_ok else "pass on the seeded code too, so they don't catch the bug")}


def grader_config(grader: str) -> dict:
    path = GRADERS_DIR / grader / CONFIG_FILENAME
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}


def cache_root() -> Path:
    return Path(os.environ.get("CRUCIBLE_CACHE") or Path.home() / ".crucible" / "cache")


def _manifests(repo: Path) -> list[str]:
    """package.json and, for an npm workspaces monorepo, every workspace's package.json."""
    root = json.loads((repo / "package.json").read_text(encoding="utf-8"))
    found = ["package.json"]
    for pattern in root.get("workspaces") or []:
        found += sorted(p.relative_to(repo).as_posix() for p in repo.glob(f"{pattern}/package.json"))
    return found


def _cached_node_modules(repo: Path, lockfile: Path | None = None) -> tuple[Path | None, str | None]:
    """node_modules installed with `npm ci` from the seeded lockfile (or the grader's `lockfile`),
    shared by every grading of it."""
    lock = lockfile or repo / "package-lock.json"
    if not lock.exists():
        return None, f"{repo.name} has no package-lock.json to install from"
    manifests = _manifests(repo)
    key = hashlib.sha256(b"".join((repo / m).read_bytes() for m in manifests) + lock.read_bytes()).hexdigest()[:16]
    target = cache_root() / "node_modules" / f"{repo.name}-{key}"
    if (target / "node_modules").is_dir():
        return target / "node_modules", None
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=target.parent))
    try:
        for name in manifests:
            (staging / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(repo / name, staging / name)
        shutil.copy2(lock, staging / "package-lock.json")
        result = _run(["npm", "ci", "--no-audit", "--no-fund", "--loglevel=error"], staging, 600)
        if result.returncode != 0:
            return None, f"npm ci failed: {result.stderr.strip()[-300:]}"
        try:
            staging.rename(target)
        except OSError:  # another grading finished the same install first
            pass
        return target / "node_modules", None
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _grading_copy(repo: Path, workspace: Path, artifacts: list[str], dest: Path) -> list[str]:
    """The seeded repo with the model's artifacts in place of the seeded ones; returns the artifacts taken."""
    ignore = shutil.ignore_patterns(*NOT_SOURCE)
    shutil.copytree(repo, dest, ignore=ignore)
    taken = []
    for rel in artifacts:
        src, target = workspace / rel, dest / rel
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        if src.is_dir():
            shutil.copytree(src, target, ignore=ignore, symlinks=True)
        elif src.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
        else:
            continue
        taken.append(rel)
    return taken


def _link_node_modules(modules: Path, copy: Path) -> None:
    """Point the grading copy at the cached install. A workspaces install links its own packages
    (node_modules/@scope/pkg -> ../../packages/pkg); those links are recreated in the copy so they
    resolve to the copy's sources, the model's artifacts, never to the cache's bare manifests."""
    links = [p for p in modules.glob("*") if p.is_symlink()] + [p for p in modules.glob("@*/*") if p.is_symlink()]
    if not links:
        (copy / "node_modules").symlink_to(modules, target_is_directory=True)
    else:
        (copy / "node_modules").mkdir()
        for entry in modules.iterdir():
            target = copy / "node_modules" / entry.name
            if entry.is_symlink():
                target.symlink_to(os.readlink(entry))
            elif entry.name.startswith("@") and any(p.is_symlink() for p in entry.iterdir()):
                target.mkdir()
                for pkg in entry.iterdir():
                    (target / pkg.name).symlink_to(os.readlink(pkg) if pkg.is_symlink() else pkg)
            else:
                target.symlink_to(entry, target_is_directory=entry.is_dir())
    # A workspace whose dependencies didn't hoist has its own node_modules in the install
    for nested in modules.parent.glob("*/*/node_modules"):
        rel = nested.relative_to(modules.parent)
        if (copy / rel.parent).is_dir() and not (copy / rel).exists():
            (copy / rel).symlink_to(nested, target_is_directory=True)


def _test_root(cfg: dict, name: str) -> str:
    """Where a hidden test file runs: its folder's test/hidden, with vitest started in that folder."""
    for pattern, root in (cfg.get("test_roots") or {}).items():
        if fnmatch.fnmatch(name, pattern):
            return root
    return "."


def _unchanged(repo: Path, workspace: Path, paths: list[str]) -> bool:
    """Every listed file is in the workspace exactly as seeded (CRLF aside)."""
    def read(p: Path) -> bytes | None:
        return p.read_bytes().replace(b"\r\n", b"\n") if p.is_file() else None
    return all(read(workspace / rel) == read(repo / rel) for rel in paths)


def _changed_files(repo: Path, workspace: Path, roots: list[str], skip: set[str]) -> list[str]:
    """Files under the roots that the model added or changed (hidden tests and installs aside)."""
    found = []
    for root in roots:
        for path in sorted((workspace / root).rglob("*")) if (workspace / root).is_dir() else []:
            rel = path.relative_to(workspace)
            if not path.is_file() or set(rel.parts) & {*NOT_SOURCE, "hidden"} or rel.as_posix() in skip:
                continue
            seeded = repo / rel
            if not seeded.is_file() or seeded.read_bytes() != path.read_bytes():
                found.append(rel.as_posix())
    return found


def _within(path: str, root: str) -> bool:
    """path is root or under it; a root of "." is the whole repo."""
    root = root.rstrip("/")
    return root in ("", ".") or path == root or path.startswith(root + "/")


def _isolated_regression(repo: Path, workspace: Path, copy: Path, modules: Path, cfg: dict) -> dict:
    """The model's new or changed tests, with any helpers it changed: they must pass in the grading copy
    (its fix) and at least one must fail in a copy with the seeded source."""
    artifacts = cfg.get("artifacts") or []
    changed = _changed_files(repo, workspace, cfg["regression_tests"], set(cfg.get("unchanged") or []))
    tests = [p for p in changed if TEST_FILE.search(p)]
    if not tests:
        return {"passed": False, "files": [], "detail": "no new or changed test files"}
    support = [p for p in changed if not any(_within(p, a) for a in artifacts)]
    seeded = copy.parent / "seeded"
    _grading_copy(repo, workspace, [], seeded)
    _link_node_modules(modules, seeded)
    for rel in sorted(set(support + tests)):
        for dest in ((copy, seeded) if rel in support else (seeded,)):
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(workspace / rel, dest / rel)
    after_ok, before_failed = True, False
    for root in cfg["regression_tests"]:
        mine = [Path(p).relative_to(root).as_posix() for p in tests if _within(p, root)]
        if not mine:
            continue
        after, error = _vitest(copy / root, mine, timeout=cfg.get("timeout", 600))
        after_ok &= bool(after) and not error and all(t["passed"] for t in after)
        # The seeded code is buggy, and a test that reproduces a hang or a render loop never finishes there:
        # a short timeout counts that as catching the bug instead of holding the run for the full one
        before, error = _vitest(seeded / root, mine, timeout=min(SEEDED_TIMEOUT, cfg.get("timeout", 600)))
        before_failed |= bool(error) or any(not t["passed"] for t in before)
    return {"passed": after_ok and before_failed, "files": tests,
            "detail": ("pass on the fix and catch the bug on the seeded code" if after_ok and before_failed
                       else "don't pass on the fix" if not after_ok else "pass on the seeded code too, so they don't catch the bug")}


def expected_tests(grader: str) -> list[dict] | None:
    """Every test the grader declares, as recorded in expected.json; None before it's recorded."""
    path = GRADERS_DIR / grader / EXPECTED_FILENAME
    if not path.exists():
        return None
    return [{**t, "passed": False, "error": None} for t in json.loads(path.read_text(encoding="utf-8"))]


def run_isolated(workspace: Path, prompt_def: dict) -> dict:
    """Hidden tests on the model's artifacts in a fresh copy of the seeded repo (see the module docstring)."""
    grader = prompt_def["grader"]
    cfg = grader_config(grader)
    files = sorted((GRADERS_DIR / grader).glob("*.grader.test.ts*"))
    expected = expected_tests(grader)
    record: dict = {"grader": grader, "isolated": True, "ran_at": datetime.now(timezone.utc).isoformat()}
    repo = REPOS_DIR / prompt_def["repo"]
    if cfg.get("unchanged"):
        record["contract_unchanged"] = _unchanged(repo, workspace, cfg["unchanged"])
    lockfile = GRADERS_DIR / grader / cfg["lockfile"] if cfg.get("lockfile") else None
    modules, error = _cached_node_modules(repo, lockfile)
    if error:
        return {**record, "error": error, "tests": expected or [t for f in files for t in _expected_tests(f)],
                **({"existing": {"passed": False}} if cfg.get("existing_tests") else {})}
    tests, errors = [], []
    with tempfile.TemporaryDirectory(prefix="crucible-grade-") as tmp:
        copy = Path(tmp) / repo.name
        record["artifacts"] = _grading_copy(repo, workspace, cfg.get("artifacts") or [], copy)
        _link_node_modules(modules, copy)
        if cfg.get("existing_tests"):  # the seeded tests, before any hidden test is in place
            apps = {}
            for root in cfg["existing_tests"]:
                found, error = _vitest(copy / root, [], timeout=cfg.get("timeout", 600))
                apps[root] = {"passed": sum(t["passed"] for t in found), "failed": sum(not t["passed"] for t in found),
                              "error": error}
            record["existing"] = {"passed": all(a["passed"] and not a["failed"] and not a["error"] for a in apps.values()),
                                  "apps": apps}
        by_root: dict[str, list[Path]] = {}
        for f in files:
            by_root.setdefault(_test_root(cfg, f.name), []).append(f)
        for root, mine in by_root.items():
            hidden = copy / root / "test" / "hidden"
            hidden.mkdir(parents=True, exist_ok=True)
            for f in mine:
                shutil.copy2(f, hidden / f.name)
            found, error = _vitest(copy / root, ["test/hidden"], timeout=cfg.get("timeout", 600))
            tests += found
            if error:
                errors.append(error if root == "." else f"{root}: {error}")
        if cfg.get("regression_tests"):  # last: the model's changed test helpers go into the copy
            record["regression"] = _isolated_regression(repo, workspace, copy, modules, cfg)
            tests.append({**REGRESSION_TEST, "passed": record["regression"]["passed"],
                          "error": None if record["regression"]["passed"] else record["regression"]["detail"]})
    # A test that never ran (its file didn't load, or vitest died) counts as failed. Before expected.json
    # is recorded, only a file that reported nothing falls back to the tests it spells out.
    ran = {(t["file"], t["group"], t["name"]) for t in tests}
    if expected is None:
        reported = {t["file"] for t in tests}
        expected = [t for f in files if f.name not in reported for t in _expected_tests(f)]
    tests += [t for t in expected if (t["file"], t["group"], t["name"]) not in ran]
    known = {(t["file"], t["group"], t["name"]) for t in expected}
    # A test name that changes between runs would count twice; the oracle refuses it
    unexpected = [t["name"] for t in tests if known and (t["file"], t["group"], t["name"]) not in known]
    return {**record, "tests": tests, "errors": errors, "unexpected": unexpected}


# --------------------------------------------------------------------------
# Python graders (`runner: pytest`)
# --------------------------------------------------------------------------

def _python_with_pytest() -> list[str]:
    """A command prefix for a Python that has pytest: this one, else an ephemeral `uv run --with pytest`."""
    probe = subprocess.run([sys.executable, "-c", "import pytest"], capture_output=True)
    if probe.returncode == 0:
        return [sys.executable]
    return ["uv", "run", "--no-project", "--quiet", "--with", "pytest>=7", "python"]


def _pytest_hidden(copy: Path, files: list[Path], timeout: int) -> tuple[list[dict], list[str]]:
    """Run the grader's pytest files in the grading copy: [{file, group, name, passed, error}] and errors."""
    hidden = copy / HIDDEN_DIR
    hidden.mkdir(parents=True, exist_ok=True)
    for f in files:
        shutil.copy2(f, hidden / f.name)
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.json"
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).parent), "PYTHONDONTWRITEBYTECODE": "1"}
        cmd = [*_python_with_pytest(), "-m", "pytest", HIDDEN_DIR, "-p", "pytest_report", "-p", "no:cacheprovider",
               "-o", "addopts=", "-q", f"--crucible-report={report}"]
        try:
            result = _run_group(cmd, copy, timeout, env)
        except subprocess.TimeoutExpired:
            return [], ["pytest timed out"]
        except FileNotFoundError as exc:
            return [], [f"pytest could not start: {exc}"]
        if not report.exists():
            return [], [(result.stderr or result.stdout).strip()[-400:] or f"pytest exited {result.returncode}"]
        data = json.loads(report.read_text(encoding="utf-8"))
    return data["tests"], data["errors"]


def _own_tests(copy: Path, folder: str, timeout: int) -> dict:
    """The model's own tests in `folder` of the grading copy: pytest, else unittest; at least one must run."""
    if not (copy / folder).is_dir():
        return {"passed": False, "detail": f"no {folder}/ folder with tests"}
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    attempts = [([*_python_with_pytest(), "-m", "pytest", folder, "-q", "-p", "no:cacheprovider"], (5,)),
                ([sys.executable, "-m", "unittest", "discover", "-s", folder], ())]
    detail = ""
    for cmd, none_found in attempts:
        try:
            result = _run_group(cmd, copy, timeout, env)
        except subprocess.TimeoutExpired:
            return {"passed": False, "detail": "your tests timed out"}
        except FileNotFoundError as exc:
            return {"passed": False, "detail": f"could not start the tests: {exc}"}
        tail = (result.stdout + result.stderr).strip().splitlines()[-1:] or [""]
        if result.returncode == 0 and "Ran 0 tests" not in result.stderr:
            return {"passed": True, "detail": f"your tests pass ({tail[0][:120]})"}
        if result.returncode not in none_found and "Ran 0 tests" not in result.stderr:
            return {"passed": False, "detail": f"your tests fail ({tail[0][:120]})"}
        detail = "no tests found"
    return {"passed": False, "detail": detail}


def run_isolated_pytest(workspace: Path, prompt_def: dict, cfg: dict) -> dict:
    """Hidden pytest tests on the model's artifacts in a fresh copy of the seeded repo (empty for `repo: null`)."""
    grader = prompt_def["grader"]
    files = sorted((GRADERS_DIR / grader).glob("*.py"))
    expected = expected_tests(grader)
    record: dict = {"grader": grader, "isolated": True, "runner": "pytest", "ran_at": datetime.now(timezone.utc).isoformat()}
    timeout = cfg.get("timeout", 600)
    tests, errors = [], []
    with tempfile.TemporaryDirectory(prefix="crucible-grade-") as tmp:
        if prompt_def.get("repo"):
            seed = REPOS_DIR / prompt_def["repo"]
        else:
            seed = Path(tmp) / "seed"
            seed.mkdir()
        copy = Path(tmp) / "grade"
        record["artifacts"] = _grading_copy(seed, workspace, cfg.get("artifacts") or [], copy)
        if cfg.get("own_tests"):  # before the hidden tests go in
            record["own_tests"] = _own_tests(copy, cfg["own_tests"], timeout)
        tests, errors = _pytest_hidden(copy, files, timeout)
        if cfg.get("own_tests"):
            tests.append({**OWN_TESTS, "passed": record["own_tests"]["passed"],
                          "error": None if record["own_tests"]["passed"] else record["own_tests"]["detail"]})
    # A test that never ran (a file that failed to load, pytest dying) counts as failed
    ran = {(t["file"], t["group"], t["name"]) for t in tests}
    tests += [t for t in expected or [] if (t["file"], t["group"], t["name"]) not in ran]
    known = {(t["file"], t["group"], t["name"]) for t in expected or []}
    unexpected = [t["name"] for t in tests if known and (t["file"], t["group"], t["name"]) not in known]
    return {**record, "tests": tests, "errors": errors, "unexpected": unexpected}


def run(run_dir: Path, prompt_def: dict) -> dict | None:
    """Run the hidden tests for a finished run and save grader_results.json; None for tests without a grader."""
    grader = prompt_def.get("grader")
    workspace = run_dir / "workspace"
    if not grader or not workspace.is_dir():
        return None
    if grader_config(grader).get("isolated"):
        cfg = grader_config(grader)
        record = (run_isolated_pytest(workspace, prompt_def, cfg) if cfg.get("runner") == "pytest"
                  else run_isolated(workspace, prompt_def))
        (run_dir / RESULTS_FILENAME).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        return record
    files = sorted((GRADERS_DIR / grader).glob("*.grader.test.ts*"))
    record: dict = {"grader": grader, "ran_at": datetime.now(timezone.utc).isoformat()}
    deps_error = _ensure_deps(workspace)
    if deps_error:
        record.update(error=deps_error, tests=[t for f in files for t in _expected_tests(f)],
                      existing={"passed": False}, contract_unchanged=None, regression={"passed": False})
    else:
        seed = _seed_commit(workspace)
        tests, errors = _hidden_tests(workspace, files)
        record.update(tests=tests, errors=errors, existing=_existing_suite(workspace),
                      contract_unchanged=_contract_unchanged(workspace, seed), regression=_regression(workspace, seed))
    (run_dir / RESULTS_FILENAME).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def selected_tests(selector: str, tests: list[dict]) -> list[dict]:
    """The hidden tests a `hidden_tests` selector picks: a grader file name or a describe-group prefix."""
    return [t for t in tests if t["file"] == selector or t["group"].lower().startswith(selector.lower())]


def per_test_cap(prompt_def: dict, record: dict | None) -> float | None:
    """Under per-test scoring, the lowest `cap_if_failed` among the criteria that didn't fully pass.

    Gates (`existing`, `contract_unchanged`) earn no points; they only cap. Any other criterion with
    `cap_if_failed` keeps its tests' points and also caps the score when any one of its tests fails:
    a core requirement half met (cursors that repeat under concurrent writes) can't score near 10."""
    caps = [item["cap_if_failed"] for item in prompt_def.get("rubric", [])
            if item.get("hidden_tests") and "cap_if_failed" in item
            and criterion_result(item["hidden_tests"], record or {})[0] < 1]
    return min(caps) if caps else None


def criterion_result(selector: str, record: dict) -> tuple[float, str]:
    """(share 0..1, detail) for one rubric criterion's `hidden_tests` selector."""
    if selector == "existing":
        ok = bool((record.get("existing") or {}).get("passed"))
        return float(ok), "the repo's own tests pass" if ok else "the repo's own tests don't all pass"
    if selector == "contract_unchanged":
        ok = record.get("contract_unchanged") is not False
        return float(ok), "contract suite untouched" if ok else "the contract suite was modified"
    if selector == "regression":
        reg = record.get("regression") or {}
        return float(bool(reg.get("passed"))), reg.get("detail") or ""
    mine = selected_tests(selector, record.get("tests", []))
    if not mine:
        return 0.0, f"no hidden tests matched '{selector}'"
    passed = sum(t["passed"] for t in mine)
    return passed / len(mine), f"{passed}/{len(mine)} hidden tests pass"


# --------------------------------------------------------------------------
# Oracle: a grader is only trusted once it scores known code the way it should
# --------------------------------------------------------------------------

def _oracle_case(prompt_def: dict, overlay: Path | None, tmp: Path, name: str) -> dict:
    """Grade the seeded repo with an overlay (a solution or calibration fixture) laid over it, like a run."""
    from crucible import checks
    run_dir = tmp / name.replace("/", "_")
    workspace = run_dir / "workspace"
    if prompt_def.get("repo"):
        shutil.copytree(REPOS_DIR / prompt_def["repo"], workspace, ignore=shutil.ignore_patterns(*NOT_SOURCE))
    else:  # a task seeded empty
        workspace.mkdir(parents=True)
    if overlay:
        shutil.copytree(overlay, workspace, dirs_exist_ok=True)
    (run_dir / "meta.json").write_text(json.dumps({"record": "run", "run_uuid": None, "run_path": name,
                                                   "task": {"id": prompt_def["id"]}}), encoding="utf-8")
    record = run(run_dir, prompt_def)
    score = checks.save_check_score(run_dir, prompt_def, checks.check_results(run_dir, prompt_def), record)
    return {"record": record, "score": score["scores"]["_overall"] if score else None,
            "criteria": score["criteria"] if score else []}


def main() -> None:
    """`crucible grader TASK`: grade the seeded repo, the reference solution and each calibration fixture,
    and check each lands in the score range grader.yaml's `oracle` declares."""
    import argparse
    from crucible import workspace
    parser = argparse.ArgumentParser(prog="crucible grader", description=main.__doc__)
    parser.add_argument("task", help="The task, e.g. react-lead-form (an earlier ID like CODE-16 works too)")
    parser.add_argument("--write-expected", action="store_true",
                        help=f"Record every test the reference solution runs into {EXPECTED_FILENAME} (all must pass)")
    args = parser.parse_args()
    prompt_def = workspace.load_task(args.task)
    grader = prompt_def.get("grader")
    cfg = grader_config(grader) if grader else {}
    if not cfg.get("isolated"):
        raise SystemExit(f"{args.task} has no isolated grader (grader.yaml with isolated: true)")
    oracle = cfg.get("oracle") or {}
    root = GRADERS_DIR / grader
    cases = [("solution", root / "solution", oracle.get("solution", [10, 10])),
             ("seeded", None, oracle.get("seeded", [0, 0]))]
    cases += [(f"calibration/{n}", root / "calibration" / n, rng) for n, rng in (oracle.get("calibration") or {}).items()]
    if args.write_expected:  # re-recorded from the solution, never matched against the old list
        (root / EXPECTED_FILENAME).unlink(missing_ok=True)
    failed = False
    with tempfile.TemporaryDirectory(prefix="crucible-oracle-") as tmp:
        for name, overlay, (low, high) in cases:
            print(f"{name}: grading...", flush=True)
            result = _oracle_case(prompt_def, overlay, Path(tmp), name)
            tests = result["record"].get("tests", [])
            if name == "solution" and args.write_expected:
                if not tests or not all(t["passed"] for t in tests):
                    raise SystemExit("The reference solution doesn't pass every hidden test; not writing expected.json")
                (root / EXPECTED_FILENAME).write_text(json.dumps(
                    [{"file": t["file"], "group": t["group"], "name": t["name"]} for t in tests], indent=2) + "\n",
                    encoding="utf-8")
                print(f"  wrote {EXPECTED_FILENAME} ({len(tests)} tests)")
            unexpected = result["record"].get("unexpected") or []
            if unexpected:
                print(f"  tests missing from {EXPECTED_FILENAME} (names must be the same every run): {unexpected[:5]}")
            ok = result["score"] is not None and low <= result["score"] <= high and not unexpected
            failed |= not ok
            print(f"  {'ok  ' if ok else 'FAIL'} score {result['score']}/10 (want {low}-{high}), "
                  f"{sum(t['passed'] for t in tests)}/{len(tests)} tests pass")
            for c in result["criteria"]:
                print(f"       {c['criterion']}: {c['score']}/{c['max_score']} ({c['detail']})")
            for error in result["record"].get("errors") or []:
                print(f"       error: {error[:300]}")
    raise SystemExit(1 if failed else 0)
