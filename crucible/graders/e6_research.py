#!/usr/bin/env python3
"""E6 — Current weather research grader.

Checks for live web fetch (via session.json tool calls) and source attribution
in the model output.
"""
from __future__ import annotations

import re
from pathlib import Path

from crucible.graders.helpers import count_tool_calls


def grade(prompt_def: dict, run_dir: Path, model_output: str) -> dict[str, float]:
    """E6: Current weather — check for live fetch + source citation."""
    rubric = {item["criterion"]: item["max_score"]
              for item in prompt_def.get("rubric", [])}
    scores = {}

    # Live fetch performed: count web-fetch tool calls in session.json
    session_path = run_dir / "session.json"
    tool_calls = count_tool_calls(session_path) if session_path.exists() else None
    if tool_calls and tool_calls > 0:
        scores["Live fetch performed"] = float(rubric.get("Live fetch performed", 3))
    else:
        # Also check stdout for evidence of a fetch
        if re.search(r'\b(fetch|retrieved|fetched|curl|web|weather\.gov|noaa|nws|api)\b',
                      model_output, re.IGNORECASE):
            scores["Live fetch performed"] = float(rubric.get("Live fetch performed", 3)) * 0.5
        else:
            scores["Live fetch performed"] = 0.0

    # Source attribution
    if re.search(r'(source|cited|weather\.gov|noaa|nws|openweather|accuweather)',
                  model_output, re.IGNORECASE):
        scores["Source attribution"] = float(rubric.get("Source attribution", 1))
    else:
        scores["Source attribution"] = 0.0

    return scores
