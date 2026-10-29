"""Items-check additions for per-item rescoring: header-less blocks, key lists, name_set and find."""
from crucible import checks


def _score(items, text, **check):
    (result,) = checks.run_checks({"checks": [{"id": "c", "type": "items", "items": items, **check}]}, text)
    return result


def _passed(result):
    return {i["id"]: i["passed"] for i in result["items"]}


def test_header_null_reads_the_labelled_lines_of_the_reply():
    items = [{"id": "a", "key": "France", "expect": "Paris"}, {"id": "b", "key": "Spain", "expect": "Madrid"}]
    text = "Thinking.\nFrance: Lyon\n```\nFrance: Paris\nSpain: Madrid\n```"
    assert _score(items, text, header=None)["passed"]          # the last France line wins
    assert _score(items, "no labels", header=None)["share"] == 0.0
    assert _score(items, "", header=None)["detail"] == "no answer to check"


def test_key_can_be_a_list_of_labels():
    items = [{"id": "t", "key": ["Türkiye", "Turkey"], "expect": "Ankara"}]
    assert _score(items, "Turkey: Ankara", header=None)["passed"]
    assert _score(items, "Türkiye: Ankara", header=None)["passed"]
    assert not _score(items, "Istanbul: Ankara", header=None)["passed"]


def test_name_set_is_one_item_per_name_on_the_right_line():
    items = [{"id": "l", "key": "Landlocked", "expect": ["Bolivia", "Laos"], "not_in": ["Not landlocked"],
              "aliases": {"Laos": ["Lao PDR"]}, "normalize": "name_set"}]
    right = "Landlocked: Bolivia and Lao PDR (Asia)\nNot landlocked: Chad"
    assert _score(items, right, header=None)["passed"]
    both = "Landlocked: Bolivia, Laos\nNot landlocked: Laos"
    result = _score(items, both, header=None)
    assert _passed(result) == {"l:Bolivia": True, "l:Laos": False}
    assert result["items"][1]["detail"] == "on both lines"
    missing = _score(items, "Not landlocked: Chad", header=None)
    assert _passed(missing) == {"l:Bolivia": False, "l:Laos": False}


def test_find_reads_the_line_naming_the_event():
    items = [{"id": "g", "find": "Gutenberg Bible", "expect": [1450, 1451, 1452, 1453, 1454, 1455, 1456], "normalize": "year"},
             {"id": "m", "find": "Magna Carta", "expect": 1215, "normalize": "year"}]
    aliases = {"Gutenberg Bible": ["Gutenberg"]}
    text = "ORDER:\n1. Gutenberg printing — c. 1455\n2. Magna Carta (1215)"
    assert _score(items, text, header="ORDER", aliases=aliases)["passed"]
    swapped = "ORDER:\n1. Magna Carta — 1215\n2. Gutenberg — 1492"
    assert _passed(_score(items, swapped, header="ORDER", aliases=aliases)) == {"g": False, "m": True}
    one_line = _score(items[1:], "ORDER:\nMagna Carta — 1215", header="ORDER")
    assert one_line["passed"]


def test_new_kinds_fail_every_item_without_a_block():
    items = [{"id": "l", "key": "L", "expect": ["A", "B"], "normalize": "name_set"},
             {"id": "y", "find": "X", "expect": 1, "normalize": "year"}]
    result = _score(items, "plain prose", header="ORDER")
    assert result["share"] == 0.0 and len(result["items"]) == 3
