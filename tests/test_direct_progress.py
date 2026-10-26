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
