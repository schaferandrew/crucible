"""Agent interface: how a benchmark run is launched and collected.

The runner owns everything agent-independent (workspace, run directory,
meta.json, timeouts); an Agent only says which command to run and how to turn
what it left behind into session.json / stdout.txt / token counts.
"""
from __future__ import annotations

import contextlib
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
# Benchmark-only mock MCP server. Tests opt in by declaring
# `mcp_servers: [mock-data]` in their prompt YAML; agents wire it up per run
# and never expect it in global configs, so fresh machines need no setup.
MOCK_MCP_SERVER = REPO_ROOT / "fixtures" / "mock-mcp-server" / "mock_server.py"

# Instruction sent alongside the attached prompt.txt. Kept to one line: on
# Windows npm CLIs are .cmd shims, and cmd.exe truncates multi-line arguments.
TASK_INSTRUCTION = "Complete the benchmark task described in the attached prompt.txt file."
WATCH_INSTRUCTION = "Read prompt.txt in the current directory and complete the benchmark task it describes."


@dataclass
class RunContext:
    test_id: str
    run_id: str
    run_dir: Path
    workspace: Path
    prompt_file: Path
    model: str | None
    watch: bool
    timeout: int
    title: str
    mcp_servers: list[str] = field(default_factory=list)


@dataclass
class Launch:
    cmd: list[str]
    cwd: Path | None = None
    # Extra variables layered over os.environ (also recorded in command.sh)
    env: dict[str, str] = field(default_factory=dict)


def mcp_server_commands(servers: list[str]) -> dict[str, list[str]]:
    """Launch commands for the MCP servers a test declares that crucible provides.

    Uses the current interpreter explicitly: Windows has no shebang support,
    and it keeps the server on the same Python everywhere.
    """
    commands = {}
    for name in servers:
        if name != "mock-data":
            print(f"[WARN] unknown MCP server '{name}' declared; ignoring")
            continue
        if not MOCK_MCP_SERVER.exists():
            print(f"[WARN] mock MCP server missing: {MOCK_MCP_SERVER}; tools unavailable")
            continue
        commands[name] = [sys.executable, str(MOCK_MCP_SERVER)]
    return commands


class Agent:
    name: str = ""
    label: str = ""
    executable: str = ""
    install_hint: str = ""
    # Model recorded (and used for the run-dir slug) when none is given
    default_model: str | None = None

    def validate(self, model: str | None) -> str | None:
        """Return an error message when this agent cannot run the model."""
        return None

    def prepare(self, ctx: RunContext) -> contextlib.AbstractContextManager:
        """Set up/tear down anything the run needs outside the run dir.

        Wraps launch, run and collect; teardown runs on every exit path
        (timeout, Ctrl+C, errors). Most agents need nothing here.
        """
        return contextlib.nullcontext()

    def launch(self, ctx: RunContext) -> Launch:
        raise NotImplementedError

    def collect(self, ctx: RunContext) -> None:
        """Post-process run artifacts into session.json / stdout.txt."""

    def token_usage(self, run_dir: Path) -> tuple[int, int] | None:
        return None

    def status(self, result: dict) -> str:
        if result["timed_out"]:
            return "TIMEOUT"
        if result["returncode"] == 0:
            return "COMPLETE"
        return f"ERROR (exit {result['returncode']})"
