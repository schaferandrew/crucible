#!/usr/bin/env python3
"""Evals: can the model under test grade an agent's response correctly?

An eval prompt shows the model a task, the criteria and an agent's response, and asks it
to finish with a `GRADE: <number>` line. The test scores it with one `grade_closeness`
check (see crucible/checks.py) that holds the hidden "actual" score:

    checks:
      - id: grade
        type: grade_closeness
        scale: [0, 10]       # valid grades
        actual_score: 7      # hidden reference grade; lives in `checks:`, never in `prompt:`
        width: 3             # width of the bell curve: the error at which 37% of points remain
        rule: "The grade is close to the reference grade."

Points follow a Gaussian (bell curve) in the distance from the actual score,
exp(-(error / width)^2): an exact match earns full points, small misses cost little, and the
penalty accelerates the farther away the grade is. A missing or out-of-range grade earns none. The model's full reply (its reasoning) is kept as `checked_text` in
its score record and shown as the run's output on the dashboard.
"""
from __future__ import annotations

import math
import re

DEFAULT_WIDTH = 3.0

# `GRADE: 7`, `Grade: 6.5` (Markdown emphasis is stripped before checks run); the last one wins
_GRADE_RE = re.compile(r"^[ \t>#-]*grade\s*[:=]\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE | re.MULTILINE)


def parse_grade(text: str, lo: float, hi: float) -> float | None:
    """The model's final GRADE line, or None if absent or outside [lo, hi]."""
    matches = _GRADE_RE.findall(text)
    if not matches:
        return None
    grade = float(matches[-1])
    return grade if lo <= grade <= hi else None


def closeness(predicted: float | None, actual: float, width: float = DEFAULT_WIDTH) -> float:
    """1.0 for an exact match, falling as a Gaussian: exp(-(error / width)^2)."""
    if predicted is None:
        return 0.0
    return round(math.exp(-(((predicted - actual) / width) ** 2)), 4)


def grade_closeness(check: dict, text: str) -> tuple[bool, str, float]:
    """(exact match?, what happened, share of the points earned) for a grade_closeness check."""
    lo, hi = check.get("scale", [0, 10])
    actual = float(check["actual_score"])
    predicted = parse_grade(text, lo, hi)
    if predicted is None:
        return False, f"no valid GRADE line ({lo:g}-{hi:g}) found; the reference grade was {actual:g}", 0.0
    share = closeness(predicted, actual, float(check.get("width", DEFAULT_WIDTH)))
    return share == 1.0, f"graded {predicted:g}, reference {actual:g} (off by {abs(predicted - actual):g})", share
