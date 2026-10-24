"""Normalized session captures shared by every agent.

Agents with their own export format (opencode) keep it in session.json;
agents without one (pi) are converted to a flat event list:

    {"type": "assistantMessage", "message": str}
    {"type": "toolCall", "name": str, "args": dict}
    {"type": "toolCallResult", "name": str, "result": str}

The scorer and metrics read both shapes.
"""
from __future__ import annotations

import json
from pathlib import Path

# Event type names for tool invocations: opencode export parts, normalized events
TOOL_CALL_TYPES = {"tool", "toolCall"}


def transcript_lines(events: list[dict]) -> list[str]:
    """Human-readable transcript for normalized session events."""
    lines = []
    for e in events:
        t = e.get("type")
        if t == "assistantMessage":
            lines.append(f"⏺ {e.get('message', '')}")
        elif t == "toolCall":
            args = e.get("args") or {}
            summary = ", ".join(f"{k}={str(v)[:60]}" for k, v in list(args.items())[:3])
            lines.append(f"⏺ {e.get('name', '?')}({summary})")
        elif t == "toolCallResult":
            result = str(e.get("result", "")).strip()
            if result:
                lines.append(f"  ⎿ {result[:200]}")
    return lines


def write_normalized(run_dir: Path, events: list[dict]) -> None:
    """Write session.json and replace stdout.txt with a readable transcript.

    The transcript includes tool output, so metrics that grep stdout (e.g.
    "N passed") see test results the agent ran.
    """
    (run_dir / "session.json").write_text(json.dumps(events, indent=2), encoding="utf-8")
    (run_dir / "stdout.txt").write_text("\n".join(transcript_lines(events)) + "\n",
                                        encoding="utf-8")


def count_tool_calls(session_path: Path) -> int | None:
    """Count tool invocations in a session file (opencode and normalized schemas)."""
    try:
        data = json.loads(session_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    count = 0
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if node.get("type") in TOOL_CALL_TYPES:
                count += 1
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return count


def timing_summary(responses: list[dict]) -> dict:
    """Run-level latency metrics from per-model-response timings.

    responses: in call order, each {"ttft_s": float | None, "duration_s":
    float | None} where ttft_s is request sent -> first streamed token and
    duration_s is request sent -> response complete. Unknowns stay None so
    agents only report what they actually measured.
    """
    def avg(values):
        values = [v for v in values if v is not None]
        return round(sum(values) / len(values), 3) if values else None

    first = responses[0].get("ttft_s") if responses else None
    return {
        "model_responses": len(responses) or None,
        "ttft_s": round(first, 3) if first is not None else None,
        "ttft_avg_s": avg(r.get("ttft_s") for r in responses),
        "response_time_avg_s": avg(r.get("duration_s") for r in responses),
    }
