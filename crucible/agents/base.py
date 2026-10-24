"""Agent interface: how a benchmark run is launched and collected.

The runner owns everything agent-independent (run directory, meta.json,
console output); an Agent says how to run one test and how to read what the
run left behind (session.json / stdout.txt / tokens / timings).

Most agents are CLIs: they implement launch() (and usually collect()), and the
default run() does the rest. An agent that is not a subprocess (direct API)
overrides run() instead.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from crucible import procs

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# MCP servers crucible ships, by the name prompts declare under mcp_servers:.
# Agents wire them up per run, never in global configs, so fresh machines
# need no setup.
BUILTIN_MCP_SERVERS = {
    "mock-data": REPO_ROOT / "fixtures" / "mock-mcp-server" / "mock_server.py",
}

# Instruction sent alongside the attached prompt.txt. Kept to one line: on
# Windows npm CLIs are .cmd shims, and cmd.exe truncates multi-line arguments.
TASK_INSTRUCTION = "Complete the benchmark task described in the attached prompt.txt file."
WATCH_INSTRUCTION = "Read prompt.txt in the current directory and complete the benchmark task it describes."


@dataclass
class RunContext:
    test_id: str
    run_id: str
    run_dir: Path
    prompt_file: Path
    model: str | None
    watch: bool
    timeout: int
    title: str
    workspace: Path | None = None   # None for agents with uses_workspace = False
    mcp_servers: list[str] = field(default_factory=list)
    fixtures: list[str] = field(default_factory=list)


@dataclass
class Launch:
    cmd: list[str]
    cwd: Path | None = None
    # Extra variables layered over os.environ (also recorded in command.sh)
    env: dict[str, str] = field(default_factory=dict)


def mcp_server_commands(servers: list[str]) -> dict[str, list[str]]:
    """Launch commands for the declared MCP servers that crucible provides.

    Uses the current interpreter explicitly: Windows has no shebang support,
    and it keeps the server on the same Python everywhere.
    """
    commands = {}
    for name in servers:
        script = BUILTIN_MCP_SERVERS.get(name)
        if script is None or not script.exists():
            print(f"[WARN] MCP server '{name}' unavailable; its tools are disabled")
            continue
        commands[name] = [sys.executable, str(script)]
    return commands


class Agent:
    name: str = ""
    label: str = ""
    executable: str | None = None   # CLI that must be on PATH, if any
    install_hint: str = ""
    # Model recorded (and used for the run-dir slug) when none is given
    default_model: str | None = None
    # Whether the runner builds workspace/ (seeded repo + fixtures) for it
    uses_workspace: bool = True

    # ---- checks ----------------------------------------------------------

    def check(self, model: str | None, prompt_def: dict) -> str | None:
        """Why this run cannot work (shown to the user), or None."""
        if self.executable and shutil.which(self.executable) is None:
            return f"'{self.executable}' not found on PATH. Install it with: {self.install_hint}"
        return self.validate(model, prompt_def)

    def validate(self, model: str | None, prompt_def: dict) -> str | None:
        """Agent-specific requirements (API keys, model support...)."""
        return None

    # ---- running ---------------------------------------------------------

    def run(self, ctx: RunContext) -> dict:
        """Run the test; returns {"returncode", "timed_out"}.

        Default: launch the agent CLI headless (output to stdout.txt) or as a
        TUI (--watch), inside prepare(), then collect().
        """
        with self.prepare(ctx):
            launch = self.launch(ctx)
            env = {**os.environ, **launch.env}
            (ctx.run_dir / "command.sh").write_text(
                "#!/bin/bash\n" + procs.format_command(launch.cmd, launch.env) + "\n",
                encoding="utf-8")
            if ctx.watch:
                print(f"Command: {' '.join(launch.cmd)}\n")
                result = procs.run_interactive(launch.cmd, ctx.timeout, ctx.test_id,
                                               cwd=launch.cwd, env=env)
            else:
                print(f"Running headless - follow along: tail -f {ctx.run_dir / 'stdout.txt'}")
                result = procs.run_logged(launch.cmd, ctx.run_dir, ctx.timeout, ctx.test_id,
                                          cwd=launch.cwd, env=env)
            self.collect(ctx)
        return result

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

    def status(self, result: dict) -> str:
        if result["timed_out"]:
            return "TIMEOUT"
        if result["returncode"] == 0:
            return "COMPLETE"
        return f"ERROR (exit {result['returncode']})"

    # ---- metrics (read back from the run dir) ----------------------------

    def token_usage(self, run_dir: Path) -> tuple[int, int] | None:
        return None

    def response_timings(self, run_dir: Path) -> list[dict]:
        """Per model response, in order: {"ttft_s", "duration_s"} (None if unknown).

        See crucible.session.timing_summary. Return [] when the agent records
        no timing at all.
        """
        return []
