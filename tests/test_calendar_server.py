"""The mock calendar MCP server, its datasets, and the A-series scheduling tests."""
import json
import subprocess
import sys

import pytest

from crucible import workspace
from crucible.agents.base import REPO_ROOT, available_mcp_servers, mcp_server_commands, split_server_spec
from crucible.mcp_servers import calendar_server as cs
from crucible.taxonomy import suite_for, validate_category

SERVER = REPO_ROOT / "crucible" / "mcp_servers" / "calendar_server.py"


def at(day, hhmm):
    return f"2026-{day}T{hhmm}:00-05:00"


def call(cal, name, **arguments):
    result = cs.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": name, "arguments": arguments}}, cal)["result"]
    return result, (json.loads(result["content"][0]["text"]) if not result.get("isError") else None)


def starts(cal, ids, first, last, minutes=60):
    return [s.strftime("%m-%d %H:%M") for s in cs.free_starts(cal, ids, at(*first), at(*last), minutes)]


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
    def test_tools_follow_the_dataset(self, spark, forge):
        def listed(cal):
            return [t["name"] for t in cs.handle({"id": 1, "method": "tools/list"}, cal)["result"]["tools"]]
        assert listed(spark) == ["get_current_time", "list_events"]
        assert "get_free_busy" in listed(forge)

    def test_withheld_tool_is_unknown(self, spark):
        reply = cs.handle({"id": 1, "method": "tools/call",
                           "params": {"name": "get_free_busy", "arguments": {}}}, spark)
        assert reply["error"]["code"] == -32601

    def test_notifications_get_no_response(self, spark):
        assert cs.handle({"method": "notifications/initialized"}, spark) is None

    def test_bad_input_is_a_tool_error(self, spark):
        assert call(spark, "list_events", time_min="soon", time_max="later")[0]["isError"] is True
        assert call(spark, "list_events")[0]["isError"] is True   # missing arguments
        assert call(spark, "list_events", calendar_id="nobody@example.com",
                    time_min=at("09-01", "00:00"), time_max=at("09-02", "00:00"))[0]["isError"] is True
        assert call(spark, "list_events", time_min=at("09-02", "00:00"),
                    time_max=at("09-01", "00:00"))[0]["isError"] is True

    def test_runs_over_stdio(self):
        requests = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                     "params": {"name": "get_current_time", "arguments": {}}}]
        out = subprocess.run([sys.executable, str(SERVER), "--dataset", "spark"], capture_output=True,
                             text=True, timeout=30, input="\n".join(json.dumps(r) for r in requests) + "\n")
        replies = [json.loads(line) for line in out.stdout.splitlines()]
        assert [r["id"] for r in replies] == [1, 2]
        assert json.loads(replies[1]["result"]["content"][0]["text"])["weekday"] == "Tuesday"

    def test_unknown_dataset_fails_at_startup(self):
        out = subprocess.run([sys.executable, str(SERVER), "--dataset", "nope"],
                             capture_output=True, text=True, timeout=30, input="")
        assert out.returncode != 0 and "spark" in out.stderr


class TestQueries:
    def test_current_time_is_the_datasets(self, spark):
        _, now = call(spark, "get_current_time")
        assert now["now"] == at("09-01", "11:20") and now["weekday"] == "Tuesday"

    def test_event_ending_at_range_start_is_not_in_range(self, spark):
        _, found = call(spark, "list_events", time_min=at("09-01", "15:30"), time_max=at("09-01", "16:30"))
        assert [e["summary"] for e in found["events"]] == ["Customer call"]

    def test_naive_times_are_in_the_dataset_zone(self, spark):
        _, a = call(spark, "list_events", time_min="2026-09-01T15:00:00", time_max="2026-09-01T15:10:00")
        _, b = call(spark, "list_events", time_min=at("09-01", "15:00"), time_max=at("09-01", "15:10"))
        assert a == b and [e["summary"] for e in a["events"]] == ["Design review"]

    def test_primary_is_the_owner(self, pair):
        _, found = call(pair, "list_events", calendar_id="primary",
                        time_min=at("09-02", "09:00"), time_max=at("09-02", "12:00"))
        assert found["calendar_id"] == "alex@example.com"
        assert "Interview loop" in [e["summary"] for e in found["events"]]

    def test_calendars_listing(self, forge):
        _, listed = call(forge, "list_calendars")
        calendars = listed["calendars"]
        assert len(calendars) == 19
        assert sum(c["team"] == "Platform" for c in calendars) == 16
        assert [c["id"] for c in calendars if c["primary"]] == ["alex@example.com"]
        marcus = next(c for c in calendars if c["id"] == "marcus@example.com")
        assert marcus["timezone"] == "America/New_York"

    def test_free_busy_skips_cancelled_and_transparent_and_merges(self, pair):
        fb = pair.get_free_busy(["alex@example.com", "jamie@example.com"],
                                at("09-03", "00:00"), at("09-04", "00:00"))
        alex = fb["calendars"]["alex@example.com"]["busy"]
        # the cancelled 13:00-15:00 focus time is not busy; sprint review and project review are
        assert [(b["start"][11:16], b["end"][11:16]) for b in alex] == [
            ("09:00", "09:30"), ("10:00", "11:00"), ("12:00", "13:00"), ("15:00", "16:00")]
        jamie = fb["calendars"]["jamie@example.com"]["busy"]
        assert ("11:00", "12:00") not in [(b["start"][11:16], b["end"][11:16]) for b in jamie]

    def test_free_busy_tool_over_the_protocol(self, forge):
        _, fb = call(forge, "get_free_busy", calendar_ids=["alex@example.com", "marcus@example.com"],
                     time_min=at("09-07", "00:00"), time_max=at("09-08", "00:00"))
        assert set(fb["calendars"]) == {"alex@example.com", "marcus@example.com"}
        assert fb["calendars"]["alex@example.com"]["busy"] == [   # Labor Day, all day
            {"start": at("09-07", "00:00"), "end": at("09-08", "00:00")}]
        assert call(forge, "get_free_busy", calendar_ids=[], time_min=at("09-07", "00:00"),
                    time_max=at("09-08", "00:00"))[0]["isError"] is True

    def test_free_busy_clips_to_range(self, spark):
        busy = spark.busy("alex@example.com", at("09-01", "14:30"), at("09-01", "16:30"))
        assert [(b["start"][11:16], b["end"][11:16]) for b in busy] == [("14:30", "15:30"), ("16:00", "16:30")]


class TestDatasetAnswers:
    """The ground truth quoted in prompts A1-A3 (keep in sync with their comments)."""

    def test_spark_is_free_at_3_30(self, spark):
        assert spark.busy("alex@example.com", at("09-01", "15:30"), at("09-01", "15:31")) == []
        assert spark.busy("alex@example.com", at("09-01", "15:29"), at("09-01", "15:31")) != []

    def test_pair_options(self, pair):
        assert starts(pair, ["alex@example.com", "jamie@example.com"], ("08-31", "08:30"), ("09-05", "00:00")) == [
            "09-02 15:30", "09-02 16:00", "09-03 11:00", "09-03 13:00", "09-03 16:00",
            "09-04 10:30", "09-04 11:00", "09-04 15:00", "09-04 15:30", "09-04 16:00"]

    def test_forge_options(self, forge):
        team = [c["id"] for c in forge.list_calendars()["calendars"] if c["team"] == "Platform"]
        assert starts(forge, team, ("08-31", "08:30"), ("09-15", "00:00")) == [
            "09-01 13:00", "09-01 13:30", "09-02 09:00", "09-03 14:00", "09-03 14:30", "09-03 15:00",
            "09-08 11:00", "09-09 15:00"]

    def test_forge_traps_hold(self, forge):
        team = [c["id"] for c in forge.list_calendars()["calendars"] if c["team"] == "Platform"]
        # 4-5 PM Central on 9/8 is empty on every calendar but outside Marcus's hours
        assert all(not forge.busy(t, at("09-08", "16:00"), at("09-08", "17:00")) for t in team)
        assert starts(forge, team, ("09-08", "16:00"), ("09-08", "17:00")) == []
        # adding the Design people shrinks the answer: leaving them out matters
        everyone = [c["id"] for c in forge.list_calendars()["calendars"]]
        assert len(starts(forge, everyone, ("08-31", "08:30"), ("09-15", "00:00"))) < 8
        # Labor Day blocks everyone
        assert starts(forge, team, ("09-07", "00:00"), ("09-08", "00:00")) == []

    def test_forge_edge_days_are_closed(self, forge):
        team = [c["id"] for c in forge.list_calendars()["calendars"] if c["team"] == "Platform"]
        assert starts(forge, team, ("08-31", "08:30"), ("09-01", "00:00")) == []
        assert starts(forge, team, ("09-14", "00:00"), ("09-15", "00:00")) == []


class TestWiring:
    A_TESTS = {"A1": "spark", "A2": "pair", "A3": "forge"}

    def test_spec_parsing(self):
        assert split_server_spec("mock-calendar:forge") == ("mock-calendar", "forge")
        assert split_server_spec("web") == ("web", None)

    def test_dataset_becomes_a_server_argument(self):
        commands = mcp_server_commands(["mock-calendar:forge", "web"])
        assert commands["mock-calendar"][1:] == [str(SERVER), "--dataset", "forge"]
        assert "--dataset" not in commands["web"]

    def test_calendar_server_needs_a_dataset(self):
        assert available_mcp_servers(["mock-calendar", "mock-calendar:spark"]) == ["mock-calendar:spark"]

    @pytest.mark.parametrize("test_id,dataset", A_TESTS.items())
    def test_prompts_declare_an_existing_dataset(self, test_id, dataset):
        prompt = workspace.load_prompt(test_id)
        assert prompt["mcp_servers"] == [f"mock-calendar:{dataset}"]
        assert (cs.DATASET_DIR / f"{dataset}.json").is_file()
        assert available_mcp_servers(prompt["mcp_servers"]) == prompt["mcp_servers"]
        validate_category(prompt["category"])
        assert suite_for(test_id) == "agentic"
        assert sum(r["max_score"] for r in prompt["rubric"]) == 10
