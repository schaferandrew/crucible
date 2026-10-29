"""The whole-document kinds of the items check (sections, language, mention, json, `section:`), grounded_numbers'
`sources:`, and the committed validation cases of the three tasks that use them."""
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

from crucible import checks, workspace

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / ".claude" / "skills" / "add-task" / "examples"


def _run(items, text, **check):
    prompt = {"checks": [{"id": "doc", "type": "items", "header": None, "items": items, **check}]}
    (result,) = checks.run_checks(prompt, text)
    return result


def _passed(result):
    return {i["id"]: i["passed"] for i in result["items"]}


BRIEF = "Intro\n\n# Brief\n\n## 1. Weather\nSunny.\n\n### Detail\nWindy.\n\n## Important Emails\n- one\n- two\n\n## Top 3\n1. a\n   - why\n2. b\n3. c\n"


def test_sections_present_and_in_order():
    item = {"id": "s", "normalize": "sections", "expect": ["Weather", ["Emails", "Email"], "Calendar", "Top 3"]}
    assert _passed(_run([item], BRIEF)) == {"s:weather": True, "s:emails": True, "s:calendar": False, "s:top-3": True}
    out_of_order = "## Emails\nx\n\n## Weather\ny\n\n## Calendar\nz"
    got = _passed(_run([{**item, "expect": ["Weather", "Emails", "Calendar"]}], out_of_order))
    assert got == {"s:weather": True, "s:emails": False, "s:calendar": True}   # one section out of place costs one item
    # a bold line is not a heading
    assert not _run([{**item, "expect": ["Weather"]}], "**Weather**\nSunny")["passed"]


def test_section_lines_and_top_level():
    assert checks._section_lines(BRIEF, "Weather") == ["Sunny.", "", "### Detail", "Windy.", ""]
    count = {"id": "n", "normalize": "count", "expect": 3, "section": "Top 3", "top_level": True}
    assert _run([count], BRIEF)["passed"]
    assert not _run([{**count, "top_level": False}], BRIEF)["passed"]       # the nested bullet is a fourth entry
    assert not _run([{**count, "section": "Nothing"}], BRIEF)["passed"]    # no such section: an empty block fails


ENGLISH = "Today you have a meeting with the team and the report is due at the end of the day, so it will be busy."
SPANISH = "Hoy tienes una reunión con el equipo y el informe vence al final del día, así que será un día muy ocupado."


def test_language_uses_function_word_shares():
    assert checks._language(SPANISH)[0] == "es" and checks._language(ENGLISH)[0] == "en"
    text = f"## English\n{ENGLISH}\n\n## Spanish\n{SPANISH}\n\n## Short\nHi"
    items = [{"id": "a", "normalize": "language", "expect": "en", "section": "English"},
             {"id": "b", "normalize": "language", "expect": "es", "section": "Spanish"},
             {"id": "c", "normalize": "language", "expect": "en", "section": "Spanish"},
             {"id": "d", "normalize": "language", "expect": "es", "section": "English"},
             {"id": "e", "normalize": "language", "expect": "es", "section": "Short"}]
    assert _passed(_run(items, text)) == {"a": True, "b": True, "c": False, "d": False, "e": False}


def test_mentions_read_the_mock_data():
    emails = checks._mock_titles("emails", None)
    assert len(emails) == 4 and "Question about the proposal timeline" in emails
    assert checks._mock_titles("events", "2026-09-02") == ["Planning", "Vendor demo", "Budget meeting"]
    assert len(checks._mock_titles("news", None)) == 3
    text = "- The client's question on the proposal timeline needs a reply.\n- Vendor demo at 10 clashes with Planning."
    items = [{"id": "e", "normalize": "mention", "source": "emails"}]
    got = _passed(_run(items, text))
    assert sum(got.values()) == 1 and got["e:question-about-the-proposal-timeline"]
    clash = {"id": "c", "normalize": "mention", "source": "events", "only": ["Planning", "Vendor demo"], "also": "clash|conflict"}
    assert _run([clash], text)["passed"]
    assert not _run([clash], "Planning and the Vendor demo are both today.")["passed"]
    assert not _run([{"id": "n", "normalize": "mention", "source": "news", "min": 1}], "Nothing happened.")["passed"]
    with pytest.raises(ValueError, match="not in the events data"):
        _run([{**clash, "only": ["Lunch"]}], text)


def test_a_generic_word_alone_is_not_a_mention():
    assert not checks._mentioned("We had a meeting about it.", "Budget meeting")
    assert checks._mentioned("The budget talk is at one.", "Budget meeting")
    assert not checks._mentioned("Everything from yesterday.", "Meeting notes from yesterday")


def _slots_doc(truth, **over):
    return json.dumps({"valid_slots": truth, "top3": [{"start": truth[0], "explanation": "x"}, {"start": truth[1], "explanation": "y"},
                                                      {"start": truth[2], "explanation": "z"}], **over})


def test_json_slots_are_computed_from_the_fixture():
    spec = {"fixture": "calendar-fixture.json", "minutes": 60, "step": 30}
    slots = checks._slot_truth(spec)
    assert len(slots["truth"]) == 85 and len(slots["conflicts"]) == 35
    assert "2026-08-31T10:00" in slots["conflicts"]       # Alex's standup
    assert "2026-08-31T15:30" in slots["truth"]            # starts as Jamie's sales call ends
    assert "2026-09-07T16:00" in slots["truth"] and "2026-09-07T16:30" not in slots["grid"]
    items = [{"id": "ok", "normalize": "json", "op": "parses"},
             {"id": "l", "normalize": "json", "op": "listed", "path": "valid_slots", "slots": spec},
             {"id": "free", "normalize": "json", "op": "no_conflict", "paths": ["valid_slots", "top3.start"], "slots": spec},
             {"id": "in", "normalize": "json", "op": "no_outside", "paths": ["valid_slots", "top3.start"], "slots": spec},
             {"id": "n", "normalize": "json", "op": "count", "path": "top3", "min": 3, "max": 3},
             {"id": "v", "normalize": "json", "op": "all_valid", "path": "top3.start", "slots": spec},
             {"id": "why", "normalize": "json", "op": "each_nonempty", "path": "top3.explanation"}]
    truth = slots["truth"]
    result = _run(items, _slots_doc(truth))
    assert result["passed"] and len(result["items"]) == 85 + 6
    assert _run(items, "").get("share") == 0.0 and len(_run(items, "")["items"]) == 91
    result = _run(items, _slots_doc(truth + ["2026-08-31T10:00"]))
    assert {k: v for k, v in _passed(result).items() if not k.startswith("l:")} == {
        "ok": True, "free": False, "in": True, "n": True, "v": True, "why": True}
    assert not _passed(_run(items, _slots_doc(truth + ["2026-08-31T11:15"])))["in"]
    assert _passed(_run(items, '{"valid_slots": [], "top3": []}'))["free"] is False                  # an empty list earns no "none overlap"
    assert not _passed(_run(items, "not json at all"))["ok"]
    assert _passed(_run(items, "```json\n" + _slots_doc(truth) + "\n```"))["ok"]


def test_json_slot_times_in_other_zones_and_shapes():
    tz = checks._slot_truth({"fixture": "calendar-fixture.json", "minutes": 60})["tz"]
    for value in ("2026-08-31T11:00", "2026-08-31 11:00", "2026-08-31T11:00:00-05:00", "2026-08-31T16:00:00Z", "2026-08-31T12:00:00-04:00"):
        assert checks._slot_key(value, tz) == "2026-08-31T11:00"
    assert checks._slot_key("Monday 11am", tz) is None and checks._slot_key(None, tz) is None


def test_grounded_numbers_sources():
    check = {"checks": [{"id": "g", "type": "grounded_numbers", "sources": ["mock-data"]}], "prompt": "Top 3 today"}
    run = lambda text: checks.run_checks(check, text)[0]   # noqa: E731
    assert run("It is 68 degrees; the meeting is at 13:00-14:00 and the report is due 17:00. 50+ speakers, 2026.")["passed"]
    assert run("09:30 AM Planning, then 10:30.")["passed"]
    assert not run("It is 85 degrees.")["passed"]
    assert not run("That is 215 minutes.")["passed"]
    plain_check = {"checks": [{"id": "g", "type": "grounded_numbers"}], "prompt": "Top 3 today"}
    assert not checks.run_checks(plain_check, "68 degrees")[0]["passed"]       # without sources, only the prompt counts


def _validate():
    spec = importlib.util.spec_from_file_location("add_task_validate", ROOT / ".claude" / "skills" / "add-task" / "validate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("task", ["two-calendar-slots-json", "morning-brief-spanish", "morning-brief-priorities"])
def test_converted_tasks_score_their_validation_cases(task):
    validate = _validate()
    p = workspace.load_task(task)
    # every rubric criterion's points are the number of items its check scores
    cases = yaml.safe_load((EXAMPLES / f"{task}.yaml").read_text(encoding="utf-8"))
    assert any(c["expect"] == 10 for c in cases) and any(c["expect"] == 0 for c in cases)
    for case in cases:
        got, results = validate.score(p, case.get("answer") or "", case.get("tools"), case.get("files"))
        assert got == pytest.approx(float(case["expect"]), abs=0.01), case["name"]
    reference = next(c for c in cases if c["name"] == "reference")
    _, results = validate.score(p, reference["answer"], None, reference.get("files"))
    by_id = {r["id"]: len(r["items"]) if "items" in r else 1 for r in results}
    for criterion in p["rubric"]:
        assert criterion["max_score"] == by_id[criterion["check"]], criterion["criterion"]
    assert p["status"] == "active"
