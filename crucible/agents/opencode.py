"""opencode agent: `opencode run` headless, the opencode TUI in watch mode."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from crucible import procs
from crucible.agents.base import TASK_INSTRUCTION, WATCH_INSTRUCTION, Agent, Launch, RunContext, mcp_server_commands


class OpenCodeAgent(Agent):
    name = "opencode"
    label = "OpenCode"
    executable = "opencode"
    install_hint = "npm install -g opencode-ai"

    def launch(self, ctx: RunContext) -> Launch:
        # MCP config rides in via OPENCODE_CONFIG_CONTENT, which opencode loads
        # with higher precedence than global config and which exists only for
        # the spawned process — global opencode config stays untouched.
        env = {}
        servers = mcp_server_commands(ctx.mcp_servers)
        if servers:
            config = {"mcp": {name: {"type": "local", "command": cmd}
                              for name, cmd in servers.items()}}
            env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config)

        workspace = str(ctx.workspace)
        if ctx.watch:
            # The TUI takes no file attachment; the agent reads prompt.txt itself.
            cmd = ["opencode", workspace, "--prompt", WATCH_INSTRUCTION, "--auto"]
        else:
            cmd = ["opencode", "run", TASK_INSTRUCTION,
                   "--file", str(ctx.prompt_file),
                   "--dir", workspace,
                   "--title", ctx.title,
                   "--auto"]
        if ctx.model:
            cmd.extend(["-m", ctx.model])
        return Launch(cmd=cmd, env=env)

    def collect(self, ctx: RunContext) -> None:
        # Watch runs capture no stdout, but the TUI session holds the full
        # transcript — export the newest session (the TUI auto-titles it).
        _export_session(str(ctx.workspace), None if ctx.watch else ctx.title, ctx.run_dir)

    def token_usage(self, run_dir: Path) -> tuple[int, int] | None:
        """Sum per-message usage at messages[].info.tokens {input, output, reasoning}.

        tokens_out includes reasoning tokens.
        """
        try:
            session = json.loads((run_dir / "session.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        messages = session.get("messages", []) if isinstance(session, dict) else None
        if not isinstance(messages, list):
            return None
        tokens_in = tokens_out = 0
        seen = False
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            tok = (msg.get("info") or {}).get("tokens") or msg.get("tokens") or {}
            if tok:
                seen = True
                tokens_in += tok.get("input", 0) or 0
                tokens_out += (tok.get("output", 0) or 0) + (tok.get("reasoning", 0) or 0)
        return (tokens_in, tokens_out) if seen else None


def _export_session(workspace: str, title: str | None, run_dir: Path) -> None:
    """Export an opencode session transcript to session.json.

    Sessions live in the workspace's project-scoped DB, so list/export must run
    with cwd=workspace. title=None exports the most recent session. No
    --sanitize: it redacts the transcript text itself, making it unreadable.
    """
    try:
        exe = procs.resolve_executable("opencode")
        listing = subprocess.run(
            [exe, "session", "list", "--format", "json"],
            cwd=workspace, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        entries = json.loads(listing.stdout or "[]")
        if title:
            sid = next((e.get("id") for e in entries if e.get("title") == title), None)
        else:
            newest = max(entries, key=lambda e: e.get("updated", 0), default=None)
            sid = newest.get("id") if newest else None
        if not sid:
            print("  Warning: session not found; skipping session.json")
            return
        export = subprocess.run(
            [exe, "export", sid],
            cwd=workspace, capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
        (run_dir / "session.json").write_text(
            json.dumps(json.loads(export.stdout), indent=2), encoding="utf-8")
    except json.JSONDecodeError:
        print("  Warning: session export was not valid JSON; skipping session.json")
    except Exception as e:
        print(f"  Warning: could not export session: {e}")
