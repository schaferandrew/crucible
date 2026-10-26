import json

import pytest

from crucible import evals, scorer, workspace
from crucible.taxonomy import validate_category

EVAL_IDS = [t for t in workspace.all_test_ids() if t.startswith("V")]


class TestParseGrade:
    def test_final_grade_line(self):
        assert evals.parse_grade("Reasoning...\nGRADE: 7", 0, 10) == 7

    def test_decimal_and_markdown_decoration(self):
        assert evals.parse_grade("**Grade:** 6.5", 0, 10) == 6.5

    def test_last_grade_wins(self):
        assert evals.parse_grade("GRADE: 3\nOn reflection...\nGRADE: 8", 0, 10) == 8

    def test_grade_must_start_a_line(self):
        assert evals.parse_grade("The grade: 9 would be generous", 0, 10) is None

    def test_missing_or_out_of_range_is_none(self):
        assert evals.parse_grade("no grade here", 0, 10) is None
        assert evals.parse_grade("GRADE: 11", 0, 10) is None
        assert evals.parse_grade("GRADE: -2", 0, 10) is None


class TestClosenessPoints:
    def test_exact_match_is_full_points(self):
        assert evals.closeness_points(7, 7, 10) == 10

    def test_points_fall_linearly_with_error(self):
        assert evals.closeness_points(8, 7, 10) == 8
        assert evals.closeness_points(5, 7, 10) == 6
        assert evals.closeness_points(6.5, 7, 10) == 9

    def test_symmetric_and_floored_at_zero(self):
        assert evals.closeness_points(4, 7, 10) == evals.closeness_points(10, 7, 10) == 4
        assert evals.closeness_points(0, 9, 10) == 0

    def test_no_grade_is_zero(self):
        assert evals.closeness_points(None, 7, 10) == 0


class TestScoreEval:
    PROMPT = {
        "eval": {"scale": [0, 10], "actual_score": 7, "falloff": 5},
        "rubric": [{"criterion": "Grade accuracy", "max_score": 10}],
    }

    def test_scores_and_keeps_reasoning(self):
        scores = evals.score_eval(self.PROMPT, "Criterion 1 is met.\nCriterion 2 is not.\nGRADE: 6")
        assert scores["Grade accuracy"] == 8
        assert scores["_eval"] == {
            "predicted": 6, "actual": 7.0, "error": 1.0, "points": 8, "max_points": 10,
            "parsed": True, "reasoning": "Criterion 1 is met.\nCriterion 2 is not.",
        }

    def test_unparseable_grade_scores_zero_and_is_flagged(self):
        scores = evals.score_eval(self.PROMPT, "I think it's pretty good overall.")
        assert scores["Grade accuracy"] == 0
        assert scores["_eval"]["parsed"] is False
        assert scores["_eval"]["predicted"] is None


class TestScoreRun:
    def test_run_is_graded_without_prompting(self, tmp_path, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("evals must not prompt"))
        run_dir = tmp_path / "m" / "evals" / "V3" / "20260101_000000"
        run_dir.mkdir(parents=True)
        (run_dir / "meta.json").write_text(json.dumps({"test_id": "V3", "run_id": "r"}))
        (run_dir / "stdout.txt").write_text("It is wrong about O(log n).\nGRADE: 2", encoding="utf-8")

        results = json.loads(scorer.score_run(run_dir).read_text())

        scores = results["scores"]
        assert scores["Grade accuracy"] == 8  # off by 1 from the hidden score of 1
        assert scores["_overall"] == 8
        assert scores["_eval"]["reasoning"] == "It is wrong about O(log n)."
        reasoning = (run_dir / evals.REASONING_FILENAME).read_text(encoding="utf-8")
        assert "It is wrong about O(log n)." in reasoning
        assert "Predicted **2**, actual **1**" in reasoning


@pytest.mark.parametrize("test_id", EVAL_IDS)
class TestEvalPrompts:
    def test_declares_valid_eval_config(self, test_id):
        prompt = workspace.load_prompt(test_id)
        validate_category(prompt["category"])
        assert prompt["category"] == "evals"
        assert prompt["needs_tools"] is False
        lo, hi = prompt["eval"]["scale"]
        assert lo <= prompt["eval"]["actual_score"] <= hi
        assert len(prompt["rubric"]) == 1

    def test_hidden_score_is_not_shown_to_the_model(self, test_id):
        prompt = workspace.load_prompt(test_id)
        assert "actual_score" not in prompt["prompt"]
        assert "hidden_answer" not in prompt["prompt"]
        assert "GRADE:" in prompt["prompt"]


def test_there_are_eval_prompts():
    assert EVAL_IDS == ["V1", "V2", "V3"]
