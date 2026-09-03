#!/usr/bin/env python3
"""Tests for deterministic auto-graders."""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from crucible import graders
from crucible.graders import (
    GRADERS, _extract_json_block, _extract_json_objects, get_model_output,
    grade_e5, grade_g1, grade_g2, grade_c1, grade_e6, has_grader,
)


# ---- Fixtures: prompt definitions matching the real YAML structure ----

def _prompt(test_id: str, rubric: list, critical_failure=None, **extra):
    prompt = {"test_id": test_id, "rubric": rubric}
    if critical_failure is not None:
        prompt["critical_failure"] = critical_failure
    prompt.update(extra)
    return prompt


E5_PROMPT = _prompt("E5", [
    {"criterion": "Correct answer", "max_score": 10,
     "description": "States that firetrucks in the US are (predominantly) red"}
])
E5_PROMPT_WITH_CF = _prompt("E5", [
    {"criterion": "Correct answer", "max_score": 10}
], critical_failure="Inventing firetruck color caps score at 5")

G1_PROMPT = _prompt("G1", [
    {"criterion": "Correct answer", "max_score": 4},
    {"criterion": "Valid reasoning", "max_score": 3},
    {"criterion": "Handles ambiguity", "max_score": 2},
    {"criterion": "Final answer clearly stated", "max_score": 1},
], hidden_answer="Dave(red,3)")

G2_PROMPT = _prompt("G2", [
    {"criterion": "Finds all valid options", "max_score": 3},
    {"criterion": "Rejects conflicts", "max_score": 2},
    {"criterion": "Ranking follows criteria", "max_score": 2},
    {"criterion": "Correct JSON", "max_score": 2},
    {"criterion": "Explanation", "max_score": 1},
])

C1_PROMPT = _prompt("C1", [
    {"criterion": "Requirements captured without being reminded", "max_score": 2},
    {"criterion": "Correct financial math", "max_score": 3},
    {"criterion": "Input validation", "max_score": 2},
    {"criterion": "Tests", "max_score": 2},
    {"criterion": "UX / docs", "max_score": 1},
], critical_failure="Wrong compound-interest math = maximum score 4/10.")

E6_PROMPT = _prompt("E6", [
    {"criterion": "Live fetch performed", "max_score": 3},
    {"criterion": "Current conditions reported", "max_score": 3},
    {"criterion": "Historical comparison", "max_score": 3},
    {"criterion": "Source attribution", "max_score": 1},
], critical_failure="Inventing live conditions without a fetch caps the score at 4.")


class TestRegistry:
    def test_graders_registered(self):
        assert "E5" in GRADERS
        assert "G1" in GRADERS
        assert "G2" in GRADERS
        assert "C1" in GRADERS
        assert "C1b" in GRADERS
        assert "E6" in GRADERS

    def test_has_grader(self):
        assert has_grader("E5") is True
        assert has_grader("W1a") is False
        assert has_grader("X9") is False

    def test_c1b_uses_c1_grader(self):
        assert graders.get_grader("C1b") is graders.get_grader("C1")


class TestExtractJson:
    def test_extract_valid_json(self):
        text = 'Here is my answer: {"key": "value", "num": 42}'
        result = _extract_json_block(text)
        assert result == {"key": "value", "num": 42}

    def test_extract_json_list(self):
        text = 'Recommendations: [{"start": "9:00", "end": "10:00"}, {"start": "10:00"}]'
        result = _extract_json_objects(text)
        assert len(result) == 1
        assert isinstance(result[0], list)
        assert len(result[0]) == 2

    def test_extract_no_json(self):
        text = "No JSON here, just plain text."
        assert _extract_json_block(text) is None

    def test_extract_json_after_code_block(self):
        text = '```json\n{"answer": "Dave"}\n```'
        result = _extract_json_block(text)
        assert result == {"answer": "Dave"}


class TestGradeE5:
    def test_correct_answer_red(self):
        scores = grade_e5(E5_PROMPT, Path("/tmp"), "Firetrucks in the US are red.")
        assert scores == {"Correct answer": 10.0}

    def test_correct_answer_with_nuance(self):
        scores = grade_e5(E5_PROMPT, Path("/tmp"),
                          "Firetrucks are predominantly red, though some departments use other colors.")
        assert scores == {"Correct answer": 10.0}

    def test_wrong_answer(self):
        scores = grade_e5(E5_PROMPT, Path("/tmp"), "Firetrucks are blue.")
        assert scores == {"Correct answer": 0.0}

    def test_empty_output(self):
        scores = grade_e5(E5_PROMPT, Path("/tmp"), "")
        assert scores == {"Correct answer": 0.0}


class TestGradeG1:
    def test_correct_answer_dave_chair3(self):
        output = "The person in chair 3 is Dave, who likes red."
        scores = grade_g1(G1_PROMPT, Path("/tmp"), output)
        assert scores["Correct answer"] == 4.0
        assert scores["Final answer clearly stated"] == 1.0

    def test_wrong_answer(self):
        output = "The person in chair 3 is Alice."
        scores = grade_g1(G1_PROMPT, Path("/tmp"), output)
        assert scores["Correct answer"] == 0.0

    def test_ambiguity_mentioned(self):
        output = "Assuming standard interpretation, Dave is in chair 3. The puzzle could be ambiguous about..."
        scores = grade_g1(G1_PROMPT, Path("/tmp"), output)
        assert scores["Handles ambiguity"] == 2.0

    def test_no_ambiguity_mentioned(self):
        output = "Dave sits in chair 3. That's the answer."
        scores = grade_g1(G1_PROMPT, Path("/tmp"), output)
        assert scores["Handles ambiguity"] == 0.0

    def test_final_answer_cleared(self):
        output = "Chair 3 is Dave."
        scores = grade_g1(G1_PROMPT, Path("/tmp"), output)
        assert scores["Final answer clearly stated"] == 1.0

    def test_no_clear_answer(self):
        output = "This is a difficult puzzle."
        scores = grade_g1(G1_PROMPT, Path("/tmp"), output)
        assert scores["Final answer clearly stated"] == 0.0


class TestGradeG2:
    def test_valid_json_correct_slots(self):
        # Model output with valid JSON containing conflict-free slots
        output = json.dumps([
            {"start": "2026-08-31T10:00:00-05:00", "end": "2026-08-31T11:00:00-05:00",
             "explanation": "Free slot Monday morning"},
            {"start": "2026-08-31T15:00:00-05:00", "end": "2026-08-31T16:00:00-05:00",
             "explanation": "After design review"},
        ])
        scores = grade_g2(G2_PROMPT, Path("/tmp"), output)
        # At minimum, correct JSON criterion should pass
        assert scores["Correct JSON"] == 2.0
        assert scores["Explanation"] >= 0.5

    def test_conflicting_slot_detected(self):
        # Slot overlaps with Alex's 10:00-11:00 event
        output = json.dumps([
            {"start": "2026-08-31T10:00:00-05:00", "end": "2026-08-31T11:00:00-05:00",
             "explanation": "Meeting slot"}
        ])
        scores = grade_g2(G2_PROMPT, Path("/tmp"), output)
        assert scores["Rejects conflicts"] == 0.0

    def test_no_json_in_output(self):
        output = "I couldn't find any good meeting times."
        scores = grade_g2(G2_PROMPT, Path("/tmp"), output)
        assert scores["Correct JSON"] == 0.0
        assert scores["Rejects conflicts"] == 0.0
        assert scores["Finds all valid options"] == 0.0

    def test_free_slot_accepted(self):
        # 11:00-12:00 on Aug 31 is free for both (Alex busy 10-11, 13-14; Jamie busy 9-10, 14:00-15:30)
        output = json.dumps([
            {"start": "2026-08-31T11:00:00-05:00", "end": "2026-08-31T12:00:00-05:00",
             "explanation": "Free for both"},
        ])
        scores = grade_g2(G2_PROMPT, Path("/tmp"), output)
        assert scores["Rejects conflicts"] == 2.0


class TestGradeC1:
    def test_no_workspace(self, tmp_path):
        """Direct-mode runs have no workspace."""
        scores = grade_c1(C1_PROMPT, tmp_path, "Firetrucks are red.")
        assert "Tests" in scores
        assert scores["Tests"] == 0.0
        assert scores["Correct financial math"] == 0.0

    @patch("crucible.graders._run_workspace_tests")
    def test_tests_pass(self, mock_run_tests, tmp_path):
        mock_run_tests.return_value = (True, 15)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "README.md").write_text("Usage: python -m interest_calc\n")
        (workspace / "interest_calc").mkdir()
        (workspace / "interest_calc" / "__init__.py").write_text("")
        scores = grade_c1(C1_PROMPT, tmp_path, "")
        assert scores["Tests"] == 2.0

    @patch("crucible.graders._run_workspace_tests")
    def test_tests_fail(self, mock_run_tests, tmp_path):
        mock_run_tests.return_value = (False, 3)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        scores = grade_c1(C1_PROMPT, tmp_path, "")
        assert scores["Tests"] == 0.0

    @patch("crucible.graders._run_workspace_tests")
    @patch("crucible.graders._verify_compound_math")
    def test_correct_math(self, mock_math, mock_tests, tmp_path):
        mock_tests.return_value = (True, 10)
        mock_math.return_value = True
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        scores = grade_c1(C1_PROMPT, tmp_path, "")
        assert scores["Correct financial math"] == 3.0

    @patch("crucible.graders._run_workspace_tests")
    @patch("crucible.graders._verify_compound_math")
    def test_wrong_math(self, mock_math, mock_tests, tmp_path):
        mock_tests.return_value = (True, 10)
        mock_math.return_value = False
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        scores = grade_c1(C1_PROMPT, tmp_path, "")
        assert scores["Correct financial math"] == 0.0

    @patch("crucible.graders._run_workspace_tests")
    @patch("crucible.graders._verify_compound_math")
    @patch("crucible.graders._check_validation")
    @patch("crucible.graders._check_readme")
    def test_all_criteria_pass(self, mock_readme, mock_validation, mock_math, mock_tests, tmp_path):
        mock_tests.return_value = (True, 20)
        mock_math.return_value = True
        mock_validation.return_value = True
        mock_readme.return_value = True
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        scores = grade_c1(C1_PROMPT, tmp_path, "")
        assert scores["Tests"] == 2.0
        assert scores["Correct financial math"] == 3.0
        assert scores["Input validation"] == 2.0
        assert scores["UX / docs"] == 1.0
        # Requirements captured → not auto-graded (left for LLM judge)
        assert "Requirements captured without being reminded" not in scores


class TestGradeE6:
    def test_live_fetch_with_session(self, tmp_path):
        import json
        session = tmp_path / "session.json"
        session.write_text(json.dumps([
            {"type": "toolCall", "name": "web_fetch", "args": {"url": "https://weather.gov"}},
        ]))
        output = "Current temperature in Saint Paul is 72°F. Source: weather.gov"
        scores = grade_e6(E6_PROMPT, tmp_path, output)
        assert scores["Live fetch performed"] == 3.0
        assert scores["Source attribution"] == 1.0

    def test_no_fetch_no_source(self, tmp_path):
        session = tmp_path / "session.json"
        session.write_text(json.dumps([]))
        output = "The weather today is sunny."
        scores = grade_e6(E6_PROMPT, tmp_path, output)
        assert scores["Live fetch performed"] == 0.0
        assert scores["Source attribution"] == 0.0

    def test_no_session_file(self, tmp_path):
        output = "It's raining. Source: Weather Channel."
        scores = grade_e6(E6_PROMPT, tmp_path, output)
        # No session → no tool calls → 0 for fetch (unless output mentions fetch keywords)
        assert scores["Live fetch performed"] == 0.0
        assert scores["Source attribution"] == 1.0


class TestGetModelOutput:
    def test_stdout_preferred(self, tmp_path):
        (tmp_path / "stdout.txt").write_text("Model output here")
        assert get_model_output(tmp_path) == "Model output here"

    def test_stdout_fallback_to_session(self, tmp_path):
        (tmp_path / "stdout.txt").write_text("")
        (tmp_path / "session.json").write_text(json.dumps([
            {"type": "assistantMessage", "message": "From session"}
        ]))
        output = get_model_output(tmp_path)
        assert "From session" in output

    def test_no_artifacts(self, tmp_path):
        output = get_model_output(tmp_path)
        assert "No stdout captured" in output
