#!/usr/bin/env python3
"""G2 — Calendar meeting scheduling grader.

Validates JSON meeting recommendations against a calendar fixture, checking
free-slot enumeration, conflict avoidance, ranking quality, and JSON structure.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from crucible.graders.helpers import _extract_json_block, FIXTURES_DIR


# --------------------------------------------------------------------------
# Calendar helpers
# --------------------------------------------------------------------------

def _parse_calendar(fixture: dict) -> tuple[dict, list]:
    """Extract the working window, meeting duration, and busy intervals."""
    window = fixture["window"]
    start = datetime.fromisoformat(window["start"])
    end = datetime.fromisoformat(window["end"])
    duration = fixture["meeting"]["duration_minutes"]

    busy = []
    for person in fixture["people"].values():
        for ev in person["events"]:
            ev_start = datetime.fromisoformat(ev["start"])
            ev_end = datetime.fromisoformat(ev["end"])
            busy.append((ev_start, ev_end, ev["title"]))
    busy.sort()

    return {"start": start, "end": end, "duration": duration,
            "tz": fixture.get("timezone", "America/Chicago")}, busy


def _is_weekday(dt) -> bool:
    """Monday=0 .. Sunday=6."""
    return dt.weekday() < 5


def _find_free_slots(window: dict, busy: list, duration_min: int) -> list:
    """Compute all valid *duration_min* free slots within the working window."""
    duration = timedelta(minutes=duration_min)
    slot_step = timedelta(minutes=30)

    free_slots = []
    day = window["start"]
    while day < window["end"]:
        d9 = day.replace(hour=9, minute=0, second=0, microsecond=0)
        d17 = day.replace(hour=17, minute=0, second=0, microsecond=0)
        if d9 < day:
            d9 = day
        if d17 > window["end"]:
            d17 = window["end"]

        if d9 >= d17:
            day += timedelta(days=1)
            continue

        day_busy = []
        for bs, be, title in busy:
            if be > d9 and bs < d17:
                day_busy.append((max(bs, d9), min(be, d17)))

        cursor = d9
        for bs, be in sorted(day_busy):
            if cursor < bs:
                free_start = cursor
                free_end = bs
                t = free_start
                while t + duration <= free_end:
                    free_slots.append({
                        "start": t.isoformat(),
                        "end": (t + duration).isoformat(),
                        "weekday": _is_weekday(t),
                    })
                    t += slot_step
            cursor = max(cursor, be)
        if cursor < d17:
            t = cursor
            while t + duration <= d17:
                free_slots.append({
                    "start": t.isoformat(),
                    "end": (t + duration).isoformat(),
                    "weekday": _is_weekday(t),
                })
                t += slot_step

        day = day.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)

    return free_slots


def _slot_overlaps_event(slot_start_str: str, slot_end_str: str, busy: list) -> bool:
    s = datetime.fromisoformat(slot_start_str)
    e = datetime.fromisoformat(slot_end_str)
    for bs, be, _ in busy:
        if s < be and e > bs:
            return True
    return False


def _grade_ranking(recommendations, valid_slots, window):
    """Score whether the ranking follows: weekdays, minimal gaps, avoid first/last hour."""
    if not recommendations or len(recommendations) < 1:
        return 0.0
    max_score = 2.0

    def slot_weekday(rec):
        s = rec.get("start", "")
        try:
            dt = datetime.fromisoformat(s)
            return dt.weekday() < 5
        except (ValueError, TypeError):
            return False

    def at_edge(rec):
        s = rec.get("start", "")
        try:
            dt = datetime.fromisoformat(s)
            hour = dt.hour
            return hour == 9 or hour >= 16
        except (ValueError, TypeError):
            return False

    weekday_first = all(slot_weekday(r) for r in recommendations[:3])
    no_edge = all(not at_edge(r) for r in recommendations[:3])

    if weekday_first and no_edge:
        return max_score
    elif weekday_first or no_edge:
        return max_score / 2
    return 0.0


# --------------------------------------------------------------------------
# Public grader entry point
# --------------------------------------------------------------------------

def grade(prompt_def: dict, run_dir: Path, model_output: str) -> dict[str, float]:
    """G2: Calendar meeting scheduling — validate JSON output against fixture."""
    rubric = {item["criterion"]: item["max_score"]
              for item in prompt_def.get("rubric", [])}
    scores = {}

    fixture_path = FIXTURES_DIR / "calendar-fixture.json"
    if not fixture_path.exists():
        return scores

    fixture = json.loads(fixture_path.read_text())
    window, busy = _parse_calendar(fixture)
    valid_slots = _find_free_slots(window, busy, window["duration"])
    recommendations = _extract_json_block(model_output)

    # Find all valid options
    if recommendations and isinstance(recommendations, list):
        rec_start_times = set()
        for rec in recommendations:
            if isinstance(rec, dict) and "start" in rec:
                rec_start_times.add(rec["start"])
        all_valid_starts = set(s["start"] for s in valid_slots)
        found_count = len(rec_start_times & all_valid_starts)
        total = len(all_valid_starts)
        scores["Finds all valid options"] = round(
            float(rubric.get("Finds all valid options", 3)) * found_count / max(total, 1), 2)
    else:
        scores["Finds all valid options"] = 0.0

    # Rejects conflicts
    if recommendations and isinstance(recommendations, list) and len(recommendations) > 0:
        conflict_free = True
        for rec in recommendations:
            if isinstance(rec, dict) and "start" in rec and "end" in rec:
                if _slot_overlaps_event(rec["start"], rec["end"], busy):
                    conflict_free = False
                    break
        scores["Rejects conflicts"] = float(rubric.get("Rejects conflicts", 2)) if conflict_free else 0.0
    else:
        scores["Rejects conflicts"] = 0.0

    # Ranking follows criteria
    if recommendations and isinstance(recommendations, list):
        scores["Ranking follows criteria"] = _grade_ranking(recommendations, valid_slots, window)
    else:
        scores["Ranking follows criteria"] = 0.0

    # Correct JSON (valid JSON list with explanation fields)
    if recommendations and isinstance(recommendations, list) and len(recommendations) > 0:
        has_explanation = all(isinstance(r, dict) and r.get("explanation") for r in recommendations)
        if has_explanation:
            scores["Correct JSON"] = float(rubric.get("Correct JSON", 2))
        else:
            scores["Correct JSON"] = 0.0
    else:
        scores["Correct JSON"] = 0.0

    # Explanation
    if recommendations and isinstance(recommendations, list):
        explained = sum(1 for r in recommendations[:3]
                        if isinstance(r, dict) and r.get("explanation"))
        if explained >= 3:
            scores["Explanation"] = float(rubric.get("Explanation", 1))
        elif explained >= 1:
            scores["Explanation"] = float(rubric.get("Explanation", 1)) / 2
        else:
            scores["Explanation"] = 0.0
    else:
        scores["Explanation"] = 0.0

    return scores
