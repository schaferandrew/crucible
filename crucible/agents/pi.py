"""pi agent (https://pi.dev): `pi -p` headless, the pi TUI in watch mode.

Everything run-specific is passed per launch, so the user's ~/.pi/agent
config is never touched:

- --session-dir <run>/pi-sessions: the session JSONL lands in the run
  directory for both headless and watch runs, and is the single source for
  session.json, the transcript and token counts.
- -e pi_extension.ts (+ --no-extensions for hermetic runs): registers local
  providers (ollama, LM Studio) and bridges declared MCP servers into native
  pi tools, configured via the CRUCIBLE_PI_CONFIG env var.
- The prompt is attached as @prompt.txt rather than passed inline, which keeps
  arguments single-line for Windows' .cmd shims.

pi has no tool-approval prompts, so watch runs never stall on permissions.
On Windows pi needs a bash (Git for Windows) for its bash tool.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from crucible.agents.base import TASK_INSTRUCTION, Agent, Launch, RunContext, mcp_server_commands
from crucible.session import write_normalized

EXTENSION = Path(__file__).resolve().parent / "pi_extension.ts"
SESSION_DIRNAME = "pi-sessions"

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/") + "/v1"
LMSTUDIO_BASE_URL = os.environ.get("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1").rstrip("/")

# Local OpenAI-compatible servers pi has no built-in provider for. They
# reject the `developer` role and reasoning_effort, hence the compat flags.
LOCAL_PROVIDERS = {
    "ollama": {"baseUrl": OLLAMA_BASE_URL, "apiKey": "ollama"},
    "lmstudio": {"baseUrl": LMSTUDIO_BASE_URL, "apiKey": "lmstudio"},
}


def pi_config(model: str | None, mcp_servers: list[str]) -> tuple[list[str], dict]:
    """Model CLI flags and CRUCIBLE_PI_CONFIG payload for a run.

    - None                -> pi's own default model/provider
    - ollama/<m>, lmstudio/<m> -> provider registered by the extension
    - anything else (openrouter/<vendor>/<m>, anthropic/<m>, ...) -> passed
      through; pi resolves "provider/id" itself and reads the provider's
      API key env var (e.g. OPENROUTER_API_KEY).
    """
    config: dict = {}
    flags: list[str] = []
    if model:
        provider, _, model_id = model.partition("/")
        if provider in LOCAL_PROVIDERS and model_id:
            config["providers"] = {provider: {
                **LOCAL_PROVIDERS[provider],
                "api": "openai-completions",
                "compat": {"supportsDeveloperRole": False, "supportsReasoningEffort": False},
                "models": [{"id": model_id}],
            }}
        flags = ["--model", model]
    servers = mcp_server_commands(mcp_servers)
    if servers:
        config["mcpServers"] = {name: {"command": cmd} for name, cmd in servers.items()}
    return flags, config


def session_events(session_file: Path) -> tuple[list[dict], tuple[int, int] | None]:
    """Normalized events and (tokens_in, tokens_out) from a pi session JSONL.

    tokens_in counts all prompt tokens (fresh + cache read/write); a
    truncated trailing line (timeout/kill) is dropped.
    """
    events: list[dict] = []
    tokens_in = tokens_out = 0
    seen_usage = False
    try:
        raw_lines = session_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return [], None
    for line in raw_lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            break
        if entry.get("type") != "message":
            continue
        msg = entry.get("message") or {}
        role = msg.get("role")
        content = msg.get("content")
        if role == "assistant":
            usage = msg.get("usage") or {}
            if usage:
                seen_usage = True
                tokens_in += sum(usage.get(k) or 0 for k in ("input", "cacheRead", "cacheWrite"))
                tokens_out += usage.get("output") or 0
            for block in content or []:
                if block.get("type") == "text" and block.get("text"):
                    events.append({"type": "assistantMessage", "message": block["text"]})
                elif block.get("type") == "toolCall":
                    events.append({"type": "toolCall", "name": block.get("name", "?"),
                                   "args": block.get("arguments") or {}})
            if msg.get("stopReason") == "error" and msg.get("errorMessage"):
                events.append({"type": "assistantMessage",
                               "message": f"[error] {msg['errorMessage']}"})
        elif role == "toolResult":
            text = "\n".join(b.get("text", "") for b in content or [] if b.get("type") == "text")
            events.append({"type": "toolCallResult", "name": msg.get("toolName", "?"),
                           "result": text})
    return events, ((tokens_in, tokens_out) if seen_usage else None)


def find_session_file(run_dir: Path) -> Path | None:
    """Newest session JSONL pi wrote for this run."""
    sessions = sorted((run_dir / SESSION_DIRNAME).glob("*.jsonl"),
                      key=lambda p: p.stat().st_mtime)
    return sessions[-1] if sessions else None


class PiAgent(Agent):
    name = "pi"
    label = "pi"
    executable = "pi"
    install_hint = "npm install -g @mariozechner/pi-coding-agent"

    def validate(self, model: str | None) -> str | None:
        if model and model.startswith("openrouter/") and not os.environ.get("OPENROUTER_API_KEY"):
            return "OPENROUTER_API_KEY required for openrouter models with pi"
        return None

    def launch(self, ctx: RunContext) -> Launch:
        model_flags, config = pi_config(ctx.model, ctx.mcp_servers)
        cmd = ["pi"]
        if not ctx.watch:
            cmd.append("-p")
        cmd += [
            "--session-dir", str(ctx.run_dir / SESSION_DIRNAME),
            "--no-extensions", "-e", str(EXTENSION),
            *model_flags,
            # cwd is the workspace, so a relative reference keeps user paths
            # (spaces, drive letters) out of the argument list
            f"@{ctx.prompt_file.name}", TASK_INSTRUCTION,
        ]
        env = {"CRUCIBLE_PI_CONFIG": json.dumps(config)} if config else {}
        return Launch(cmd=cmd, cwd=ctx.workspace, env=env)

    def collect(self, ctx: RunContext) -> None:
        session_file = find_session_file(ctx.run_dir)
        if session_file is None:
            print("  Warning: pi session not found; skipping session.json")
            return
        events, _ = session_events(session_file)
        if events:
            write_normalized(ctx.run_dir, events)

    def token_usage(self, run_dir: Path) -> tuple[int, int] | None:
        session_file = find_session_file(run_dir)
        return session_events(session_file)[1] if session_file else None
