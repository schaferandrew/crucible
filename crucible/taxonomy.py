#!/usr/bin/env python3
"""Single source of truth for crucible's test taxonomy.

How tests are grouped:
  mode      - agentic (runs in an agent harness with tools and a workspace) or chat (one API
              call, no tools), from needs_tools. The two are never mixed: not in a run, not in a
              score, and each mode has its own harnesses.
  area      - what the test is about, declared in each prompt YAML; each area belongs to one mode
  tier      - difficulty declared in each prompt YAML (spark, temper, forge);
              tiers are scored separately, never blended (see test-tiers.md)
  category  - finer scoring class with its sweep aggregation weight (coding_build, ...)
"""
from __future__ import annotations

import re

MODES = ("chat", "agentic")
MODE_LABELS = {"chat": "Chat", "agentic": "Agentic"}
MODE_BLURBS = {
    "chat": "one API call, no tools",
    "agentic": "an agent harness with tools and a workspace",
}
# Which harnesses may run each mode: chat is always a plain API call, so harness quirks never
# leak into a chat score
MODE_HARNESSES = {"chat": ("direct",), "agentic": ("opencode", "pi")}

# Areas by mode, in menu order: area -> label
AREAS = {
    "chat": {"writing": "Writing", "math": "Math & logic", "geography": "Geography",
             "history": "History", "general": "General knowledge"},
    "agentic": {"coding": "Coding", "research": "Research", "everyday": "Everyday"},
}
# Every test ID is its area's four letters, a hyphen and a number (WRIT-2b, CODE-11, ...)
AREA_PREFIXES = {"writing": "WRIT", "math": "MATH", "geography": "GEOG", "history": "HIST", "general": "KNOW",
                 "coding": "CODE", "research": "RSCH", "everyday": "TASK"}

# Category -> weight used when aggregating a full sweep across categories.
# Must sum to 1.0. Scoring a single run never uses these weights.
CATEGORY_WEIGHTS = {
    "coding_build": 0.10,
    "coding_debug": 0.10,
    "coding_repo": 0.15,
    "browser_tool": 0.10,
    "writing": 0.10,
    "everyday": 0.10,
    "reasoning": 0.05,
    "structured_data": 0.05,
    "long_agent": 0.05,
    "home_maintenance": 0.05,
    "math": 0.05,
    "geography": 0.05,
    "history": 0.05,
}


# Difficulty tiers, easiest first:
#   spark  - the basics: loads, follows a format, calls a tool, makes a small correct change (a gate)
#   temper - everyday work you'd actually use (the headline score)
#   forge  - work you'd normally need a frontier model for
TIERS = ("spark", "temper", "forge")

# provisional tests run and show up but stay out of tier scores until calibrated
TEST_STATUSES = ("provisional", "active", "retired")


def mode_for(prompt_def: dict) -> str:
    return "agentic" if prompt_def.get("needs_tools") else "chat"


def area_label(area: str) -> str:
    return next(areas[area] for areas in AREAS.values() if area in areas)


def validate_area(prompt_def: dict) -> None:
    mode, area = mode_for(prompt_def), prompt_def.get("area")
    if area not in AREAS[mode]:
        raise ValueError(f"{prompt_def.get('test_id')}: area '{area}' isn't a {mode} area "
                         f"(expected one of {list(AREAS[mode])}; see crucible/taxonomy.py)")
    test_id = prompt_def.get("test_id") or ""
    if not re.fullmatch(AREA_PREFIXES[area] + r"-\d+[a-z]?", test_id):
        raise ValueError(f"{test_id}: a {area} test's ID is {AREA_PREFIXES[area]}, a hyphen and a number "
                         f"(e.g. {AREA_PREFIXES[area]}-4, {AREA_PREFIXES[area]}-4b)")


def harness_problem(prompt_def: dict, harness: str) -> str | None:
    mode = mode_for(prompt_def)
    if harness in MODE_HARNESSES[mode]:
        return None
    return (f"{prompt_def.get('test_id')} is a {MODE_LABELS[mode]} test, which runs with "
            f"{' or '.join(MODE_HARNESSES[mode])}, not {harness}")


def validate_category(category: str) -> None:
    if category not in CATEGORY_WEIGHTS:
        raise ValueError(
            f"Unknown category '{category}' — add it to crucible/taxonomy.py CATEGORY_WEIGHTS "
            f"(known: {sorted(CATEGORY_WEIGHTS)})"
        )


def validate_tier(tier: str) -> None:
    if tier not in TIERS:
        raise ValueError(f"Unknown tier '{tier}'; expected one of {list(TIERS)}")


def validate_status(status: str) -> None:
    if status not in TEST_STATUSES:
        raise ValueError(f"Unknown test status '{status}'; expected one of {list(TEST_STATUSES)}")
