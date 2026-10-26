"""Evals: a model's grade of an agent response is scored by closeness to a hidden reference grade."""
import json

import pytest

from crucible import checks, evals, workspace

EVAL_IDS = [t for t in workspace.all_test_ids() if t.startswith("EVAL-")]
CHECK = {"id": "grade", "type": "grade_closeness", "scale": [0, 10], "actual_score": 7, "width": 3}


class TestParseGrade:
    def test_final_grade_line(self):
        assert evals.parse_grade("Reasoning...\nGRADE: 7", 0, 10) == 7

    def test_decimal(self):
        assert evals.parse_grade("Grade: 6.5", 0, 10) == 6.5

    def test_last_grade_wins(self):
        assert evals.parse_grade("GRADE: 3\nOn reflection...\nGRADE: 8", 0, 10) == 8

    def test_grade_must_start_a_line(self):
        assert evals.parse_grade("The grade: 9 would be generous", 0, 10) is None

    def test_missing_or_out_of_range_is_none(self):
        assert evals.parse_grade("no grade here", 0, 10) is None
        assert evals.parse_grade("GRADE: 11", 0, 10) is None
        assert evals.parse_grade("GRADE: -2", 0, 10) is None


class TestCloseness:
    def test_exact_match_is_full(self):
        assert evals.closeness(7, 7) == 1

    def test_falls_as_a_gaussian_of_the_error(self):
        assert evals.closeness(8, 7) == pytest.approx(0.8948, abs=1e-4)
        assert evals.closeness(9, 7) == pytest.approx(0.6412, abs=1e-4)
        assert evals.closeness(10, 7) == pytest.approx(0.3679, abs=1e-4)  # one width away: 1/e

    def test_penalty_accelerates_with_distance(self):
        shares = [evals.closeness(7 + e, 7) for e in range(6)]
        drops = [a - b for a, b in zip(shares, shares[1:])]
        assert drops[:3] == sorted(drops[:3])  # each extra point of error costs more, up to the knee

    def test_symmetric_and_never_negative(self):
        assert evals.closeness(4, 7) == evals.closeness(10, 7)
        assert 0 <= evals.closeness(0, 10) < 0.01

    def test_no_grade_is_zero(self):
        assert evals.closeness(None, 7) == 0


class TestGradeCloseness:
    def test_reports_partial_credit(self):
        passed, detail, share = evals.grade_closeness(CHECK, "Criterion 1 is met.\nGRADE: 6")
        assert (passed, share) == (False, pytest.approx(0.8948, abs=1e-4))
        assert detail == "graded 6, reference 7 (off by 1)"

    def test_exact_match_passes(self):
        assert evals.grade_closeness(CHECK, "GRADE: 7")[0] is True

    def test_unparseable_grade_scores_zero(self):
        passed, detail, share = evals.grade_closeness(CHECK, "I think it is pretty good.")
        assert (passed, share) == (False, 0.0)
        assert "no valid GRADE line" in detail

    def test_custom_scale_and_width(self):
        check = {**CHECK, "scale": [0, 100], "actual_score": 80, "width": 20}
        assert evals.grade_closeness(check, "GRADE: 60")[2] == pytest.approx(0.3679, abs=1e-4)
        assert evals.grade_closeness(check, "GRADE: 101")[2] == 0.0


class TestScoring:
    def test_partial_credit_flows_into_the_criterion_score(self):
        prompt = {"checks": [CHECK], "rubric": [{"criterion": "Grade accuracy", "max_score": 10, "check": "grade"}]}
        results = checks.run_checks(prompt, "Reasoning.\n**GRADE: 6**")
        assert checks.criterion_scores(prompt, results) == {"Grade accuracy": 8.95}

    def test_run_is_scored_without_a_judge(self, tmp_path):
        prompt = workspace.load_prompt("EVAL-3")
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "meta.json").write_text(json.dumps({"run_id": "r", "test_id": "EVAL-3"}))
        (run_dir / "stdout.txt").write_text("It claims O(n log n), which is wrong.\nGRADE: 2", encoding="utf-8")

        record = checks.save_check_score(run_dir, prompt, checks.check_results(run_dir, prompt))

        assert record["scores"]["Grade accuracy"] == 8.95  # off by 1 from the reference grade of 1
        assert record["scores"]["_overall"] == 8.95
        assert "wrong" in record["checked_text"]  # the reasoning is kept for people to read


@pytest.mark.parametrize("test_id", EVAL_IDS)
class TestEvalPrompts:
    def test_is_fully_checked_and_in_range(self, test_id):
        prompt = workspace.load_prompt(test_id)
        assert prompt["category"] == "evals" and prompt["area"] == "evals"
        assert prompt["needs_tools"] is False
        assert checks.fully_checked(prompt)
        (check,) = prompt["checks"]
        lo, hi = check["scale"]
        assert check["type"] == "grade_closeness" and lo <= check["actual_score"] <= hi

    def test_hidden_score_is_not_shown_to_the_model(self, test_id):
        prompt = workspace.load_prompt(test_id)
        assert "actual_score" not in prompt["prompt"]
        assert "hidden_answer" not in prompt["prompt"]
        assert "GRADE:" in prompt["prompt"]


def test_there_are_three_eval_prompts():
    assert EVAL_IDS == ["EVAL-1", "EVAL-2", "EVAL-3"]
