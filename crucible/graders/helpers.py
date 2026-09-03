#!/usr/bin/env python3
"""Shared helpers for the graders package.

No imports from other ``crucible`` modules — safe from circular dependencies.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROMPTS_DIR = REPO_ROOT / "prompts"
FIXTURES_DIR = REPO_ROOT / "fixtures"
RUNS_DIR = REPO_ROOT / "runs"


# Tool-call type strings recognized by count_tool_calls
TOOL_CALL_TYPES = {"tool", "toolCall"}  # opencode export, pool NLJSON


def count_tool_calls(session_path: Path) -> int | None:
    """Count tool invocations in a session file (opencode and pool schemas)."""
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


def get_model_output(run_dir: Path) -> str:
    """Return the model's text output from a run directory.

    Prefers stdout.txt; falls back to session.json transcript (watch runs).
    """
    stdout_path = run_dir / "stdout.txt"
    if stdout_path.exists():
        text = stdout_path.read_text(encoding="utf-8", errors="replace")
        if text.strip():
            return text

    session_path = run_dir / "session.json"
    if session_path.exists():
        try:
            data = json.loads(session_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return ""
        texts = []
        if isinstance(data, dict):
            for msg in data.get("messages", []):
                if msg.get("info", {}).get("role") not in (None, "assistant"):
                    continue
                for part in msg.get("parts", []):
                    if part.get("type") == "text" and part.get("text"):
                        texts.append(part["text"])
        elif isinstance(data, list):
            for event in data:
                if event.get("type") == "assistantMessage" and event.get("message"):
                    texts.append(event["message"])
        if texts:
            return "\n\n".join(texts)

    return "[No stdout captured]"


def _extract_json_objects(text: str) -> list:
    """Find all valid JSON values embedded in free text."""
    results = []
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(text):
        try:
            obj, end = decoder.raw_decode(text[idx:])
            results.append(obj)
            idx += end
        except json.JSONDecodeError:
            idx += 1
    return results


def _extract_json_block(text: str):
    """Extract the first JSON object/list found in text, or None."""
    objs = _extract_json_objects(text)
    for obj in objs:
        if isinstance(obj, (dict, list)):
            return obj
    return None


def load_prompt(test_id: str) -> dict:
    """Load a prompt YAML file by test_id.

    Moved here from scorer.py to avoid circular imports
    (scorer → graders → scorer for YAML loading).
    """
    import yaml
    with open(PROMPTS_DIR / f"{test_id}.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)
