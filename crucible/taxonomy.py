#!/usr/bin/env python3
"""Single source of truth for crucible's test taxonomy.

Two axes:
  suite     - user-facing CLI grouping, derived from the test-ID prefix
              (C1 -> coding, W2 -> writing, ...)
  category  - scoring class declared in each prompt YAML, with its sweep
              aggregation weight (coding_build, coding_debug, ...)
"""
from __future__ import annotations

# Suite is derived from test-ID prefix; the prefix IS the suite key.
SUITE_PREFIXES = {
    "C": "coding",
    "W": "writing",
    "E": "everyday",
    "G": "reasoning",
    "H": "home",
}

# Category -> weight used when aggregating a full sweep across categories.
# Must sum to 1.0. Scoring a single run never uses these weights.
CATEGORY_WEIGHTS = {
    "coding_build": 0.10,
    "coding_debug": 0.10,
    "coding_repo": 0.15,
    "browser_tool": 0.10,
    "writing": 0.10,
    "everyday": 0.10,
    "reasoning": 0.10,
    "structured_data": 0.10,
    "long_agent": 0.05,
    "home_maintenance": 0.10,
}


def suite_for(test_id: str) -> str:
    prefix = test_id[0].upper()
    if prefix not in SUITE_PREFIXES:
        raise ValueError(f"Unknown test-ID prefix '{prefix}' (from '{test_id}'); expected one of {sorted(SUITE_PREFIXES)}")
    return SUITE_PREFIXES[prefix]


def validate_category(category: str) -> None:
    if category not in CATEGORY_WEIGHTS:
        raise ValueError(
            f"Unknown category '{category}' — add it to crucible/taxonomy.py CATEGORY_WEIGHTS "
            f"(known: {sorted(CATEGORY_WEIGHTS)})"
        )


def derive_suites(test_ids: list[str]) -> dict[str, list[str]]:
    """Group test IDs into suites by prefix, sorted within each suite."""
    suites: dict[str, list[str]] = {}
    for tid in sorted(test_ids):
        suites.setdefault(suite_for(tid), []).append(tid)
    return suites
