#!/usr/bin/env python3
"""crucible's mock calendar MCP server (stdio JSON-RPC) for scheduling tests.

Declared per prompt as `mcp_servers: ["mock-calendar:<dataset>"]`; the dataset
(fixtures/mock-calendar/<dataset>.json) is the whole world the model sees: who
exists, what "now" is, and every event.

It imitates the Google Calendar MCP servers people actually use, so a model is
tested on the tools and data shapes it will meet for real:
  list_calendars   calendar list entries (id, summary, timeZone, accessRole)
  list_events      events.list: calendarId, startTime, endTime, timeZone,
                   fullText, eventType, orderBy, pageSize, pageToken
  get_event        events.get
  search_events    keyword search on the user's primary calendar
  get_freebusy     freebusy.query: busy blocks per calendar, no details
  get_current_time (community servers offer it; the dataset's "now")
Events are Google Event resources (start/end as {dateTime, timeZone} or {date},
status, transparency, eventType, attendees[].responseStatus). Colleagues share
only free/busy: list_events and get_event on their calendars fail with 403, and
get_freebusy is how you see them. There is deliberately no suggest_time or any
tool that intersects several people's time; the model does that.

A dataset can restrict `tools`, though the shipped ones offer them all. Stdlib only.
Busy means status != cancelled, transparency != transparent, and the calendar
owner has not declined.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DATASET_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "mock-calendar"

# UTC offsets valid for the datasets' dates (September 2026)
ZONES = {"America/Chicago": "-05:00", "America/New_York": "-04:00", "America/Denver": "-06:00",
         "America/Los_Angeles": "-07:00", "Europe/London": "+01:00", "Europe/Zurich": "+02:00", "UTC": "+00:00"}
DEFAULT_EVENT_TYPES = {"default", "outOfOffice", "focusTime", "fromGmail"}
EVENT_TYPE_NAMES = {"DEFAULT": "default", "OUT_OF_OFFICE": "outOfOffice", "FOCUS_TIME": "focusTime",
                    "WORKING_LOCATION": "workingLocation", "BIRTHDAY": "birthday", "FROM_GMAIL": "fromGmail",
                    "EVENT_TYPE_UNSPECIFIED": "default"}

_TIME_ARGS = {
    "timeZone": {"type": "string", "description": "IANA time zone used to resolve times given without an offset. "
                                                    "Leave unset to use the user's own."},
}
TOOLS = {
    "get_current_time": {
        "description": "Get the current date and time and the user's time zone.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "list_calendars": {
        "description": ("Returns the calendars this user owns or has subscribed to, including colleagues' "
                        "calendars shared with them. Use it to resolve a person or team into a calendar id "
                        "(an email address) and to see each calendar's time zone and the user's access to it."),
        "inputSchema": {"type": "object", "properties": {
            "pageSize": {"type": "integer", "description": "Max results per page. Default 100, max 250."},
            "pageToken": {"type": "string", "description": "Token for the next page."}}},
    },
    "list_events": {
        "description": ("Returns events on the given calendar that overlap a time range. Only calendars that "
                        "share their events can be read; a calendar shared for free/busy only is not readable "
                        "here (use get_freebusy). Declined and transparent events are returned with their "
                        "details so the caller can tell."),
        "inputSchema": {"type": "object", "properties": {
            "calendarId": {"type": "string", "description": "Email address of the calendar. Default: primary calendar."},
            "startTime": {"type": "string", "description": "Lower bound of the range, ISO 8601, e.g. 2026-09-01T10:00:00. Default: now."},
            "endTime": {"type": "string", "description": "Upper bound of the range, ISO 8601. Default: startTime + 7 days."},
            "eventType": {"type": "array", "items": {"type": "string", "enum": list(EVENT_TYPE_NAMES)},
                          "description": "Event types to return. Default: DEFAULT, OUT_OF_OFFICE, FOCUS_TIME, FROM_GMAIL."},
            "fullText": {"type": "string", "description": "Case-insensitive search over title, description, location and attendees (AND of terms)."},
            "orderBy": {"type": "string", "description": "default, startTime, startTimeDesc or lastModified."},
            "pageSize": {"type": "integer", "description": "Max events per page (default 100, max 250)."},
            "pageToken": {"type": "string", "description": "Next page token from a previous call."},
            **_TIME_ARGS}},
    },
    "get_event": {
        "description": "Returns a single event on the given calendar.",
        "inputSchema": {"type": "object", "properties": {
            "eventId": {"type": "string", "description": "Event id, from list_events or search_events."},
            "calendarId": {"type": "string", "description": "Email address of the calendar. Default: primary calendar."}},
            "required": ["eventId"]},
    },
    "search_events": {
        "description": "Searches events on the user's primary calendar by keyword.",
        "inputSchema": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Search query (case-insensitive)."},
            "pageSize": {"type": "integer"}, "pageToken": {"type": "string"}},
            "required": ["query"]},
    },
    "get_freebusy": {
        "description": ("Returns when each of several calendars is busy over a time range: busy blocks only, "
                        "no titles or details. Works for any calendar shared with the user, including "
                        "colleagues who share free/busy only."),
        "inputSchema": {"type": "object", "properties": {
            "calendars": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string"}},
                                                      "required": ["id"]},
                          "description": "Calendars to check, as [{\"id\": \"name@example.com\"}]. \"primary\" is the user's own."},
            "timeMin": {"type": "string", "description": "Start of the range, ISO 8601."},
            "timeMax": {"type": "string", "description": "End of the range, ISO 8601."},
            **_TIME_ARGS}, "required": ["calendars", "timeMin", "timeMax"]},
    },
}


class ToolError(Exception):
    """Reported to the model as an isError tool result, not a protocol error."""

    def __init__(self, code: int, message: str):
        super().__init__(json.dumps({"error": {"code": code, "message": message}}))


def fixed_offset(text: str) -> timezone:
    sign = -1 if text.startswith("-") else 1
    hours, _, minutes = text.lstrip("+-").partition(":")
    return timezone(sign * timedelta(hours=int(hours), minutes=int(minutes or 0)))


def parse_time(value: str, tz: timezone) -> datetime:
    """ISO 8601 -> aware datetime; a value without an offset is in `tz`."""
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        raise ToolError(400, f"Invalid time '{value}': expected ISO 8601, e.g. 2026-09-01T15:30:00") from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)


def midnight(day: datetime) -> datetime:
    return day.replace(hour=0, minute=0, second=0, microsecond=0)


def _minutes(text: str) -> int:
    return int(text[:2]) * 60 + int(text[3:])


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

    # ---- model of the data -----------------------------------------------

    def calendar(self, calendar_id: str | None) -> dict:
        calendar_id = self.owner if calendar_id in (None, "", "primary") else calendar_id
        cal = self.calendars.get(calendar_id)
        if cal is None:
            raise ToolError(404, "Not Found")
        return cal

    def readable(self, calendar_id: str | None) -> dict:
        """A calendar whose events the user may read (their own)."""
        cal = self.calendar(calendar_id)
        if cal["id"] != self.owner:
            raise ToolError(403, f"Forbidden: you have free/busy access only to {cal['id']}; "
                                 "its events are not visible. Use get_freebusy.")
        return cal

    def zone(self, name: str | None) -> timezone:
        if not name:
            return self.tz
        if name not in ZONES:
            raise ToolError(400, f"Unknown time zone: {name}")
        return fixed_offset(ZONES[name])

    def span(self, event: dict, cal: dict) -> tuple[datetime, datetime]:
        """Absolute start and end of a Google event resource."""
        tz = fixed_offset(cal["utc_offset"]) if "utc_offset" in cal else self.tz
        out = []
        for side in ("start", "end"):
            if "dateTime" in event[side]:
                out.append(parse_time(event[side]["dateTime"], self.tz))
            else:   # all-day: midnight to midnight in the calendar's zone
                out.append(datetime.combine(date.fromisoformat(event[side]["date"]), datetime.min.time(), tz))
        return out[0], out[1]

    @staticmethod
    def is_busy(event: dict, owner: str) -> bool:
        if event.get("status", "confirmed") == "cancelled" or event.get("transparency") == "transparent":
            return False
        return not any(a.get("email") == owner and a.get("responseStatus") == "declined"
                       for a in event.get("attendees", []))

    def overlapping(self, cal: dict, start: datetime, end: datetime) -> list[dict]:
        found = [e for e in cal["events"] if self.span(e, cal)[0] < end and self.span(e, cal)[1] > start]
        return sorted(found, key=lambda e: self.span(e, cal))

    def busy_blocks(self, calendar_id: str, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
        """Merged busy intervals clipped to [start, end)."""
        cal = self.calendar(calendar_id)
        blocks: list[list[datetime]] = []
        for e in self.overlapping(cal, start, end):
            if not self.is_busy(e, cal["id"]):
                continue
            s, f = max(self.span(e, cal)[0], start), min(self.span(e, cal)[1], end)
            if blocks and s <= blocks[-1][1]:
                blocks[-1][1] = max(blocks[-1][1], f)
            else:
                blocks.append([s, f])
        return [(s, f) for s, f in blocks]

    def busy(self, calendar_id: str, time_min: str, time_max: str) -> list[dict]:
        """busy_blocks as {start, end} ISO strings (what get_freebusy reports)."""
        start, end = parse_time(time_min, self.tz), parse_time(time_max, self.tz)
        return [{"start": s.isoformat(), "end": f.isoformat()} for s, f in self.busy_blocks(calendar_id, start, end)]

    # ---- tools -------------------------------------------------------------

    def get_current_time(self) -> dict:
        return {"currentTime": self.now.isoformat(), "dayOfWeek": self.now.strftime("%A"),
                "timeZone": self.timezone_name}

    def list_calendars(self, pageSize: int = 100, pageToken: str | None = None) -> dict:
        entries = [{"kind": "calendar#calendarListEntry", "id": c["id"], "summary": c["name"],
                    **({"description": c["team"]} if c.get("team") else {}),
                    "timeZone": c.get("timezone", self.timezone_name),
                    "accessRole": "owner" if c["id"] == self.owner else "freeBusyReader",
                    **({"primary": True} if c["id"] == self.owner else {})}
                   for c in self.calendars.values()]
        items, token = self._page(entries, pageSize, pageToken)
        return {"kind": "calendar#calendarList", "items": items, **({"nextPageToken": token} if token else {})}

    def list_events(self, calendarId: str | None = None, startTime: str | None = None, endTime: str | None = None,
                    eventType: list | None = None, fullText: str | None = None, orderBy: str | None = None,
                    pageSize: int = 100, pageToken: str | None = None, timeZone: str | None = None,
                    eventTypeFilter: list | None = None) -> dict:
        cal = self.readable(calendarId)
        tz = self.zone(timeZone)
        start = parse_time(startTime, tz) if startTime else self.now
        end = parse_time(endTime, tz) if endTime else start + timedelta(days=7)
        if end <= start:
            raise ToolError(400, "endTime must be after startTime")
        types = {EVENT_TYPE_NAMES.get(t, t) for t in (eventType or eventTypeFilter or [])} or DEFAULT_EVENT_TYPES
        found = [e for e in self.overlapping(cal, start, end) if e.get("eventType", "default") in types]
        if fullText:
            found = [e for e in found if all(term in self._haystack(e) for term in fullText.lower().split())]
        if orderBy == "startTimeDesc":
            found.reverse()
        items, token = self._page(found, pageSize, pageToken)
        return {"kind": "calendar#events", "summary": cal["name"], "timeZone": cal.get("timezone", self.timezone_name),
                "items": items, **({"nextPageToken": token} if token else {})}

    def get_event(self, eventId: str, calendarId: str | None = None) -> dict:
        cal = self.readable(calendarId)
        event = next((e for e in cal["events"] if e["id"] == eventId), None)
        if event is None:
            raise ToolError(404, "Not Found")
        return event

    def search_events(self, query: str, pageSize: int = 100, pageToken: str | None = None) -> dict:
        cal = self.readable(None)
        found = [e for e in cal["events"] if all(term in self._haystack(e) for term in query.lower().split())]
        found.sort(key=lambda e: self.span(e, cal))
        items, token = self._page(found, pageSize, pageToken)
        return {"kind": "calendar#events", "items": items, **({"nextPageToken": token} if token else {})}

    def get_freebusy(self, calendars: list, timeMin: str, timeMax: str, timeZone: str | None = None) -> dict:
        if not isinstance(calendars, list) or not calendars:
            raise ToolError(400, "calendars must be a non-empty list of {\"id\": ...}")
        tz = self.zone(timeZone)
        start, end = parse_time(timeMin, tz), parse_time(timeMax, tz)
        if end <= start:
            raise ToolError(400, "timeMax must be after timeMin")
        result = {}
        for item in calendars:
            cid = item.get("id") if isinstance(item, dict) else item
            if cid in ("primary", None) or cid in self.calendars:
                blocks = self.busy_blocks(self.calendar(cid)["id"], start, end)
                result[cid or "primary"] = {"busy": [{"start": s.isoformat(), "end": f.isoformat()} for s, f in blocks]}
            else:
                result[cid] = {"errors": [{"domain": "global", "reason": "notFound"}], "busy": []}
        return {"kind": "calendar#freeBusy", "timeMin": start.isoformat(), "timeMax": end.isoformat(),
                "calendars": result}

    # ---- helpers -----------------------------------------------------------

    @staticmethod
    def _haystack(event: dict) -> str:
        parts = [event.get("summary", ""), event.get("description", ""), event.get("location", "")]
        parts += [a.get("email", "") for a in event.get("attendees", [])]
        return " ".join(parts).lower()

    @staticmethod
    def _page(items: list, size: int | None, token: str | None) -> tuple[list, str | None]:
        size = max(1, min(int(size or 100), 250))
        offset = int(token) if token and str(token).isdigit() else 0
        page = items[offset:offset + size]
        return page, (str(offset + size) if offset + size < len(items) else None)


# --------------------------------------------------------------------------
# Ground truth (not a tool): what a correct scheduling answer may contain
# --------------------------------------------------------------------------

def free_starts(cal: Calendar, calendar_ids: list, time_min: str, time_max: str,
                minutes: int, step_minutes: int = 30) -> list[datetime]:
    """Start times (on the step grid) where a `minutes`-long meeting fits.

    Everyone must be free of busy time, and the meeting must sit inside each
    attendee's 9-5 (their working_hours) on a weekday in their own zone. Used by
    tests and graders to know the right answer; models never see this.
    """
    start, end = parse_time(time_min, cal.tz), parse_time(time_max, cal.tz)
    busy = {cid: cal.busy_blocks(cid, start, end) for cid in calendar_ids}
    length, step = timedelta(minutes=minutes), timedelta(minutes=step_minutes)
    slot = midnight(cal.now)
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
                  "serverInfo": {"name": "crucible-mock-calendar", "version": "2.0.0"}}
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
