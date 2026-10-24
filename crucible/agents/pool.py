"""pool agent (Poolside): `pool exec` headless, the pool TUI in watch mode.

Model modes:
- no model           -> tenant mode (logged-in Poolside managed model)
- ollama/<model>     -> standalone against local ollama. The base URL must be
  pinned explicitly: with tenant credentials present, pool ignores
  settings.yaml's pool.api_url and would otherwise hit Poolside cloud.
- openrouter/<v>/<m> -> standalone against OpenRouter. The --api-url flag gets
  blocked by Cloudflare bot detection, but POOLSIDE_STANDALONE_BASE_URL works.

pool has no per-launch MCP config, so declared MCP servers are added to its
global settings.yaml for the run and removed afterwards (prepare()); a
pre-existing entry is never touched.

Captures: headless `-o json` prints NLJSON events, which already use the
normalized schema (crucible.session). Watch runs print nothing, so the session
is rebuilt from pool's trajectory record, whose session.start event names the
working directories (run -> trajectory mapping). Token counts come from the
trajectory too.
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path

import yaml

from crucible.agents.base import WATCH_INSTRUCTION, Agent, Launch, RunContext, mcp_server_commands
from crucible.session import write_normalized

OPENROUTER_API = "https://openrouter.ai/api/v1"
# Ollama's OpenAI-compatible endpoint; an explicit base URL forces pool into
# standalone mode even when tenant credentials are present.
OLLAMA_OPENAI_API = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/") + "/v1"

POOL_SETTINGS = Path.home() / ".config" / "poolside" / "settings.yaml"
TENANT_MODEL = "pool"  # placeholder model name for tenant mode
EXIT_TASK_FAILED = 4   # pool exec: agent ran but could not complete the task


def trajectory_dirs() -> list[Path]:
    """Where pool may keep its trajectory records, most specific first.

    macOS is verified. The Linux (XDG data dir) and Windows (%APPDATA%)
    locations are the platform conventions and unverified; set
    CRUCIBLE_POOL_TRAJECTORIES_DIR to point at the right place.
    """
    override = os.environ.get("CRUCIBLE_POOL_TRAJECTORIES_DIR")
    if override:
        return [Path(override)]
    home = Path.home()
    if sys.platform == "darwin":
        return [home / "Library" / "Application Support" / "poolside" / "trajectories"]
    if os.name == "nt":
        appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        return [appdata / "poolside" / "trajectories", local / "poolside" / "trajectories"]
    data = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))
    return [data / "poolside" / "trajectories", home / ".config" / "poolside" / "trajectories"]


def pool_config(model: str | None) -> tuple[dict[str, str], list[str], str | None]:
    """Env additions, extra `pool exec` flags and standalone model name."""
    env: dict[str, str] = {}
    extra_flags: list[str] = []
    standalone_model = None

    if model and model.startswith("openrouter/"):
        env["POOLSIDE_API_KEY"] = os.environ.get("OPENROUTER_API_KEY", "")
        env["POOLSIDE_STANDALONE_BASE_URL"] = OPENROUTER_API
        env["POOLSIDE_STANDALONE_MODEL"] = standalone_model = model.split("/", 1)[1]
        extra_flags = ["--sandbox", "disabled"]
    elif model and model.startswith("ollama/"):
        standalone_model = model.rsplit("/", 1)[-1]
        env["POOLSIDE_STANDALONE_BASE_URL"] = OLLAMA_OPENAI_API
        env["POOLSIDE_STANDALONE_MODEL"] = standalone_model
        # Ollama ignores auth, but the TUI's ACP session/new refuses to start
        # without a token ("Authentication required"); any placeholder works.
        if not os.environ.get("POOLSIDE_API_KEY"):
            env["POOLSIDE_API_KEY"] = "ollama"
    elif model and model != TENANT_MODEL:
        standalone_model = model.rsplit("/", 1)[-1]
        env["POOLSIDE_STANDALONE_MODEL"] = standalone_model

    return env, extra_flags, standalone_model


# --------------------------------------------------------------------------
# MCP provisioning (global settings.yaml, scoped to the run)
# --------------------------------------------------------------------------

def _read_settings() -> dict | None:
    if not POOL_SETTINGS.exists():
        return {}
    try:
        return yaml.safe_load(POOL_SETTINGS.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        print(f"[WARN] cannot read {POOL_SETTINGS}: {exc}")
        return None


def _write_settings(settings: dict) -> bool:
    try:
        POOL_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        POOL_SETTINGS.write_text(yaml.safe_dump(settings, sort_keys=False), encoding="utf-8")
        return True
    except OSError as exc:
        print(f"[WARN] cannot write {POOL_SETTINGS}: {exc}")
        return False


def add_mcp_servers(servers: list[str]) -> list[str]:
    """Add declared servers missing from settings.yaml; returns the names added.

    Entries that already exist (any definition) are left alone and not
    returned, so the harness never clobbers user config.
    """
    commands = mcp_server_commands(servers)
    if not commands:
        return []
    settings = _read_settings()
    if settings is None:
        print("[WARN] mock tools unavailable for pool")
        return []
    mcp = settings.setdefault("mcp_servers", {})
    added = [name for name in commands if name not in mcp]
    if not added:
        return []
    if os.name == "nt":
        print("[WARN] pool MCP provisioning assumes the POSIX poolside config "
              "location; verify pool reads this settings.yaml on Windows")
    for name in added:
        mcp[name] = {"command": commands[name]}
    return added if _write_settings(settings) else []


def remove_mcp_servers(names: list[str]) -> None:
    """Undo add_mcp_servers (best effort)."""
    if not names:
        return
    settings = _read_settings()
    mcp = (settings or {}).get("mcp_servers")
    if not mcp:
        return
    for name in names:
        mcp.pop(name, None)
    if not mcp:
        del settings["mcp_servers"]
    _write_settings(settings)


# --------------------------------------------------------------------------
# Captures
# --------------------------------------------------------------------------

def _ndjson(path: Path) -> list[dict]:
    """Parsed NDJSON lines; a truncated tail (timeout/kill) is dropped."""
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    events = []
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            break
    return events


def split_output(run_dir: Path) -> None:
    """Turn headless NLJSON stdout into session.json + transcript.

    stdout.txt is left untouched when nothing parses.
    """
    events = [e for e in _ndjson(run_dir / "stdout.txt") if isinstance(e, dict) and "type" in e]
    if events:
        write_normalized(run_dir, events)


def find_trajectory(workspace: str) -> Path | None:
    """Newest trajectory whose session.start names the workspace."""
    best: tuple[float, Path] | None = None
    for directory in trajectory_dirs():
        if not directory.is_dir():
            continue
        for path in directory.glob("trajectory-*.ndjson"):
            try:
                with open(path, encoding="utf-8") as f:
                    first = json.loads(f.readline())
                mtime = path.stat().st_mtime
            except (OSError, json.JSONDecodeError):
                continue
            dirs = (first.get("session_start") or {}).get("working_directories") or []
            if workspace in dirs and (best is None or mtime > best[0]):
                best = (mtime, path)
    return best[1] if best else None


def trajectory_events(trajectory: Path) -> list[dict]:
    """Convert trajectory events into the normalized session schema."""
    events = []
    for event in _ndjson(trajectory):
        t = event.get("type")
        if t == "tool_call.parsed":
            tc = event.get("tool_call_parsed") or {}
            events.append({"type": "toolCall", "name": tc.get("name", "?"),
                           "args": tc.get("args") or {}})
        elif t == "tool_call.result":
            tcr = event.get("tool_call_result") or {}
            events.append({"type": "toolCallResult", "name": tcr.get("tool_name", "?"),
                           "result": tcr.get("observation", "")})
        elif t == "assistant_message.end":
            msg = (event.get("assistant_message_end") or {}).get("assistant_message", "")
            if msg:
                events.append({"type": "assistantMessage", "message": msg})
    return events


def trajectory_tokens(trajectory: Path) -> tuple[int, int] | None:
    """Sum input/output tokens over tool_call.inference.end events."""
    tokens_in = tokens_out = 0
    seen = False
    for event in _ndjson(trajectory):
        end = event.get("tool_call_inference_end") or {}
        if "input_tokens" in end or "output_tokens" in end:
            seen = True
            tokens_in += end.get("input_tokens") or 0
            tokens_out += end.get("output_tokens") or 0
    return (tokens_in, tokens_out) if seen else None


class PoolAgent(Agent):
    name = "pool"
    label = "Pool (Poolside)"
    executable = "pool"
    install_hint = "see https://poolside.ai for the pool CLI"
    default_model = TENANT_MODEL

    def validate(self, model: str | None) -> str | None:
        if model and model.startswith("openrouter/") and not os.environ.get("OPENROUTER_API_KEY"):
            return "OPENROUTER_API_KEY required for openrouter-backed pool runs"
        return None

    @contextlib.contextmanager
    def prepare(self, ctx: RunContext):
        added = add_mcp_servers(ctx.mcp_servers)
        try:
            yield
        finally:
            remove_mcp_servers(added)

    def launch(self, ctx: RunContext) -> Launch:
        env, extra_flags, standalone_model = pool_config(ctx.model)
        workspace = str(ctx.workspace)
        if ctx.watch:
            # TUI in the workspace with the instruction pre-queued (auto-sent).
            # --mode always-allow mirrors headless --unsafe-auto-allow: without
            # it the TUI blocks on tool-approval prompts.
            cmd = ["pool", "-C", workspace, "--mode", "always-allow"]
            if standalone_model:
                cmd.extend(["-m", standalone_model])
            cmd.extend(["-q", WATCH_INSTRUCTION])
        else:
            cmd = ["pool", "exec", "-f", str(ctx.prompt_file), "-d", workspace,
                   "--unsafe-auto-allow", *extra_flags, "-o", "json"]
        return Launch(cmd=cmd, env=env)

    def collect(self, ctx: RunContext) -> None:
        if not ctx.watch:
            split_output(ctx.run_dir)
            return
        trajectory = find_trajectory(str(ctx.workspace))
        if trajectory is None:
            print("  Warning: pool trajectory not found; skipping session.json")
            return
        events = trajectory_events(trajectory)
        if events:
            write_normalized(ctx.run_dir, events)

    def token_usage(self, run_dir: Path) -> tuple[int, int] | None:
        trajectory = find_trajectory(str(run_dir / "workspace"))
        return trajectory_tokens(trajectory) if trajectory else None

    def status(self, result: dict) -> str:
        if not result["timed_out"] and result["returncode"] == EXIT_TASK_FAILED:
            return "TASK FAILED (agent could not complete)"
        return super().status(result)
