import json
import sys

import pytest

from crucible import procs, runner, session
from crucible.agents import AGENTS, RunContext
from crucible.agents import pi as pi_agent


def _ctx(tmp_path, **overrides):
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    fields = dict(test_id="C1", run_id="m/coding/C1/ts", run_dir=tmp_path,
                  workspace=workspace, prompt_file=workspace / "prompt.txt",
                  model=None, watch=False, timeout=60, title="ts_C1_m")
    fields.update(overrides)
    return RunContext(**fields)


def _pi_session(tmp_path, entries):
    sessions = tmp_path / pi_agent.SESSION_DIRNAME
    sessions.mkdir(exist_ok=True)
    path = sessions / "2026-01-01T00-00-00-000Z_abc.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    return path


USAGE = {"input": 100, "output": 10, "cacheRead": 50, "cacheWrite": 0}
PI_ENTRIES = [
    {"type": "session", "version": 3, "id": "abc", "cwd": "/w"},
    {"type": "message", "message": {"role": "user", "content": [{"type": "text", "text": "do it"}]}},
    {"type": "message", "message": {"role": "assistant", "usage": USAGE, "content": [
        {"type": "thinking", "thinking": "hmm"},
        {"type": "toolCall", "id": "1", "name": "bash", "arguments": {"command": "npm test"}},
    ]}},
    {"type": "message", "message": {"role": "toolResult", "toolName": "bash",
                                    "content": [{"type": "text", "text": "3 passed"}]}},
    {"type": "message", "message": {"role": "assistant", "usage": USAGE,
                                    "content": [{"type": "text", "text": "Done."}]}},
]


class TestPiSession:
    def test_normalizes_events_and_tokens(self, tmp_path):
        events, usage = pi_agent.session_events(_pi_session(tmp_path, PI_ENTRIES))
        assert [e["type"] for e in events] == ["toolCall", "toolCallResult", "assistantMessage"]
        assert events[0] == {"type": "toolCall", "name": "bash", "args": {"command": "npm test"}}
        assert usage == (300, 20)  # input includes cache reads

    def test_truncated_tail_keeps_complete_prefix(self, tmp_path):
        path = _pi_session(tmp_path, PI_ENTRIES[:3])
        with open(path, "a", encoding="utf-8") as f:
            f.write('{"type":"message","message":{"role":"assis')
        events, _ = pi_agent.session_events(path)
        assert len(events) == 1

    def test_collect_writes_session_and_transcript(self, tmp_path):
        _pi_session(tmp_path, PI_ENTRIES)
        AGENTS["pi"].collect(_ctx(tmp_path))
        transcript = (tmp_path / "stdout.txt").read_text(encoding="utf-8")
        assert "⏺ bash(command=npm test)" in transcript
        assert "⎿ 3 passed" in transcript
        assert "⏺ Done." in transcript
        metrics = runner.extract_metrics(tmp_path, AGENTS["pi"])
        assert metrics["tool_calls"] == 1
        assert metrics["tests_passed"] == 3
        assert (metrics["tokens_in"], metrics["tokens_out"]) == (300, 20)

    def test_collect_without_session_is_harmless(self, tmp_path):
        AGENTS["pi"].collect(_ctx(tmp_path))
        assert not (tmp_path / "session.json").exists()


class TestPiLaunch:
    def test_default_model_has_no_flags_or_config(self, tmp_path):
        launch = AGENTS["pi"].launch(_ctx(tmp_path))
        assert "--model" not in launch.cmd
        assert launch.env == {}
        assert launch.cwd == tmp_path / "workspace"
        assert "-p" in launch.cmd

    def test_ollama_registers_local_provider(self, tmp_path):
        launch = AGENTS["pi"].launch(_ctx(tmp_path, model="ollama/qwen3:30b-a3b"))
        assert launch.cmd[launch.cmd.index("--model") + 1] == "ollama/qwen3:30b-a3b"
        provider = json.loads(launch.env["CRUCIBLE_PI_CONFIG"])["providers"]["ollama"]
        assert provider["baseUrl"] == pi_agent.OLLAMA_BASE_URL
        assert provider["models"] == [{"id": "qwen3:30b-a3b"}]

    def test_openrouter_passes_through(self, tmp_path):
        launch = AGENTS["pi"].launch(_ctx(tmp_path, model="openrouter/moonshotai/kimi-k2.6"))
        assert launch.cmd[launch.cmd.index("--model") + 1] == "openrouter/moonshotai/kimi-k2.6"
        assert launch.env == {}  # pi reads OPENROUTER_API_KEY itself

    def test_mcp_servers_use_current_interpreter(self, tmp_path):
        launch = AGENTS["pi"].launch(_ctx(tmp_path, mcp_servers=["mock-data"]))
        servers = json.loads(launch.env["CRUCIBLE_PI_CONFIG"])["mcpServers"]
        assert servers["mock-data"]["command"][0] == sys.executable

    def test_watch_opens_tui_with_prompt_attached(self, tmp_path):
        ctx = _ctx(tmp_path, watch=True)
        launch = AGENTS["pi"].launch(ctx)
        assert "-p" not in launch.cmd
        assert "@prompt.txt" in launch.cmd

    def test_args_are_single_line(self, tmp_path):
        # Windows .cmd shims truncate multi-line arguments
        for watch in (False, True):
            launch = AGENTS["pi"].launch(_ctx(tmp_path, watch=watch, mcp_servers=["mock-data"]))
            assert all("\n" not in arg for arg in launch.cmd)


class TestPiValidate:
    def test_openrouter_needs_key(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        assert AGENTS["pi"].validate("openrouter/x/y")
        monkeypatch.setenv("OPENROUTER_API_KEY", "k")
        assert AGENTS["pi"].validate("openrouter/x/y") is None
        assert AGENTS["pi"].validate("ollama/q") is None


class TestOpenCodeLaunch:
    def test_mcp_via_config_content(self, tmp_path):
        launch = AGENTS["opencode"].launch(_ctx(tmp_path, mcp_servers=["mock-data"],
                                                model="openrouter/x/y"))
        config = json.loads(launch.env["OPENCODE_CONFIG_CONTENT"])
        assert config["mcp"]["mock-data"]["command"][0] == sys.executable
        assert launch.cmd[-2:] == ["-m", "openrouter/x/y"]

    def test_watch_args_are_single_line(self, tmp_path):
        launch = AGENTS["opencode"].launch(_ctx(tmp_path, watch=True))
        assert all("\n" not in arg for arg in launch.cmd)

    def test_token_usage(self, tmp_path):
        (tmp_path / "session.json").write_text(json.dumps({"messages": [
            {"info": {"tokens": {"input": 5, "output": 2, "reasoning": 1}}},
            {"info": {"tokens": {"input": 7, "output": 3}}},
        ]}), encoding="utf-8")
        assert AGENTS["opencode"].token_usage(tmp_path) == (12, 6)


class TestCountToolCalls:
    def test_opencode_schema(self, tmp_path):
        path = tmp_path / "session.json"
        path.write_text(json.dumps({"messages": [
            {"parts": [{"type": "tool"}, {"type": "text"}]},
            {"parts": [{"type": "tool"}]},
        ]}))
        assert session.count_tool_calls(path) == 2

    def test_normalized_schema(self, tmp_path):
        path = tmp_path / "session.json"
        path.write_text(json.dumps([
            {"type": "assistantMessage", "message": "hi"},
            {"type": "toolCall", "name": "shell"},
            {"type": "toolCallResult", "result": ""},
            {"type": "toolCall", "name": "write"},
        ]))
        assert session.count_tool_calls(path) == 2  # results not double-counted

    def test_invalid_file_returns_none(self, tmp_path):
        path = tmp_path / "session.json"
        path.write_text("not json at all {")
        assert session.count_tool_calls(path) is None


class TestProcs:
    def test_timeout_kills_process_tree(self, tmp_path):
        # Parent spawns a grandchild; both must die on timeout
        # (marker path goes in argv: Windows backslashes break string literals)
        marker = tmp_path / "survived"
        grandchild = "import sys, time; time.sleep(3); open(sys.argv[1], 'w')"
        script = (
            "import subprocess, sys, time\n"
            f"subprocess.Popen([sys.executable, '-c', {grandchild!r}, sys.argv[1]])\n"
            "time.sleep(30)\n"
        )
        result = procs.run_logged([sys.executable, "-c", script, str(marker)], tmp_path, 1, "t")
        assert result["timed_out"], (tmp_path / "stderr.txt").read_text()
        import time
        time.sleep(4)
        assert not marker.exists()

    def test_missing_executable(self):
        with pytest.raises(FileNotFoundError):
            procs.resolve_executable("definitely-not-a-real-binary-xyz")

    def test_format_command_quotes(self):
        text = procs.format_command(["pi", "a b"], {"X": '{"k": 1}'})
        assert text == "export X='{\"k\": 1}'\npi 'a b'"
