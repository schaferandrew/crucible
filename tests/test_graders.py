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
    prompt = workspace.load_prompt("CODE-16")
    expected = graders.expected_tests(prompt["grader"])
    modules = tmp_path / "node_modules"
    modules.mkdir()
    monkeypatch.setattr(graders, "_cached_node_modules", lambda repo: (modules, None))
    # vitest reports only the first test; the rest of the file never ran (it failed to load, say)
    first = {**expected[0], "passed": True}
    monkeypatch.setattr(graders, "_vitest", lambda *a, **k: ([first], "form.grader.test.tsx: SyntaxError"))
    record = graders.run_isolated(tmp_path, prompt)
    assert len(record["tests"]) == len(expected)
    assert sum(t["passed"] for t in record["tests"]) == 1
    assert record["errors"]


ISOLATED = [t for t in workspace.all_test_ids()
            if (p := workspace.load_prompt(t)).get("grader") and graders.grader_config(p["grader"]).get("isolated")]


@pytest.mark.parametrize("test_id", ISOLATED)
def test_isolated_graders_are_complete(test_id):
    prompt = workspace.load_prompt(test_id)
    root = graders.GRADERS_DIR / prompt["grader"]
    cfg = graders.grader_config(prompt["grader"])
    assert (root / "solution").is_dir(), "an isolated grader needs a reference solution"
    assert (root / graders.EXPECTED_FILENAME).exists(), "run crucible grader --write-expected"
    assert cfg.get("artifacts"), "list the paths taken from the workspace"
    assert (workspace.REPOS_DIR / prompt["repo"] / "package-lock.json").exists(), "pin dependencies with a lockfile"
    for name in (cfg.get("oracle") or {}).get("calibration") or {}:
        assert (root / "calibration" / name).is_dir()
    # Every expected test is picked by exactly one criterion, so the levels add up to the whole score
    for t in graders.expected_tests(prompt["grader"]):
        picked = [c["criterion"] for c in prompt["rubric"] if t in graders.selected_tests(c["hidden_tests"], [t])]
        assert len(picked) == 1, f"{t['group']} > {t['name']}: picked by {picked}"


def test_per_test_rubrics_are_all_hidden_tests():
    for test_id in workspace.all_test_ids():
        prompt = workspace.load_prompt(test_id)
        if checks.per_test(prompt):
            assert all(item.get("hidden_tests") and not item.get("check") for item in prompt["rubric"]), test_id
