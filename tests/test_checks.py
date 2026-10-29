"""Programmatic checks: deterministic scoring of the final answer (WRIT-3's forbidden words)."""
import json

import pytest

from tests.records import run_meta

from crucible import checks, judge, workspace


@pytest.fixture
def w3():
    return workspace.load_task("WRIT-3")


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
    (run_dir / "meta.json").write_text(json.dumps(run_meta(w3["id"], w3["version"])))
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
    # Chat runs need room to reason too, unless reasoning is off
    assert runner._context_problem(AGENTS["direct"], "lmstudio/x") is not None
    assert runner._context_problem(AGENTS["direct"], "lmstudio/x", "off") is None
    monkeypatch.setattr(runner.environment, "inference", lambda model: {"context_length": 65536})
    assert runner._context_problem(AGENTS["opencode"], "lmstudio/x") is None


def test_markdown_emphasis_does_not_hide_a_fix():
    prompt = workspace.load_task("WRIT-1b")
    text = ("CORRECTED:\nThe station was louder **than** she remembered it, people talking *too* fast. "
            "Not waiting for her, exactly. That would have been too kind. Still—she was back. "
            "Mara stepped off the train and into a city that smelled like rain, hot asphalt, and somebody's breakfast. "
            "And she didn't know whether to laugh, or leave.\n\nPOSSIBLY INTENTIONAL:\n- the fragments")
    by_id = {r["id"]: r for r in checks.run_checks(prompt, text)}
    assert by_id["errors_fixed"]["passed"] and by_id["voice_kept"]["passed"] and by_id["flags_intent"]["passed"]


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


EVERY_TYPE = [
    {"id": "forbidden", "type": "forbidden_patterns", "patterns": ["water"]},
    {"id": "lines", "type": "line_count", "lines": 0},
    {"id": "words", "type": "non_empty", "min_words": 0},
    {"id": "required", "type": "required_patterns", "patterns": ["x"], "min_matches": 0},
    {"id": "count", "type": "list_items", "min": 0},
    {"id": "distinct", "type": "list_items", "distinct": True},
    {"id": "described", "type": "list_items", "each_matches": r"\S+\s*(—|-|:)\s*\S+"},
    {"id": "grounded", "type": "grounded_numbers"},
    {"id": "grade", "type": "grade_closeness", "actual_score": 5, "width": 100},
    {"id": "block", "type": "items", "normalize": "letter_set",
     "items": [{"id": "q", "expect": ["B"], "of": ["A", "B", "C"]}, {"id": "n", "key": "2", "expect": 2}]},
]


@pytest.mark.parametrize("text", ["", "   \n\t\n", "** **\n``"])
def test_an_empty_answer_fails_every_check_type(text):
    """B2: a timed-out run with no output used to pass `distinct` and `each_matches` on 0 items."""
    assert {c["type"] for c in EVERY_TYPE} == set(checks.CHECKS)
    results = checks.run_checks({"checks": EVERY_TYPE, "prompt": "Source: 1,234"}, text)
    assert [r["passed"] for r in results] == [False] * len(EVERY_TYPE)
    assert {r["detail"] for r in results} == {"no answer to check"}
    block = results[-1]
    # Every item fails, expanded as a real block would be (3 letters + 1 line), so the total doesn't change
    assert block["share"] == 0.0 and len(block["items"]) == 4 and not any(i["passed"] for i in block["items"])


def test_an_empty_file_fails_its_checks(tmp_path):
    (tmp_path / "workspace").mkdir()
    (tmp_path / "workspace" / "NOTES.md").write_text("\n")
    prompt = {"checks": [{"id": "count", "type": "list_items", "min": 0, "file": "NOTES.md"}]}
    assert checks.run_checks(prompt, "a reply", tmp_path)[0] == {
        "id": "count", "type": "list_items", "passed": False, "detail": "no answer to check", "rule": None}


def test_an_empty_answer_scores_zero(tmp_path):
    p = workspace.load_task("WRIT-2")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "meta.json").write_text(json.dumps(run_meta(p["id"], p["version"])))
    record = checks.save_check_score(run_dir, p, checks.check_results(run_dir, p))
    assert record["scores"]["_overall"] == 0.0


def test_fully_checked_tests_score_without_a_judge(tmp_path):
    w3 = workspace.load_task("WRIT-3")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "meta.json").write_text(json.dumps(run_meta(w3["id"], w3["version"])))
    (run_dir / "stdout.txt").write_text("Cold stones hum below\na heron folds into dusk\nthe current keeps time")
    record = checks.save_check_score(run_dir, w3, checks.check_results(run_dir, w3))
    assert record["passed"] and record["scores"]["_overall"] == 10.0
    assert record["scorer"] == {"type": "checks"} and record["checked_text"].startswith("Cold stones")
    score = json.loads((run_dir / "scores" / f"r{w3['rubric_version']}.checks.json").read_text())
    assert score["score"] == 10.0 and score["raw"] == {"passed": 10, "total": 10, "unit": "points"}
    assert score["run_uuid"] == run_meta(w3["id"])["run_uuid"] and score["rubric_version"] == w3["rubric_version"]
    assert {i["group"] for i in score["items"]} <= {c["criterion"] for c in w3["rubric"]}


def test_every_writing_test_is_deterministic():
    for test_id in ("WRIT-1a", "WRIT-1b", "WRIT-1c", "WRIT-2", "WRIT-2b", "WRIT-3"):
        p = workspace.load_task(test_id)
        assert checks.fully_checked(p), test_id
        assert all(c.get("rule") for c in p["checks"]), f"{test_id}: every check needs a plain-English rule"
        bound = {item["check"] for item in p["rubric"]}
        assert bound <= {c["id"] for c in p["checks"]}, test_id


@pytest.mark.parametrize("returncode, timed_out, metrics, stdout, outcome", [
    (1, False, {}, "", "harness_error"),
    (0, False, {}, "", "harness_error"),
    (0, False, {"model_responses": 3, "tokens_out": 50}, "", "no_answer"),
    (1, False, {"tokens_out": 50}, "partial", "failed"),
    (None, True, {}, "", "timeout"),
    (0, False, {"tokens_out": 9}, "Red.", "completed"),
])
def test_outcome_classification(tmp_path, returncode, timed_out, metrics, stdout, outcome):
    from crucible.runner import classify_outcome
    (tmp_path / "stdout.txt").write_text(stdout)
    meta = {"outcome": {"returncode": returncode, "timed_out": timed_out}, "metrics": metrics}
    assert classify_outcome(meta, tmp_path) == outcome
