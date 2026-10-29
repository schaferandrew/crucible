"""Programmatic checks: deterministic tests on a run's final answer, declared per prompt.

A prompt can list checks:

    checks:
      - id: no_forbidden_words
        type: forbidden_patterns
        patterns: ['\\w*water\\w*', '\\bwet\\w*']   # case-insensitive regexes

and bind a rubric criterion to one with `check: <id>`. The runner records every check's
result in meta.json, and the judge's score for a bound criterion is replaced by the
check: full marks when it passes, zero when it fails. Machines decide what machines
can decide exactly; the judge handles the rest.

Checks read the final answer only (the last assistant reply), never tool output:
an agent that reads prompt.txt would otherwise echo the forbidden list and fail itself.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from crucible import evals


def final_answer(run_dir: Path) -> str:
    """The model's last reply: from session.json when it has one, else stdout.txt."""
    session_path = run_dir / "session.json"
    if session_path.exists():
        try:
            data = json.loads(session_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = None
        texts: list[str] = []
        if isinstance(data, dict):  # opencode export
            from crucible.agents.opencode import message_texts
            texts = message_texts(data)
        elif isinstance(data, list):  # normalized events (pi)
            texts = [e["message"] for e in data if e.get("type") == "assistantMessage" and e.get("message")]
        if texts:
            return texts[-1]
    stdout = run_dir / "stdout.txt"
    return stdout.read_text(encoding="utf-8", errors="replace") if stdout.exists() else ""


def plain(text: str) -> str:
    """Text with Markdown emphasis removed, so **than** and `Treasury` match like plain words."""
    return re.sub(r"\*\*|__|(?<!\w)[*_](?=\S)|(?<=\S)[*_](?!\w)|`", "", text)


# Every check fails an empty or whitespace-only answer (run_checks applies it to every type)
NO_ANSWER = "no answer to check"


def _forbidden_patterns(check: dict, text: str) -> tuple[bool, str]:
    hits = []
    for pattern in check.get("patterns", []):
        hits += [m.group(0) for m in re.finditer(pattern, text, re.IGNORECASE)]
    if not text.strip():
        return False, NO_ANSWER
    return (not hits), ("none found" if not hits else "found: " + ", ".join(sorted(set(h.lower() for h in hits))))


def _line_count(check: dict, text: str) -> tuple[bool, str]:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return len(lines) == check["lines"], f"{len(lines)} non-empty lines (want {check['lines']})"


def _non_empty(check: dict, text: str) -> tuple[bool, str]:
    """At least min_words (default 1) and, with max_words, no more than that."""
    words = len(text.split())
    want, cap = check.get("min_words", 1), check.get("max_words")
    if words < want:
        return False, f"{words} words (want at least {want})"
    if cap is not None and words > cap:
        return False, f"{words} words (want at most {cap})"
    return True, f"{words} words"


def _required_patterns(check: dict, text: str) -> tuple[bool, str]:
    """Every pattern must match, or with `min_matches`, at least that many of them."""
    flags = 0 if check.get("case_sensitive") else re.IGNORECASE
    found = [p for p in check["patterns"] if re.search(p, text, flags)]
    missing = [p for p in check["patterns"] if p not in found]
    need = check.get("min_matches", len(check["patterns"]))
    passed = len(found) >= need
    detail = f"{len(found)}/{len(check['patterns'])} found"
    if missing and not passed:
        detail += "; missing: " + ", ".join(missing[:6])
    return passed, detail


# A list item: "1. Name", "1) Name", "- Name", "* Name", "• Name", or a markdown table row
LIST_ITEM = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+(.+)$|^\s*\|(?!\s*:?-{2,})(.+)\|\s*$")
# What counts as the item's name: text before a dash, colon, parenthesis or comma
NAME_END = re.compile(r"\s+[—–-]\s+|\s*[:(|,]")


def _items(text: str) -> list[str]:
    items = []
    for line in text.splitlines():
        match = LIST_ITEM.match(line)
        if match:
            items.append((match.group(1) or match.group(2) or "").strip())
    return items


def _item_name(item: str) -> str:
    clean = re.sub(r"[*_`#]", "", item).strip()
    return NAME_END.split(clean, maxsplit=1)[0].strip().lower()


def _list_items(check: dict, text: str) -> tuple[bool, str]:
    """Counts list items (min/max), and optionally requires distinct names or a pattern on every item."""
    items = _items(text)
    problems = []
    if len(items) < check.get("min", 0):
        problems.append(f"{len(items)} items (want at least {check['min']})")
    if "max" in check and len(items) > check["max"]:
        problems.append(f"{len(items)} items (want at most {check['max']})")
    if check.get("distinct"):
        # distinct_within: only the main list (e.g. the first 20), not a later "top five" recap
        names = [_item_name(i) for i in items[:check.get("distinct_within") or len(items)]]
        dupes = sorted({n for n in names if n and names.count(n) > 1})
        if dupes:
            problems.append("repeated: " + ", ".join(dupes[:5]))
    if check.get("each_matches"):
        bad = [i for i in items if not re.search(check["each_matches"], i, re.IGNORECASE)]
        if bad:
            problems.append(f"{len(bad)} items without the required detail")
    return (not problems), ("; ".join(problems) if problems else f"{len(items)} items")


NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in NUMBER.findall(text)}


def _grounded_numbers(check: dict, text: str) -> tuple[bool, str]:
    """Every figure in the answer appears in the source material (the prompt), so none were invented.
    Small whole numbers (up to `ignore_below`, default 11) are left out: list numbering, "five stories"."""
    if not text.strip():
        return False, NO_ANSWER
    allowed = _numbers(check["_source"]) | {str(n) for n in check.get("allow", [])}
    small = check.get("ignore_below", 11)
    invented = sorted(n for n in _numbers(text) - allowed if not (n.isdigit() and int(n) < small))
    return (not invented), ("every figure is in the sources" if not invented else "not in the sources: " + ", ".join(invented[:8]))


# --------------------------------------------------------------------------
# Answer blocks: score only the fixed block a model ends with, one item at a time
# --------------------------------------------------------------------------
#
#     checks:
#       - id: answers
#         type: items
#         header: ANSWERS            # or a list of names for the same block: [ERRORS, ERROR]
#         normalize: number          # the default for every item; an item can name its own
#         items:
#           - {id: q1, key: "1", expect: 42}                    # the line labelled 1 / Q1 / 1. / 1)
#           - {id: q2, key: "2", expect: 71.91, normalize: money}
#           - {id: q3, key: France, expect: Paris, normalize: name, aliases: ["Paris, France"]}
#           - {id: q4, expect: [B, D], of: [A, B, C, D, E], normalize: letter_set}   # 5 items: each letter in or out
#           - {id: q5, expect: [Gutenberg, Columbus, Luther], normalize: ordering}  # 3 items: each pair in order
#           - {id: flagged, expect: [1, 4], of: [1, 2, 3, 4], normalize: line_set}  # 4 items: each line listed or not
#           - {id: fix1, key: "1", expect: 1492, normalize: year}  # every year in the value is 1492
#
# An item with a `key` reads the block line with that label; without one, items take the block's
# lines in order (ordering, letter_set and line_set read the whole block). A value written as
# `wrong → right` is scored on what follows the arrow. The score is items passed / all items, each
# item weighing the same; a missing block scores 0.

HEADER_MARKS = r"(?:#{1,6}\s*)?(?:[*_]{1,2}\s*)?"
# Any other block's header ("TOP FIVE:") or a Markdown heading ends a block
OTHER_HEADER = re.compile(r"^\s*(?:#{1,6}\s+\S.*|" + HEADER_MARKS + r"[A-Z][A-Z _/-]*[A-Z]\s*(?:[*_]{1,2})?\s*:\s*(?:[*_]{1,2})?\s*)$")
FENCE = re.compile(r"^\s*(```|~~~)")


def _header(names: str | list[str]) -> re.Pattern:
    names = [names] if isinstance(names, str) else list(names)
    alternatives = "|".join(re.escape(n.strip().rstrip(":")) for n in names)
    # `ANSWERS:`, `**Answers**:`, `## ANSWERS`, `Answers` alone on its line; text after the colon is a first line
    return re.compile(r"^\s*" + HEADER_MARKS + r"(?:" + alternatives + r")\s*(?:[*_]{1,2})?\s*(?::\s*(?:[*_]{1,2})?(.*)|$)",
                      re.IGNORECASE)


def answer_block(text: str, header: str | list[str], multiline: bool = False) -> list[str] | None:
    """The lines of the last block under `header`: up to a blank line or the next header; None without one.

    With `multiline`, blank lines don't end the block (for a block that holds an email or a paragraph).

    Tolerant of case, a missing colon, **bold** and `#` heading marks, and code fences (fence lines are
    skipped). A model that writes a draft block and then a final one is scored on the final one."""
    pattern = _header(header)
    block: list[str] | None = None
    collecting = False
    for line in text.splitlines():
        if FENCE.match(line):
            continue
        found = pattern.match(line)
        if found:
            block, collecting = [], True
            rest = (found.group(1) or "").strip().strip("*_").strip()
            if rest:
                block.append(rest)
            continue
        if not collecting:
            continue
        if not line.strip():
            collecting = collecting and (multiline or not block)  # blank lines right after the header don't end it
            continue
        if OTHER_HEADER.match(line):
            collecting = False
            continue
        block.append(line.strip())
    return block


# A block line's label and value: "1. 42", "Q1: 42", "France: Paris", "2) $7", "- Gutenberg — 1450"
BULLET = re.compile(r"^\s*[-*•]\s+")
LABELLED = re.compile(r"^(?P<label>[^:=—–]{1,40}?)\s*(?:[:=]|\s[—–-]\s|\)|\.(?=\s))\s*(?P<value>.*)$")
NUMERIC_LABEL = re.compile(r"^(?:q|question|no|item|line|claim|sentence|#)?\s*(\d+)$")
# "1493 → 1492": the corrected value is what follows the last arrow
ARROW = re.compile(r"\s*(?:→|⇒|->|=>|\$\\rightarrow\$)\s*")


def _split(line: str) -> tuple[str | None, str]:
    line = BULLET.sub("", line).strip()
    found = LABELLED.match(line)
    return (found.group("label").strip(), found.group("value").strip()) if found else (None, line)


def _fold(text: str) -> str:
    """Lowercase, accents and punctuation gone, whitespace collapsed: for short names only."""
    import unicodedata
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return re.sub(r"^the ", "", text)


def _same_label(label: str | None, key) -> bool:
    if label is None:
        return False
    key = str(key)
    if key.isdigit():
        found = NUMERIC_LABEL.match(_fold(label))
        return bool(found) and int(found.group(1)) == int(key)
    return _fold(label) == _fold(key)


NUMBER_IN = re.compile(r"-?\d[\d,]*(?:\.\d+)?|-?\.\d+")


def _number(value) -> float | None:
    found = NUMBER_IN.search(str(value).replace(" ", "") if not isinstance(value, (int, float)) else str(value))
    try:
        return float(found.group(0).replace(",", "")) if found else None
    except ValueError:
        return None


def _accepted(item: dict) -> list:
    expect = item["expect"]
    return list(expect) if isinstance(expect, list) else [expect]


def _norm_number(item: dict, value: str, default_tolerance: float = 1e-9) -> tuple[bool, str]:
    got = _number(value)
    tolerance = float(item.get("tolerance", default_tolerance))
    passed = got is not None and any(abs(got - float(e)) <= tolerance for e in _accepted(item))
    return passed, f"got {value or 'nothing'}"


def _norm_money(item: dict, value: str) -> tuple[bool, str]:
    # Half a cent either way: $71.91 and 71.910 are the same amount, $71.92 isn't
    return _norm_number(item, re.sub(r"(?i)usd|\$|€|£", "", value), 0.005)


def _norm_name(item: dict, value: str, aliases: dict | None = None) -> tuple[bool, str]:
    names = [*_accepted(item), *(item.get("aliases") or [])]
    for name in list(names):
        names += (aliases or {}).get(name) or []
    passed = _fold(value) in {_fold(n) for n in names}
    return passed, f"got {value or 'nothing'}"


YEAR = re.compile(r"(?<![\d.,])\d{3,4}(?![\d,]|\.\d)")


def _norm_year(item: dict, value: str) -> tuple[bool, str]:
    """Every year (3 or 4 digits) in the value is an expected one: "18 June 1815" is 1815, "1812 or 1815" isn't."""
    years = {int(y) for y in YEAR.findall(value)}
    passed = bool(years) and years <= {int(e) for e in _accepted(item)}
    return passed, f"got {value or 'nothing'}"


def _line_numbers(lines: list[str]) -> set[int]:
    """The numbers the block's lines are labelled with: "1: 1492", "Line 4 — 1815", "5. April 1912"."""
    labels = [_fold(label) for label, _ in map(_split, lines) if label is not None]
    return {int(found.group(1)) for found in map(NUMERIC_LABEL.match, labels) if found}


def _norm_line_number(item: dict, value: str) -> tuple[bool, str]:
    found = re.search(r"\d+", value)
    passed = bool(found) and int(found.group(0)) in {int(e) for e in _accepted(item)}
    return passed, f"got {value or 'nothing'}"


DATETIME = re.compile(r"(?:(?P<date>\d{4}[-/]\d{1,2}[-/]\d{1,2})[ T,]*)?(?P<h>\d{1,2}):(?P<m>\d{2})(?::(?P<s>\d{2}))?"
                      r"\s*(?P<ampm>[ap]\.?m\.?)?\s*(?P<tz>[A-Za-z][A-Za-z_/+-]*)?", re.IGNORECASE)


def _datetime(value) -> dict | None:
    found = DATETIME.search(str(value))
    if not found:
        return None
    hour = int(found.group("h"))
    ampm = (found.group("ampm") or "").lower().replace(".", "")
    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    date = found.group("date")
    if date:
        y, mo, d = re.split(r"[-/]", date)
        date = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    return {"date": date, "time": (hour, int(found.group("m"))), "seconds": found.group("s"),
            "tz": (found.group("tz") or "").upper() or None}


def _norm_datetime(item: dict, value: str) -> tuple[bool, str]:
    """Same date, time and seconds and time zone, each only when the expected value states it."""
    got = _datetime(value)

    def matches(expected) -> bool:
        want = _datetime(expected)
        return bool(got and want) and all(want[k] is None or want[k] == got[k] for k in ("date", "time", "seconds", "tz"))

    return any(matches(e) for e in _accepted(item)), f"got {value or 'nothing'}"


LETTER = re.compile(r"(?<![A-Za-z])([A-Za-z])(?![A-Za-z])")


def _letters(value: str) -> set[str]:
    return set() if _fold(value) in ("none", "") else {m.upper() for m in LETTER.findall(value)}


SEPARATORS = re.compile(r"\s*(?:,|;|>|→|->)\s*")


def _ordering_entries(lines: list[str]) -> list[str]:
    if len(lines) == 1:
        return SEPARATORS.split(lines[0])
    return [value if label is None or NUMERIC_LABEL.match(_fold(label)) else f"{label} {value}"
            for label, value in map(_split, lines)]


def _position(entries: list[str], name: str, item: dict, aliases: dict) -> int | None:
    """The first entry naming `name` (or one of its aliases) as whole words."""
    names = [name, *((item.get("aliases") or {}).get(name) or []), *(aliases.get(name) or [])]
    folded = [f" {_fold(n)} " for n in names]
    return next((i for i, entry in enumerate(entries) if any(n in f" {_fold(entry)} " for n in folded)), None)


def _score_item(item: dict, lines: list[str], index: int, check: dict, text: str = "") -> list[dict]:
    """One result per expected item; letter_set with `of:` and ordering expand into several."""
    kind = item.get("normalize") or check.get("normalize") or "name"
    if kind in BLOCK_KINDS:
        return [_score_block_item(item, lines, kind, text)]
    aliases = check.get("aliases") or {}
    label = item.get("label", item.get("id"))
    if "key" in item:
        values = [value for line_label, value in map(_split, lines) if _same_label(line_label, item["key"])]
        value = values[-1] if values else None
    elif kind in ("ordering", "letter_set", "line_set"):
        value = "\n".join(lines)
    else:
        value = _split(lines[index])[1] if index < len(lines) else None

    if kind == "ordering":
        entries = _ordering_entries(lines if "key" not in item else ([value] if value else []))
        order = item["expect"]
        positions = {name: _position(entries, name, item, aliases) for name in order}
        results = []
        for i, first in enumerate(order):
            for second in order[i + 1:]:
                a, b = positions[first], positions[second]
                results.append({"id": f"{item['id']}:{first}<{second}", "label": f"{first} before {second}",
                                "passed": a is not None and b is not None and a < b,
                                "detail": "missing" if a is None or b is None else ("in order" if a < b else "out of order")})
        return results
    if kind == "letter_set":
        got, want = _letters(value or ""), {str(e).upper() for e in _accepted(item)}
        if item.get("of"):
            return [{"id": f"{item['id']}:{letter}", "label": f"{letter} {'listed' if letter in want else 'left out'}",
                     "passed": (letter in got) == (letter in want),
                     "detail": "listed" if letter in got else "not listed"}
                    for letter in (str(x).upper() for x in item["of"])]
        return [{"id": item["id"], "label": label, "passed": got == want,
                 "detail": f"got {', '.join(sorted(got)) or 'none'}"}]
    if kind == "line_set":
        got, want = _line_numbers(lines), {int(e) for e in _accepted(item)}
        return [{"id": f"{item['id']}:{n}", "label": f"Line {n} {'listed' if n in want else 'left out'}",
                 "passed": (n in got) == (n in want), "detail": "listed" if n in got else "not listed"}
                for n in (int(x) for x in item["of"])]
    if value is None:
        return [{"id": item["id"], "label": label, "passed": False, "detail": "not in the block"}]
    value = ARROW.split(value)[-1]
    if kind == "name":
        passed, detail = _norm_name(item, value, aliases)
    else:
        passed, detail = ITEM_NORMALIZERS[kind](item, value)
    return [{"id": item["id"], "label": label, "passed": passed, "detail": detail}]


ITEM_NORMALIZERS = {
    "number": _norm_number,
    "money": _norm_money,
    "line_number": _norm_line_number,
    "datetime": _norm_datetime,
    "year": _norm_year,
}
ITEM_KINDS = ("number", "money", "name", "year", "letter_set", "line_set", "line_number", "datetime", "ordering",
              "pattern", "each", "count", "distinct", "subset")

# Kinds that judge the whole block (an email, a paragraph, a list of names), one item each:
#   {id: a, normalize: pattern, expect: 'haven.t'}           the regex is found in the block (every one, if a list)
#   {id: b, normalize: pattern, expect: sorry, absent: true}  ...or is not found
#   {id: c, normalize: pattern, expect: pierogi, absent: true, part: name}   searched in the entries' names only
#   {id: d, normalize: each, expect: '\w+ \w+ [—-] .+'}           every entry matches (at least one entry)
#   {id: e, normalize: count, expect: 20}                     exactly 20 entries (or min: / max:)
#   {id: f, normalize: distinct}                              no two entries have the same name
#   {id: g, normalize: subset, source: NAMES}                 every entry's name is a name in the NAMES block
# Entries are the numbered or bulleted lines of the block (all its lines when none are); an entry's name is what
# precedes a dash, colon or parenthesis, after the number. Matching ignores case and **bold**. An empty block
# fails every item, so a block with nothing in it can't earn an "absent" item for free.
BLOCK_KINDS = ("pattern", "each", "count", "distinct", "subset")
ENTRY_NAME_END = re.compile(r"\s+[—–-]+\s+|\s*[—–:(|,]")
ENTRY_LABEL = re.compile(r"^\s*(?:\d+\s*[.):]|[-*•])\s+")


def _entries(lines: list[str]) -> list[str]:
    labelled = [ENTRY_LABEL.sub("", plain(line)).strip() for line in lines if ENTRY_LABEL.match(plain(line))]
    return labelled or [plain(line).strip() for line in lines if line.strip()]


def _entry_name(entry: str) -> str:
    return _fold(ENTRY_NAME_END.split(entry, maxsplit=1)[0])


def _score_block_item(item: dict, lines: list[str], kind: str, text: str) -> dict:
    label = item.get("label", item.get("id"))
    entries = _entries(lines)

    def result(passed: bool, detail: str) -> dict:
        return {"id": item["id"], "label": label, "passed": bool(passed) and bool(entries), "detail": detail if entries else "empty block"}

    flags = 0 if item.get("case_sensitive") else re.IGNORECASE
    if kind == "pattern":
        wanted = item["expect"] if isinstance(item["expect"], list) else [item["expect"]]
        body = "\n".join(ENTRY_NAME_END.split(e, maxsplit=1)[0] for e in entries) \
            if item.get("part") == "name" else plain("\n".join(lines))
        found = [p for p in wanted if re.search(p, body, flags)]
        if item.get("absent"):
            return result(not found, "none found" if not found else "found: " + ", ".join(found[:3]))
        return result(len(found) == len(wanted), f"{len(found)}/{len(wanted)} found")
    if kind == "each":
        bad = [e for e in entries if not re.search(item["expect"], e, flags)]
        return result(not bad, f"{len(entries) - len(bad)}/{len(entries)} entries match" + (f"; not: {bad[0][:60]}" if bad else ""))
    if kind == "count":
        lo, hi = item.get("min", item.get("expect", 0)), item.get("max", item.get("expect"))
        return result(len(entries) >= lo and (hi is None or len(entries) <= hi), f"{len(entries)} entries")
    names = [_entry_name(e) for e in entries]
    if kind == "distinct":
        dupes = sorted({n for n in names if n and names.count(n) > 1})
        return result(not dupes, "all distinct" if not dupes else "repeated: " + ", ".join(dupes[:5]))
    source = answer_block(text, item["source"], multiline=True) or []  # subset
    known = {_entry_name(e) for e in _entries(source)}
    unknown = [n for n in names if n not in known]
    return result(bool(known) and not unknown, "all in the list" if not unknown else "not in the list: " + ", ".join(unknown[:5]))


def _all_failed(check: dict, detail: str) -> list[dict]:
    """Every item failed, expanded as a block would be (each letter, each pair), so the total stays the same."""
    return [{**r, "passed": False, "detail": detail}
            for n, item in enumerate(check["items"]) for r in _score_item(item, [], n, check)]


def _items_check(check: dict, text: str) -> tuple[bool, str, float, list[dict]]:
    """Each expected item in the answer block scored on its own; share = items passed / all items."""
    header = check.get("header", "ANSWERS")
    if not text.strip():
        return False, NO_ANSWER, 0.0, _all_failed(check, NO_ANSWER)
    lines = answer_block(text, header, multiline=bool(check.get("multiline")))
    if lines is None:
        name = header if isinstance(header, str) else header[0]
        return False, f"no {name.rstrip(':')}: block", 0.0, _all_failed(check, "no answer block")
    results = [r for n, item in enumerate(check["items"]) for r in _score_item(item, lines, n, check, text)]
    passed = sum(r["passed"] for r in results)
    share = round(passed / len(results), 4) if results else 0.0
    failed = [f"{r['id']} ({r['detail']})" for r in results if not r["passed"]]
    detail = f"{passed}/{len(results)} items" + ("; failed: " + ", ".join(failed[:6]) if failed else "")
    return passed == len(results), detail, share, results


# A check returns (passed, detail), or (passed, detail, share) when it earns partial credit, plus the
# per-item results when it scores items (passed, detail, share, items)
CHECKS: dict[str, Callable[[dict, str], tuple]] = {
    "grade_closeness": evals.grade_closeness,
    "grounded_numbers": _grounded_numbers,
    "non_empty": _non_empty,
    "required_patterns": _required_patterns,
    "forbidden_patterns": _forbidden_patterns,
    "line_count": _line_count,
    "list_items": _list_items,
    "items": _items_check,
}


def run_checks(prompt_def: dict, text: str, run_dir: Path | None = None) -> list[dict]:
    """[{id, type, passed, detail, rule}] for every check the prompt declares.

    A check runs on the final answer, or with `file:` on that file in the run's workspace
    (e.g. a postmortem the model was asked to write)."""
    results = []
    text = plain(text)
    for check in prompt_def.get("checks") or []:
        subject = text
        if check.get("file"):
            path = (run_dir / "workspace" / check["file"]) if run_dir else None
            if not path or not path.is_file():
                results.append({"id": check["id"], "type": check["type"], "passed": False,
                                "detail": f"{check['file']} wasn't written", "rule": check.get("rule")})
                continue
            subject = plain(path.read_text(encoding="utf-8", errors="replace"))
        if not subject.strip():
            # An empty answer fails every check, whatever its type: a list of 0 items has no
            # duplicates and no undescribed items, but there is nothing to score (B2)
            results.append({"id": check["id"], "type": check["type"], "passed": False, "detail": NO_ANSWER,
                            "rule": check.get("rule"),
                            **({"share": 0.0, "items": _all_failed(check, NO_ANSWER)} if check["type"] == "items" else {})})
            continue
        passed, detail, *extra = CHECKS[check["type"]]({**check, "_source": prompt_def.get("prompt", "")}, subject)
        results.append({"id": check["id"], "type": check["type"], "passed": passed, "detail": detail,
                        "rule": check.get("rule"), **({"share": extra[0]} if extra else {}),
                        # Per-item results (the items check), for the dashboard's detail view
                        **({"items": extra[1]} if len(extra) > 1 else {})})
    return results


def check_results(run_dir: Path, prompt_def: dict) -> list[dict]:
    return run_checks(prompt_def, final_answer(run_dir), run_dir) if prompt_def.get("checks") else []


# --------------------------------------------------------------------------
# Deterministic scoring: tests whose every rubric criterion is a check or hidden tests
# --------------------------------------------------------------------------

# Before 3.0.0 a check score was saved here; now it's a score record (crucible/runrecord.py)
LEGACY_RESULTS_FILENAME = "check_results.json"


def fully_checked(prompt_def: dict) -> bool:
    rubric = prompt_def.get("rubric") or []
    return bool(rubric) and all(item.get("check") or item.get("hidden_tests") for item in rubric)


def criterion_scores(prompt_def: dict, results: list[dict], grader: dict | None = None) -> dict[str, float]:
    """A check is all or nothing (unless it reports a `share`, like grade_closeness); hidden tests earn
    the share of their tests that pass."""
    from crucible.graders import criterion_result
    by_id = {r["id"]: r for r in results}
    scores = {}
    for item in prompt_def.get("rubric", []):
        if item.get("check"):
            result = by_id.get(item["check"], {})
            share = result.get("share", 1 if result.get("passed") else 0)
            scores[item["criterion"]] = round(item["max_score"] * share, 2)
        elif item.get("hidden_tests"):
            share = criterion_result(item["hidden_tests"], grader)[0] if grader else 0.0
            scores[item["criterion"]] = round(item["max_score"] * share, 2)
    return scores


def per_test(prompt_def: dict) -> bool:
    """`scoring: per_test`: every hidden test weighs the same, the score is passed / all tests x 10,
    and a criterion is the share of the 10 points its tests carry."""
    return prompt_def.get("scoring") == "per_test"


def _per_test_criteria(prompt_def: dict, grader: dict | None) -> tuple[list[dict], float | None]:
    from crucible.graders import GATES, selected_tests
    tests = (grader or {}).get("tests") or []
    # Gates (existing tests, an untouched contract) earn no points under per-test scoring; they only cap
    rubric = [item for item in prompt_def["rubric"] if item["hidden_tests"] not in GATES]
    if not tests:
        return [{"criterion": item["criterion"], "max_score": None, "score": 0.0, "detail": "no hidden test results"}
                for item in rubric], 0.0
    criteria = []
    for item in rubric:
        mine = selected_tests(item["hidden_tests"], tests)
        passed = sum(t["passed"] for t in mine)
        criteria.append({"criterion": item["criterion"], "max_score": round(len(mine) / len(tests) * 10, 2),
                         "score": round(passed / len(tests) * 10, 2), "detail": f"{passed}/{len(mine)} hidden tests pass"})
    return criteria, round(sum(t["passed"] for t in tests) / len(tests) * 10, 2)


def _cap(prompt_def: dict, scores: dict[str, float]) -> float | None:
    """The lowest `cap_if_failed` among criteria that earned nothing (e.g. a modified contract suite)."""
    caps = [item["cap_if_failed"] for item in prompt_def.get("rubric", [])
            if "cap_if_failed" in item and not scores.get(item["criterion"])]
    return min(caps) if caps else None


def save_check_score(run_dir: Path, prompt_def: dict, results: list[dict], grader: dict | None = None) -> dict | None:
    """For a fully deterministic task, write a score record: a score no judge or human is needed for.

    Returns what was computed (criteria, scores, checks); the score record on disk is built from it.
    """
    if not fully_checked(prompt_def):
        return None
    from crucible import graders, provenance, runrecord, versioning
    from crucible.graders import criterion_result
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    if per_test(prompt_def):
        criteria, overall = _per_test_criteria(prompt_def, grader)
        scores, cap = {c["criterion"]: c["score"] for c in criteria}, graders.per_test_cap(prompt_def, grader)
        if cap is not None and overall is not None:
            overall = min(overall, cap)
    else:
        scores = criterion_scores(prompt_def, results, grader)
        # Points earned over points available: a 3-point criterion weighs three times a 1-point one
        total = sum(item["max_score"] for item in prompt_def["rubric"])
        overall = round(sum(scores.values()) / total * 10, 2) if total else None
        cap = _cap(prompt_def, scores)
        if cap is not None and overall is not None:
            overall = min(overall, cap)
        criteria = [{"criterion": item["criterion"], "max_score": item["max_score"], "score": scores.get(item["criterion"]),
                     "detail": (criterion_result(item["hidden_tests"], grader)[1] if item.get("hidden_tests") and grader
                                else next((r["detail"] for r in results if r["id"] == item.get("check")), None))}
                    for item in prompt_def["rubric"]]
    record = {
        "run_path": meta.get("run_path"),
        "task_id": prompt_def.get("id"),
        "scorer": {"type": "tests" if grader else "checks"},
        "criteria": criteria,
        "capped_at": cap,
        "test_version": prompt_def.get("version"),
        "rubric_version": prompt_def.get("rubric_version"),
        "rubric_hash": versioning.rubric_hash(prompt_def),
        "scores": {**scores, "_overall": overall},
        "checks": results,
        "passed": all(c["score"] == c["max_score"] for c in criteria),
        # Saved so the scored text can be audited without re-deriving it from the transcript
        "checked_text": final_answer(run_dir),
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }
    runrecord.write_score(run_dir, runrecord.score_from_checks(
        record, meta.get("run_uuid"), grader, provenance.crucible_version(), prompt_def.get("rubric")))
    return record


# --------------------------------------------------------------------------
# Rules documentation
# --------------------------------------------------------------------------

def rules_markdown() -> str:
    """Every task's programmatic rules, for docs/checks.md."""
    from crucible import workspace
    out = ["# Programmatic checks", "",
           "Generated by `crucible checks --doc`; do not edit by hand. Each check runs on the model's final "
           "answer (its last reply, never tool output) after every run. A task whose rubric criteria are all "
           "checks is scored with no judge at all; elsewhere a check overrides the judge for its criterion. "
           "Tasks are listed by name, with their slug and the ID they had before Crucible 3.0.0.", ""]
    for task_id in workspace.all_task_ids():
        p = workspace.load_task(task_id)
        if not p.get("checks"):
            continue
        scoring = "fully deterministic" if fully_checked(p) else "checks plus judge"
        formerly = f", formerly {', '.join(p['aliases'])}" if p.get("aliases") else ""
        out += [f"## {p.get('name') or task_id}", "", f"`{task_id}`{formerly}; {p.get('tier')}, {scoring}.", "",
                "| Check | Rule | Criterion (points) |", "|---|---|---|"]
        criteria = {item.get("check"): f"{item['criterion']} ({item['max_score']})" for item in p.get("rubric", [])}
        for check in p["checks"]:
            out.append(f"| `{check['id']}` | {check.get('rule', check['type'])} | {criteria.get(check['id'], 'not scored')} |")
        out.append("")
    return "\n".join(out)


def main() -> None:
    """`crucible checks`: re-run checks and hidden tests on existing runs (scoring fully deterministic tasks), or write the rules doc."""
    import argparse
    from crucible import graders, runrecord, workspace
    parser = argparse.ArgumentParser(prog="crucible checks", description=main.__doc__)
    parser.add_argument("--runs", type=Path, default=Path("runs"))
    parser.add_argument("--task", help="Only this task (its slug or an earlier ID)")
    parser.add_argument("--no-hidden", action="store_true", help="Skip the hidden tests (they take a while per run)")
    parser.add_argument("--doc", type=Path, metavar="PATH", help="Write the rules doc (e.g. docs/checks.md) and exit")
    args = parser.parse_args()
    if args.doc:
        args.doc.parent.mkdir(parents=True, exist_ok=True)
        args.doc.write_text(rules_markdown() + "\n", encoding="utf-8")
        print(f"Wrote {args.doc}")
        return
    counts = rescore(args.runs, [workspace.resolve(args.task)[0]] if args.task else None, hidden=not args.no_hidden)
    print(f"Checked {counts['checked']} runs, ran hidden tests on {counts['graded']}; {counts['full']} earned full marks.")


def rescore(runs_dir: Path, task_ids: list[str] | None = None, hidden: bool = True) -> dict[str, int]:
    """Re-run checks (and hidden tests) on every valid run of the current task versions; each score
    lands in the score record for the task's current rubric version."""
    from crucible import graders, runrecord, workspace
    runrecord.require_migrated(runs_dir)
    counts = {"checked": 0, "graded": 0, "full": 0}
    known = set(workspace.all_task_ids())
    for run_dir in runrecord.run_dirs(runs_dir):
        meta = runrecord.read(run_dir)
        task_id = meta.get("task", {}).get("id")
        if not meta or (task_ids and task_id not in task_ids) or runrecord.invalid(run_dir, meta) or task_id not in known:
            continue
        prompt_def = workspace.load_task(task_id)
        run_version = meta["task"].get("version")
        wants_grader = prompt_def.get("grader") and hidden
        if not (prompt_def.get("checks") or wants_grader) or (run_version is not None and run_version != prompt_def.get("version")):
            continue
        results = check_results(run_dir, prompt_def)
        if results:
            meta.setdefault("local", {})["checks"] = results
            runrecord.write_json(run_dir / "meta.json", meta)
            counts["checked"] += 1
        grader = None
        if wants_grader:
            print(f"  hidden tests: {meta.get('run_path')}")
            grader = graders.run(run_dir, prompt_def)
            counts["graded"] += bool(grader)
        record = save_check_score(run_dir, prompt_def, results, grader)
        counts["full"] += bool(record and record["passed"])
    return counts
