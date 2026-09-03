#!/usr/bin/env python3
"""Tests for the LLM judge module."""
import json
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError, URLError

import pytest

from crucible.llm_judge import (
    LLMJudge, _parse_judge_model, _parse_scores, JUDGE_PROMPT_TEMPLATE,
)
from crucible.scorer import auto_score, _compute_overall


class TestParseJudgeModel:
    def test_ollama(self):
        provider, model = _parse_judge_model("ollama/qwen3:14b")
        assert provider == "ollama"
        assert model == "qwen3:14b"

    def test_openrouter(self):
        provider, model = _parse_judge_model("openrouter/deepseek/deepseek-v4-flash")
        assert provider == "openrouter"
        assert model == "deepseek/deepseek-v4-flash"

    def test_lmstudio(self):
        provider, model = _parse_judge_model("lmstudio/mistral-7b")
        assert provider == "lmstudio"
        assert model == "mistral-7b"

    def test_invalid_provider(self):
        with pytest.raises(ValueError, match="Unsupported judge model"):
            _parse_judge_model("unknown/model")


class TestParseScores:
    def test_valid_json(self):
        rubric = [
            {"criterion": "Correct answer", "max_score": 10},
            {"criterion": "Valid reasoning", "max_score": 3},
        ]
        response = '{"Correct answer": 10, "Valid reasoning": 2}'
        scores = _parse_scores(response, rubric)
        assert scores["Correct answer"] == 10.0
        assert scores["Valid reasoning"] == 2.0

    def test_json_with_extra_text(self):
        rubric = [{"criterion": "Accuracy", "max_score": 5}]
        response = 'Here are my scores: {"Accuracy": 4.5}'
        scores = _parse_scores(response, rubric)
        assert scores["Accuracy"] == 4.5

    def test_scores_clamped_to_max(self):
        rubric = [{"criterion": "Score", "max_score": 3}]
        response = '{"Score": 5}'
        scores = _parse_scores(response, rubric)
        assert scores["Score"] == 3.0

    def test_scores_clamped_to_min(self):
        rubric = [{"criterion": "Score", "max_score": 3}]
        response = '{"Score": -1}'
        scores = _parse_scores(response, rubric)
        assert scores["Score"] == 0.0

    def test_skip_criteria(self):
        rubric = [{"criterion": "A", "max_score": 3}, {"criterion": "B", "max_score": 3}]
        response = '{"A": 3, "B": 2}'
        scores = _parse_scores(response, rubric, skip={"A"})
        assert "A" not in scores
        assert scores["B"] == 2.0

    def test_list_format(self):
        rubric = [{"criterion": "A", "max_score": 3}]
        response = '[{"criterion": "A", "score": 2}]'
        scores = _parse_scores(response, rubric)
        assert scores["A"] == 2.0

    def test_regex_fallback(self):
        rubric = [{"criterion": "Correct answer", "max_score": 10}]
        response = 'Score: "Correct answer": 8'
        scores = _parse_scores(response, rubric)
        assert scores["Correct answer"] == 8.0

    def test_empty_response(self):
        rubric = [{"criterion": "A", "max_score": 3}]
        scores = _parse_scores("no json here", rubric)
        assert scores == {}


class TestLLMJudgeBuildPrompt:
    def test_build_prompt_structure(self):
        prompt_def = {
            "prompt": "What color are firetrucks?",
            "rubric": [{"criterion": "Correct answer", "max_score": 10,
                        "description": "States red"}],
            "critical_failure": "Inventing caps at 5",
        }
        judge = LLMJudge("ollama/qwen3:14b")
        messages = judge._build_prompt(prompt_def, "Firetrucks are red.")

        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        content = messages[0]["content"]
        assert "What color are firetrucks?" in content
        assert "Correct answer" in content
        assert "Firetrucks are red." in content
        assert "Inventing caps at 5" in content

    def test_build_prompt_truncation(self):
        prompt_def = {
            "prompt": "Test",
            "rubric": [{"criterion": "A", "max_score": 5}],
            "critical_failure": None,
        }
        judge = LLMJudge("ollama/qwen3:14b")
        long_output = "x" * 10000
        messages = judge._build_prompt(prompt_def, long_output)
        # Output should be truncated to MAX_OUTPUT_CHARS
        assert "truncated" in messages[0]["content"]


class TestLLMJudgeChatComplete:
    @patch("crucible.llm_judge.urllib.request.urlopen")
    def test_ollama_request(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": '{"A": 3}'}}]
        }).encode()
        mock_urlopen.return_value = mock_resp

        judge = LLMJudge("ollama/qwen3:8b")
        result = judge._chat_complete([{"role": "user", "content": "test"}])
        assert result == '{"A": 3}'

    @patch("crucible.llm_judge.urllib.request.urlopen")
    def test_openrouter_request(self, mock_urlopen, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-123")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": '{"A": 2}'}}]
        }).encode()
        mock_urlopen.return_value = mock_resp

        judge = LLMJudge("openrouter/deepseek/deepseek-v4-flash")
        result = judge._chat_complete([{"role": "user", "content": "test"}])
        assert result == '{"A": 2}'

    def test_openrouter_no_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        judge = LLMJudge("openrouter/deepseek/deepseek-v4-flash")
        with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
            judge._chat_complete([{"role": "user", "content": "test"}])

    @patch("crucible.llm_judge.urllib.request.urlopen")
    def test_api_error_raises(self, mock_urlopen):
        mock_urlopen.side_effect = HTTPError(
            "http://localhost:11434/v1/chat/completions", 404, "Not Found", {},
            MagicMock()
        )
        judge = LLMJudge("ollama/qwen3:8b")
        with pytest.raises(RuntimeError, match="Judge API error"):
            judge._chat_complete([{"role": "user", "content": "test"}])


class TestLLMJudgeJudge:
    @patch("crucible.llm_judge.urllib.request.urlopen")
    def test_judge_returns_scores(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": '{"Accurate definition": 3, "Mechanism": 2}'}}]
        }).encode()
        mock_urlopen.return_value = mock_resp

        prompt_def = {
            "prompt": "Explain enshittification",
            "rubric": [
                {"criterion": "Accurate definition", "max_score": 3},
                {"criterion": "Mechanism", "max_score": 2},
            ],
            "critical_failure": None,
        }
        judge = LLMJudge("ollama/qwen3:14b")
        scores = judge.judge(prompt_def, "Enshittification is...", skip=set())
        assert scores["Accurate definition"] == 3.0
        assert scores["Mechanism"] == 2.0

    @patch("crucible.llm_judge.urllib.request.urlopen")
    def test_judge_respects_skip(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": '{"A": 3, "B": 2}'}}]
        }).encode()
        mock_urlopen.return_value = mock_resp

        prompt_def = {
            "prompt": "Test",
            "rubric": [
                {"criterion": "A", "max_score": 3},
                {"criterion": "B", "max_score": 3},
            ],
            "critical_failure": None,
        }
        judge = LLMJudge("ollama/qwen3:14b")
        scores = judge.judge(prompt_def, "output", skip={"A"})
        assert "A" not in scores
        assert "B" in scores


class TestComputeOverall:
    def test_plain_mean_normalized(self):
        prompt = {"rubric": [
            {"criterion": "A", "max_score": 2},
            {"criterion": "B", "max_score": 2},
        ]}
        scores = {"A": 2.0, "B": 1.0}
        overall = _compute_overall(scores, prompt)
        # (2/2*10 + 1/2*10) / 2 = (10 + 5) / 2 = 7.5
        assert overall == 7.5

    def test_skips_private_keys(self):
        prompt = {"rubric": [{"criterion": "A", "max_score": 5}]}
        scores = {"A": 3.0, "_raw_metrics_auto": {"tool_calls": 5}}
        overall = _compute_overall(scores, prompt)
        assert overall == 6.0  # 3/5*10 = 6.0

    def test_no_scored_criteria(self):
        prompt = {"rubric": [{"criterion": "A", "max_score": 5}]}
        scores = {"_raw_metrics_auto": {}}
        assert _compute_overall(scores, prompt) is None


class TestAutoScore:
    def test_deterministic_only(self, tmp_path):
        # Use the real E5 grader with a proper stdout.txt containing the answer
        (tmp_path / "stdout.txt").write_text("Firetrucks in the US are red.")
        (tmp_path / "meta.json").write_text(json.dumps({"test_id": "E5", "metrics": {}}))
        prompt_def = {"rubric": [{"criterion": "Correct answer", "max_score": 10}]}

        scores, prov = auto_score("E5", prompt_def, tmp_path, judge_model=None)
        assert scores["Correct answer"] == 10.0
        assert "Correct answer" in prov["deterministic"]

    @patch("crucible.scorer.llm_judge.LLMJudge")
    def test_deterministic_plus_judge(self, mock_judge_cls, tmp_path):
        mock_judge = MagicMock()
        mock_judge.judge.return_value = {"Valid reasoning": 2.0}
        mock_judge_cls.return_value = mock_judge

        prompt_def = {"rubric": [
            {"criterion": "Correct answer", "max_score": 4},
            {"criterion": "Valid reasoning", "max_score": 3},
        ]}
        (tmp_path / "stdout.txt").write_text("The answer is unclear.")
        (tmp_path / "meta.json").write_text(json.dumps({"test_id": "G1", "metrics": {}}))

        scores, prov = auto_score("G1", prompt_def, tmp_path, judge_model="ollama/qwen3:14b")
        assert "Correct answer" in prov["deterministic"]
        assert "Valid reasoning" in prov["llm_judge"]

    def test_no_grader_no_judge_returns_none(self, tmp_path):
        (tmp_path / "meta.json").write_text(json.dumps({"test_id": "W1a", "metrics": {}}))
        prompt_def = {"rubric": [{"criterion": "Objective corrections", "max_score": 4}]}
        result = auto_score("W1a", prompt_def, tmp_path, judge_model=None)
        assert result is None
