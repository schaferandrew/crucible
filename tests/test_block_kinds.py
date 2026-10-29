"""Whole-block item kinds of the `items` check (pattern, each, count, distinct, subset) and multiline blocks."""
from crucible import checks


def _run(items, text, header="B", **check):
    check = {"id": "c", "type": "items", "header": header, "items": items, **check}
    ok, detail, share, results = checks._items_check(check, text)
    return [r["passed"] for r in results]


def test_multiline_block_keeps_blank_lines_and_ends_at_next_header():
    text = "B:\nline one\n\nline two\n\nNEXT:\nother"
    assert checks.answer_block(text, "B") == ["line one"]
    assert checks.answer_block(text, "B", multiline=True) == ["line one", "line two"]


def test_pattern_present_and_absent():
    text = "B:\nI haven't heard\n\nsorry about that"
    items = [{"id": "a", "normalize": "pattern", "expect": "haven.t"},
             {"id": "b", "normalize": "pattern", "expect": "sorry", "absent": True},
             {"id": "c", "normalize": "pattern", "expect": ["haven", "heard"]}]
    assert _run(items, text, multiline=True) == [True, False, True]


def test_pattern_ignores_bold_and_case():
    assert _run([{"id": "a", "normalize": "pattern", "expect": "than"}], "B:\nlouder **THAN** she", multiline=True) == [True]


def test_empty_block_fails_every_item():
    items = [{"id": "a", "normalize": "pattern", "expect": "x", "absent": True},
             {"id": "b", "normalize": "each", "expect": "x"}, {"id": "c", "normalize": "distinct"}]
    assert _run(items, "B:\n\nNEXT:\nx") == [False, False, False]


def test_each_count_distinct():
    text = "B:\n1. Ann Lee — a good reason here\n2. Bo Ray — another good reason\n3. ann lee — dup reason here"
    items = [{"id": "each", "normalize": "each", "expect": r"\s[—-]\s"},
             {"id": "n3", "normalize": "count", "expect": 3}, {"id": "n2", "normalize": "count", "expect": 2},
             {"id": "range", "normalize": "count", "min": 2, "max": 4},
             {"id": "d", "normalize": "distinct"}]
    assert _run(items, text) == [True, True, False, True, False]


def test_pattern_on_names_only():
    text = "B:\n1. Pat Lee — avoids pierogi clichés\n2. Pierogi Smith — x"
    item = {"id": "a", "normalize": "pattern", "part": "name", "absent": True, "expect": "pierogi"}
    assert _run([item], text) == [False]
    assert _run([item], text.splitlines()[0] + "\n1. Pat Lee — avoids pierogi clichés") == [True]


def test_subset_reads_another_block():
    text = "NAMES:\n1. Ann Lee — a\n2. Bo Ray — b\n\nTOP:\n1. Bo Ray\n2. Ann Lee"
    item = {"id": "s", "normalize": "subset", "source": "NAMES"}
    assert _run([item], text, header="TOP", multiline=True) == [True]
    assert _run([item], text.replace("2. Ann Lee\n", "").replace("1. Bo Ray", "1. Cy Fox"), header="TOP", multiline=True) == [False]
