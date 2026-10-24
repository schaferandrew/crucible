import json
import sys

import pytest
import yaml

from crucible import console, metrics, procs, session
from crucible.agents import AGENTS, Agent, RunContext
from crucible.agents import pi as pi_agent
from crucible.agents import pool as pool_agent


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
        found = metrics.extract_metrics(tmp_path, AGENTS["pi"])
        assert found["tool_calls"] == 1
        assert found["tests_passed"] == 3
        assert (found["tokens_in"], found["tokens_out"]) == (300, 20)

    def test_collect_without_session_is_harmless(self, tmp_path):
        AGENTS["pi"].collect(_ctx(tmp_path))
        assert not (tmp_path / "session.json").exists()


class TestPiLaunch:
    def test_default_model_has_no_flags_or_config(self, tmp_path):
        launch = AGENTS["pi"].launch(_ctx(tmp_path))
        assert "--model" not in launch.cmd
        # only the timing hook is configured
        assert json.loads(launch.env["CRUCIBLE_PI_CONFIG"]) == {
            "timingFile": str(tmp_path / pi_agent.TIMING_FILENAME)}
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
        # pi reads OPENROUTER_API_KEY itself; no provider is registered
        assert "providers" not in json.loads(launch.env["CRUCIBLE_PI_CONFIG"])

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
        assert AGENTS["pi"].validate("openrouter/x/y", {})
        monkeypatch.setenv("OPENROUTER_API_KEY", "k")
        assert AGENTS["pi"].validate("openrouter/x/y", {}) is None
        assert AGENTS["pi"].validate("ollama/q", {}) is None


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

    def test_format_command_redacts_secrets(self):
        text = procs.format_command(["pool"], {"POOLSIDE_API_KEY": "sk-1", "MODEL": "m"})
        assert "sk-1" not in text and "MODEL=m" in text


class TestPoolConfig:
    def test_tenant_mode(self):
        for model in (None, "pool"):
            mode = pool_agent.pool_mode(model)
            assert mode.env == {} and mode.exec_flags == [] and mode.standalone_model is None

    def test_ollama_standalone_pins_base_url(self, monkeypatch):
        # With tenant credentials present, pool ignores settings.yaml's
        # api_url — the base URL must be pinned or inference silently goes
        # to Poolside cloud instead of ollama
        monkeypatch.delenv("POOLSIDE_API_KEY", raising=False)
        mode = pool_agent.pool_mode("ollama/laguna-xs-2.1:nvfp4")
        assert mode.env["POOLSIDE_STANDALONE_MODEL"] == "laguna-xs-2.1:nvfp4"
        assert mode.env["POOLSIDE_STANDALONE_BASE_URL"] == pool_agent.OLLAMA_OPENAI_API
        assert mode.env["POOLSIDE_API_KEY"] == "ollama"
        assert mode.exec_flags == [] and mode.standalone_model == "laguna-xs-2.1:nvfp4"

    def test_openrouter_standalone(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        mode = pool_agent.pool_mode("openrouter/deepseek/deepseek-v4-flash")
        assert mode.env["POOLSIDE_API_KEY"] == "test-key"
        assert mode.env["POOLSIDE_STANDALONE_BASE_URL"] == pool_agent.OPENROUTER_API
        assert mode.standalone_model == "deepseek/deepseek-v4-flash"
        assert mode.exec_flags == ["--sandbox", "disabled"]

    def test_openrouter_key_never_lands_in_command_sh(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-secret")
        mode = pool_agent.pool_mode("openrouter/x/y")
        assert "sk-secret" not in procs.format_command(["pool"], mode.env)

    def test_validate_openrouter_needs_key(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        assert AGENTS["pool"].validate("openrouter/x/y", {})
        assert AGENTS["pool"].validate(None, {}) is None


class TestPoolLaunch:
    def test_headless(self, tmp_path):
        ctx = _ctx(tmp_path)
        cmd = AGENTS["pool"].launch(ctx).cmd
        assert cmd[:2] == ["pool", "exec"] and "--unsafe-auto-allow" in cmd
        assert cmd[-2:] == ["-o", "json"]

    def test_watch_single_line_and_auto_approve(self, tmp_path):
        cmd = AGENTS["pool"].launch(_ctx(tmp_path, watch=True, model="ollama/m")).cmd
        assert "always-allow" in cmd and cmd[cmd.index("-m") + 1] == "m"
        assert all("\n" not in arg for arg in cmd)

    def test_exit_4_is_task_failed(self):
        assert AGENTS["pool"].status({"timed_out": False, "returncode": 4}).startswith("TASK FAILED")
        assert AGENTS["pool"].status({"timed_out": False, "returncode": 0}) == "COMPLETE"


class TestPoolMcpSettings:
    def test_add_then_remove_restores_user_settings(self, tmp_path, monkeypatch):
        settings = tmp_path / "settings.yaml"
        settings.write_text("theme: dark\n", encoding="utf-8")
        monkeypatch.setattr(pool_agent, "POOL_SETTINGS", settings)
        added = pool_agent.add_mcp_servers(["mock-data"])
        assert added == ["mock-data"]
        entry = yaml.safe_load(settings.read_text(encoding="utf-8"))["mcp_servers"]["mock-data"]
        # pool rejects a list-valued command (verified against pool 1.0.16)
        assert entry["command"] == sys.executable and isinstance(entry["args"], list)
        pool_agent.remove_mcp_servers(added)
        assert settings.read_text(encoding="utf-8") == "theme: dark\n"

    def test_existing_entry_left_alone(self, tmp_path, monkeypatch):
        settings = tmp_path / "settings.yaml"
        settings.write_text("mcp_servers:\n  mock-data:\n    command: [mine]\n", encoding="utf-8")
        monkeypatch.setattr(pool_agent, "POOL_SETTINGS", settings)
        assert pool_agent.add_mcp_servers(["mock-data"]) == []
        assert "mine" in settings.read_text(encoding="utf-8")

    def test_prepare_cleans_up_on_error(self, tmp_path, monkeypatch):
        settings = tmp_path / "settings.yaml"
        monkeypatch.setattr(pool_agent, "POOL_SETTINGS", settings)
        with pytest.raises(KeyboardInterrupt):
            with AGENTS["pool"].prepare(_ctx(tmp_path, mcp_servers=["mock-data"])):
                assert "mock-data" in settings.read_text(encoding="utf-8")
                raise KeyboardInterrupt
        assert "mock-data" not in settings.read_text(encoding="utf-8")


class TestPoolCaptures:
    def test_split_output(self, tmp_path):
        (tmp_path / "stdout.txt").write_text("\n".join([
            json.dumps({"type": "assistantMessage", "message": "hello"}),
            json.dumps({"type": "toolCall", "name": "shell", "args": {"cmd": "ls"}}),
            '{"type":"toolCallResult","res',  # truncated by a timeout
        ]) + "\n", encoding="utf-8")
        pool_agent.split_output(tmp_path)
        assert len(json.loads((tmp_path / "session.json").read_text())) == 2
        assert "⏺ shell(cmd=ls)" in (tmp_path / "stdout.txt").read_text(encoding="utf-8")

    def test_non_json_stdout_untouched(self, tmp_path):
        (tmp_path / "stdout.txt").write_text("plain text\n", encoding="utf-8")
        pool_agent.split_output(tmp_path)
        assert not (tmp_path / "session.json").exists()

    def test_watch_trajectory_export_and_tokens(self, tmp_path, monkeypatch):
        trajectories = tmp_path / "trajectories"
        trajectories.mkdir()
        monkeypatch.setenv("CRUCIBLE_POOL_TRAJECTORIES_DIR", str(trajectories))
        ctx = _ctx(tmp_path, watch=True)
        (trajectories / "trajectory-standalone_1.ndjson").write_text("\n".join(json.dumps(e) for e in [
            {"type": "session.start", "session_start": {"working_directories": [str(ctx.workspace)]}},
            {"type": "tool_call.parsed", "tool_call_parsed": {"name": "get_news", "args": {}}},
            {"type": "tool_call.inference.end", "tool_call_inference_end": {"input_tokens": 40, "output_tokens": 4}},
            {"type": "tool_call.result", "tool_call_result": {"tool_name": "get_news", "observation": "MN news"}},
            {"type": "assistant_message.end", "assistant_message_end": {"assistant_message": "Done"}},
        ]) + "\n", encoding="utf-8")
        AGENTS["pool"].collect(ctx)
        assert [e["type"] for e in json.loads((tmp_path / "session.json").read_text())] == \
            ["toolCall", "toolCallResult", "assistantMessage"]
        assert AGENTS["pool"].token_usage(tmp_path) == (40, 4)

    def test_other_workspace_trajectory_ignored(self, tmp_path, monkeypatch):
        trajectories = tmp_path / "trajectories"
        trajectories.mkdir()
        monkeypatch.setenv("CRUCIBLE_POOL_TRAJECTORIES_DIR", str(trajectories))
        (trajectories / "trajectory-x.ndjson").write_text(json.dumps(
            {"session_start": {"working_directories": ["/elsewhere"]}}) + "\n", encoding="utf-8")
        assert pool_agent.find_trajectory(str(tmp_path / "workspace")) is None


class TestRegistry:
    def test_every_agent_is_complete(self):
        for name, agent in AGENTS.items():
            assert agent.name == name and agent.label
            # A CLI harness implements launch(); anything else overrides run()
            assert type(agent).launch is not Agent.launch or type(agent).run is not Agent.run
            assert not agent.executable or agent.install_hint


class TestMetricsSummary:
    def test_only_known_metrics_shown(self):
        assert console.metrics_summary({"tool_calls": 2, "tests_passed": 3, "tests_failed": None,
                                        "tokens_in": None, "tokens_out": None}) == \
            "2 tool calls, tests 3 passed"

    def test_nothing_known(self):
        assert console.metrics_summary({}) == ""


class TestTiming:
    def test_summary(self):
        summary = metrics.timing_summary([
            {"ttft_s": 0.5, "duration_s": 2.0},
            {"ttft_s": None, "duration_s": 1.0},
            {"ttft_s": 0.3, "duration_s": 3.0},
        ])
        assert summary == {"model_responses": 3, "ttft_s": 0.5, "ttft_avg_s": 0.4,
                           "response_time_avg_s": 2.0}

    def test_summary_empty_is_all_unknown(self):
        assert set(metrics.timing_summary([]).values()) == {None}

    def test_pi_timing_file(self, tmp_path):
        (tmp_path / pi_agent.TIMING_FILENAME).write_text(
            json.dumps({"request_start": 1000, "first_token": 1250, "end": 2000}) + "\n"
            + json.dumps({"request_start": 3000, "first_token": None, "end": 3500}) + "\n"
            + '{"request_st', encoding="utf-8")  # truncated by a kill
        assert AGENTS["pi"].response_timings(tmp_path) == [
            {"ttft_s": 0.25, "duration_s": 1.0}, {"ttft_s": None, "duration_s": 0.5}]

    def test_opencode_message_times(self, tmp_path):
        (tmp_path / "session.json").write_text(json.dumps({"messages": [
            {"info": {"role": "user", "time": {"created": 0}}},
            {"info": {"role": "assistant", "time": {"created": 1000, "completed": 4000}}},
            {"info": {"role": "assistant", "time": {"created": 5000}}},  # interrupted
        ]}), encoding="utf-8")
        assert AGENTS["opencode"].response_timings(tmp_path) == [
            {"ttft_s": None, "duration_s": 3.0}, {"ttft_s": None, "duration_s": None}]

    def test_metrics_line_shows_ttft(self):
        line = console.metrics_summary({"ttft_s": 0.21, "ttft_avg_s": 0.3, "model_responses": 3,
                                        "response_time_avg_s": 1.5})
        assert line == "TTFT 0.21s (avg 0.30s), 3 model responses, avg 1.50s"
