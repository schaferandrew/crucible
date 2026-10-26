#!/usr/bin/env python3
"""Evals: can the model under test grade an agent's response correctly?

An eval prompt shows the model a task, the criteria and an agent's response,
and asks it to finish with a `GRADE: <number>` line. The hidden "actual" score
lives in the prompt's top-level `eval:` key (never in `prompt:`), e.g.

    eval:
      scale: [0, 10]      # valid range for the grade
      actual_score: 6     # hidden reference grade
      falloff: 5          # error at which points reach zero

Points fall linearly with the distance from the actual score: an exact match
earns full points, an error of `falloff` or more earns none. A missing or
out-of-range grade earns none and is flagged.
"""
from __future__ import annotations

import re
from pathlib import Path

REASONING_FILENAME = "reasoning.md"
DEFAULT_FALLOFF = 5.0

# `GRADE: 7`, `**Grade:** 7.5` ... the last occurrence wins
_GRADE_RE = re.compile(r"^[ \t>*#_-]*grade\s*[:=]\s*[*_ \t]*(-?\d+(?:\.\d+)?)", re.IGNORECASE | re.MULTILINE)


def is_eval(prompt_def: dict) -> bool:
    return bool(prompt_def.get("eval"))


def parse_grade(text: str, lo: float, hi: float) -> float | None:
    """The model's final GRADE line, or None if absent or outside [lo, hi]."""
    matches = _GRADE_RE.findall(text)
    if not matches:
        return None
    grade = float(matches[-1])
    return grade if lo <= grade <= hi else None


def closeness_points(predicted: float | None, actual: float, max_points: float,
                     falloff: float = DEFAULT_FALLOFF) -> float:
    """max_points for an exact match, shrinking linearly to 0 at `falloff` away."""
    if predicted is None:
        return 0.0
    return round(max_points * max(0.0, 1 - abs(predicted - actual) / falloff), 2)


def split_reasoning(text: str) -> str:
    """The model's reply without its final GRADE line."""
    lines = text.rstrip().splitlines()
    for i in range(len(lines) - 1, -1, -1):
        if _GRADE_RE.match(lines[i]):
            del lines[i]
            break
    return "\n".join(lines).strip()


def score_eval(prompt_def: dict, output: str) -> dict:
    """Programmatic scores for one eval run, shaped like the interactive scorer's.

    Scores the rubric's criterion with the closeness points and records the
    comparison under `_eval` (predicted vs actual, error, the model's reasoning).
    """
    config = prompt_def["eval"]
    lo, hi = config.get("scale", [0, 10])
    actual = float(config["actual_score"])
    falloff = float(config.get("falloff", DEFAULT_FALLOFF))
    criterion = prompt_def["rubric"][0]

    predicted = parse_grade(output, lo, hi)
    points = closeness_points(predicted, actual, criterion["max_score"], falloff)
    return {
        criterion["criterion"]: points,
        "_eval": {
            "predicted": predicted,
            "actual": actual,
            "error": None if predicted is None else round(abs(predicted - actual), 2),
            "points": points,
            "max_points": criterion["max_score"],
            "parsed": predicted is not None,
            "reasoning": split_reasoning(output),
        },
    }


def write_reasoning(run_dir: Path, test_id: str, result: dict) -> Path:
    """reasoning.md: the model's grade against the actual one, then its reasoning."""
    if result["parsed"]:
        verdict = (f"Predicted **{result['predicted']:g}**, actual **{result['actual']:g}** "
                   f"(off by {result['error']:g}) — {result['points']:g}/{result['max_points']:g} points")
    else:
        verdict = (f"No valid `GRADE:` line found (actual **{result['actual']:g}**) — "
                   f"0/{result['max_points']:g} points")
    path = run_dir / REASONING_FILENAME
    path.write_text(f"# {test_id} — grader reasoning\n\n{verdict}\n\n## Reasoning\n\n"
                    f"{result['reasoning'] or '_(none)_'}\n", encoding="utf-8")
    return path
