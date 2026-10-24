"""Agents (harnesses) that execute benchmark tests.

Each harness is one module subclassing base.Agent. To add one, write
agents/<name>.py and list an instance in AGENTS below; `--agent <name>`,
preflight checks and install hints all come from this registry.
"""
from __future__ import annotations

from crucible.agents.base import Agent, Launch, RunContext
from crucible.agents.opencode import OpenCodeAgent
from crucible.agents.pi import PiAgent
from crucible.agents.pool import PoolAgent

AGENTS: dict[str, Agent] = {a.name: a for a in (OpenCodeAgent(), PiAgent(), PoolAgent())}
DEFAULT_AGENT = "opencode"

__all__ = ["AGENTS", "DEFAULT_AGENT", "Agent", "Launch", "RunContext"]
