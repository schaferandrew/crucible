"""The mock calendar MCP server, its datasets, and the A-series scheduling tests."""
import json
import subprocess
import sys

import pytest

from crucible import workspace
from crucible.agents.base import REPO_ROOT, available_mcp_servers, mcp_server_commands, split_server_spec
from crucible.mcp_servers import calendar_server as cs
from crucible.taxonomy import mode_for, validate_area, validate_category

SERVER = REPO_ROOT / "crucible" / "mcp_servers" / "calendar_server.py"


def at(day, hhmm):
    return f"2026-{day}T{hhmm}:00-05:00"


def local(day, hhmm):
    return f"2026-{day}T{hhmm}:00"   # no offset, as real clients send it


def call(cal, name, **arguments):
    result = cs.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": name, "arguments": arguments}}, cal)["result"]
    return result, (json.loads(result["content"][0]["text"]) if not result.get("isError") else None)


def platform(cal):
    return [c["id"] for c in cal.list_calendars()["items"] if c.get("description") == "Platform"]


def starts(cal, ids, first, last, minutes=60):
    return [s.strftime("%m-%d %H:%M") for s in cs.free_starts(cal, ids, at(*first), at(*last), minutes)]


def times(blocks):
    return [(b["start"][11:16], b["end"][11:16]) for b in blocks]


@pytest.fixture(scope="module")
def spark():
    return cs.Calendar.load("spark")


@pytest.fixture(scope="module")
def pair():
    return cs.Calendar.load("pair")


@pytest.fixture(scope="module")
def forge():
    return cs.Calendar.load("forge")


class TestProtocol:
    def test_datasets_offer_the_whole_tool_set(self, spark, forge):
        def listed(cal):
            return [t["name"] for t in cs.handle({"id": 1, "method": "tools/list"}, cal)["result"]["tools"]]
        assert listed(spark) == listed(forge) == list(cs.TOOLS)

    def test_a_dataset_can_restrict_tools(self):
        cal = cs.Calendar({**json.loads((cs.DATASET_DIR / "spark.json").read_text(encoding="utf-8")),
                           "tools": ["list_events"]})
        assert [t["name"] for t in cs.handle({"id": 1, "method": "tools/list"}, cal)["result"]["tools"]] == ["list_events"]
        reply = cs.handle({"id": 1, "method": "tools/call", "params": {"name": "get_freebusy", "arguments": {}}}, cal)
        assert reply["error"]["code"] == -32601

    def test_no_tool_does_the_scheduling_for_the_model(self):
        # the real connector's suggest_time, and anything like it, must stay out
        assert not {"suggest_time", "find_free_time", "get_availability"} & set(cs.TOOLS)

    def test_notifications_get_no_response(self, spark):
        assert cs.handle({"method": "notifications/initialized"}, spark) is None

    def test_bad_input_is_a_tool_error(self, spark):
        assert call(spark, "list_events", startTime="soon")[0]["isError"] is True
        assert call(spark, "list_events", calendarId="nobody@example.com")[0]["isError"] is True
        assert call(spark, "list_events", startTime=local("09-02", "00:00"),
                    endTime=local("09-01", "00:00"))[0]["isError"] is True
        assert call(spark, "list_events", timeZone="Mars/Olympus")[0]["isError"] is True

    def test_runs_over_stdio(self):
        requests = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                     "params": {"name": "get_current_time", "arguments": {}}}]
        out = subprocess.run([sys.executable, str(SERVER), "--dataset", "spark"], capture_output=True,
                             text=True, timeout=30, input="\n".join(json.dumps(r) for r in requests) + "\n")
        replies = [json.loads(line) for line in out.stdout.splitlines()]
        assert [r["id"] for r in replies] == [1, 2]
        assert json.loads(replies[1]["result"]["content"][0]["text"])["dayOfWeek"] == "Tuesday"

    def test_unknown_dataset_fails_at_startup(self):
        out = subprocess.run([sys.executable, str(SERVER), "--dataset", "nope"],
                             capture_output=True, text=True, timeout=30, input="")
        assert out.returncode != 0 and "spark" in out.stderr


class TestEvents:
    """list_events / get_event / search_events behave like Google Calendar's."""

    def test_current_time_is_the_datasets(self, spark):
        _, now = call(spark, "get_current_time")
        assert now["currentTime"] == at("09-01", "11:20") and now["dayOfWeek"] == "Tuesday"

    def test_defaults_to_now_and_a_week(self, spark):
        _, found = call(spark, "list_events")
        titles = [e["summary"] for e in found["items"]]
        # 11:20 Tuesday: the 11:00 1:1 is still running, the 9:00 standup is over
        assert titles[0] == "1:1 with Jamie" and "Standup" not in titles and "Budget review" in titles

    def test_event_ending_at_range_start_is_not_in_range(self, spark):
        _, found = call(spark, "list_events", startTime=local("09-01", "15:30"), endTime=local("09-01", "16:30"))
        assert [e["summary"] for e in found["items"]] == ["Customer call"]

    def test_times_without_offset_use_the_users_zone_or_the_given_one(self, spark):
        _, a = call(spark, "list_events", startTime="2026-09-01T15:00:00", endTime="2026-09-01T15:10:00")
        _, b = call(spark, "list_events", startTime=at("09-01", "15:00"), endTime=at("09-01", "15:10"))
        _, c = call(spark, "list_events", startTime="2026-09-01T16:00:00", endTime="2026-09-01T16:10:00",
                    timeZone="America/New_York")
        assert a == b and [e["summary"] for e in a["items"]] == ["Design review"]
        assert [e["summary"] for e in c["items"]] == ["Design review"]   # 4 PM Eastern is 3 PM Central

    def test_events_are_google_event_resources(self, pair):
        _, found = call(pair, "list_events", startTime=local("09-03", "00:00"), endTime=local("09-04", "00:00"),
                        eventType=["DEFAULT", "BIRTHDAY"])
        by_title = {e["summary"]: e for e in found["items"]}
        sync = by_title["Design sync (declined)"]
        assert sync["start"] == {"dateTime": at("09-03", "13:00"), "timeZone": "America/Chicago"}
        assert sync["attendees"][0] == {"email": "alex@example.com", "self": True, "responseStatus": "declined"}
        assert by_title["Standup"]["status"] == "confirmed"

    def test_birthdays_hidden_by_default_all_day_uses_date(self, pair):
        args = dict(startTime=local("09-04", "00:00"), endTime=local("09-05", "00:00"))
        _, default = call(pair, "list_events", **args)
        _, asked = call(pair, "list_events", eventType=["BIRTHDAY"], **args)
        assert "Priya's birthday" not in [e["summary"] for e in default["items"]]
        birthday = asked["items"][0]
        assert birthday["start"] == {"date": "2026-09-04"} and birthday["transparency"] == "transparent"

    def test_full_text_orders_and_pages(self, forge):
        args = dict(startTime=local("09-01", "00:00"), endTime=local("09-12", "00:00"))
        _, standups = call(forge, "list_events", fullText="platform STANDUP", **args)
        assert len(standups["items"]) == 8 and standups["items"] == sorted(
            standups["items"], key=lambda e: e["start"]["dateTime"])
        _, first = call(forge, "list_events", fullText="standup", pageSize=3, **args)
        _, second = call(forge, "list_events", fullText="standup", pageSize=3, pageToken=first["nextPageToken"], **args)
        assert len(first["items"]) == 3 and second["items"][0] != first["items"][0]
        _, desc = call(forge, "list_events", fullText="standup", orderBy="startTimeDesc", **args)
        assert desc["items"][0]["start"]["dateTime"].startswith("2026-09-11")

    def test_get_event_and_search_events(self, pair):
        _, found = call(pair, "search_events", query="interview")
        event = found["items"][0]
        assert event["summary"] == "Interview loop"
        _, same = call(pair, "get_event", eventId=event["id"])
        assert same == event
        assert call(pair, "get_event", eventId="nope")[0]["isError"] is True

    def test_primary_is_the_owner(self, pair):
        _, found = call(pair, "list_events", calendarId="primary",
                        startTime=local("09-02", "09:00"), endTime=local("09-02", "12:00"))
        assert found["summary"] == "Alex Rivera"
        assert "Interview loop" in [e["summary"] for e in found["items"]]

    def test_colleagues_share_free_busy_only(self, pair):
        for tool, args in (("list_events", {}), ("get_event", {"eventId": "jamie001"})):
            result, _ = call(pair, tool, calendarId="jamie@example.com", **args)
            text = result["content"][0]["text"]
            assert result["isError"] is True and '"code": 403' in text and "get_freebusy" in text


class TestCalendars:
    def test_listing_is_a_calendar_list(self, forge):
        _, listed = call(forge, "list_calendars")
        items = listed["items"]
        assert len(items) == 19 and listed["kind"] == "calendar#calendarList"
        assert len(platform(forge)) == 16
        assert [c["id"] for c in items if c.get("primary")] == ["alex@example.com"]
        roles = {c["accessRole"] for c in items if not c.get("primary")}
        assert roles == {"freeBusyReader"}
        marcus = next(c for c in items if c["id"] == "marcus@example.com")
        assert (marcus["summary"], marcus["timeZone"]) == ("Marcus Webb", "America/New_York")
        # nothing the real API would not tell you: no team field, no working hours
        assert not {"team", "working_hours", "utc_offset"} & set(marcus)


class TestFreeBusy:
    def test_busy_blocks_skip_declined_and_transparent_and_merge(self, pair):
        _, fb = call(pair, "get_freebusy", calendars=[{"id": "primary"}, {"id": "jamie@example.com"}],
                     timeMin=local("09-03", "00:00"), timeMax=local("09-04", "00:00"))
        assert fb["kind"] == "calendar#freeBusy"
        # Alex: the declined 13:00-15:00 Design sync does not block
        assert times(fb["calendars"]["primary"]["busy"]) == [
            ("09:00", "09:30"), ("10:00", "11:00"), ("12:00", "13:00"), ("15:00", "16:00")]
        # Jamie: only blocks, no titles; the declined 11:00 1:1 does not block
        jamie = fb["calendars"]["jamie@example.com"]["busy"]
        assert times(jamie) == [("09:30", "10:30"), ("12:00", "13:00"), ("14:00", "16:00")]
        assert all(set(b) == {"start", "end"} for b in jamie)

    def test_all_day_and_out_of_office_block_the_day(self, forge):
        _, fb = call(forge, "get_freebusy", calendars=[{"id": "alex@example.com"}, {"id": "priya@example.com"}],
                     timeMin=local("09-07", "00:00"), timeMax=local("09-08", "00:00"))
        assert fb["calendars"]["alex@example.com"]["busy"] == [
            {"start": at("09-07", "00:00"), "end": at("09-08", "00:00")}]       # Labor Day (all-day)
        _, fb = call(forge, "get_freebusy", calendars=[{"id": "priya@example.com"}],
                     timeMin=local("09-10", "09:00"), timeMax=local("09-10", "17:00"))
        assert fb["calendars"]["priya@example.com"]["busy"] == [
            {"start": at("09-10", "09:00"), "end": at("09-10", "17:00")}]       # out of office, clipped

    def test_range_clips_blocks(self, spark):
        busy = spark.busy("alex@example.com", at("09-01", "14:30"), at("09-01", "16:30"))
        assert times(busy) == [("14:30", "15:30"), ("16:00", "16:30")]

    def test_unknown_calendar_is_reported_per_calendar_and_input_is_checked(self, forge):
        _, fb = call(forge, "get_freebusy", calendars=[{"id": "ghost@example.com"}],
                     timeMin=local("09-01", "09:00"), timeMax=local("09-01", "17:00"))
        assert fb["calendars"]["ghost@example.com"]["errors"][0]["reason"] == "notFound"
        assert call(forge, "get_freebusy", calendars=[], timeMin="2026-09-01T09:00:00",
                    timeMax="2026-09-01T17:00:00")[0]["isError"] is True


class TestDatasetAnswers:
    """The ground truth quoted in prompts TASK-4 to TASK-6 (keep in sync with their comments)."""

    def test_spark_is_free_at_3_30(self, spark):
        assert spark.busy("alex@example.com", at("09-01", "15:30"), at("09-01", "15:31")) == []
        assert spark.busy("alex@example.com", at("09-01", "15:29"), at("09-01", "15:31")) != []

    def test_pair_options(self, pair):
        assert starts(pair, ["alex@example.com", "jamie@example.com"], ("08-31", "08:30"), ("09-05", "00:00")) == [
            "09-02 15:30", "09-02 16:00", "09-03 11:00", "09-03 13:00", "09-03 16:00",
            "09-04 10:30", "09-04 11:00", "09-04 15:00", "09-04 15:30", "09-04 16:00"]

    def test_forge_options(self, forge):
        assert starts(forge, platform(forge), ("08-31", "08:30"), ("09-15", "00:00")) == [
            "09-01 13:00", "09-01 13:30", "09-02 09:00", "09-03 14:00", "09-03 14:30", "09-03 15:00",
            "09-08 11:00", "09-09 15:00"]

    def test_forge_traps_hold(self, forge):
        team = platform(forge)
        # 4-5 PM Central on 9/8 is empty on every calendar but outside Marcus's hours
        assert all(not forge.busy(t, at("09-08", "16:00"), at("09-08", "17:00")) for t in team)
        assert starts(forge, team, ("09-08", "16:00"), ("09-08", "17:00")) == []
        # adding the Design people shrinks the answer: leaving them out matters
        everyone = [c["id"] for c in forge.list_calendars()["items"]]
        assert len(starts(forge, everyone, ("08-31", "08:30"), ("09-15", "00:00"))) < 8
        # Labor Day blocks everyone
        assert starts(forge, team, ("09-07", "00:00"), ("09-08", "00:00")) == []

    def test_forge_edge_days_are_closed(self, forge):
        team = platform(forge)
        assert starts(forge, team, ("08-31", "08:30"), ("09-01", "00:00")) == []
        assert starts(forge, team, ("09-14", "00:00"), ("09-15", "00:00")) == []


class TestWiring:
    CALENDAR_TESTS = {"TASK-4": "spark", "TASK-5": "pair", "TASK-6": "forge"}

    def test_spec_parsing(self):
        assert split_server_spec("mock-calendar:forge") == ("mock-calendar", "forge")
        assert split_server_spec("web") == ("web", None)

    def test_dataset_becomes_a_server_argument(self):
        commands = mcp_server_commands(["mock-calendar:forge", "web"])
        assert commands["mock-calendar"][1:] == [str(SERVER), "--dataset", "forge"]
        assert "--dataset" not in commands["web"]

    def test_calendar_server_needs_a_dataset(self):
        assert available_mcp_servers(["mock-calendar", "mock-calendar:spark"]) == ["mock-calendar:spark"]

    @pytest.mark.parametrize("test_id,dataset", CALENDAR_TESTS.items())
    def test_prompts_declare_an_existing_dataset(self, test_id, dataset):
        prompt = workspace.load_prompt(test_id)
        assert prompt["mcp_servers"] == [f"mock-calendar:{dataset}"]
        assert (cs.DATASET_DIR / f"{dataset}.json").is_file()
        assert available_mcp_servers(prompt["mcp_servers"]) == prompt["mcp_servers"]
        validate_category(prompt["category"])
        validate_area(prompt)
        assert mode_for(prompt) == "agentic" and prompt["area"] == "everyday"
        assert sum(r["max_score"] for r in prompt["rubric"]) == 10
