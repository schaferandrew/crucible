from crucible.agents import AGENTS
from crucible.taxonomy import derive_suites


class TestDirectAgentGate:
    """Direct mode is an explicit harness; tool-requiring tests can never use it."""

    def _check(self, needs_tools, model):
        return AGENTS["direct"].validate(model, {"needs_tools": needs_tools})

    def test_allowed_on_direct_providers(self):
        for model in ("openrouter/z-ai/glm-5.3-flash", "ollama/qwen3:9b", "lmstudio/gpt-oss-20b"):
            assert self._check(False, model) is None

    def test_needs_tools_never_direct(self):
        assert "requires tool access" in self._check(True, "openrouter/z-ai/glm-5.3-flash")

    def test_undeclared_needs_tools_defaults_to_refused(self):
        assert AGENTS["direct"].validate("ollama/q", {}) is not None

    def test_no_model_or_unsupported_provider(self):
        assert self._check(False, None) is not None
        assert self._check(False, "someprovider/mistral-7b") is not None

    def test_direct_needs_no_workspace_or_cli(self):
        assert AGENTS["direct"].uses_workspace is False
        assert AGENTS["direct"].executable is None


class TestPromptToolFlags:
    """The needs_tools flag must be declared on every prompt (no silent defaults)."""

    def test_every_prompt_declares_needs_tools(self, prompts_dir=None):
        from crucible.workspace import PROMPTS_DIR
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
        from crucible.workspace import PROMPTS_DIR
        data = yaml.safe_load((PROMPTS_DIR / "E1.yaml").read_text())
        assert data["needs_tools"] is True  # today's-news task requires web access


class TestSuitesIncludeAllPrompts:
    def test_every_prompt_reachable_via_its_suite(self):
        from crucible.workspace import PROMPTS_DIR
        test_ids = sorted(p.stem for p in PROMPTS_DIR.glob("*.yaml"))
        suites = derive_suites(test_ids)
        reachable = [t for ts in suites.values() for t in ts]
        assert sorted(reachable) == test_ids
