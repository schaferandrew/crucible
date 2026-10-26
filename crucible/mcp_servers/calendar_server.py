#!/usr/bin/env python3
"""crucible's mock calendar MCP server (stdio JSON-RPC) for scheduling tests.

Declared per prompt as `mcp_servers: ["mock-calendar:<dataset>"]`; the dataset
(fixtures/mock-calendar/<dataset>.json) is the whole world the model sees:
who exists, what "now" is, and every event. Unlike mock-data's static dumps,
the tools take arguments (calendar, time range) the way real calendar MCP
servers do, so a model has to query rather than read one blob.

It works like the calendar MCP servers people actually use: the user's own
calendar is read as events (list_events), while colleagues' calendars are shared
for availability only, so the model reads their open windows (get_availability)
and cannot see their events. There is deliberately no tool that intersects
several people's time; the model does that. A dataset declares which `tools`
it offers. Stdlib only.

Tools: get_current_time, list_calendars, list_events (own calendar only),
get_availability (any calendar: open windows inside its working hours).
A time is busy unless its event is cancelled or marked transparent.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATASET_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "mock-calendar"

TOOLS = {
    "get_current_time": {
        "description": "Get the current date, time and the user's time zone.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "list_calendars": {
        "description": ("List the calendars the user can see: their own plus those shared with them. "
                        "Returns id, name, email, team, time zone and working hours for each."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    "list_events": {
        "description": ("List events on the user's own calendar that overlap a time range, ordered by "
                        "start time. Other people's calendars are shared for availability only. "
                        "Cancelled events and events marked transparent (shown as free) are included "
                        "with their status so the caller can tell."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "calendar_id": {"type": "string", "description": "The user's own calendar id (default \"primary\")"},
                "time_min": {"type": "string", "description": "ISO 8601 start of range (inclusive)"},
                "time_max": {"type": "string", "description": "ISO 8601 end of range (exclusive)"},
            },
            "required": ["time_min", "time_max"],
        },
    },
    "get_availability": {
        "description": ("Get when each of several calendars is open: the free windows inside each owner's "
                        "working hours over a time range, in order. Works for calendars shared with the "
                        "user, whose events are not visible. Busy time is not listed."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "calendar_ids": {"type": "array", "items": {"type": "string"},
                                 "description": "Calendar ids to check (\"primary\" is the user's own)"},
                "time_min": {"type": "string", "description": "ISO 8601 start of range (inclusive)"},
                "time_max": {"type": "string", "description": "ISO 8601 end of range (exclusive)"},
            },
            "required": ["calendar_ids", "time_min", "time_max"],
        },
    },
}


class ToolError(Exception):
    """Reported to the model as an isError tool result, not a protocol error."""


# --------------------------------------------------------------------------
# Dataset
# --------------------------------------------------------------------------

def parse_time(value: str, tz: timezone) -> datetime:
    """ISO 8601 -> aware datetime; a value without an offset is in the dataset's zone."""
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        raise ToolError(f"Invalid time '{value}': expected ISO 8601, e.g. 2026-09-01T15:30:00-05:00") from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)


def fixed_offset(text: str) -> timezone:
    sign = -1 if text.startswith("-") else 1
    hours, _, minutes = text.lstrip("+-").partition(":")
    return timezone(sign * timedelta(hours=int(hours), minutes=int(minutes or 0)))


class Calendar:
    def __init__(self, dataset: dict):
        self.name = dataset.get("name", "")
        self.timezone_name = dataset["timezone"]
        self.tz = fixed_offset(dataset["utc_offset"])
        self.now = parse_time(dataset["now"], self.tz)
        self.calendars = {c["id"]: c for c in dataset["calendars"]}
        self.owner = dataset.get("owner") or dataset["calendars"][0]["id"]
        self.tools = dataset.get("tools") or list(TOOLS)

    @classmethod
    def load(cls, name: str) -> "Calendar":
        path = DATASET_DIR / f"{name}.json"
        if not path.is_file():
            available = sorted(p.stem for p in DATASET_DIR.glob("*.json"))
            raise SystemExit(f"Unknown calendar dataset '{name}' (available: {', '.join(available)})")
        dataset = json.loads(path.read_text(encoding="utf-8"))
        dataset.setdefault("name", name)
        return cls(dataset)

    # ---- queries ---------------------------------------------------------

    def calendar(self, calendar_id: str | None) -> dict:
        calendar_id = self.owner if calendar_id in (None, "", "primary") else calendar_id
        cal = self.calendars.get(calendar_id)
        if cal is None:
            raise ToolError(f"Calendar not found: {calendar_id}. Use list_calendars to see valid ids.")
        return cal

    def _range(self, time_min: str, time_max: str) -> tuple[datetime, datetime]:
        start, end = parse_time(time_min, self.tz), parse_time(time_max, self.tz)
        if end <= start:
            raise ToolError("time_max must be after time_min")
        return start, end

    def events(self, calendar_id: str | None, time_min: str, time_max: str) -> list[dict]:
        cal = self.calendar(calendar_id)
        start, end = self._range(time_min, time_max)
        found = [e for e in cal["events"]
                 if parse_time(e["start"], self.tz) < end and parse_time(e["end"], self.tz) > start]
        return sorted(found, key=lambda e: parse_time(e["start"], self.tz))

    def busy(self, calendar_id: str, time_min: str, time_max: str) -> list[dict]:
        """Merged busy intervals, clipped to the range."""
        start, end = self._range(time_min, time_max)
        blocks: list[list[datetime]] = []
        for e in self.events(calendar_id, time_min, time_max):
            if e.get("status", "confirmed") == "cancelled" or e.get("transparency") == "transparent":
                continue
            s = max(parse_time(e["start"], self.tz), start)
            f = min(parse_time(e["end"], self.tz), end)
            if blocks and s <= blocks[-1][1]:
                blocks[-1][1] = max(blocks[-1][1], f)
            else:
                blocks.append([s, f])
        return [{"start": s.isoformat(), "end": f.isoformat()} for s, f in blocks]

    # ---- tool handlers ---------------------------------------------------

    def get_current_time(self) -> dict:
        return {"now": self.now.isoformat(), "weekday": self.now.strftime("%A"),
                "timezone": self.timezone_name, "utc_offset": self.now.strftime("%z")}

    def list_calendars(self) -> dict:
        keys = ("id", "name", "email", "team", "type", "timezone", "working_hours")
        return {"calendars": [{k: c[k] for k in keys if k in c} | {"primary": c["id"] == self.owner}
                              for c in self.calendars.values()]}

    def list_events(self, time_min: str, time_max: str, calendar_id: str | None = None) -> dict:
        cal = self.calendar(calendar_id)
        if cal["id"] != self.owner:
            raise ToolError(f"No access to {cal['id']}'s events: that calendar is shared for availability "
                            "only. Use get_availability.")
        return {"calendar_id": cal["id"], "time_zone": self.timezone_name,
                "events": [{"id": e["id"], "summary": e["summary"], "start": e["start"], "end": e["end"],
                            "status": e.get("status", "confirmed"),
                            "transparency": e.get("transparency", "opaque"),
                            **{k: e[k] for k in ("all_day", "location", "attendees") if k in e}}
                           for e in self.events(calendar_id, time_min, time_max)]}

    def get_availability(self, calendar_ids: list, time_min: str, time_max: str) -> dict:
        if not isinstance(calendar_ids, list) or not calendar_ids:
            raise ToolError("calendar_ids must be a non-empty list")
        return {"time_min": time_min, "time_max": time_max, "time_zone": self.timezone_name,
                "calendars": {cid: {"free": self.free_windows(self.calendar(cid)["id"], time_min, time_max)}
                              for cid in calendar_ids}}

    def free_windows(self, calendar_id: str, time_min: str, time_max: str) -> list[dict]:
        """Open windows inside the owner's weekday working hours, minus busy time."""
        entry = self.calendar(calendar_id)
        start, end = self._range(time_min, time_max)
        tz = fixed_offset(entry["utc_offset"]) if "utc_offset" in entry else self.tz
        hours = entry.get("working_hours") or {"start": "00:00", "end": "24:00"}
        busy = [(parse_time(b["start"], self.tz), parse_time(b["end"], self.tz))
                for b in self.busy(calendar_id, time_min, time_max)]
        windows = []
        day = start.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        while day < end:
            if day.weekday() < 5:
                open_at = max(day + timedelta(minutes=_minutes(hours["start"])), start)
                close_at = min(day + timedelta(minutes=_minutes(hours["end"])), end)
                cursor = open_at
                for b0, b1 in busy:
                    if b1 <= cursor or b0 >= close_at:
                        continue
                    if b0 > cursor:
                        windows.append((cursor, b0))
                    cursor = max(cursor, b1)
                if cursor < close_at:
                    windows.append((cursor, close_at))
            day += timedelta(days=1)
        return [{"start": a.astimezone(self.tz).isoformat(), "end": b.astimezone(self.tz).isoformat()}
                for a, b in windows]


def _minutes(text: str) -> int:
    return int(text[:2]) * 60 + int(text[3:])


# --------------------------------------------------------------------------
# Ground truth (not a tool): what a correct scheduling answer may contain
# --------------------------------------------------------------------------

def free_starts(cal: Calendar, calendar_ids: list, time_min: str, time_max: str,
                minutes: int, step_minutes: int = 30) -> list[datetime]:
    """Start times (on the step grid) where a `minutes`-long meeting fits.

    Everyone must be free of busy events, and the meeting must sit inside each
    attendee's working hours on a weekday in their own zone. Used by tests and
    graders to know the right answer; models never see this.
    """
    start, end = cal._range(time_min, time_max)
    busy = {cid: [(parse_time(b["start"], cal.tz), parse_time(b["end"], cal.tz))
                  for b in cal.busy(cid, time_min, time_max)] for cid in calendar_ids}
    length, step = timedelta(minutes=minutes), timedelta(minutes=step_minutes)
    slot = cal.now.replace(hour=0, minute=0, second=0, microsecond=0)
    while slot < start:
        slot += step
    starts = []
    while slot + length <= end:
        if all(_within_hours(cal, cal.calendar(cid), slot, slot + length)
               and all(slot + length <= b0 or slot >= b1 for b0, b1 in busy[cid])
               for cid in calendar_ids):
            starts.append(slot)
        slot += step
    return starts


def _within_hours(cal: Calendar, entry: dict, start: datetime, end: datetime) -> bool:
    """Whether [start, end) sits inside the calendar owner's weekday working hours."""
    tz = fixed_offset(entry["utc_offset"]) if "utc_offset" in entry else cal.tz
    s, e = start.astimezone(tz), end.astimezone(tz)
    hours = entry.get("working_hours") or {"start": "00:00", "end": "24:00"}

    same_day = s.date() == e.date() or (e.hour, e.minute) == (0, 0)
    end_minute = 24 * 60 if (e.hour, e.minute) == (0, 0) else e.hour * 60 + e.minute
    return (s.weekday() < 5 and same_day
            and _minutes(hours["start"]) <= s.hour * 60 + s.minute and end_minute <= _minutes(hours["end"]))


# --------------------------------------------------------------------------
# Protocol
# --------------------------------------------------------------------------

def handle(request: dict, cal: Calendar) -> dict | None:
    """JSON-RPC response for one request (None for notifications)."""
    request_id, method = request.get("id"), request.get("method")
    if request_id is None:
        return None
    params = request.get("params") or {}
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "crucible-mock-calendar", "version": "1.0.0"}}
    elif method == "tools/list":
        result = {"tools": [{"name": n, **TOOLS[n]} for n in cal.tools]}
    elif method == "tools/call":
        name = params.get("name")
        if name not in cal.tools:
            return {"jsonrpc": "2.0", "id": request_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {name}"}}
        try:
            payload = getattr(cal, name)(**(params.get("arguments") or {}))
            result = {"content": [{"type": "text", "text": json.dumps(payload)}]}
        except (ToolError, TypeError) as exc:
            result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": request_id,
                "error": {"code": -32601, "message": f"Unknown method: {method}"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main() -> None:
    parser = argparse.ArgumentParser(description="crucible mock calendar MCP server")
    parser.add_argument("--dataset", required=True, help="fixtures/mock-calendar/<dataset>.json")
    cal = Calendar.load(parser.parse_args().dataset)
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            response = handle(json.loads(line), cal)
        except json.JSONDecodeError as exc:
            response = {"jsonrpc": "2.0", "error": {"code": -32700, "message": f"Invalid JSON: {exc}"}}
        if response:
            print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
