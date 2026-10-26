"""opencode agent: `opencode run` headless, the opencode TUI in watch mode.

Supports opencode 1.x and 2.x, which differ in ways that matter here:

  1.x  `run --dir <workspace>`; `opencode export <id>`; messages[].info + parts[]
  2.x  `run` in the cwd; `session export <id>`; flat messages with content[]
       and a first-token timestamp. 2.x routes commands through a shared
       background service, which never sees a run's OPENCODE_CONFIG_CONTENT
       (MCP servers, extra providers), so runs use --standalone: a private
       server per run, which also keeps parallel runs apart.
"""
from __future__ import annotations

import functools
import json
import re
import subprocess
from pathlib import Path

from crucible import procs, providers
from crucible.agents.base import TASK_INSTRUCTION, WATCH_INSTRUCTION, Agent, Launch, RunContext, mcp_server_commands


EXTRA_OPENROUTER_PROVIDER = "openrouter-extra"


class OpenCodeAgent(Agent):
    name = "opencode"
    label = "OpenCode"
    executable = "opencode"
    install_hint = "npm install -g opencode-ai"
    builtin_web_tools = ["webfetch"]

    def launch(self, ctx: RunContext) -> Launch:
        # MCP config rides in via OPENCODE_CONFIG_CONTENT, which opencode loads
        # with higher precedence than global config and which exists only for
        # the spawned process — global opencode config stays untouched.
        env = {}
        config: dict = {}
        servers = mcp_server_commands(ctx.mcp_servers)
        if servers:
            config["mcp"] = {name: {"type": "local", "command": cmd} for name, cmd in servers.items()}
        # OpenRouter adds models before opencode's catalog (models.dev) lists them, and
        # opencode won't add models to its built-in openrouter provider. Route those
        # through an OpenAI-compatible provider pointed at OpenRouter, for this run only.
        model = ctx.model
        if model and model.startswith("openrouter/") and model not in _known_models("openrouter"):
            model_id = model.split("/", 1)[1]
            config["provider"] = {EXTRA_OPENROUTER_PROVIDER: {
                "npm": "@ai-sdk/openai-compatible",
                "name": "OpenRouter (models not yet in opencode's catalog)",
                "options": {"baseURL": "https://openrouter.ai/api/v1", "apiKey": "{env:OPENROUTER_API_KEY}"},
                "models": {model_id: {"name": model_id, "tool_call": True, **_cost_config(model_id)}},
            }}
            model = f"{EXTRA_OPENROUTER_PROVIDER}/{model_id}"
        if config:
            env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config)

        v2 = _major_version() >= 2
        standalone = ["--standalone"] if v2 else []

        workspace = str(ctx.workspace)
        if ctx.watch:
            # The TUI takes no file attachment; the agent reads prompt.txt itself.
            cmd = ["opencode", *standalone, workspace, "--prompt", WATCH_INSTRUCTION, "--auto"]
        else:
            # 2.x: JSON events on stdout carry the session ID, which collect() exports
            cmd = ["opencode", "run", *standalone, *(["--format", "json"] if v2 else []), TASK_INSTRUCTION,
                   "--file", str(ctx.prompt_file),
                   *([] if v2 else ["--dir", workspace]),
                   "--title", ctx.title,
                   "--auto"]
        if model:
            cmd.extend(["-m", model])
        # 2.x has no --dir: it works in its current directory, which it takes from $PWD,
        # so PWD must name the workspace too (the inherited one is crucible's own checkout)
        if v2:
            env["PWD"] = str(ctx.workspace)
        return Launch(cmd=cmd, env=env, cwd=ctx.workspace if v2 else None)

    def collect(self, ctx: RunContext) -> None:
        if _major_version() >= 2 and not ctx.watch:
            _collect_v2(ctx)
            return
        # Watch runs capture no stdout, but the TUI session holds the full
        # transcript — export the newest session (the TUI auto-titles it).
        _export_session(str(ctx.workspace), None if ctx.watch else ctx.title, ctx.run_dir)

    def token_usage(self, run_dir: Path) -> tuple[int, int] | None:
        """Sum per-message usage at messages[].info.tokens {input, output, reasoning}.

        tokens_out includes reasoning tokens.
        """
        tokens_in = tokens_out = 0
        seen = False
        for msg in _messages(run_dir):
            tok = _info(msg).get("tokens") or {}
            if tok:
                seen = True
                tokens_in += tok.get("input", 0) or 0
                tokens_out += (tok.get("output", 0) or 0) + (tok.get("reasoning", 0) or 0)
        return (tokens_in, tokens_out) if seen else None

    def cost_estimate(self, run_dir: Path) -> float | None:
        """Sum of messages[].info.cost (opencode's own price list)."""
        costs = [_info(msg).get("cost") for msg in _messages(run_dir)]
        costs = [c for c in costs if isinstance(c, (int, float))]
        return sum(costs) if costs else None

    def response_timings(self, run_dir: Path) -> list[dict]:
        """Per assistant message: time {created, streamed (2.x only), completed} in epoch ms.

        2.x records when streaming started, which gives time to first token; 1.x doesn't.
        """
        timings = []
        for msg in _messages(run_dir):
            info = _info(msg)
            if _role(msg) != "assistant":
                continue
            t = info.get("time") or {}
            created, streamed, completed = t.get("created"), t.get("streamed"), t.get("completed")
            timings.append({
                "ttft_s": (streamed - created) / 1000 if created and streamed else None,
                "duration_s": (completed - created) / 1000 if created and completed else None,
            })
        return timings


def _messages(run_dir: Path) -> list[dict]:
    """messages[] of the exported session.json ([] when missing or malformed)."""
    try:
        session = json.loads((run_dir / "session.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    messages = session.get("messages", []) if isinstance(session, dict) else []
    return [m for m in messages if isinstance(m, dict)] if isinstance(messages, list) else []


def _info(msg: dict) -> dict:
    """Per-message metadata: under info in 1.x exports, on the message itself in 2.x."""
    return msg.get("info") or msg


def _role(msg: dict) -> str | None:
    return _info(msg).get("role") or msg.get("type")


def message_texts(session: object) -> list[str]:
    """The assistant's text replies from an export of either version."""
    messages = session.get("messages", []) if isinstance(session, dict) else []
    texts = []
    for msg in messages:
        if not isinstance(msg, dict) or _role(msg) not in (None, "assistant"):
            continue
        for part in msg.get("parts") or msg.get("content") or []:
            if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
                texts.append(part["text"])
    return texts


@functools.lru_cache(maxsize=None)
def _major_version() -> int:
    """opencode's major version (1 when it can't be read: the older interface)."""
    try:
        out = subprocess.run([procs.resolve_executable("opencode"), "--version"],
                             capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return 1
    match = re.search(r"(\d+)\.\d+", out)
    return int(match.group(1)) if match else 1


def _collect_v2(ctx: RunContext) -> None:
    """2.x headless: export the session named in the JSON event stream, then make stdout readable.

    Looking the session up by title in `session list` misses sessions created by a
    headless run, so the ID comes from the events; stdout.txt (the raw events) is
    kept as events.ndjson and replaced with a transcript built from the export.
    """
    stdout = ctx.run_dir / "stdout.txt"
    events = stdout.read_text(encoding="utf-8", errors="replace") if stdout.exists() else ""
    (ctx.run_dir / "events.ndjson").write_text(events, encoding="utf-8")
    sid = None
    for line in events.splitlines():
        try:
            sid = json.loads(line).get("sessionID") or sid
        except (json.JSONDecodeError, AttributeError):
            continue
    if not sid:
        print("  Warning: no session ID in opencode's output; skipping session.json")
        return
    try:
        export = subprocess.run(
            [procs.resolve_executable("opencode"), "session", "export", "--standalone", sid],
            cwd=str(ctx.workspace), stdin=subprocess.DEVNULL, capture_output=True, text=True,
            encoding="utf-8", timeout=120)
        session = json.loads(export.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"  Warning: could not export session {sid}: {exc}")
        return
    (ctx.run_dir / "session.json").write_text(json.dumps(session, indent=2), encoding="utf-8")
    stdout.write_text("\n".join(transcript_v2(session)) + "\n", encoding="utf-8")


def transcript_v2(session: dict) -> list[str]:
    """Readable transcript of a 2.x export: replies, tool calls and the start of their output."""
    lines = []
    for msg in session.get("messages", []):
        if not isinstance(msg, dict) or msg.get("type") != "assistant":
            continue
        for part in msg.get("content") or []:
            if part.get("type") == "text" and part.get("text"):
                lines.append(f"⏺ {part['text']}")
            elif part.get("type") == "tool":
                state = part.get("state") or {}
                args = ", ".join(f"{k}={str(v)[:60]}" for k, v in list((state.get("input") or {}).items())[:3])
                lines.append(f"⏺ {part.get('name', '?')}({args})")
                output = " ".join(c.get("text", "") for c in state.get("content") or [] if isinstance(c, dict)).strip()
                if output:
                    lines.append(f"  ⎿ {output[:300]}")
    return lines


def _export_session(workspace: str, title: str | None, run_dir: Path) -> None:
    """Export an opencode session transcript to session.json.

    Sessions live in the workspace's project-scoped DB, so list/export must run
    with cwd=workspace. title=None exports the most recent session. No
    --sanitize: it redacts the transcript text itself, making it unreadable.
    """
    try:
        exe = procs.resolve_executable("opencode")
        v2 = _major_version() >= 2
        standalone = ["--standalone"] if v2 else []
        listing = subprocess.run(
            [exe, "session", "list", *standalone, "--format", "json"],
            cwd=workspace, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        entries = json.loads(listing.stdout or "[]")
        if title:
            sid = next((e.get("id") for e in entries if e.get("title") == title), None)
        else:
            newest = max(entries, key=lambda e: e.get("updated", 0), default=None)
            sid = newest.get("id") if newest else None
        if not sid:
            seen = ", ".join(repr(e.get("title")) for e in entries[:5]) or "none"
            print(f"  Warning: session not found (looked for {title!r}; listing had {seen}"
                  f"{'; ' + listing.stderr.strip()[:200] if listing.stderr.strip() else ''}); skipping session.json")
            return
        export = subprocess.run(
            [exe, *(["session", "export", "--standalone"] if v2 else ["export"]), sid],
            cwd=workspace, capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
        (run_dir / "session.json").write_text(
            json.dumps(json.loads(export.stdout), indent=2), encoding="utf-8")
    except json.JSONDecodeError:
        print("  Warning: session export was not valid JSON; skipping session.json")
    except Exception as e:
        print(f"  Warning: could not export session: {e}")


@functools.lru_cache(maxsize=None)
def _known_models(provider: str) -> frozenset[str]:
    """Model IDs opencode's catalog has for a provider (empty when opencode can't be asked).

    `opencode models` with no argument lists every provider/model in both 1.x and 2.x.
    """
    try:
        out = subprocess.run([procs.resolve_executable("opencode"), "models"],
                             capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    return frozenset(line.strip() for line in out.splitlines() if line.strip().startswith(provider + "/"))


def _cost_config(model_id: str) -> dict:
    """OpenRouter's prices in opencode's config shape, so its own cost estimate isn't $0."""
    pricing = providers.fetch_openrouter_pricing(model_id)
    return {"cost": {"input": pricing[0], "output": pricing[1]}} if pricing else {}
