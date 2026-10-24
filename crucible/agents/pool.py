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
from datetime import datetime
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from crucible.agents.base import WATCH_INSTRUCTION, Agent, Launch, RunContext, mcp_server_commands
from crucible.session import write_normalized

OPENROUTER_API = "https://openrouter.ai/api/v1"
# Ollama's OpenAI-compatible endpoint; an explicit base URL forces pool into
# standalone mode even when tenant credentials are present.
OLLAMA_OPENAI_API = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/") + "/v1"

# Same location on every OS, Windows included (verified with pool 1.0.16)
POOL_SETTINGS = Path.home() / ".config" / "poolside" / "settings.yaml"
TENANT_MODEL = "pool"  # placeholder model name for tenant mode
EXIT_TASK_FAILED = 4   # pool exec: agent ran but could not complete the task


def _state_home() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))


# Where pool writes trajectories, per platform (as printed by `pool config`,
# verified with pool 1.0.16 on each OS)
TRAJECTORY_DIRS = {
    "darwin": lambda: Path.home() / "Library" / "Application Support" / "poolside" / "trajectories",
    "win32": lambda: Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    / "poolside" / "trajectories",
    "linux": lambda: _state_home() / "poolside" / "trajectories",
}


def trajectory_dir() -> Path:
    """pool's trajectory directory; CRUCIBLE_POOL_TRAJECTORIES_DIR overrides it."""
    override = os.environ.get("CRUCIBLE_POOL_TRAJECTORIES_DIR")
    if override:
        return Path(override)
    return TRAJECTORY_DIRS.get(sys.platform, TRAJECTORY_DIRS["linux"])()


@dataclass
class PoolMode:
    env: dict[str, str] = field(default_factory=dict)
    exec_flags: list[str] = field(default_factory=list)
    standalone_model: str | None = None   # passed as -m to the TUI


def _openrouter_mode(model_id: str) -> PoolMode:
    return PoolMode(env={"POOLSIDE_API_KEY": os.environ.get("OPENROUTER_API_KEY", ""),
                         "POOLSIDE_STANDALONE_BASE_URL": OPENROUTER_API,
                         "POOLSIDE_STANDALONE_MODEL": model_id},
                    exec_flags=["--sandbox", "disabled"], standalone_model=model_id)


def _ollama_mode(model_id: str) -> PoolMode:
    env = {"POOLSIDE_STANDALONE_BASE_URL": OLLAMA_OPENAI_API,
           "POOLSIDE_STANDALONE_MODEL": model_id}
    # Ollama ignores auth, but the TUI's ACP session/new refuses to start
    # without a token ("Authentication required"); any placeholder works.
    if not os.environ.get("POOLSIDE_API_KEY"):
        env["POOLSIDE_API_KEY"] = "ollama"
    return PoolMode(env=env, standalone_model=model_id)


def _named_model_mode(model_id: str) -> PoolMode:
    """Any other model: pool's standalone default endpoint, model by name."""
    return PoolMode(env={"POOLSIDE_STANDALONE_MODEL": model_id}, standalone_model=model_id)


# provider prefix -> mode builder, given the model ID after the prefix
POOL_MODES = {"openrouter": _openrouter_mode, "ollama": _ollama_mode}


def pool_mode(model: str | None) -> PoolMode:
    """Tenant mode (no model / "pool"), else standalone per provider prefix."""
    if not model or model == TENANT_MODEL:
        return PoolMode()
    provider, _, model_id = model.partition("/")
    if provider in POOL_MODES and model_id:
        return POOL_MODES[provider](model_id)
    return _named_model_mode(model.rsplit("/", 1)[-1])


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
    for name in added:
        # pool's schema: command is a single executable string, args a list
        mcp[name] = {"command": commands[name][0], "args": commands[name][1:]}
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
    for path in trajectory_dir().glob("trajectory-*.ndjson"):
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


def _tool_call(event: dict) -> dict:
    tc = event.get("tool_call_parsed") or {}
    return {"type": "toolCall", "name": tc.get("name", "?"), "args": tc.get("args") or {}}


def _tool_result(event: dict) -> dict:
    tcr = event.get("tool_call_result") or {}
    return {"type": "toolCallResult", "name": tcr.get("tool_name", "?"),
            "result": tcr.get("observation", "")}


def _assistant_message(event: dict) -> dict | None:
    msg = (event.get("assistant_message_end") or {}).get("assistant_message", "")
    return {"type": "assistantMessage", "message": msg} if msg else None


# trajectory event type -> converter to a normalized event (None = skip)
TRAJECTORY_CONVERTERS = {
    "tool_call.parsed": _tool_call,
    "tool_call.result": _tool_result,
    "assistant_message.end": _assistant_message,
}


def trajectory_events(trajectory: Path) -> list[dict]:
    """Convert trajectory events into the normalized session schema."""
    events = []
    for event in _ndjson(trajectory):
        convert = TRAJECTORY_CONVERTERS.get(event.get("type"))
        normalized = convert(event) if convert else None
        if normalized:
            events.append(normalized)
    return events


def _epoch_s(timestamp: str) -> float:
    """ISO-8601 'YYYY-MM-DDTHH:MM:SS.fffffffZ' -> epoch seconds.

    pool writes 7 fractional digits, which datetime.fromisoformat rejects
    before Python 3.11, so the fraction is cut to microseconds first.
    """
    base, _, rest = timestamp.rstrip("Z").partition(".")
    micro = (rest + "000000")[:6]
    return datetime.fromisoformat(f"{base}.{micro}+00:00").timestamp()


def trajectory_timings(trajectory: Path) -> list[dict]:
    """Per model call: inference.start -> inference.end duration, paired by step_id.

    ttft_s stays None: pool's trajectory has no first-token or streaming event
    (verified with pool 1.0.16), only inference start/end per call.
    """
    starts: dict[str, float] = {}
    timings = []
    for event in _ndjson(trajectory):
        kind, step, ts = event.get("type"), event.get("step_id"), event.get("timestamp")
        if not (step and ts):
            continue
        if kind == "tool_call.inference.start":
            starts[step] = _epoch_s(ts)
        elif kind == "tool_call.inference.end" and step in starts:
            timings.append({"ttft_s": None, "duration_s": _epoch_s(ts) - starts.pop(step)})
    return timings


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

    def validate(self, model: str | None, prompt_def: dict) -> str | None:
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
        mode = pool_mode(ctx.model)
        workspace = str(ctx.workspace)
        if ctx.watch:
            # TUI in the workspace with the instruction pre-queued (auto-sent).
            # --mode always-allow mirrors headless --unsafe-auto-allow: without
            # it the TUI blocks on tool-approval prompts.
            model_flag = ["-m", mode.standalone_model] if mode.standalone_model else []
            cmd = ["pool", "-C", workspace, "--mode", "always-allow", *model_flag,
                   "-q", WATCH_INSTRUCTION]
        else:
            cmd = ["pool", "exec", "-f", str(ctx.prompt_file), "-d", workspace,
                   "--unsafe-auto-allow", *mode.exec_flags, "-o", "json"]
        return Launch(cmd=cmd, env=mode.env)

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

    def response_timings(self, run_dir: Path) -> list[dict]:
        trajectory = find_trajectory(str(run_dir / "workspace"))
        return trajectory_timings(trajectory) if trajectory else []

    def status(self, result: dict) -> str:
        if not result["timed_out"] and result["returncode"] == EXIT_TASK_FAILED:
            return "TASK FAILED (agent could not complete)"
        return super().status(result)
