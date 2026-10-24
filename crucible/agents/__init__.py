"""Agents that execute benchmark tests (see base.Agent)."""
from __future__ import annotations

from crucible.agents.base import Agent, Launch, RunContext
from crucible.agents.opencode import OpenCodeAgent
from crucible.agents.pi import PiAgent

AGENTS: dict[str, Agent] = {a.name: a for a in (OpenCodeAgent(), PiAgent())}
DEFAULT_AGENT = "opencode"

__all__ = ["AGENTS", "DEFAULT_AGENT", "Agent", "Launch", "RunContext"]
