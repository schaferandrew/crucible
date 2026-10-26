from crucible import providers, runner


def test_stream_timer_collects_reasoning_and_reports_progress():
    seen = []
    token = providers._PROGRESS.set(lambda elapsed, reasoning, answer: seen.append((reasoning, answer)))
    try:
        timer = providers._StreamTimer()
        timer.token(reasoning="Let me think. ")
        timer.token(answer="Red.")
    finally:
        providers._PROGRESS.reset(token)
    result = timer.result("Red.", None, None)
    assert result["reasoning"] == "Let me think. "
    assert seen and seen[0] == (len("Let me think. "), 0)  # throttled: later calls may be dropped


def test_interrupted_run_is_discarded_with_its_workspace(tmp_path):
    outside = tmp_path / "workspaces" / "run1"
    outside.mkdir(parents=True)
    run_dir = tmp_path / "runs" / "model" / "math" / "MATH-3" / "20261026_160456"
    run_dir.mkdir(parents=True)
    (run_dir / "prompt.txt").write_text("q", encoding="utf-8")
    (run_dir / "workspace").symlink_to(outside, target_is_directory=True)
    runner._discard(run_dir)
    assert not run_dir.exists() and not outside.exists()
    assert not (tmp_path / "runs" / "model").exists()  # emptied parents go too
    assert (tmp_path / "runs").exists()


def test_reasoning_levels_map_to_each_provider():
    from crucible.reasoning import request_params
    assert request_params("lmstudio", "default") == {}
    assert request_params("lmstudio", "off") == {"reasoning_effort": "none"}
    assert request_params("lmstudio", "high") == {"reasoning_effort": "high"}
    assert request_params("openrouter", "off") == {"reasoning": {"enabled": False}}
    assert request_params("openrouter", "low") == {"reasoning": {"effort": "low"}}
    assert request_params("ollama", "off") == {"think": False}


def test_each_reasoning_level_is_its_own_model(tmp_path):
    from crucible import plan as planner, workspace
    assert planner.model_slug("lmstudio/qwen/qwen3.5-9b", "off") == "lmstudio_qwen_qwen3.5-9b@reasoning-off"
    run = workspace.new_run_dir(tmp_path, "MATH-1", "lmstudio/qwen/qwen3.5-9b", {"category": "math"}, "off")
    assert run.run_id.startswith("lmstudio_qwen_qwen3.5-9b@reasoning-off/math/MATH-1/")
    plan = planner.build("lmstudio/qwen/qwen3.5-9b", ["MATH-1"], reasoning="off")
    assert "--reasoning off" in planner.command_line(plan, ["MATH-1"], None, None, None, None, None, False)


def test_opencode_cant_set_reasoning():
    from crucible import plan as planner
    plan = planner.build("lmstudio/x", ["CODE-1", "WRIT-2"], harness="opencode", reasoning="off")
    assert "opencode" in planner.reasoning_problem(plan)
    assert planner.reasoning_problem(planner.build("lmstudio/x", ["CODE-1"], harness="pi", reasoning="off")) is None
    assert planner.reasoning_problem(planner.build("lmstudio/x", ["CODE-1"], harness="opencode")) is None


def _run_dir(tmp_path, response, context, reasoning="default", agent="direct"):
    import json
    (tmp_path / "direct-response.json").write_text(json.dumps(response), encoding="utf-8")
    (tmp_path / "stdout.txt").write_text("", encoding="utf-8")
    return {"agent": agent, "reasoning": reasoning, "returncode": 0, "timed_out": False,
            "metrics": {"tokens_out": response.get("tokens_out")},
            "environment": {"inference": {"context_length": context}}}


def test_filling_a_small_context_is_a_setup_problem(tmp_path):
    from crucible import runner
    meta = _run_dir(tmp_path, {"tokens_in": 230, "tokens_out": 7957}, 8192)  # the Gemma run
    assert runner.classify_outcome(meta, tmp_path) == "context_limit"
    assert runner.context_limit_is_setup(meta) == 8192


def test_filling_a_big_context_is_a_runaway_that_counts(tmp_path):
    from crucible import runner
    meta = _run_dir(tmp_path, {"tokens_in": 230, "tokens_out": 9000, "finish_reason": "length"}, 65536)
    assert runner.classify_outcome(meta, tmp_path) == "context_limit"
    assert runner.context_limit_is_setup(meta) is None


def test_reasoning_off_needs_less_context(tmp_path):
    from crucible import runner
    meta = _run_dir(tmp_path, {"finish_reason": "length", "tokens_out": 9000}, 16384, reasoning="off")
    assert runner.context_limit_is_setup(meta) is None
    meta["reasoning"] = "default"
    assert runner.context_limit_is_setup(meta) == 16384


def test_chat_runs_refuse_a_small_loaded_context(monkeypatch):
    from crucible import environment, runner
    from crucible.agents import AGENTS
    monkeypatch.setattr(environment, "inference", lambda model: {"context_length": 8192})
    assert "32,768" in runner._context_problem(AGENTS["direct"], "lmstudio/x")
    assert runner._context_problem(AGENTS["direct"], "lmstudio/x", "off") is None
    monkeypatch.setattr(environment, "inference", lambda model: {"context_length": None})
    assert runner._context_problem(AGENTS["direct"], "openrouter/x") is None  # cloud: unknown, never refused


def test_reasoning_question_only_for_models_that_reason(monkeypatch, capsys):
    from crucible import reasoning, wizard
    monkeypatch.setattr(wizard, "choose", lambda question, options, default=0: "high")
    monkeypatch.setattr(reasoning, "levels", lambda model: reasoning.LEVELS)
    assert wizard.ask_reasoning("openrouter/qwen/qwen3.8-27b") == "high"   # asked
    monkeypatch.setattr(reasoning, "levels", lambda model: ("default",))
    assert wizard.ask_reasoning("lmstudio/plain-model") == "default"       # not asked
    monkeypatch.setattr(reasoning, "levels", lambda model: None)
    assert wizard.ask_reasoning("lmstudio/not-loaded") == "default"        # not asked, says why
    assert "Couldn't tell" in capsys.readouterr().out


def test_openrouter_support_comes_from_supported_parameters(monkeypatch):
    from crucible import providers, reasoning
    monkeypatch.setattr(providers, "_get_json", lambda url, headers=None: {"data": [
        {"id": "a/thinks", "supported_parameters": ["reasoning", "tools"]},
        {"id": "a/plain", "supported_parameters": ["tools"]}]})
    assert reasoning.supports("openrouter/a/thinks") is True
    assert reasoning.supports("openrouter/a/plain") is False
    assert reasoning.supports("openrouter/a/missing") is None


def test_lmstudio_reasoning_options_become_levels():
    from crucible.reasoning import lmstudio_options_to_levels as to_levels
    assert to_levels(["off", "on"]) == ("default", "off")                     # qwen3.5, gemma 4
    assert to_levels(["low", "medium", "high"]) == ("default", "low", "medium", "high")  # gpt-oss
    assert to_levels(["low", "medium", "high", "xhigh"]) == ("default", "low", "medium", "high")


def test_wizard_offers_only_the_levels_the_model_takes(monkeypatch):
    from crucible import reasoning, wizard
    offered = []
    monkeypatch.setattr(wizard, "choose", lambda q, options, default=0: offered.extend(v for _, v in options) or "off")
    monkeypatch.setattr(reasoning, "levels", lambda model: ("default", "off"))
    assert wizard.ask_reasoning("lmstudio/qwen/qwen3.5-9b") == "off"
    assert offered == ["default", "off"]
