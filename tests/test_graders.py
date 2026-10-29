"""Isolated graders and per-test scoring, without running npm (the oracle covers the real thing:
`crucible grader <test>` grades the seeded repo, the reference solution and calibration fixtures)."""
import json

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
