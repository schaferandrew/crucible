#!/usr/bin/env python3
"""Regenerate the mock-calendar datasets (spark.json, pair.json, forge.json).

The JSON files are committed and are what tests read; this script is how they
were made, so a dataset can be changed in one readable place. It checks each
result against the server's own free_starts() oracle, so the data and the
documented answers cannot drift apart.

    python fixtures/mock-calendar/build.py

Datasets (the scheduling tests that use each):
  spark - A1, "am I free at 3:30?": one calendar, one boundary trap.
  pair  - A2, find an hour for two people this week: read my events, then
          Jamie's open windows.
  forge - A3, find an hour for a team of 16 over the next two weeks.
"""
from __future__ import annotations

import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
from crucible.mcp_servers.calendar_server import Calendar, free_starts  # noqa: E402

OFFSET = "-05:00"   # America/Chicago in September (CDT)
WORKING_HOURS = {"start": "09:00", "end": "17:00"}


def at(day: str, hhmm: str) -> str:
    return f"{day}T{hhmm}:00{OFFSET}"


class Person:
    """A calendar. Event times are Central wall-clock; utc_offset only sets working hours."""

    def __init__(self, cal_id: str, name: str, team: str = "Platform", **extra):
        self.cal = {"id": cal_id, "name": name, "email": cal_id, "team": team,
                    "type": "person", "timezone": "America/Chicago", "utc_offset": OFFSET,
                    "working_hours": dict(WORKING_HOURS), "events": [], **extra}
        self._n = 0

    def add(self, day: str, start: str, end: str, summary: str, **extra) -> "Person":
        self._n += 1
        self.cal["events"].append({"id": f"{self.cal['id'].split('@')[0]}-{self._n}", "summary": summary,
                                   "start": at(day, start), "end": at(day, end), **extra})
        return self

    def all_day(self, day: str, summary: str, **extra) -> "Person":
        nxt = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
        self._n += 1
        self.cal["events"].append({"id": f"{self.cal['id'].split('@')[0]}-{self._n}", "summary": summary,
                                   "start": at(day, "00:00"), "end": at(nxt, "00:00"),
                                   "all_day": True, **extra})
        return self


def dataset(name: str, now: str, calendars: list[Person], tools: list[str], owner: str) -> dict:
    return {"name": name, "timezone": "America/Chicago", "utc_offset": OFFSET, "now": now,
            "owner": owner, "tools": tools, "calendars": [p.cal for p in calendars]}


def write(data: dict) -> Calendar:
    for cal in data["calendars"]:
        cal["events"].sort(key=lambda e: e["start"])
    (HERE / f"{data['name']}.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return Calendar(data)


# --------------------------------------------------------------------------
# spark: "Am I free at 3:30?"  Tuesday 11:20 AM.
# Design review ends at exactly 3:30 (not a conflict) and the next event starts
# at 4:00; tomorrow has a 3:00-4:00 event as a wrong-day distractor.
# --------------------------------------------------------------------------

def build_spark() -> dict:
    alex = Person("alex@example.com", "Alex Rivera")
    alex.add("2026-09-01", "09:00", "09:30", "Standup", location="Zoom")
    alex.add("2026-09-01", "11:00", "12:00", "1:1 with Jamie", location="Zoom")
    alex.add("2026-09-01", "12:00", "13:00", "Lunch")
    alex.add("2026-09-01", "14:00", "15:30", "Design review", location="Conference Room A")
    alex.add("2026-09-01", "16:00", "17:00", "Customer call", location="Zoom")
    alex.add("2026-09-02", "15:00", "16:00", "Budget review", location="Conference Room B")
    return dataset("spark", at("2026-09-01", "11:20"), [alex], owner=alex.cal["id"],
                   tools=["get_current_time", "list_events"])


# --------------------------------------------------------------------------
# pair: an hour for Alex and Jamie "this week" (Mon 8:30 AM, through Friday).
# Traps: a cancelled event and a "free" (transparent) event that look busy,
# lunches, and an afternoon that is blocked for Jamie only.
# --------------------------------------------------------------------------

def build_pair() -> dict:
    alex = Person("alex@example.com", "Alex Rivera")
    jamie = Person("jamie@example.com", "Jamie Chen")
    for day in ("2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"):
        alex.add(day, "09:00", "09:30", "Standup", location="Zoom")
        alex.add(day, "12:00", "13:00", "Lunch")
        jamie.add(day, "12:00", "13:00", "Lunch")
    alex.add("2026-08-31", "10:00", "12:00", "Roadmap workshop", location="Conference Room A")
    alex.add("2026-08-31", "13:00", "14:00", "Design review", location="Conference Room A")
    alex.add("2026-08-31", "15:00", "16:30", "Customer call", location="Zoom")
    alex.add("2026-09-01", "11:00", "12:00", "1:1 with manager")
    alex.add("2026-09-01", "14:00", "17:00", "Offsite prep", location="Conference Room B")
    alex.add("2026-09-02", "09:30", "11:30", "Interview loop", location="Conference Room C")
    alex.add("2026-09-02", "13:00", "14:00", "Planning", location="Conference Room A")
    alex.add("2026-09-03", "10:00", "11:00", "Sprint review", location="Zoom")
    alex.add("2026-09-03", "13:00", "15:00", "Focus time (cancelled)", status="cancelled")
    alex.add("2026-09-03", "15:00", "16:00", "Project review", location="Zoom")
    alex.all_day("2026-09-04", "Priya's birthday", transparency="transparent")
    jamie.add("2026-08-31", "09:00", "11:00", "Hiring sync", location="Zoom")
    jamie.add("2026-08-31", "14:00", "17:00", "Board prep", location="Conference Room D")
    jamie.add("2026-09-01", "09:30", "10:30", "Vendor call", location="Zoom")
    jamie.add("2026-09-01", "13:00", "14:30", "Quarterly planning", location="Conference Room A")
    jamie.add("2026-09-02", "09:00", "12:00", "Offsite workshop", location="Downtown office")
    jamie.add("2026-09-02", "14:00", "15:30", "Budget review", location="Conference Room B")
    jamie.add("2026-09-03", "09:30", "10:30", "Sprint review", location="Zoom")
    jamie.add("2026-09-03", "11:00", "12:00", "1:1 with Alex (cancelled)", status="cancelled")
    jamie.add("2026-09-03", "14:00", "16:00", "Roadmap review", location="Conference Room A")
    jamie.add("2026-09-04", "09:00", "10:30", "Team retro", location="Zoom")
    jamie.add("2026-09-04", "13:30", "15:00", "Customer demo", location="Zoom")
    return dataset("pair", at("2026-08-31", "08:30"), [alex, jamie], owner=alex.cal["id"],
                   tools=["get_current_time", "list_calendars", "list_events", "get_availability"])


# --------------------------------------------------------------------------
# forge: one hour for the 16-person Platform team, "next two weeks" (Mon
# 8/31 8:30 AM). Labor Day (9/7) is a holiday. Every working day is filled
# with seeded random meetings except a few protected windows that are free for
# all 16, so the answer is the intersection of 16 calendars, not a lucky
# glance. Traps: cancelled/"free" events inside the answers, a teammate on
# vacation 9/10-9/11, a teammate in New York (working hours end at 4 PM
# Central), a 4-5 PM window that is empty on every calendar but outside that
# teammate's hours, and three non-team calendars that must be left out.
# Nothing is free on 8/31 or 9/14 so "next two weeks" has one reading.
# --------------------------------------------------------------------------

TEAM = [("alex", "Alex Rivera"), ("jamie", "Jamie Chen"), ("priya", "Priya Nair"),
        ("marcus", "Marcus Webb"), ("dana", "Dana Kowalski"), ("theo", "Theo Martin"),
        ("lena", "Lena Fischer"), ("omar", "Omar Haddad"), ("chloe", "Chloe Bennett"),
        ("ravi", "Ravi Patel"), ("sofia", "Sofia Alvarez"), ("ben", "Ben Thompson"),
        ("nina", "Nina Petrov"), ("caleb", "Caleb Wright"), ("mei", "Mei Tanaka"),
        ("eli", "Eli Brooks")]
OTHERS = [("jordan", "Jordan Lee", "Design"), ("sam", "Sam Okafor", "Design")]
DAYS = ["2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04",
        "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11", "2026-09-14"]
HOLIDAY = "2026-09-07"
# Windows (day, start, end) that no random event may touch: free for all 16
OPEN_WINDOWS = [("2026-09-01", "13:00", "14:30"), ("2026-09-02", "09:00", "10:00"),
                ("2026-09-03", "14:00", "16:00"), ("2026-09-08", "11:00", "12:00"),
                ("2026-09-09", "15:00", "16:00")]
# Empty on every calendar, but after New York's 5 PM Eastern close
TRAP_WINDOW = ("2026-09-08", "16:00", "17:00")
MEETINGS = ["Sync", "1:1", "Design review", "Incident review", "Roadmap", "Interview", "Planning",
            "Customer call", "Code review", "Office hours", "Retro", "Vendor call", "Demo prep", "Training"]


def _minutes(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def _random_day(rng: random.Random, person: Person, day: str, protected: list) -> None:
    for _ in range(rng.randint(3, 5)):
        start = rng.randrange(_minutes("09:00"), _minutes("16:30"), 30)
        end = start + rng.choice([30, 30, 60, 60, 90])
        if any(day == d and start < _minutes(e) and end > _minutes(s) for d, s, e in protected):
            continue
        person.add(day, f"{start // 60:02d}:{start % 60:02d}", f"{end // 60:02d}:{end % 60:02d}",
                   rng.choice(MEETINGS))


def build_forge() -> dict:
    rng = random.Random(2026)
    people = []
    for cal_id, name in TEAM:
        extra = {"timezone": "America/New_York", "utc_offset": "-04:00"} if cal_id == "marcus" else {}
        person = Person(f"{cal_id}@example.com", name, **extra)
        people.append(person)
    outsiders = [Person(f"{cal_id}@example.com", name, team) for cal_id, name, team in OTHERS]
    protected = OPEN_WINDOWS + [TRAP_WINDOW]

    for person in people + outsiders:
        person.all_day(HOLIDAY, "Labor Day")
        if person.cal["id"] == "priya@example.com":
            for day in ("2026-09-10", "2026-09-11"):
                person.all_day(day, "Out of office")
        for day in DAYS:
            if person.cal["id"] == "priya@example.com" and day in ("2026-09-10", "2026-09-11"):
                continue
            if person in people:
                person.add(day, "10:30", "11:00", "Platform standup")
            _random_day(rng, person, day, protected if person in people else [])

    # Cancelled / "free" events sitting on an open window: not busy, but they look it
    by_id = {p.cal["id"]: p for p in people}
    by_id["dana@example.com"].add("2026-09-01", "13:00", "14:00", "Vendor sync (cancelled)", status="cancelled")
    by_id["theo@example.com"].add("2026-09-01", "13:30", "14:30", "Lunch & learn (optional)", transparency="transparent")
    by_id["lena@example.com"].add("2026-09-03", "14:00", "15:00", "Design crit (cancelled)", status="cancelled")
    by_id["omar@example.com"].add("2026-09-09", "15:00", "16:00", "Focus block", transparency="transparent")
    # Near misses: exactly one person blocks an otherwise open stretch
    by_id["ravi@example.com"].add("2026-09-10", "13:00", "15:00", "Customer onsite")
    by_id["sofia@example.com"].add("2026-09-04", "14:00", "15:00", "Dentist")
    # Nothing is free on the edge days
    for day, start, end in (("2026-08-31", "09:00", "17:00"), ("2026-09-14", "09:00", "17:00")):
        by_id["ben@example.com"].add(day, start, end, "Training")

    room = Person("room-atlas@example.com", "Atlas (12 seats)", "Facilities", type="resource")
    room.all_day(HOLIDAY, "Closed")
    for day in DAYS:
        _random_day(rng, room, day, [])

    calendars = people + outsiders + [room]
    return dataset("forge", at("2026-08-31", "08:30"), calendars, owner="alex@example.com",
                   tools=["get_current_time", "list_calendars", "list_events", "get_availability"])


# --------------------------------------------------------------------------

def main() -> None:
    spark = write(build_spark())
    free = spark.busy("alex@example.com", at("2026-09-01", "15:30"), at("2026-09-01", "16:30"))
    assert free and free[0]["start"].startswith("2026-09-01T16:00"), free   # 15:30 itself is free

    pair = write(build_pair())
    ids = ["alex@example.com", "jamie@example.com"]
    pair_starts = free_starts(pair, ids, at("2026-08-31", "08:30"), at("2026-09-05", "00:00"), 60)
    print("pair 60-minute starts:", [s.strftime("%a %H:%M") for s in pair_starts])

    forge = write(build_forge())
    team = [f"{cal_id}@example.com" for cal_id, _ in TEAM]
    forge_starts = free_starts(forge, team, at("2026-08-31", "08:30"), at("2026-09-15", "00:00"), 60)
    print("forge 60-minute starts:", [s.strftime("%a %m-%d %H:%M") for s in forge_starts])


if __name__ == "__main__":
    main()
