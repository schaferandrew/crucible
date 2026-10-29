"""The answer-block parser and the `items` check (Suite v2 groundwork; no prompt uses them yet)."""
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
    for text in ("The answer is 42.", ""):
        result = _score(items, text, normalize="number")
        assert not result["passed"] and result["share"] == 0.0
        assert result["detail"] == "no ANSWERS: block"


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
