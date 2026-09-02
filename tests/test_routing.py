from crucible import runner
from crucible.taxonomy import derive_suites


class TestShouldRunDirect:
    """Tool-requiring tests must never bypass the agent."""

    def test_needs_tools_never_direct(self):
        assert runner.should_run_direct("opencode", True, "openrouter/z-ai/glm-5.3-flash") is False
        assert runner.should_run_direct("opencode", True, "ollama/qwen3:9b") is False

    def test_no_tools_with_direct_capable_model(self):
        assert runner.should_run_direct("opencode", False, "openrouter/z-ai/glm-5.3-flash") is True
        assert runner.should_run_direct("opencode", False, "ollama/qwen3:9b") is True
        assert runner.should_run_direct("opencode", False, "lmstudio/gpt-oss-20b") is True

    def test_pool_agent_never_direct(self):
        assert runner.should_run_direct("pool", False, "openrouter/z-ai/glm-5.3-flash") is False

    def test_no_model_never_direct(self):
        assert runner.should_run_direct("opencode", False, None) is False

    def test_unsupported_provider_never_direct(self):
        assert runner.should_run_direct("opencode", False, "someprovider/mistral-7b") is False


class TestPromptToolFlags:
    """The needs_tools flag must be declared on every prompt (no silent defaults)."""

    def test_every_prompt_declares_needs_tools(self, prompts_dir=None):
        from crucible.runner import PROMPTS_DIR
        import yaml
        from pathlib import Path

        undeclared = []
        for path in sorted(PROMPTS_DIR.glob("*.yaml")):
            data = yaml.safe_load(path.read_text())
            if "needs_tools" not in data:
                undeclared.append(path.name)
        assert undeclared == [], f"Prompts missing explicit needs_tools: {undeclared}"

    def test_e1_requires_tools(self):
        import yaml
        from crucible.runner import PROMPTS_DIR
        data = yaml.safe_load((PROMPTS_DIR / "E1.yaml").read_text())
        assert data["needs_tools"] is True  # today's-news task requires web access


class TestSuitesIncludeAllPrompts:
    def test_every_prompt_reachable_via_its_suite(self):
        from crucible.runner import PROMPTS_DIR
        test_ids = sorted(p.stem for p in PROMPTS_DIR.glob("*.yaml"))
        suites = derive_suites(test_ids)
        reachable = [t for ts in suites.values() for t in ts]
        assert sorted(reachable) == test_ids
