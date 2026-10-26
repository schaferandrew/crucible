"""Programmatic checks: deterministic scoring of the final answer (WRIT-3's forbidden words)."""
import json

import pytest

from crucible import checks, judge, workspace


@pytest.fixture
def w3():
    return workspace.load_prompt("WRIT-3")


@pytest.mark.parametrize("text, passed", [
    ("Cold stones hum below\na heron folds into dusk\nthe current keeps time", True),
    ("A wavering heron", True),          # waver is not wave
    ("Between two stone hills", True),   # contains no 'wet' word
    ("Along the riverbank", False),
    ("Waterfall of light", False),
    ("Wavy reeds bend low", False),
    ("Wetland herons wait", False),
    ("Rippling silver flows", False),
    ("WAVES at dusk", False),            # case-insensitive
    ("", False),                         # no answer is not a pass
])
def test_forbidden_patterns(w3, text, passed):
    result = next(r for r in checks.run_checks(w3, text) if r["id"] == "no_forbidden_words")
    assert result["passed"] is passed


def test_line_count():
    prompt = {"checks": [{"id": "three", "type": "line_count", "lines": 3}]}
    assert checks.run_checks(prompt, "a\n\nb\nc\n")[0]["passed"]
    assert not checks.run_checks(prompt, "a\nb")[0]["passed"]


def test_final_answer_ignores_tool_output(tmp_path):
    """An agent that reads prompt.txt echoes the forbidden list; only its last reply is checked."""
    (tmp_path / "session.json").write_text(json.dumps({"messages": [
        {"type": "assistant", "content": [
            {"type": "tool", "name": "read", "state": {"content": [{"type": "text", "text": "Don't mention water, waves"}]}},
            {"type": "text", "text": "Draft: water..."}]},
        {"type": "assistant", "content": [{"type": "text", "text": "Stones hum in the dusk"}]},
    ]}))
    (tmp_path / "stdout.txt").write_text("read prompt: Don't mention water\n")
    assert checks.final_answer(tmp_path) == "Stones hum in the dusk"


def test_final_answer_falls_back_to_stdout(tmp_path):
    (tmp_path / "stdout.txt").write_text("Cold stones hum below")
    assert checks.final_answer(tmp_path) == "Cold stones hum below"


def test_judge_cannot_override_a_check(tmp_path, w3):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "meta.json").write_text(json.dumps({"test_id": "WRIT-3", "run_id": "m/writing/WRIT-3/x", "test": {"version": w3["version"]}}))
    (run_dir / "stdout.txt").write_text("Along the riverbank\nreeds bow to passing light\nstones remember snow")
    criteria = {c["criterion"]: {"score": c["max_score"], "note": "judge says fine"} for c in w3["rubric"]}
    results = judge.save_agent_score(run_dir, {"criteria": criteria})
    assert results["scores"]["No forbidden words"] == 0
    assert "riverbank" in results["notes"]["No forbidden words"]
    assert results["scores"]["_overall"] < 10


def test_lm_link_device_comes_from_the_cli():
    from crucible import environment
    link = {"deviceIdentifier": "here", "deviceName": "Ironwood.local",
            "peers": [{"deviceIdentifier": "far", "deviceName": "DESKTOP-D2J5PM9"}]}
    remote = [{"identifier": "qwen/qwen3.5-9b", "modelKey": "qwen/qwen3.5-9b", "deviceIdentifier": "far"}]
    local = [{"identifier": "gemma", "modelKey": "gemma", "deviceIdentifier": "here"}]
    assert environment.lmstudio_device("qwen/qwen3.5-9b", remote, link) == {
        "device": "Whitehall", "same_machine": False, "served_via": "LM Link"}
    assert environment.lmstudio_device("gemma", local, link) == {"device": "Ironwood", "same_machine": True}
    # Not loaded, loaded on both devices, or no CLI: unknown, never a guess
    assert environment.lmstudio_device("other", remote, link) == {}
    both = remote + [{**remote[0], "deviceIdentifier": "here"}]
    assert environment.lmstudio_device("qwen/qwen3.5-9b", both, link) == {}
    assert environment.lmstudio_device("qwen/qwen3.5-9b", None, None) == {}


def test_test_counts_use_the_final_summary(tmp_path):
    from crucible.metrics import _test_counts
    (tmp_path / "stdout.txt").write_text(
        " ❯ test/cursor.test.ts (6 tests | 1 failed)\n"
        "   ... fixing ...\n"
        "      Tests  26 passed (26)\n", encoding="utf-8")
    assert _test_counts(tmp_path) == (26, 0)
    (tmp_path / "stdout.txt").write_text("Tests  2 failed | 24 passed (26)\n", encoding="utf-8")
    assert _test_counts(tmp_path) == (24, 2)
    (tmp_path / "stdout.txt").write_text("no tests run\n", encoding="utf-8")
    assert _test_counts(tmp_path) == (None, None)


def test_agent_environment_drops_crucibles_virtualenv(monkeypatch):
    import os
    from crucible.agents.base import REPO_ROOT, agent_environ
    venv = str(REPO_ROOT / ".venv")
    monkeypatch.setenv("VIRTUAL_ENV", venv)
    monkeypatch.setenv("PATH", os.pathsep.join([venv + "/bin", "/usr/bin", "/bin"]))
    env = agent_environ()
    assert "VIRTUAL_ENV" not in env
    assert env["PATH"] == os.pathsep.join(["/usr/bin", "/bin"])


def test_small_local_context_refuses_agent_runs(monkeypatch):
    from crucible import runner
    from crucible.agents import AGENTS
    monkeypatch.setattr(runner.environment, "inference", lambda model: {"context_length": 8192})
    assert "8,192" in runner._context_problem(AGENTS["opencode"], "lmstudio/x")
    assert runner._context_problem(AGENTS["direct"], "lmstudio/x") is None   # no agent prompt to fit
    monkeypatch.setattr(runner.environment, "inference", lambda model: {"context_length": 65536})
    assert runner._context_problem(AGENTS["opencode"], "lmstudio/x") is None


def test_markdown_emphasis_does_not_hide_a_fix():
    prompt = workspace.load_prompt("WRIT-1b")
    text = ("The station was louder **than** she remembered it, people talking *too* fast. "
            "Not waiting for her, exactly. That would have been too kind. Still—she was back. "
            "Mara stepped off the train and into a city that smelled like rain, hot asphalt, and somebody's breakfast. "
            "I kept the fragments; they look intentional. " + "word " * 40)
    by_id = {r["id"]: r for r in checks.run_checks(prompt, text)}
    assert by_id["fixes_than"]["passed"] and by_id["fixes_too"]["passed"] and by_id["keeps_fragments"]["passed"]


def test_required_patterns_min_matches():
    prompt = {"checks": [{"id": "x", "type": "required_patterns", "min_matches": 2, "patterns": ["a\\b", "b\\b", "c\\b"]}]}
    assert checks.run_checks(prompt, "a c")[0]["passed"]
    assert not checks.run_checks(prompt, "only a")[0]["passed"]


def test_list_items_counts_and_distinct_within():
    names = "\n".join(f"{i}. Name{i} Surname — a short feel" for i in range(1, 21))
    recap = "\nTop five:\n1. Name1 Surname — still great\n2. Name2 Surname — fits"
    prompt = {"checks": [
        {"id": "count", "type": "list_items", "min": 20},
        {"id": "distinct", "type": "list_items", "distinct": True, "distinct_within": 20},
        {"id": "described", "type": "list_items", "each_matches": r"\S+\s*(—|–|-|:)\s*\S+"},
    ]}
    assert all(r["passed"] for r in checks.run_checks(prompt, names + recap))
    assert not checks.run_checks(prompt, "\n".join(names.splitlines()[:5]))[0]["passed"]
    dup = names.replace("Name3 Surname", "Name1 Surname")
    assert not checks.run_checks(prompt, dup)[1]["passed"]


def test_fully_checked_tests_score_without_a_judge(tmp_path):
    w3 = workspace.load_prompt("WRIT-3")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "meta.json").write_text(json.dumps({"test_id": "WRIT-3", "run_id": "m/writing/WRIT-3/x"}))
    (run_dir / "stdout.txt").write_text("Cold stones hum below\na heron folds into dusk\nthe current keeps time")
    record = checks.save_check_score(run_dir, w3, checks.check_results(run_dir, w3))
    assert record["passed"] and record["scores"]["_overall"] == 10.0
    assert record["scorer"] == {"type": "checks"} and record["checked_text"].startswith("Cold stones")
    assert json.loads((run_dir / "check_results.json").read_text())["rubric_version"] == w3["rubric_version"]


def test_every_writing_test_is_deterministic():
    for test_id in ("WRIT-1a", "WRIT-1b", "WRIT-1c", "WRIT-2", "WRIT-2b", "WRIT-3"):
        p = workspace.load_prompt(test_id)
        assert checks.fully_checked(p), test_id
        assert all(c.get("rule") for c in p["checks"]), f"{test_id}: every check needs a plain-English rule"
        bound = {item["check"] for item in p["rubric"]}
        assert bound <= {c["id"] for c in p["checks"]}, test_id


@pytest.mark.parametrize("meta, stdout, outcome", [
    ({"returncode": 1, "timed_out": False, "metrics": {}}, "", "harness_error"),
    ({"returncode": 0, "timed_out": False, "metrics": {}}, "", "harness_error"),
    ({"returncode": 0, "timed_out": False, "metrics": {"model_responses": 3, "tokens_out": 50}}, "", "no_answer"),
    ({"returncode": 1, "timed_out": False, "metrics": {"tokens_out": 50}}, "partial", "failed"),
    ({"returncode": None, "timed_out": True, "metrics": {}}, "", "timeout"),
    ({"returncode": 0, "timed_out": False, "metrics": {"tokens_out": 9}}, "Red.", "completed"),
])
def test_outcome_classification(tmp_path, meta, stdout, outcome):
    from crucible.runner import classify_outcome
    (tmp_path / "stdout.txt").write_text(stdout)
    assert classify_outcome(meta, tmp_path) == outcome
