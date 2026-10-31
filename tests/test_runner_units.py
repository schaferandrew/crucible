import json
import sys

import pytest
import yaml

from crucible import console, cost, metrics, procs, session, workspace
from crucible.agents import AGENTS, Agent, RunContext
from crucible.agents import pi as pi_agent
from crucible.agents.base import available_mcp_servers
from crucible.mcp_servers import web_server


def _ctx(tmp_path, **overrides):
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    fields = dict(task_id="interest-cli-open-ended", run_path="m/interest-cli-open-ended/ts", run_dir=tmp_path,
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

    def test_lmstudio_run_ignores_user_agent_dir(self, tmp_path):
        # the user's ~/.pi/agent may hold an empty stored lmstudio credential,
        # which would override the apiKey registered here
        launch = AGENTS["pi"].launch(_ctx(tmp_path, model="lmstudio/qwen/qwen3.5-9b"))
        assert launch.env["PI_CODING_AGENT_DIR"] == str(tmp_path / pi_agent.AGENT_DIRNAME)
        provider = json.loads(launch.env["CRUCIBLE_PI_CONFIG"])["providers"]["lmstudio"]
        assert provider["apiKey"] == "lmstudio"
        assert provider["api"] == "openai-completions"
        assert provider["models"][0]["id"] == "qwen/qwen3.5-9b"

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


class TestPiValidate:
    def test_openrouter_needs_key(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        assert AGENTS["pi"].validate("openrouter/x/y", {})
        monkeypatch.setenv("OPENROUTER_API_KEY", "k")
        assert AGENTS["pi"].validate("openrouter/x/y", {}) is None
        assert AGENTS["pi"].validate("ollama/q", {}) is None


class TestOpenCodeLaunch:
    @pytest.fixture(autouse=True)
    def catalog(self, monkeypatch):
        """opencode's model catalog, without shelling out to opencode."""
        from crucible.agents import opencode as opencode_agent
        monkeypatch.setattr(opencode_agent, "_known_models", lambda provider: frozenset({"openrouter/x/y"}))
        monkeypatch.setattr(opencode_agent.providers, "fetch_openrouter_pricing", lambda model_id: (0.06, 0.12))
        monkeypatch.setattr(opencode_agent, "_major_version", lambda: 1)

    def test_v1_runs_with_dir_flag(self, tmp_path):
        launch = AGENTS["opencode"].launch(_ctx(tmp_path, model="openrouter/x/y"))
        assert "--dir" in launch.cmd and "--standalone" not in launch.cmd and launch.cwd is None

    def test_v2_runs_standalone_in_the_workspace(self, tmp_path, monkeypatch):
        from crucible.agents import opencode as opencode_agent
        monkeypatch.setattr(opencode_agent, "_major_version", lambda: 2)
        ctx = _ctx(tmp_path, model="openrouter/x/y", mcp_servers=["mock-data"])
        launch = AGENTS["opencode"].launch(ctx)
        # --standalone: the shared 2.x background service never sees a run's config
        assert launch.cmd[:5] == ["opencode", "run", "--standalone", "--format", "json"]
        assert "--dir" not in launch.cmd and launch.cwd == ctx.workspace
        assert launch.env["PWD"] == str(ctx.workspace)
        assert "OPENCODE_CONFIG_CONTENT" in launch.env
        watch = AGENTS["opencode"].launch(_ctx(tmp_path, watch=True))
        assert watch.cmd[:2] == ["opencode", "--standalone"]

    def test_v2_export_reading(self, tmp_path):
        from crucible.agents import opencode as opencode_agent
        (tmp_path / "session.json").write_text(json.dumps({"info": {}, "messages": [
            {"type": "user", "text": "do it", "time": {"created": 1000}},
            {"type": "assistant", "time": {"created": 1000, "streamed": 2500, "completed": 4000},
             "content": [{"type": "tool", "name": "read"}, {"type": "text", "text": "done"}],
             "cost": 0.01, "tokens": {"input": 10, "output": 4, "reasoning": 2}},
            {"type": "idle", "outcome": "succeeded"},
        ]}), encoding="utf-8")
        agent = AGENTS["opencode"]
        assert agent.token_usage(tmp_path) == (10, 6)
        assert agent.cost_estimate(tmp_path) == 0.01
        # time.streamed isn't the first token, so there's no TTFT and no decode speed
        assert agent.response_timings(tmp_path) == [{"ttft_s": None, "duration_s": 3.0, "tokens_out": 6}]
        assert metrics.timing_summary(agent.response_timings(tmp_path))["output_tokens_per_s"] is None
        session = json.loads((tmp_path / "session.json").read_text())
        assert opencode_agent.message_texts(session) == ["done"]
        assert session_mod_count(tmp_path / "session.json") == 1

    def test_v2_transcript_from_export(self):
        from crucible.agents import opencode as opencode_agent
        lines = opencode_agent.transcript_v2({"messages": [
            {"type": "assistant", "content": [
                {"type": "tool", "name": "bash", "state": {"input": {"command": "npm test"},
                                                          "content": [{"type": "text", "text": "12 passed"}]}},
                {"type": "text", "text": "All green."}]}]})
        assert lines == ["⏺ bash(command=npm test)", "  ⎿ 12 passed", "⏺ All green."]

    def test_mcp_via_config_content(self, tmp_path):
        launch = AGENTS["opencode"].launch(_ctx(tmp_path, mcp_servers=["mock-data"],
                                                model="openrouter/x/y"))
        config = json.loads(launch.env["OPENCODE_CONFIG_CONTENT"])
        assert config["mcp"]["mock-data"]["command"][0] == sys.executable
        assert launch.cmd[-2:] == ["-m", "openrouter/x/y"]

    def test_catalogued_openrouter_model_passes_through(self, tmp_path):
        launch = AGENTS["opencode"].launch(_ctx(tmp_path, model="openrouter/x/y"))
        assert "OPENCODE_CONFIG_CONTENT" not in launch.env

    def test_uncatalogued_openrouter_model_routed_via_compatible_provider(self, tmp_path):
        launch = AGENTS["opencode"].launch(_ctx(tmp_path, model="openrouter/new/model-1"))
        provider = json.loads(launch.env["OPENCODE_CONFIG_CONTENT"])["provider"]["openrouter-extra"]
        assert provider["options"]["baseURL"] == "https://openrouter.ai/api/v1"
        # The key is referenced, never written into the config (or command.sh)
        assert provider["options"]["apiKey"] == "{env:OPENROUTER_API_KEY}"
        assert provider["models"]["new/model-1"]["cost"] == {"input": 0.06, "output": 0.12}
        assert launch.cmd[-2:] == ["-m", "openrouter-extra/new/model-1"]

    def test_token_usage(self, tmp_path):
        (tmp_path / "session.json").write_text(json.dumps({"messages": [
            {"info": {"tokens": {"input": 5, "output": 2, "reasoning": 1}}},
            {"info": {"tokens": {"input": 7, "output": 3}}},
        ]}), encoding="utf-8")
        assert AGENTS["opencode"].token_usage(tmp_path) == (12, 6)


def session_mod_count(path):
    return session.count_tool_calls(path)


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
        text = procs.format_command(["pi"], {"OPENROUTER_API_KEY": "sk-1", "MODEL": "m"})
        assert "sk-1" not in text and "MODEL=m" in text


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
                           "response_time_avg_s": 2.0, "output_tokens_per_s": None}

    def test_decode_speed_is_tokens_over_generation_time(self):
        summary = metrics.timing_summary([
            {"ttft_s": 1.0, "duration_s": 3.0, "tokens_out": 60},    # 2 s decoding
            {"ttft_s": 2.0, "duration_s": 4.0, "tokens_out": 20},    # 2 s decoding
            {"ttft_s": None, "duration_s": 9.0, "tokens_out": 900},  # no TTFT: left out, not guessed
            {"ttft_s": 1.0, "duration_s": 5.0, "tokens_out": None},  # no token count: left out
        ])
        assert summary["output_tokens_per_s"] == 20.0

    def test_decode_speed_unknown_without_generation_time(self):
        assert metrics.timing_summary([{"ttft_s": 1.0, "duration_s": 1.0, "tokens_out": 5}])["output_tokens_per_s"] is None

    def test_pi_timings_carry_each_responses_output_tokens(self, tmp_path):
        (tmp_path / pi_agent.TIMING_FILENAME).write_text(
            json.dumps({"request_start": 0, "first_token": 500, "end": 2500}) + "\n"
            + json.dumps({"request_start": 3000, "first_token": 3500, "end": 4500}) + "\n", encoding="utf-8")
        entries = [{"type": "message", "message": {"role": "user", "content": []}},
                   {"type": "message", "message": {"role": "assistant", "usage": {"output": 40}, "content": []}},
                   {"type": "message", "message": {"role": "toolResult", "content": []}},
                   {"type": "message", "message": {"role": "assistant", "usage": {"output": 30}, "content": []}}]
        _pi_session(tmp_path, entries)
        timings = AGENTS["pi"].response_timings(tmp_path)
        assert [t["tokens_out"] for t in timings] == [40, 30]
        assert metrics.timing_summary(timings)["output_tokens_per_s"] == 23.3  # 70 tokens over 2.0 s + 1.0 s of decoding

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
            {"ttft_s": None, "duration_s": 3.0, "tokens_out": None},
            {"ttft_s": None, "duration_s": None, "tokens_out": None}]

    def test_metrics_line_shows_ttft(self):
        line = console.metrics_summary({"ttft_s": 0.21, "ttft_avg_s": 0.3, "model_responses": 3,
                                        "response_time_avg_s": 1.5})
        assert line == "TTFT 0.21s (avg 0.30s), 3 model responses, avg 1.50s"

    def test_metrics_line_shows_decode_speed(self):
        assert "31.5 tok/s" in console.metrics_summary({"output_tokens_per_s": 31.5})


class TestCost:
    def test_billed_delta_for_openrouter(self):
        usage = iter([1.25, 1.2875])
        with cost.BilledCost("openrouter/x/y", read_usage=lambda: next(usage)) as bill:
            pass
        assert bill.usd == 0.0375

    def test_billed_waits_for_lagging_usage(self):
        usage = iter([2.0, 2.0, 2.01])
        sleeps = []
        with cost.BilledCost("openrouter/x/y", read_usage=lambda: next(usage),
                             sleep=sleeps.append) as bill:
            pass
        assert bill.usd == 0.01 and len(sleeps) == 1

    def test_not_billed_for_other_providers_or_unreachable(self):
        with cost.BilledCost("ollama/qwen3", read_usage=lambda: 1 / 0) as local:
            pass
        with cost.BilledCost("openrouter/x/y", read_usage=lambda: None) as offline:
            pass
        assert local.usd is None and offline.usd is None

    def test_billed_off_for_parallel_sweeps(self, monkeypatch):
        monkeypatch.setenv("CRUCIBLE_BILLED_COST", "0")
        with cost.BilledCost("openrouter/x/y", read_usage=lambda: 1 / 0) as bill:
            pass
        assert bill.usd is None

    def test_billed_beats_estimate(self):
        assert cost.run_cost("pi", 0.5, 0.4) == {"cost_usd": 0.4, "cost_source": "openrouter_billed"}
        assert cost.run_cost("pi", 0.5, None) == {"cost_usd": 0.5, "cost_source": "pi_estimate"}
        assert cost.run_cost("pi", None, None) == {"cost_usd": None, "cost_source": None}

    def test_pi_estimate_sums_usage_cost(self, tmp_path):
        priced = {**USAGE, "cost": {"total": 0.002}}
        entries = [e if e.get("message", {}).get("role") != "assistant" else
                   {**e, "message": {**e["message"], "usage": priced}} for e in PI_ENTRIES]
        _pi_session(tmp_path, entries)
        assert AGENTS["pi"].cost_estimate(tmp_path) == pytest.approx(0.004)

    def test_pi_estimate_unknown_without_cost(self, tmp_path):
        _pi_session(tmp_path, PI_ENTRIES)
        assert AGENTS["pi"].cost_estimate(tmp_path) is None

    def test_opencode_estimate(self, tmp_path):
        (tmp_path / "session.json").write_text(json.dumps({"messages": [
            {"info": {"role": "user"}},
            {"info": {"role": "assistant", "cost": 0.01}},
            {"info": {"role": "assistant", "cost": 0.02}},
        ]}), encoding="utf-8")
        assert AGENTS["opencode"].cost_estimate(tmp_path) == pytest.approx(0.03)

    def test_metrics_line_shows_cost(self):
        assert console.metrics_summary({"cost_usd": 0.01234, "cost_source": "pi_estimate"}) == \
            "cost $0.0123 (pi_estimate)"

    def test_metrics_include_cost(self, tmp_path):
        m = metrics.extract_metrics(tmp_path, AGENTS["pi"], billed_usd=0.1)
        assert (m["cost_usd"], m["cost_source"]) == (0.1, "openrouter_billed")


class TestWebMcpServer:
    def _call(self, name, **arguments):
        return web_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                  "params": {"name": name, "arguments": arguments}})["result"]

    def test_search_listed_only_with_key(self, monkeypatch):
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
        listed = web_server.handle({"id": 1, "method": "tools/list"})["result"]["tools"]
        assert [t["name"] for t in listed] == ["web_fetch"]
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "k")
        listed = web_server.handle({"id": 1, "method": "tools/list"})["result"]["tools"]
        assert {t["name"] for t in listed} == {"web_search", "web_fetch"}

    def test_bad_input_is_a_tool_error(self):
        assert self._call("web_fetch", url="file:///etc/passwd")["isError"] is True
        assert self._call("web_fetch")["isError"] is True  # missing url

    def test_fetch_reduces_html_and_truncates(self, monkeypatch):
        page = "<html><style>x{}</style><script>evil()</script><p>Hello &amp; hi</p></html>"
        monkeypatch.setattr(web_server, "_get", lambda url, headers=None: (200, "text/html", page))
        text = self._call("web_fetch", url="https://example.com", max_chars=9)["content"][0]["text"]
        assert text.startswith("HTTP 200 (text/html)\n\nHello & h") and "evil" not in text
        assert "[truncated at 9 characters]" in text

    def test_notifications_get_no_response(self):
        assert web_server.handle({"method": "notifications/initialized"}) is None

    def test_declared_and_recorded(self):
        assert "web" in workspace.load_task("RSCH-2")["mcp_servers"]
        assert available_mcp_servers(["web", "mock-data", "nope"]) == ["web", "mock-data"]
