"""The answer-block parser and the `items` check (fact-check-history is the first task to use them)."""
import pytest

from crucible import checks

BLOCK = ["1. 42", "2. 7"]


@pytest.mark.parametrize("text", [
    "Working...\n\nANSWERS:\n1. 42\n2. 7",
    "Working...\n\nAnswers:\n1. 42\n2. 7\n",
    "answers\n1. 42\n2. 7",                                   # no colon
    "**ANSWERS:**\n1. 42\n2. 7",
    "**ANSWERS**:\n1. 42\n2. 7",
    "## Answers\n\n1. 42\n2. 7\n\nThanks!",                   # blank lines after the header are skipped
    "ANSWERS:\n```\n1. 42\n2. 7\n```",                       # fenced
    "```\nANSWERS:\n1. 42\n2. 7\n```",
    "ANSWERS:\n1. 42\n2. 7\n\nThat's my answer.",            # ends at a blank line
    "ANSWERS:\n1. 42\n2. 7\nNOTES:\nchecked twice",          # ends at the next header
    "ANSWERS:\n1. 42\n2. 7\n# Working\nmore",                # or a Markdown heading
])
def test_block_variants(text):
    assert checks.answer_block(text, "ANSWERS") == BLOCK


def test_last_block_wins():
    text = "ANSWERS:\n1. 40\n2. 6\n\nWait, let me recheck.\n\nANSWERS:\n1. 42\n2. 7"
    assert checks.answer_block(text, "ANSWERS") == BLOCK


def test_text_after_the_header_is_a_line():
    assert checks.answer_block("The answer is below.\nANSWER: red", ["ANSWERS", "ANSWER"]) == ["red"]


def test_no_block():
    assert checks.answer_block("1. 42\n2. 7", "ANSWERS") is None
    assert checks.answer_block("The answers are 42 and 7.", "ANSWERS") is None


def _score(items, text, **check):
    prompt = {"checks": [{"id": "block", "type": "items", "header": "ANSWERS", "items": items, **check}]}
    (result,) = checks.run_checks(prompt, text)
    return result


def _passed(result):
    return {i["id"]: i["passed"] for i in result["items"]}


def test_number():
    items = [{"id": "q1", "key": "1", "expect": 1234}, {"id": "q2", "key": "2", "expect": 0.5},
             {"id": "q3", "key": "3", "expect": 10, "tolerance": 0.5}, {"id": "q4", "key": "4", "expect": [371, 481]}]
    result = _score(items, "ANSWERS:\nQ1: 1,234\n2) 0.50\n3. about 10.4\n4. 481", normalize="number")
    assert result["passed"] and result["share"] == 1.0
    result = _score(items, "ANSWERS:\n1. 1243\n2. 0.5\n3. 11\n4. 400", normalize="number")
    assert _passed(result) == {"q1": False, "q2": True, "q3": False, "q4": False}
    assert result["share"] == 0.25 and result["detail"].startswith("1/4 items")


def test_money():
    items = [{"id": "q1", "key": "1", "expect": 71.91}, {"id": "q2", "key": "2", "expect": 1500}]
    assert _score(items, "ANSWERS:\n1. $71.91\n2. USD 1,500.00", normalize="money")["passed"]
    assert _passed(_score(items, "ANSWERS:\n1. $71.92\n2. $1,500", normalize="money")) == {"q1": False, "q2": True}


def test_name_with_aliases():
    items = [{"id": "fr", "key": "France", "expect": "Paris"},
             {"id": "ci", "key": "Côte d'Ivoire", "expect": "Yamoussoukro"},
             {"id": "us", "key": "United States", "expect": "Washington, D.C.", "aliases": ["Washington"]}]
    text = "ANSWERS:\nFrance: paris\nCote d'Ivoire: Yamoussoukro\nUnited States: Washington"
    assert _score(items, text, normalize="name")["passed"]
    # Check-level aliases, keyed by the expected name
    items = [{"id": "q1", "key": "1", "expect": "Myanmar"}]
    assert _score(items, "ANSWERS:\n1. Burma", normalize="name", aliases={"Myanmar": ["Burma"]})["passed"]
    # Short values only: no fuzzy matching
    assert not _score(items, "ANSWERS:\n1. Myanmar (formerly Burma)", normalize="name")["passed"]


def test_letter_set():
    one = [{"id": "set", "expect": ["B", "D"]}]
    assert _score(one, "ANSWERS:\nD, B", normalize="letter_set")["passed"]
    assert not _score(one, "ANSWERS:\nB, C, D", normalize="letter_set")["passed"]
    # With `of`, each letter is its own item: correctly in or correctly out
    each = [{"id": "set", "key": "Anachronisms", "expect": ["B", "D"], "of": ["A", "B", "C", "D", "E"]}]
    result = _score(each, "ANSWERS:\nAnachronisms: B, C, (D)", normalize="letter_set")
    assert _passed(result) == {"set:A": True, "set:B": True, "set:C": False, "set:D": True, "set:E": True}
    assert result["share"] == 0.8
    assert _score(each, "ANSWERS:\nAnachronisms: none", normalize="letter_set")["share"] == 0.6


def test_line_number():
    items = [{"id": "e1", "expect": 3}, {"id": "e2", "expect": 12}]
    assert _score(items, "ANSWERS:\nline 3\nL12", normalize="line_number")["passed"]
    assert _passed(_score(items, "ANSWERS:\nline 4\n12", normalize="line_number")) == {"e1": False, "e2": True}


def test_datetime():
    items = [{"id": "deploy", "key": "Deploy", "expect": "14:02:11"},
             {"id": "slot", "key": "Option", "expect": "2026-11-03 14:00 PT"},
             {"id": "any", "key": "Report", "expect": "09:30"}]
    text = "ANSWERS:\nDeploy = 14:02:11\nOption: 2026/11/3 2:00 pm PT\nReport: 9:30:45"
    assert _score(items, text, normalize="datetime")["passed"]
    wrong = "ANSWERS:\nDeploy = 14:02:12\nOption: 2026-11-03 14:00 ET\nReport: 21:30"
    assert _passed(_score(items, wrong, normalize="datetime")) == {"deploy": False, "slot": False, "any": False}


def test_ordering():
    items = [{"id": "order", "expect": ["Gutenberg", "Columbus", "Luther"],
              "aliases": {"Gutenberg": ["printing press"]}}]
    right = "ORDER:\n1. Printing press — 1450\n2. Columbus reaches the Americas — 1492\n3. Luther's theses — 1517"
    result = _score(items, right, header="ORDER", normalize="ordering")
    assert result["passed"] and len(result["items"]) == 3   # every pair is its own item
    result = _score(items, "ORDER:\nColumbus, Gutenberg, Luther", header="ORDER", normalize="ordering")
    assert _passed(result) == {"order:Gutenberg<Columbus": False, "order:Gutenberg<Luther": True,
                               "order:Columbus<Luther": True}
    missing = _score(items, "ORDER:\nGutenberg\nLuther", header="ORDER", normalize="ordering")
    assert missing["items"][0]["detail"] == "missing" and missing["share"] == round(1 / 3, 4)


def test_items_take_lines_in_order_without_a_key():
    items = [{"id": "a", "expect": 1}, {"id": "b", "expect": 2}, {"id": "c", "expect": 3}]
    result = _score(items, "ANSWERS:\n- 1\n- 2", normalize="number")
    assert _passed(result) == {"a": True, "b": True, "c": False}
    assert result["items"][2]["detail"] == "not in the block"


def test_missing_block_or_empty_answer_scores_zero():
    items = [{"id": "q1", "key": "1", "expect": 42}]
    for text, detail in (("The answer is 42.", "no ANSWERS: block"), ("", "no answer to check")):
        result = _score(items, text, normalize="number")
        assert not result["passed"] and result["share"] == 0.0
        assert result["detail"] == detail


def test_missing_block_fails_every_expanded_item():
    """letter_set leaves letters out, so a missing block must fail them explicitly, not pass them."""
    items = [{"id": "q", "expect": ["B"], "of": ["A", "B", "C"], "normalize": "letter_set"},
             {"id": "o", "expect": ["x", "y", "z"], "normalize": "ordering"}]
    result = _score(items, "No block here.")
    assert result["share"] == 0.0 and len(result["items"]) == 6
    assert {i["detail"] for i in result["items"]} == {"no answer block"}


def test_items_check_scores_its_criterion_by_share(tmp_path):
    import json
    prompt = {"version": 1, "rubric_version": 1,
              "checks": [{"id": "block", "type": "items", "normalize": "number",
                          "items": [{"id": "q1", "key": "1", "expect": 1}, {"id": "q2", "key": "2", "expect": 2}]}],
              "rubric": [{"criterion": "Answers", "max_score": 10, "check": "block"}]}
    (tmp_path / "meta.json").write_text(json.dumps({"run_id": "r", "test_id": "T"}))
    results = checks.run_checks(prompt, "ANSWERS:\n1. 1\n2. 3")
    record = checks.save_check_score(tmp_path, prompt, results)
    assert record["scores"]["_overall"] == 5.0


def test_other_checks_report_no_items():
    prompt = {"checks": [{"id": "three", "type": "line_count", "lines": 3}]}
    assert "items" not in checks.run_checks(prompt, "a\nb\nc")[0]


def test_line_set_scores_each_line_in_or_out():
    items = [{"id": "flagged", "expect": [1, 4], "of": [1, 2, 3, 4], "normalize": "line_set"}]
    result = _score(items, "ANSWERS:\n- Line 1: 1492\n(4) 1815\n3. 1776\nnot a numbered line")
    assert _passed(result) == {"flagged:1": True, "flagged:2": True, "flagged:3": False, "flagged:4": True}
    assert [i["label"] for i in result["items"]] == ["Line 1 listed", "Line 2 left out", "Line 3 left out", "Line 4 listed"]
    none = _score(items, "ANSWERS: none")
    assert _passed(none) == {"flagged:1": False, "flagged:2": True, "flagged:3": True, "flagged:4": False}


@pytest.mark.parametrize("value, passed", [
    ("1815", True), ("18 June 1815", True), ("June 18, 1815", True), ("**1815**", True),
    ("1812 → 1815", True), ("1812 -> 1815", True), ("1812 $\\rightarrow$ 1815", True),
    ("1812", False), ("1812 or 1815", False), ("1815 → 1812", False), ("the 19th century", False), ("", False),
])
def test_year(value, passed):
    items = [{"id": "y", "key": "4", "expect": 1815, "normalize": "year"}]
    assert _score(items, f"ANSWERS:\n4: {value}")["passed"] is passed


def test_a_value_after_an_arrow_is_the_answer():
    items = [{"id": "king", "key": "2", "expect": "John", "aliases": ["King John"]}]
    assert _score(items, "ANSWERS:\n2: King Richard → King John")["passed"]
    assert not _score(items, "ANSWERS:\n2: King John → King Richard")["passed"]


def test_fact_check_history_oracle():
    """The converted HIST-2: a reference answer 10, an empty one 0, flagging everything well below 10."""
    from crucible import workspace
    p = workspace.load_task("fact-check-history")

    def score(text):
        results = checks.run_checks(p, text)
        assert sum(len(r["items"]) for r in results) == 17
        return round(sum(checks.criterion_scores(p, results).values()) / 17 * 10, 2)

    reference = "Reasoning...\n\nERRORS:\n2: King John\n3: 1492\n6: 1815\n7: 1912\n10: 1989"
    assert score(reference) == 10.0
    assert score("") == 0.0 and score("1493 → 1492") == 0.0
    assert score("ERRORS:\n" + "\n".join(f"{n}: wrong" for n in range(1, 13))) == 2.94
    everything = {1: 1066, 2: "John", 3: 1492, 4: 1776, 5: 1789, 6: 1815, 7: 1912, 8: 1947, 9: 1969, 10: 1989,
                  11: 1990, 12: 1994}
    assert score("ERRORS:\n" + "\n".join(f"{n}: {v}" for n, v in everything.items())) == 5.88
    assert score("ERRORS: none") == 4.12


def test_cited_paragraphs_check():
    """Prose paragraphs found by their citations: cited once, together, marked, absent; facts per paragraph."""
    items = [
        {"id": "a", "source": "S1", "with": ["S2"], "only": ["S1", "S2", "S9"]},
        {"id": "b", "source": "S2", "with": ["S1"]},
        {"id": "c", "source": "S3", "absent": True},
        {"id": "d", "source": "S9", "marker": "opinion"},
        {"id": "e", "cited": ["S1"], "all": ["41\\.6"], "none": ["signed"]},
        {"id": "f", "forbid": ["okoro"]},
    ]
    p = {"checks": [{"id": "c", "type": "cited_paragraphs", "items": items}]}

    def passed(text):
        r = checks.run_checks(p, text)[0]
        return {i["id"]: i["passed"] for i in r["items"]}

    good = "Levy of $41.6 million. [S1, S2, S9 opinion]\n\nOther story. [S4]"
    assert all(passed(good).values())
    assert all(passed("Levy of $41.6 million. (S1; S2), [S9, opinion]").values())
    assert passed("Levy $41.6 million [S1]\n\nMore [S2, S9 opinion]")["a"] is False   # not merged
    assert passed("Levy $41.6 million [S1, S2, S9]")["d"] is False                    # opinion unmarked
    assert passed("Levy $41.6 million [S1, S2, S9 opinion]\n\nOkoro [S3]") == {
        "a": True, "b": True, "c": False, "d": True, "e": True, "f": False}
    assert passed("Levy [S1, S2, S4] 41.6 [S9 opinion]")["a"] is False                # stray source
    assert not any(passed("Levy $41.6 million, signed. [S1, S2, S9 opinion]")[k] for k in ["e"])
    empty = checks.run_checks(p, "")[0]
    assert not empty["passed"] and empty["share"] == 0.0 and len(empty["items"]) == 6


def test_news_briefing_oracle():
    from crucible import workspace
    p = workspace.load_task("news-briefing-from-feeds")
    ref = ("The council voted 7-2 on a $41.6 million levy. [S1, S2, S9 opinion]\n\nOne firefighter was hurt. [S3, S4]\n\n"
           "Ledger reporters said about 300, organizers more than 1,000, police 400. [S5, S6]\n\n"
           "The governor is expected to sign it. [S7]\n\nRates rose 0.25 to 3.75%. [S8]")

    def score(text):
        results = checks.run_checks(p, text)
        return round(sum(checks.criterion_scores(p, results).values()) / 22 * 10, 2)

    assert score(ref) == 10.0 and score("") == 0.0
    assert score(ref + "\n\nOkoro won. [S10]") == 9.09
