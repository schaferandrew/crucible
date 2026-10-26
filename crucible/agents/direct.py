"""direct: text-only run straight against the provider API (no agent, no tools).

Only for prompts declaring needs_tools: false, on a provider crucible can call
itself (crucible.providers). Fixture contents are inlined into the prompt,
since there are no file tools; the exact prompt sent is kept in prompt.txt.
The response is streamed, so tokens and time to first token are recorded.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from crucible import providers
from crucible.agents.base import Agent, RunContext
from crucible.workspace import inline_fixtures

RESPONSE_FILENAME = "direct-response.json"  # timing + usage of the one response


class _Progress:
    """One live status line while a response streams, so a long think doesn't look like a hang."""

    def __init__(self):
        self.shown = False

    def show(self, elapsed: float, reasoning: int, answer: int) -> None:
        if not sys.stderr.isatty():
            return
        clock = f"{int(elapsed) // 60}m{int(elapsed) % 60:02d}s"
        what = (f"answering · {answer:,} chars" if answer else "thinking") + (
            f" · {reasoning:,} chars of reasoning" if reasoning else "")
        sys.stderr.write(f"\r\033[K  {clock}  {what}")
        sys.stderr.flush()
        self.shown = True

    def done(self) -> None:
        if self.shown:
            sys.stderr.write("\r\033[K")
            sys.stderr.flush()


class DirectAgent(Agent):
    name = "direct"
    label = "Direct API (no tool use)"
    uses_workspace = False
    builtin_web_tools: list[str] = []
    reasoning_levels = ("default", "off", "low", "medium", "high")

    def validate(self, model: str | None, prompt_def: dict) -> str | None:
        if prompt_def.get("needs_tools", True):
            return ("this test requires tool access; refusing to run it directly. "
                    "Use an agent harness (--agent opencode or pi).")
        try:
            providers.split_model(model or "")
        except ValueError as exc:
            return f"direct mode needs a provider crucible can call: {exc}"
        return None

    def run(self, ctx: RunContext) -> dict:
        prompt = inline_fixtures(ctx.prompt_file.read_text(encoding="utf-8"), ctx.fixtures)
        ctx.prompt_file.write_text(prompt, encoding="utf-8")  # the exact prompt sent
        stdout, stderr, timed_out = "", "", False
        progress = _Progress()
        try:
            response = providers.complete(ctx.model, prompt, ctx.timeout, on_progress=progress.show,
                                          reasoning=ctx.reasoning)
        except providers.StreamTimeout as exc:
            # Keep what streamed: a runaway answer is itself the result
            response, timed_out = exc.partial, True
            stderr = f"Direct runner: response still streaming after {ctx.timeout}s; stopped"
        except Exception as exc:
            response, stderr = None, f"Direct runner error: {exc}"
        progress.done()
        if response is not None:
            stdout = response.pop("text")
            # Kept apart from the answer: checks and the dashboard only ever see the answer
            reasoning = response.pop("reasoning", "")
            response["reasoning_chars"] = len(reasoning)
            if reasoning:
                (ctx.run_dir / "reasoning.txt").write_text(reasoning, encoding="utf-8")
            (ctx.run_dir / RESPONSE_FILENAME).write_text(json.dumps(response, indent=2),
                                                         encoding="utf-8")
        (ctx.run_dir / "stdout.txt").write_text(stdout, encoding="utf-8")
        (ctx.run_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
        return {"returncode": 1 if stderr else 0, "timed_out": timed_out}

    def _response(self, run_dir: Path) -> dict | None:
        try:
            return json.loads((run_dir / RESPONSE_FILENAME).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def token_usage(self, run_dir: Path) -> tuple[int, int] | None:
        response = self._response(run_dir)
        if not response or response.get("tokens_in") is None:
            return None
        return response["tokens_in"], response.get("tokens_out")

    def response_timings(self, run_dir: Path) -> list[dict]:
        response = self._response(run_dir)
        return [response] if response else []
