import json

import pytest

from crucible import runner


class TestSplitPoolOutput:
    def _write(self, tmp_path, lines):
        (tmp_path / "stdout.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_splits_valid_events(self, tmp_path):
        self._write(tmp_path, [
            json.dumps({"type": "assistantMessage", "message": "hello"}),
            json.dumps({"type": "toolCall", "name": "shell", "args": {"cmd": "ls"}}),
            json.dumps({"type": "toolCallResult", "result": "file.txt"}),
        ])
        runner.split_pool_output(tmp_path)
        events = json.loads((tmp_path / "session.json").read_text())
        assert len(events) == 3
        transcript = (tmp_path / "stdout.txt").read_text()
        assert "⏺ hello" in transcript
        assert "⏺ shell(cmd=ls)" in transcript
        assert "⎿ file.txt" in transcript

    def test_truncated_tail_keeps_complete_prefix(self, tmp_path):
        # A timeout can leave the last event half-written
        self._write(tmp_path, [
            json.dumps({"type": "assistantMessage", "message": "working"}),
            '{"type":"assistantMessage","mess',  # truncated
        ])
        runner.split_pool_output(tmp_path)
        events = json.loads((tmp_path / "session.json").read_text())
        assert len(events) == 1
        assert events[0]["message"] == "working"

    def test_non_json_stdout_untouched(self, tmp_path):
        self._write(tmp_path, ["plain text output", "more text"])
        runner.split_pool_output(tmp_path)
        assert not (tmp_path / "session.json").exists()
        assert "plain text output" in (tmp_path / "stdout.txt").read_text()


class TestCountToolCalls:
    def test_opencode_schema(self, tmp_path):
        session = tmp_path / "session.json"
        session.write_text(json.dumps({
            "messages": [
                {"parts": [{"type": "tool"}, {"type": "text"}]},
                {"parts": [{"type": "tool"}]},
            ]
        }))
        assert runner.count_tool_calls(session) == 2

    def test_pool_schema(self, tmp_path):
        session = tmp_path / "session.json"
        session.write_text(json.dumps([
            {"type": "assistantMessage", "message": "hi"},
            {"type": "toolCall", "name": "shell"},
            {"type": "toolCallResult", "result": ""},
            {"type": "toolCall", "name": "write"},
        ]))
        assert runner.count_tool_calls(session) == 2  # results not double-counted

    def test_invalid_file_returns_none(self, tmp_path):
        session = tmp_path / "session.json"
        session.write_text("not json at all {")
        assert runner.count_tool_calls(session) is None


class TestPoolConfig:
    def test_tenant_mode_no_model(self):
        env, flags, standalone = runner._pool_config(None)
        assert "POOLSIDE_STANDALONE_MODEL" not in env
        assert flags == []
        assert standalone is None

    def test_pool_placeholder_is_tenant_mode(self):
        env, flags, standalone = runner._pool_config("pool")
        assert "POOLSIDE_STANDALONE_MODEL" not in env
        assert standalone is None

    def test_ollama_standalone(self):
        env, flags, standalone = runner._pool_config("ollama/laguna-xs-2.1:nvfp4")
        assert env["POOLSIDE_STANDALONE_MODEL"] == "laguna-xs-2.1:nvfp4"
        assert flags == []
        assert standalone == "laguna-xs-2.1:nvfp4"

    def test_openrouter_standalone(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        env, flags, standalone = runner._pool_config("openrouter/deepseek/deepseek-v4-flash")
        assert env["POOLSIDE_API_KEY"] == "test-key"
        assert env["POOLSIDE_STANDALONE_BASE_URL"] == runner.OPENROUTER_API
        assert env["POOLSIDE_STANDALONE_MODEL"] == "deepseek/deepseek-v4-flash"
        assert flags == ["--sandbox", "disabled"]
        assert standalone == "deepseek/deepseek-v4-flash"
