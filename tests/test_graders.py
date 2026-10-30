"""Isolated graders and per-test scoring, without running npm (the oracle covers the real thing:
`crucible grader <test>` grades the seeded repo, the reference solution and calibration fixtures)."""
import json
import os
import sys
import time

import pytest

from crucible import checks, graders, workspace

PER_TEST = {"version": 1, "rubric_version": 1, "scoring": "per_test", "rubric": [
    {"criterion": "Typing", "hidden_tests": "level 2"},
    {"criterion": "Submit", "hidden_tests": "level 3"},
]}


def _tests(*rows):
    return [{"file": "form.grader.test.tsx", "group": g, "name": f"{g} {i}", "passed": p, "error": None}
            for i, (g, p) in enumerate(rows)]


def test_per_test_score_is_share_of_all_tests(tmp_path):
    (tmp_path / "meta.json").write_text(json.dumps({"run_id": "m/c/CODE-16/1", "test_id": "CODE-16"}))
    grader = {"tests": _tests(("level 2: typing", True), ("level 3: submit", True), ("level 3: submit", False),
                              ("level 3: submit", False))}
    record = checks.save_check_score(tmp_path, PER_TEST, [], grader)
    assert record["scores"]["_overall"] == 5.0                     # 2 of 4 tests, out of 10
    by_name = {c["criterion"]: c for c in record["criteria"]}
    assert by_name["Typing"]["max_score"] == 2.5 and by_name["Typing"]["score"] == 2.5
    assert by_name["Submit"]["max_score"] == 7.5 and by_name["Submit"]["score"] == 2.5
    assert record["passed"] is False


def test_per_test_without_results_scores_zero(tmp_path):
    (tmp_path / "meta.json").write_text(json.dumps({"run_id": "m/c/CODE-16/1", "test_id": "CODE-16"}))
    record = checks.save_check_score(tmp_path, PER_TEST, [], {"tests": [], "error": "npm ci failed"})
    assert record["scores"]["_overall"] == 0.0


def test_grading_copy_takes_only_artifacts(tmp_path):
    seeded, ws, dest = tmp_path / "seeded", tmp_path / "ws", tmp_path / "copy"
    for root, form, pkg in ((seeded, "broken", "seeded"), (ws, "fixed", "tampered")):
        (root / "app").mkdir(parents=True)
        (root / "app" / "Form.tsx").write_text(form)
        (root / "package.json").write_text(pkg)
        (root / "vitest.config.ts").write_text(pkg)
    (seeded / "app" / "Old.tsx").write_text("removed by the model")
    (ws / "lib").mkdir()
    (ws / "lib" / "email.ts").write_text("new")
    (ws / "app" / "node_modules").mkdir()
    taken = graders._grading_copy(seeded, ws, ["app", "lib", "missing"], dest)
    assert taken == ["app", "lib"]
    assert (dest / "app" / "Form.tsx").read_text() == "fixed"
    assert not (dest / "app" / "Old.tsx").exists()                 # the model's tree replaces the seeded one
    assert not (dest / "app" / "node_modules").exists()
    assert (dest / "lib" / "email.ts").read_text() == "new"
    assert (dest / "package.json").read_text() == "seeded"         # config stays as seeded
    assert (dest / "vitest.config.ts").read_text() == "seeded"


def test_tests_that_never_ran_count_as_failed(tmp_path, monkeypatch):
    prompt = workspace.load_task("CODE-16")
    expected = graders.expected_tests(prompt["grader"])
    modules = tmp_path / "node_modules"
    modules.mkdir()
    monkeypatch.setattr(graders, "_cached_node_modules", lambda repo, lockfile=None: (modules, None))
    # vitest reports only the first test; the rest of the file never ran (it failed to load, say)
    first = {**expected[0], "passed": True}
    monkeypatch.setattr(graders, "_vitest", lambda *a, **k: ([first], "form.grader.test.tsx: SyntaxError"))
    record = graders.run_isolated(tmp_path, prompt)
    assert len(record["tests"]) == len(expected)
    assert sum(t["passed"] for t in record["tests"]) == 1
    assert record["errors"]


CAPPED = {"version": 1, "rubric_version": 1, "scoring": "per_test", "rubric": [
    {"criterion": "Contract", "hidden_tests": "contract"},
    {"criterion": "Existing tests still pass", "hidden_tests": "existing", "cap_if_failed": 5},
    {"criterion": "Contract suite untouched", "hidden_tests": "contract_unchanged", "cap_if_failed": 4},
]}


@pytest.mark.parametrize("existing, unchanged, cap", [
    (True, True, None), (False, True, 5), (True, False, 4), (False, False, 4)])
def test_gates_cap_instead_of_paying(existing, unchanged, cap):
    record = {"tests": _tests(("contract", True)), "existing": {"passed": existing}, "contract_unchanged": unchanged}
    assert graders.per_test_cap(CAPPED, record) == cap


def test_per_test_score_is_capped_by_a_failed_gate(tmp_path):
    (tmp_path / "meta.json").write_text(json.dumps({"run_id": "m/c/CODE-11/1", "test_id": "CODE-11"}))
    grader = {"tests": _tests(("contract", True), ("contract", True)), "existing": {"passed": False},
              "contract_unchanged": True}
    record = checks.save_check_score(tmp_path, CAPPED, [], grader)
    assert record["scores"]["_overall"] == 5 and record["capped_at"] == 5     # 10 by tests, capped
    assert [c["criterion"] for c in record["criteria"]] == ["Contract"]       # gates earn no points
    grader["existing"]["passed"] = True
    assert checks.save_check_score(tmp_path, CAPPED, [], grader)["scores"]["_overall"] == 10.0


CORE_CAPPED = {**CAPPED, "rubric": [{"criterion": "Contract", "hidden_tests": "contract", "cap_if_failed": 6},
                                    {"criterion": "Extras", "hidden_tests": "extras"}, *CAPPED["rubric"][1:]]}


def test_a_test_criterion_caps_when_any_of_its_tests_fails(tmp_path):
    (tmp_path / "meta.json").write_text(json.dumps({"run_id": "m/c/CODE-12/1", "test_id": "CODE-12"}))
    tests = _tests(*[("contract", True)] * 3, ("contract", False), *[("extras", True)] * 6)
    grader = {"tests": tests, "existing": {"passed": True}, "contract_unchanged": True}
    record = checks.save_check_score(tmp_path, CORE_CAPPED, [], grader)
    assert record["scores"]["_overall"] == 6 and record["capped_at"] == 6     # 9 by tests, capped
    assert record["scores"]["Contract"] == 3.0                                # its tests still earn their points
    grader["tests"] = _tests(*[("contract", True)] * 4, ("extras", False), *[("extras", True)] * 5)
    record = checks.save_check_score(tmp_path, CORE_CAPPED, [], grader)
    assert record["scores"]["_overall"] == 9.0 and record["capped_at"] is None   # another criterion's miss: no cap
    grader["existing"]["passed"] = False
    assert graders.per_test_cap(CORE_CAPPED, grader) == 5                     # the lowest failed cap wins
    grader["tests"][0]["passed"] = False
    assert graders.per_test_cap(CORE_CAPPED, grader) == 5


def test_no_gate_results_means_no_unchanged_cap():
    # A grader that doesn't check the contract file can't fail that gate; a missing existing run does fail
    assert graders.per_test_cap(CAPPED, {"tests": []}) == 5


def test_unchanged_compares_with_the_seeded_file(tmp_path):
    seeded, ws = tmp_path / "seeded", tmp_path / "ws"
    for root in (seeded, ws):
        (root / "test").mkdir(parents=True)
    (seeded / "test" / "contract.test.ts").write_bytes(b"a\nb\n")
    (ws / "test" / "contract.test.ts").write_bytes(b"a\r\nb\r\n")
    assert graders._unchanged(seeded, ws, ["test/contract.test.ts"])
    (ws / "test" / "contract.test.ts").write_text("a\n")
    assert not graders._unchanged(seeded, ws, ["test/contract.test.ts"])
    (ws / "test" / "contract.test.ts").unlink()
    assert not graders._unchanged(seeded, ws, ["test/contract.test.ts"])   # deleting it is changing it


def test_hidden_tests_run_where_test_roots_say():
    cfg = {"test_roots": {"*.web.grader.test.tsx": "apps/web", "*.grader.test.ts": "apps/api"}}
    assert graders._test_root(cfg, "loop.web.grader.test.tsx") == "apps/web"
    assert graders._test_root(cfg, "invites.grader.test.ts") == "apps/api"
    assert graders._test_root({}, "form.grader.test.tsx") == "."


def test_manifests_cover_every_workspace(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"workspaces": ["packages/*", "apps/*"]}))
    for ws in ("packages/shared", "apps/api", "apps/web"):
        (tmp_path / ws).mkdir(parents=True)
        (tmp_path / ws / "package.json").write_text("{}")
    assert graders._manifests(tmp_path) == ["package.json", "packages/shared/package.json",
                                            "apps/api/package.json", "apps/web/package.json"]


def test_workspace_links_resolve_to_the_grading_copy(tmp_path):
    install, copy = tmp_path / "cache", tmp_path / "copy"
    (install / "node_modules" / "express").mkdir(parents=True)
    (install / "node_modules" / "@types" / "node").mkdir(parents=True)
    (install / "node_modules" / "@conduit").mkdir()
    (install / "node_modules" / "@conduit" / "shared").symlink_to("../../packages/shared")
    (install / "packages" / "shared").mkdir(parents=True)                     # the install's bare manifest
    (install / "apps" / "web" / "node_modules" / "vite").mkdir(parents=True)  # didn't hoist
    (copy / "packages" / "shared" / "src").mkdir(parents=True)
    (copy / "packages" / "shared" / "src" / "index.ts").write_text("the model's")
    (copy / "apps" / "web").mkdir(parents=True)
    graders._link_node_modules(install / "node_modules", copy)
    assert (copy / "node_modules" / "@conduit" / "shared" / "src" / "index.ts").read_text() == "the model's"
    assert (copy / "node_modules" / "express").resolve() == (install / "node_modules" / "express").resolve()
    assert (copy / "node_modules" / "@types").resolve() == (install / "node_modules" / "@types").resolve()
    assert (copy / "apps" / "web" / "node_modules" / "vite").is_dir()


def test_plain_installs_link_the_whole_folder(tmp_path):
    (tmp_path / "cache" / "node_modules" / "next").mkdir(parents=True)
    (tmp_path / "copy").mkdir()
    graders._link_node_modules(tmp_path / "cache" / "node_modules", tmp_path / "copy")
    assert (tmp_path / "copy" / "node_modules").is_symlink()


def test_changed_files_are_new_or_edited_tests_and_helpers(tmp_path):
    repo, ws = tmp_path / "repo", tmp_path / "ws"
    for root in (repo, ws):
        (root / "apps" / "api" / "test").mkdir(parents=True)
        (root / "apps" / "api" / "test" / "contract.test.ts").write_text("seeded")
        (root / "apps" / "api" / "test" / "helpers.ts").write_text("seeded")
    (ws / "apps" / "api" / "test" / "helpers.ts").write_text("changed")
    (ws / "apps" / "api" / "test" / "review.test.ts").write_text("new")
    (ws / "apps" / "api" / "test" / "hidden").mkdir()
    (ws / "apps" / "api" / "test" / "hidden" / "x.grader.test.ts").write_text("left over")
    (ws / "apps" / "api" / "node_modules").mkdir()
    (ws / "apps" / "api" / "node_modules" / "a.test.ts").write_text("installed")
    (ws / "apps" / "api" / "test" / "contract.test.ts").write_text("edited")
    assert graders._changed_files(repo, ws, ["apps/api", "apps/web"], {"apps/api/test/contract.test.ts"}) == [
        "apps/api/test/helpers.ts", "apps/api/test/review.test.ts"]


@pytest.mark.parametrize("after, before, passed", [
    (True, False, True),     # passes on the fix, catches the bug on the seeded code
    (True, True, False),     # passes on the seeded code too
    (False, False, False)])  # fails on the fix
def test_isolated_regression(tmp_path, monkeypatch, after, before, passed):
    repo, ws, copy = tmp_path / "repo", tmp_path / "ws", tmp_path / "grade" / "copy"
    for root in (repo, ws, copy):
        (root / "apps" / "api" / "src").mkdir(parents=True)
        (root / "apps" / "api" / "src" / "app.ts").write_text("seeded")
    (ws / "apps" / "api" / "src" / "app.ts").write_text("fixed")
    (ws / "apps" / "api" / "test").mkdir()
    (ws / "apps" / "api" / "test" / "review.test.ts").write_text("new")
    monkeypatch.setattr(graders, "_link_node_modules", lambda modules, dest: None)
    ran = []

    def vitest(app_dir, args, timeout=300):
        fixed = (app_dir / "src" / "app.ts").read_text() == "fixed"
        assert (app_dir / "test" / "review.test.ts").read_text() == "new"   # both copies get the model's test
        ran.append(fixed)
        return [{"passed": after if fixed else before}], None
    monkeypatch.setattr(graders, "_vitest", vitest)
    cfg = {"artifacts": ["apps/api/src"], "regression_tests": ["apps/api"]}
    (copy / "apps" / "api" / "src" / "app.ts").write_text("fixed")         # the grading copy holds the fix
    result = graders._isolated_regression(repo, ws, copy, tmp_path, cfg)
    assert result["passed"] is passed and result["files"] == ["apps/api/test/review.test.ts"]
    assert ran == [True, False]


def test_no_new_tests_fails_regression(tmp_path):
    (tmp_path / "repo").mkdir(), (tmp_path / "ws").mkdir()
    result = graders._isolated_regression(tmp_path / "repo", tmp_path / "ws", tmp_path / "copy", tmp_path,
                                          {"regression_tests": ["apps/api"]})
    assert result == {"passed": False, "files": [], "detail": "no new or changed test files"}


ISOLATED = [t for t in workspace.all_task_ids()
            if (p := workspace.load_task(t)).get("grader") and graders.grader_config(p["grader"]).get("isolated")]


@pytest.mark.parametrize("test_id", ISOLATED)
def test_isolated_graders_are_complete(test_id):
    prompt = workspace.load_task(test_id)
    root = graders.GRADERS_DIR / prompt["grader"]
    cfg = graders.grader_config(prompt["grader"])
    assert (root / "solution").is_dir(), "an isolated grader needs a reference solution"
    assert (root / graders.EXPECTED_FILENAME).exists(), "run crucible grader --write-expected"
    assert cfg.get("artifacts"), "list the paths taken from the workspace"
    if cfg.get("runner") != "pytest":
        lock = root / cfg["lockfile"] if cfg.get("lockfile") else workspace.REPOS_DIR / prompt["repo"] / "package-lock.json"
        assert lock.exists(), "pin dependencies with a lockfile"
    for name in (cfg.get("oracle") or {}).get("calibration") or {}:
        assert (root / "calibration" / name).is_dir()
    # Every expected test is picked by exactly one criterion, so the levels add up to the whole score
    for t in graders.expected_tests(prompt["grader"]):
        picked = [c["criterion"] for c in prompt["rubric"] if t in graders.selected_tests(c["hidden_tests"], [t])]
        assert len(picked) == 1, f"{t['group']} > {t['name']}: picked by {picked}"


def test_per_test_rubrics_are_all_hidden_tests():
    for test_id in workspace.all_task_ids():
        prompt = workspace.load_task(test_id)
        if checks.per_test(prompt):
            assert all(item.get("hidden_tests") and not item.get("check") for item in prompt["rubric"]), test_id


# --- runner: pytest (Python graders) ---------------------------------------------------------------

PY_PROMPT = {"id": "py-task", "grader": "py-task", "repo": None}
PY_CFG = {"isolated": True, "runner": "pytest", "artifacts": ["pkg", "tests"], "own_tests": "tests", "timeout": 120}


def _py_grader(tmp_path, monkeypatch):
    root = tmp_path / "graders"
    (root / "py-task").mkdir(parents=True)
    (root / "py-task" / "support.py").write_text("import sys\nPY = sys.executable\n")
    (root / "py-task" / "test_hidden.py").write_text(
        "import subprocess, pathlib\nfrom support import PY\n\n\nclass TestAdds:\n    \"\"\"math: adds\"\"\"\n\n"
        "    def test_two_plus_two(self):\n        root = pathlib.Path(__file__).resolve().parent.parent\n"
        "        out = subprocess.run([PY, '-c', 'import pkg; print(pkg.add(2, 2))'], cwd=root, capture_output=True, text=True)\n"
        "        assert out.stdout.strip() == '4'\n\n\ndef test_loose():\n    assert True\n")
    monkeypatch.setattr(graders, "GRADERS_DIR", root)
    monkeypatch.setattr(graders, "grader_config", lambda g: PY_CFG)


def _workspace(tmp_path, add="a + b", own_test="def test_ok():\n    assert True\n"):
    ws = tmp_path / "ws"
    (ws / "pkg").mkdir(parents=True)
    (ws / "pkg" / "__init__.py").write_text(f"def add(a, b):\n    return {add}\n")
    if own_test is not None:
        (ws / "tests").mkdir()
        (ws / "tests" / "test_own.py").write_text(own_test)
    return ws


def test_pytest_runner_groups_by_class_docstring(tmp_path, monkeypatch):
    _py_grader(tmp_path, monkeypatch)
    record = graders.run_isolated_pytest(_workspace(tmp_path), PY_PROMPT, PY_CFG)
    got = {(t["group"], t["name"]): t["passed"] for t in record["tests"]}
    assert got == {("math: adds", "test_two_plus_two"): True, ("hidden", "test_loose"): True,
                   ("own tests", "your own tests run and pass"): True}
    assert record["artifacts"] == ["pkg", "tests"] and not record["errors"]


def test_pytest_runner_fails_wrong_code_and_missing_tests(tmp_path, monkeypatch):
    _py_grader(tmp_path, monkeypatch)
    record = graders.run_isolated_pytest(_workspace(tmp_path, add="a - b", own_test="def test_bad():\n    assert False\n"),
                                         PY_PROMPT, PY_CFG)
    got = {t["name"]: t["passed"] for t in record["tests"]}
    assert got["test_two_plus_two"] is False and got["test_loose"] is True and got["your own tests run and pass"] is False
    empty = graders.run_isolated_pytest(tmp_path / "nothing", PY_PROMPT, PY_CFG)  # an empty workspace, seeded empty
    assert not any(t["passed"] for t in empty["tests"] if t["name"] != "test_loose")
    assert "no tests/" in empty["own_tests"]["detail"]


def test_own_tests_accept_unittest_and_need_at_least_one(tmp_path):
    ws = _workspace(tmp_path, own_test="import unittest\n\n\nclass T(unittest.TestCase):\n    def test_x(self):\n"
                                       "        self.assertTrue(True)\n")
    # a unittest file named like pytest's pattern is found by pytest; one that isn't is found by the unittest fallback
    (ws / "tests" / "test_own.py").rename(ws / "tests" / "tests_own.py")
    assert graders._own_tests(ws, "tests", 60)["passed"]
    (ws / "tests" / "tests_own.py").write_text("x = 1\n")
    assert graders._own_tests(ws, "tests", 60) == {"passed": False, "detail": "no tests found"}


def test_oracle_seeds_a_repo_less_task_empty(tmp_path, monkeypatch):
    _py_grader(tmp_path, monkeypatch)
    monkeypatch.setattr(graders, "run", lambda run_dir, prompt: {"tests": []})
    from crucible import checks
    monkeypatch.setattr(checks, "save_check_score", lambda *a: None)
    monkeypatch.setattr(checks, "check_results", lambda *a: [])
    graders._oracle_case(PY_PROMPT, None, tmp_path, "seeded")
    assert list((tmp_path / "seeded" / "workspace").iterdir()) == []


def test_a_timeout_kills_the_runners_workers(tmp_path):
    # A runner that spawns a worker and hangs, like vitest on a render loop: the worker must not outlive it
    pidfile = tmp_path / "worker.pid"
    script = (f"import subprocess, sys, time\n"
              f"w = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
              f"open({str(pidfile)!r}, 'w').write(str(w.pid))\ntime.sleep(60)\n")
    result = graders._run([sys.executable, "-c", script], tmp_path, 2)
    assert result.returncode == 124 and "[timed out]" in result.stderr
    worker = int(pidfile.read_text())
    for _ in range(50):
        try:
            os.kill(worker, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("the worker outlived the timeout")


def test_regression_run_on_seeded_code_gets_a_short_timeout(tmp_path, monkeypatch):
    repo, ws, copy = tmp_path / "repo", tmp_path / "ws", tmp_path / "grade" / "copy"
    for root in (repo, ws, copy):
        (root / "apps" / "web" / "src").mkdir(parents=True)
        (root / "apps" / "web" / "src" / "app.ts").write_text("seeded")
    (ws / "apps" / "web" / "test").mkdir()
    (ws / "apps" / "web" / "test" / "loop.test.tsx").write_text("new")
    monkeypatch.setattr(graders, "_link_node_modules", lambda modules, dest: None)
    timeouts = []

    def vitest(app_dir, args, timeout=300):
        timeouts.append(timeout)
        # On the seeded code the test hangs, so vitest writes no report
        return ([{"passed": True}], None) if len(timeouts) == 1 else ([], "[timed out]")
    monkeypatch.setattr(graders, "_vitest", vitest)
    cfg = {"artifacts": ["apps/web/src"], "regression_tests": ["apps/web"], "timeout": 600}
    result = graders._isolated_regression(repo, ws, copy, tmp_path, cfg)
    assert timeouts == [600, graders.SEEDED_TIMEOUT] and result["passed"] is True
