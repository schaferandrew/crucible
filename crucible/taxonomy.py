#!/usr/bin/env python3
"""How tasks are grouped: modes in code, everything else read from tasks/taxonomy.yaml.

  mode      - agentic (runs in an agent harness with tools and a workspace) or chat (one API
              call, no tools), from needs_tools. The two are never mixed: not in a run, not in a
              score, and each mode has its own harnesses. Modes are part of the tool, not the suite.
  area      - what the task is about, declared in each task YAML; each area belongs to one mode
  tier      - difficulty declared in each task YAML (spark, temper, forge);
              tiers are scored separately, never blended (see docs/task-tiers.md)
  category  - finer scoring class with its sweep aggregation weight (coding_build, ...)

Areas, categories, weights, tiers and statuses are suite data (tasks/taxonomy.yaml): changing them
is a suite change, not a Crucible release (docs/versioning.md).
"""
from __future__ import annotations

import re

import yaml

from crucible.workspace import TASKS_DIR

MODES = ("chat", "agentic")
MODE_LABELS = {"chat": "Chat", "agentic": "Agentic"}
MODE_BLURBS = {
    "chat": "one API call, no tools",
    "agentic": "an agent harness with tools and a workspace",
}
# Which harnesses may run each mode: chat is always a plain API call, so harness quirks never
# leak into a chat score
MODE_HARNESSES = {"chat": ("direct",), "agentic": ("opencode", "pi")}

TAXONOMY_PATH = TASKS_DIR / "taxonomy.yaml"
TAXONOMY = yaml.safe_load(TAXONOMY_PATH.read_text(encoding="utf-8"))

# Areas by mode, in menu order: area -> label
AREAS = {mode: {a["id"]: a["label"] for a in TAXONOMY["areas"][mode]} for mode in MODES}
# Category -> weight used when aggregating a full sweep across categories. Sums to 1.0.
# Scoring a single run never uses these weights.
CATEGORY_WEIGHTS = dict(TAXONOMY["categories"])
# Difficulty tiers, easiest first, with label, blurb, role (gate, headline, stretch) and gate thresholds
TIER_INFO = {t["id"]: t for t in TAXONOMY["tiers"]}
TIERS = tuple(TIER_INFO)
TIER_BLURBS = {t: info.get("blurb", "") for t, info in TIER_INFO.items()}
# provisional tasks run and show up but stay out of tier scores until a suite cut makes them active
TASK_STATUSES = tuple(TAXONOMY["statuses"])
SCORING_POLICY = dict(TAXONOMY.get("scoring_policy") or {})


def mode_for(prompt_def: dict) -> str:
    return "agentic" if prompt_def.get("needs_tools") else "chat"


def area_label(area: str) -> str:
    return next(areas[area] for areas in AREAS.values() if area in areas)


def validate_area(prompt_def: dict) -> None:
    mode, area = mode_for(prompt_def), prompt_def.get("area")
    if area not in AREAS[mode]:
        raise ValueError(f"{prompt_def.get('id')}: area '{area}' isn't a {mode} area "
                         f"(expected one of {list(AREAS[mode])}; see tasks/taxonomy.yaml)")
    validate_id(prompt_def.get("id") or "")


# A task's ID is a kebab-case slug that says what the task is (react-lead-form). It never encodes
# the task's tier, area or difficulty, so moving a task between them never renames it.
SLUG = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
SLUG_MAX = 40
NOT_IN_SLUGS = {"spark", "temper", "forge", "hard", "easy", "harder", "easier"}


def validate_id(task_id: str) -> None:
    if not SLUG.fullmatch(task_id) or len(task_id) > SLUG_MAX:
        raise ValueError(f"'{task_id}': a task ID is a kebab-case slug of lowercase letters, digits and hyphens, "
                         f"at most {SLUG_MAX} characters (e.g. react-lead-form)")
    words = NOT_IN_SLUGS.intersection(task_id.split("-"))
    if words:
        raise ValueError(f"{task_id}: a task ID describes the task, not its tier or difficulty "
                         f"(drop {', '.join(sorted(words))})")


def harness_problem(prompt_def: dict, harness: str) -> str | None:
    mode = mode_for(prompt_def)
    if harness in MODE_HARNESSES[mode]:
        return None
    return (f"{prompt_def.get('id')} is {'an' if mode == 'agentic' else 'a'} {MODE_LABELS[mode].lower()} task, which runs with "
            f"{' or '.join(MODE_HARNESSES[mode])}, not {harness}")


def validate_category(category: str) -> None:
    if category not in CATEGORY_WEIGHTS:
        raise ValueError(
            f"Unknown category '{category}' — add it to tasks/taxonomy.yaml categories "
            f"(known: {sorted(CATEGORY_WEIGHTS)})"
        )


def validate_tier(tier: str) -> None:
    if tier not in TIERS:
        raise ValueError(f"Unknown tier '{tier}'; expected one of {list(TIERS)}")


def validate_status(status: str) -> None:
    if status not in TASK_STATUSES:
        raise ValueError(f"Unknown task status '{status}'; expected one of {list(TASK_STATUSES)}")
