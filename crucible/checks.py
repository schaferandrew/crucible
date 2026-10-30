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


def _source_numbers(names: list[str]) -> set[str]:
    """Every number in the named fixture files (paths under fixtures/), leading zeros dropped. Timestamps
    count: "T13:00:00" holds 13 and 0. A whole hour from 1 to 11 also stands for its 24-hour form (5 PM is 17)."""
    from crucible import workspace
    found: set[str] = set()
    for name in names:
        root = workspace.FIXTURES_DIR / name
        for path in sorted(p for p in root.rglob("*") if p.is_file()) if root.is_dir() else [root]:
            found |= {(n.lstrip("0") or "0") if n.isdigit() else n
                      for n in re.findall(r"\d+(?:\.\d+)?", path.read_text(encoding="utf-8"))}
    return found | {str(int(n) + 12) for n in found if n.isdigit() and 1 <= int(n) <= 11}


def _grounded_numbers(check: dict, text: str) -> tuple[bool, str]:
    """Every figure in the answer appears in the source material (the prompt), so none were invented.
    Small whole numbers (up to `ignore_below`, default 11) are left out: list numbering, "five stories"."""
    if not text.strip():
        return False, NO_ANSWER
    allowed = _numbers(check["_source"]) | {str(n) for n in check.get("allow", [])}
    small = check.get("ignore_below", 11)
    got = _numbers(text)
    if check.get("sources"):  # fixture files the answer may quote: every digit run in them, hours also as 24-hour times
        allowed |= _source_numbers(check["sources"])
        got = {(n.lstrip("0") or "0") if n.isdigit() else n for n in got}
    invented = sorted(n for n in got - allowed if not (n.isdigit() and int(n) < small))
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
#           - {id: bolivia, key: Landlocked, expect: [Bolivia, Laos], not_in: [Not landlocked], normalize: name_set}
#                                                      # 2 items: each name is on that line, and not on the others
#           - {id: moon, find: Moon landing, expect: 1969, normalize: year}   # the year on the line naming the event
#
# `key` can be a list of accepted labels ([Türkiye, Turkey]). `header: null` means the answer has no
# header line: the labelled lines of the whole reply are the block (the last line with a label wins).
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
    if isinstance(key, (list, tuple)):
        return any(_same_label(label, k) for k in key)
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


def _line_entries(lines: list[str]) -> list[str]:
    """Each line as one entry: "1. Magna Carta — 1215" and "Magna Carta — 1215" both read "Magna Carta 1215"."""
    return [value if label is None or NUMERIC_LABEL.match(_fold(label)) else f"{label} {value}"
            for label, value in map(_split, lines)]


def _ordering_entries(lines: list[str]) -> list[str]:
    if len(lines) == 1:
        return SEPARATORS.split(lines[0])
    return _line_entries(lines)


NAME_LIST_SPLIT = re.compile(r"\s*(?:,|;|/|&)\s*")
AND_SPLIT = re.compile(r"\s+and\s+", re.IGNORECASE)


def _name_list(value: str) -> set[str]:
    """The names a line lists, folded: "Bolivia, Laos (Asia) and Chad" is bolivia, laos, chad.

    "A and B" counts as both A and B, and as the one name "A and B" (Bosnia and Herzegovina)."""
    value = re.sub(r"\([^)]*\)", " ", value)
    parts = []
    for part in NAME_LIST_SPLIT.split(value):
        pieces = AND_SPLIT.split(part)
        parts += [" and ".join(pieces[i:j]) for i in range(len(pieces)) for j in range(i + 1, len(pieces) + 1)]
    return {n for n in (_fold(p) for p in parts) if n and n != "none"}


def _line_value(lines: list[str], key) -> str | None:
    values = [value for label, value in map(_split, lines) if _same_label(label, key)]
    return values[-1] if values else None


def _position(entries: list[str], name: str, item: dict, aliases: dict) -> int | None:
    """The first entry naming `name` (or one of its aliases) as whole words."""
    names = [name, *((item.get("aliases") or {}).get(name) or []), *(aliases.get(name) or [])]
    folded = [f" {_fold(n)} " for n in names]
    return next((i for i, entry in enumerate(entries) if any(n in f" {_fold(entry)} " for n in folded)), None)


def _score_item(item: dict, lines: list[str], index: int, check: dict, text: str = "") -> list[dict]:
    """One result per expected item; letter_set with `of:` and ordering expand into several."""
    kind = item.get("normalize") or check.get("normalize") or "name"
    if kind in DOCUMENT_KINDS:
        return DOCUMENT_KINDS[kind](item, text)
    if kind in BLOCK_KINDS:
        if item.get("section"):  # the lines of one `##` section of the whole reply, not the check's block
            lines = _section_lines(text, item["section"], top_level=bool(item.get("top_level")))
        return [_score_block_item(item, lines, kind, text)]
    aliases = check.get("aliases") or {}
    label = item.get("label", item.get("id"))
    if "key" in item:
        value = _line_value(lines, item["key"])
    elif "find" in item:
        entries = _line_entries(lines)
        at = _position(entries, item["find"], item, aliases)
        value = entries[at] if at is not None else None
    elif kind in ("ordering", "letter_set", "line_set", "name_set"):
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
    if kind == "name_set":
        listed = _name_list(value or "")
        elsewhere = set().union(*(_name_list(_line_value(lines, k) or "") for k in item.get("not_in") or []))
        where = item.get("key", "the block")
        results = []
        for name in _accepted(item):
            names = {_fold(n) for n in [name, *((item.get("aliases") or {}).get(name) or []),
                                        *(aliases.get(name) or [])]}
            here, there = bool(names & listed), bool(names & elsewhere)
            results.append({"id": f"{item['id']}:{name}", "label": f"{name} on the {where} line",
                            "passed": here and not there,
                            "detail": "on both lines" if here and there else ("listed" if here else "not listed")})
        return results
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
ITEM_KINDS = ("number", "money", "name", "year", "letter_set", "line_set", "name_set", "line_number", "datetime",
              "ordering", "pattern", "each", "count", "distinct", "subset", "language", "json", "sections", "mention")

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
BLOCK_KINDS = ("pattern", "each", "count", "distinct", "subset", "language")
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
    if kind == "language":
        found, detail = _language(plain("\n".join(lines)))
        return result(found == "es" if item["expect"] == "es" else found != "es", detail)
    names = [_entry_name(e) for e in entries]
    if kind == "distinct":
        dupes = sorted({n for n in names if n and names.count(n) > 1})
        return result(not dupes, "all distinct" if not dupes else "repeated: " + ", ".join(dupes[:5]))
    source = answer_block(text, item["source"], multiline=True) or []  # subset
    known = {_entry_name(e) for e in _entries(source)}
    unknown = [n for n in names if n not in known]
    return result(bool(known) and not unknown, "all in the list" if not unknown else "not in the list: " + ", ".join(unknown[:5]))


# --------------------------------------------------------------------------
# Whole-document kinds of the items check: sections, languages, mentions of fixture data, JSON files
# --------------------------------------------------------------------------
#
# These read the whole reply (or the file a check names with `file:`), not one answer block. Use them with
# `header: null`. Each returns one result per item, or several where the doc says so.
#
#   sections: one item per heading, each present and after the one before it ("## Emails", "### 1. Emails"):
#     {id: order, normalize: sections, expect: [Weather, [Outstanding work, Open work], Emails]}   # a list = aliases
#     Headings are Markdown `#` lines; a name matches as whole words anywhere in the heading's text.
#   section: on a pattern, each, count, distinct or language item, the lines under that heading (up to the next
#     heading of the same or a higher level) are the block. `top_level: true` counts only the outermost list items.
#     {id: top3, normalize: count, expect: 3, section: [Top 3, Top three], top_level: true}
#   language: the section's (or, without `section`, the whole reply's) share of Spanish and of English function
#     words (a short list of each; accents ignored). `expect: es` passes for Spanish prose, `expect: en` for
#     anything that is not Spanish.
#     {id: closing, normalize: language, expect: es, section: Spanish practice}
#   mention: the titles in fixtures/mock-data are in the reply. An entry is mentioned when its title is a
#     substring, or when 60% of its distinctive words (the first five letters of each, generic words like
#     "meeting" and "report" set aside) are in one paragraph or list item.
#     {id: email, normalize: mention, source: emails}             # one item per yesterday's email subject
#     {id: today, normalize: mention, source: events, today: "2026-09-02"}   # ...per event starting that day
#     {id: news, normalize: mention, source: news, min: 1}        # one item: at least one headline
#     {id: tax, normalize: mention, source: emails, only: ["Reminder: Q3 expense report due Wednesday 5 PM"]}
#     {id: clash, normalize: mention, source: events, only: [Planning, Vendor demo], also: 'conflict|overlap'}
#     `also` is a regex that must be found too (one combined item). An `only` title missing from the data raises.
#   json: a JSON file (the check's `file:`). `op` picks the rule; the right slots come from a fixture calendar:
#     slots: {fixture: calendar-fixture.json, minutes: 60, step: 30}   # every start with both people free, 9 to 5
#     {id: parses, normalize: json, op: parses}                              # strict JSON object
#     {id: listed, normalize: json, op: listed, path: valid_slots, slots: ...} # one item per true slot
#     {id: days, normalize: json, op: listed_by_day, path: valid_slots, slots: ...}  # one item per day: all its true slots, none overlapping
#     {id: free, normalize: json, op: no_conflict, paths: [valid_slots, top3.start], slots: ...}
#     {id: hours, normalize: json, op: no_outside, paths: [valid_slots, top3.start], slots: ...}
#     {id: three, normalize: json, op: count, path: top3, min: 3, max: 3}
#     {id: valid, normalize: json, op: all_valid, path: top3.start, slots: ...}  # distinct and all true slots
#     {id: why, normalize: json, op: each_nonempty, path: top3.explanation}
#     `a.b` reads field b of each entry of list a. A slot is `YYYY-MM-DDTHH:MM` (a space, seconds or an offset are
#     fine) in the fixture's time zone. no_conflict and no_outside fail on a file that lists nothing.

HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")


def _headings(lines: list[str]) -> list[tuple[int, int, str]]:
    """(line number, level, folded title) of every Markdown heading outside code fences."""
    out, fenced = [], False
    for n, line in enumerate(lines):
        if FENCE.match(line):
            fenced = not fenced
        found = None if fenced else HEADING.match(line)
        if found:
            out.append((n, len(found.group(1)), _fold(found.group(2))))
    return out


def _names(spec) -> list[str]:
    return [spec] if isinstance(spec, str) else list(spec)


def _named(title: str, spec) -> bool:
    return any(re.search(r"\b" + re.escape(_fold(n)) + r"\b", title) for n in _names(spec))


def _section_lines(text: str, names, top_level: bool = False) -> list[str]:
    """The raw lines under the first heading that names `names`, up to the next heading of the same or a higher level."""
    lines = text.splitlines()
    heads = _headings(lines)
    start = next((i for i, (_, _, title) in enumerate(heads) if _named(title, names)), None)
    if start is None:
        return []
    first, level, _ = heads[start]
    end = next((n for n, lv, _ in heads[start + 1:] if lv <= level), len(lines))
    body = lines[first + 1:end]
    if top_level:
        indents = [len(l) - len(l.lstrip()) for l in body if ENTRY_LABEL.match(plain(l))]
        body = [l for l in body if not ENTRY_LABEL.match(plain(l)) or len(l) - len(l.lstrip()) <= min(indents)]
    return body


def _sections_item(item: dict, text: str) -> list[dict]:
    """One result per expected heading: present, and after the last expected heading found before it."""
    heads = _headings(text.splitlines())
    results, previous = [], -1
    for spec in item["expect"]:
        at = next((n for n, _, title in heads if _named(title, spec)), None)
        name = _names(spec)[0]
        if at is None:
            passed, detail = False, "no such heading"
        elif at < previous:
            passed, detail = False, "out of order"
        else:
            passed, detail, previous = True, f"line {at + 1}", at
        results.append({"id": f"{item['id']}:{_fold(name).replace(' ', '-')}", "label": f"{name} section in order",
                        "passed": passed, "detail": detail})
    return results


# Function words that are one language's and not the other's (a, me, he, no, es... are left out)
STOPWORDS = {
    "en": set("the of and to in is you that it for on with as are was at be this have from or an by not but your will "
              "we can they their what which there been has had were would about into than them then when who how "
              "its our also more all any these those only over some such here very just".split()),
    "es": set("de la el en y que los las del un una por con para es se su al lo como mas pero sus le ya o este si "
              "porque esta entre cuando muy sin sobre tambien hay hoy manana tu te tienes tiene son fue ser estan "
              "estoy nos otros todo todos cada donde tus mis mi unos unas ese eso esa".split()),
}


def _language(text: str) -> tuple[str, str]:
    """("es" | "en" | "mixed" | "none", detail): which language's function words dominate the text."""
    import unicodedata
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    words = re.findall(r"[a-z]+", folded)
    if len(words) < 5:
        return "none", f"{len(words)} words"
    es, en = (sum(w in STOPWORDS[k] for w in words) / len(words) for k in ("es", "en"))
    kind = "es" if es >= 0.15 and es > 2 * en else "en" if en >= 0.15 and en > 2 * es else "mixed"
    return kind, f"{kind}: Spanish words {es:.0%}, English {en:.0%}"


# Words that name a kind of thing and not the thing; they match only when a title has nothing else
GENERIC = set("meeting call review update notes team report reminder question".split())
FILLER = set(STOPWORDS["en"]) | set("yesterday today tomorrow pm am new".split())
MOCK_DATA = "mock-data"


def _stems(phrase: str) -> list[str]:
    words = [w for w in _fold(re.sub(r"\([^)]*\)", " ", phrase)).split() if w not in FILLER and (len(w) > 2 or len(w) == 2 and any(c.isdigit() for c in w))]
    return sorted({w[:5] for w in ([x for x in words if x not in GENERIC] or words)})


def _mentioned(text: str, phrase: str) -> bool:
    folded = f" {_fold(text)} "
    if f" {_fold(phrase)} " in folded:
        return True
    stems = _stems(phrase)
    need = max(1, -(-len(stems) * 6 // 10))
    return any(sum(any(w.startswith(s) for w in unit) for s in stems) >= need
               for unit in (_fold(p).split() for p in paragraphs(text))) if stems else False


def _mock_titles(source: str, today: str | None) -> list[str]:
    from crucible import workspace
    root = workspace.FIXTURES_DIR / MOCK_DATA
    load = lambda name: json.loads((root / name).read_text(encoding="utf-8"))   # noqa: E731
    if source == "emails":
        return [e["subject"] for e in load("emails.json")["yesterday"]]
    if source == "news":
        return [a["title"] for a in load("news.json")["articles"]]
    if source == "events":
        return [e["title"] for e in load("calendar.json")["events"] if not today or e["start"].startswith(str(today))]
    raise ValueError(f"unknown mention source: {source}")


def _mention_item(item: dict, text: str) -> list[dict]:
    titles = _mock_titles(item["source"], item.get("today"))
    if item.get("only"):
        unknown = [t for t in item["only"] if t not in titles]
        if unknown:
            raise ValueError(f"mention item {item['id']}: not in the {item['source']} data: {unknown}")
        titles = list(item["only"])
    body = "\n".join(_section_lines(text, item["section"])) if item.get("section") else text
    # accept: {title: [other phrasings]}, for a brief that summarizes an item instead of quoting its title
    accept = item.get("accept") or {}
    unknown = [t for t in accept if t not in titles]
    if unknown:
        raise ValueError(f"mention item {item['id']}: accept names a title not in the {item['source']} data: {unknown}")
    hits = {t: _mentioned(body, t) or any(_mentioned(body, a) for a in accept.get(t, [])) for t in titles}
    if item.get("min") or item.get("also"):
        enough = sum(hits.values()) >= item.get("min", len(titles))
        extra = [p for p in _names(item.get("also") or []) if not re.search(p, body, re.IGNORECASE)]
        label = item.get("label", item["id"])
        missed = [t for t, hit in hits.items() if not hit]
        detail = f"{sum(hits.values())}/{len(titles)} mentioned" + (f"; not: {missed[0]}" if missed and not enough else "") \
            + (f"; no match for {extra[0]}" if extra else "")
        return [{"id": item["id"], "label": label, "passed": enough and not extra, "detail": detail}]
    return [{"id": f"{item['id']}:{_fold(t).replace(' ', '-')[:40]}", "label": f"Mentions {t}", "passed": hit,
             "detail": "mentioned" if hit else "not mentioned"} for t, hit in hits.items()]


SLOT_TIME = re.compile(r"(\d{4})-(\d{2})-(\d{2})[T ]+(\d{1,2}):(\d{2})(?::\d{2}(?:\.\d+)?)?\s*(Z|[+-]\d{2}:?\d{2})?")
_SLOTS: dict = {}


def _slot_truth(spec: dict) -> dict:
    """{tz, truth, conflicts, grid}: the free starts, the starts that overlap an event, and every start on the grid
    (strings `YYYY-MM-DDTHH:MM` in the fixture's zone), for a fixture calendar's people over its whole window."""
    from datetime import timedelta
    from crucible import workspace
    key = json.dumps(spec, sort_keys=True)
    if key not in _SLOTS:
        data = json.loads((workspace.FIXTURES_DIR / spec["fixture"]).read_text(encoding="utf-8"))
        parse = lambda v: datetime.fromisoformat(v.replace("Z", "+00:00"))   # noqa: E731
        window = [parse(data["window"][k]) for k in ("start", "end")]
        events = [(parse(e["start"]), parse(e["end"])) for p in data["people"].values() for e in p["events"]]
        tz, length, step = window[0].tzinfo, timedelta(minutes=spec["minutes"]), timedelta(minutes=spec.get("step", 30))
        truth, conflicts = [], []
        for d in range((window[1].date() - window[0].date()).days + 1):
            midnight_ = (window[0] + timedelta(days=d)).replace(hour=0, minute=0)
            slot, close = midnight_ + timedelta(hours=9), midnight_ + timedelta(hours=17)
            while slot + length <= close:
                if slot >= window[0] and slot + length <= window[1]:
                    busy = any(slot < end and start < slot + length for start, end in events)
                    (conflicts if busy else truth).append(slot.strftime("%Y-%m-%dT%H:%M"))
                slot += step
        _SLOTS[key] = {"tz": tz, "truth": truth, "conflicts": set(conflicts), "grid": set(truth) | set(conflicts)}
    return _SLOTS[key]


def _slot_key(value, tz) -> str | None:
    found = SLOT_TIME.search(value) if isinstance(value, str) else None
    if not found:
        return None
    y, mo, d, h, mi, off = found.groups()
    try:
        moment = datetime(int(y), int(mo), int(d), int(h), int(mi))
    except ValueError:
        return None
    if off:
        sign = -1 if off.startswith("-") else 1
        digits = off.lstrip("+-").replace(":", "") if off != "Z" else "0000"
        from datetime import timedelta
        zone = timezone(sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:])))
        moment = moment.replace(tzinfo=zone).astimezone(tz).replace(tzinfo=None)
    return moment.strftime("%Y-%m-%dT%H:%M")


def _json_load(text: str) -> tuple[dict | None, bool]:
    """(the file's JSON object, whether it was strictly valid). Code fence lines are ignored; with prose around
    it, the outermost braces are read but the file doesn't count as valid JSON."""
    # (run_checks has already removed backticks, so a "```json" fence line is left as a line reading "json")
    body = "\n".join(l for l in text.splitlines() if not FENCE.match(l) and l.strip().lower() != "json")
    for candidate, strict in ((body, True), (body[body.find("{"):body.rfind("}") + 1], False)):
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data, strict
    return None, False


def _json_list(data: dict, path: str):
    """The entries at `a` (a list) or `a.b` (field b of each entry of list a); None when it isn't a list."""
    head, _, field = path.partition(".")
    entries = data.get(head)
    if not isinstance(entries, list):
        return None
    return [e.get(field) if isinstance(e, dict) else None for e in entries] if field else entries


def _json_item(item: dict, text: str) -> list[dict]:
    op, label = item["op"], item.get("label", item["id"])
    data, strict = _json_load(text)
    spec = item.get("slots")
    truth = _slot_truth(spec) if spec else None

    def one(passed: bool, detail: str) -> list[dict]:
        return [{"id": item["id"], "label": label, "passed": bool(passed) and data is not None, "detail": detail if data is not None else "not a JSON object"}]

    if op == "listed":
        listed = {_slot_key(v, truth["tz"]) for v in (_json_list(data, item["path"]) if data else None) or []}
        return [{"id": f"{item['id']}:{s}", "label": f"{s} listed", "passed": s in listed,
                 "detail": "listed" if s in listed else ("not listed" if data else "not a JSON object")} for s in truth["truth"]]
    if op == "listed_by_day":
        listed = {_slot_key(v, truth["tz"]) for v in (_json_list(data, item["path"]) if data else None) or []}
        results = []
        for day in sorted({t[:10] for t in truth["grid"]}):
            want = {t for t in truth["truth"] if t.startswith(day)}
            extra = {t for t in truth["conflicts"] if t.startswith(day)} & listed
            missing = want - listed
            results.append({"id": f"{item['id']}:{day}", "label": f"{day}: every free start listed, none that overlaps an event",
                            "passed": data is not None and not missing and not extra,
                            "detail": "not a JSON object" if data is None else
                            f"{len(want) - len(missing)}/{len(want)} listed" + (f"; {len(extra)} overlapping" if extra else "")})
        return results
    if op == "parses":
        return [{"id": item["id"], "label": label, "passed": strict, "detail": "valid JSON" if strict else "not valid JSON"}]
    if data is None:
        return one(False, "")
    paths = item.get("paths") or [item["path"]]
    lists = [_json_list(data, p) for p in paths]
    if op == "count":
        n = len(lists[0]) if lists[0] is not None else -1
        return one(n >= item.get("min", 1) and (item.get("max") is None or n <= item["max"]), f"{max(n, 0)} entries")
    if op == "each_nonempty":
        values = lists[0] or []
        bad = [v for v in values if not (isinstance(v, str) and v.strip())]
        return one(bool(values) and not bad, f"{len(values) - len(bad)}/{len(values)} non-empty")
    entries = [v for entries in lists for v in (entries or [])]
    keys = [_slot_key(v, truth["tz"]) for v in entries]
    if op == "all_valid":
        bad = [repr(v) for v, k in zip(entries, keys) if k not in truth["truth"]]
        dupes = len(set(keys)) < len(keys)
        return one(bool(entries) and not bad and not dupes, "all free" if entries and not bad and not dupes else
                   ("nothing listed" if not entries else "repeated" if not bad else "not free: " + "; ".join(bad[:3])))
    if op == "no_conflict":
        bad = sorted({k for k in keys if k in truth["conflicts"]})
        return one(bool(entries) and not bad, "none overlap an event" if entries and not bad else
                   ("nothing listed" if not entries else "overlaps an event: " + ", ".join(bad[:3])))
    if op == "no_outside":
        bad = [repr(v) for v, k in zip(entries, keys) if k not in truth["grid"]]
        return one(bool(entries) and not bad, "all inside" if entries and not bad else
                   ("nothing listed" if not entries else "outside the window or grid: " + "; ".join(bad[:3])))
    raise ValueError(f"unknown json op: {op}")


DOCUMENT_KINDS = {"sections": _sections_item, "mention": _mention_item, "json": _json_item}


# Check types that score items, one result per item, each weighing the same
ITEM_CHECKS = ("items", "cited_paragraphs", "time_options", "tool_calls")


def _summarize(results: list[dict]) -> tuple[bool, str, float, list[dict]]:
    """(all passed, detail, share passed, results) for a check that scores items."""
    passed = sum(r["passed"] for r in results)
    share = round(passed / len(results), 4) if results else 0.0
    failed = [f"{r['id']} ({r['detail']})" for r in results if not r["passed"]]
    detail = f"{passed}/{len(results)} items" + ("; failed: " + ", ".join(failed[:6]) if failed else "")
    return passed == len(results), detail, share, results


def _all_failed(check: dict, detail: str) -> list[dict]:
    """Every item failed, expanded as a block would be (each letter, each pair), so the total stays the same."""
    if check["type"] != "items":
        return [{"id": item["id"], "label": item.get("label", item["id"]), "passed": False, "detail": detail}
                for item in check["items"]]
    return [{**r, "passed": False, "detail": detail}
            for n, item in enumerate(check["items"]) for r in _score_item(item, [], n, check)]


def _items_check(check: dict, text: str) -> tuple[bool, str, float, list[dict]]:
    """Each expected item in the answer block scored on its own; share = items passed / all items."""
    header = check.get("header", "ANSWERS")
    if not text.strip():
        return False, NO_ANSWER, 0.0, _all_failed(check, NO_ANSWER)
    # `header: null`: no header line, the reply's own lines are the block
    lines = answer_block(text, header, multiline=bool(check.get("multiline"))) if header else \
        [l.strip() for l in text.splitlines() if l.strip() and not FENCE.match(l)]
    if lines is None:
        name = header if isinstance(header, str) else header[0]
        return False, f"no {name.rstrip(':')}: block", 0.0, _all_failed(check, "no answer block")
    results = [r for n, item in enumerate(check["items"]) for r in _score_item(item, lines, n, check, text)]
    return _summarize(results)


# --------------------------------------------------------------------------
# Cited paragraphs: a prose briefing whose paragraphs end with the numbered sources they used
# --------------------------------------------------------------------------
#
#     checks:
#       - id: sources
#         type: cited_paragraphs
#         items:
#           - {id: s1, source: S1, with: [S2], only: [S1, S2, S9]}   # S1 cited in exactly one paragraph, together with
#                                                                    # S2, and with no source outside the list
#           - {id: s10, source: S10, absent: true}                   # never cited
#           - {id: opinion, source: S9, marker: opinion}             # cited as `[S9 opinion]`
#           - {id: levy, cited: [S1, S2], all: ['41\.6 million']}    # the paragraphs citing S1 or S2 hold every pattern
#           - {id: stale, forbid: ['okoro']}                         # no pattern anywhere in the text (case-insensitive)
#           - {id: bill, cited: [S7], all: ['expected to sign'], none: ['signed into law']}
#
# A citation is a bracket or parenthesis group of source IDs: `[S1, S2, S9]`, `[S1][S2]`, `(S3; S4)`,
# `[S9 opinion]`, `[S9, opinion]`. Paragraphs are split at blank lines, headings and list bullets.
# Every item weighs the same; the share is items passed / all items.

CITATION_GROUP = re.compile(r"\[([^\[\]]*\bS\d+\b[^\[\]]*)\]|\(([^()\[\]]*\bS\d+\b[^()\[\]]*)\)", re.IGNORECASE)
SOURCE_ID = re.compile(r"\bS(\d+)\b", re.IGNORECASE)
BLOCK_START = re.compile(r"^\s*(?:#{1,6}\s|\d+[.)]\s|[-*•]\s)")


def paragraphs(text: str) -> list[str]:
    """Paragraphs of prose: blank lines, headings and list bullets start a new one (a heading stands alone)."""
    out: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            if current:
                out.append(" ".join(current))
            current = []
        elif BLOCK_START.match(line):
            if current:
                out.append(" ".join(current))
            current = [line.strip()]
            if line.lstrip().startswith("#"):
                out.append(" ".join(current))
                current = []
        else:
            current.append(line.strip())
    if current:
        out.append(" ".join(current))
    return out


def citations(paragraph: str) -> tuple[set[str], set[str]]:
    """(source IDs cited, source IDs cited as opinion) in one paragraph."""
    cited: set[str] = set()
    marked: set[str] = set()
    for square, round_ in CITATION_GROUP.findall(paragraph):
        group = square or round_
        last: list[str] = []
        for part in re.split(r"[,;/&]|\band\b", group, flags=re.IGNORECASE):
            ids = ["S" + n for n in SOURCE_ID.findall(part)]
            if ids:
                last = ids
                cited.update(ids)
            if "opinion" in part.lower():
                marked.update(last)
    return cited, marked


def _score_cited(item: dict, paras: list[tuple[str, set[str], set[str]]], text: str) -> dict:
    label = item.get("label", item.get("id"))
    result = lambda passed, detail: {"id": item["id"], "label": label, "passed": passed, "detail": detail}
    if item.get("forbid") and "source" not in item and "cited" not in item:
        hits = sorted({m.group(0).lower() for p in item["forbid"] for m in re.finditer(p, text, re.IGNORECASE)})
        return result(not hits, "found: " + ", ".join(hits) if hits else "none found")
    if "source" in item:
        source = item["source"]
        where = [(body, cited, marked) for body, cited, marked in paras if source in cited]
        if item.get("absent"):
            return result(not where, "not cited" if not where else f"cited in {len(where)} paragraph(s)")
        if len(where) != 1:
            return result(False, "not cited" if not where else f"cited in {len(where)} paragraphs (want 1)")
        _, cited, marked = where[0]
        missing = [s for s in item.get("with", []) if s not in cited]
        stray = sorted(cited - set(item["only"]) - {source}) if item.get("only") else []
        if missing:
            return result(False, "not together with " + ", ".join(missing))
        if stray:
            return result(False, "paragraph also cites " + ", ".join(stray))
        if item.get("marker") and source not in marked:
            return result(False, f"not marked {item['marker']}")
        return result(True, "cited once")
    body = " ".join(b for b, cited, _ in paras if cited & set(item["cited"]))
    if not body:
        return result(False, "no paragraph cites " + ", ".join(item["cited"]))
    missing = [p for p in item.get("all", []) if not re.search(p, body, re.IGNORECASE)]
    found = [m.group(0).lower() for p in item.get("none", []) for m in re.finditer(p, body, re.IGNORECASE)]
    if missing:
        return result(False, "missing: " + ", ".join(missing[:3]))
    if found:
        return result(False, "found: " + ", ".join(sorted(set(found))))
    return result(True, "found")


def _cited_paragraphs_check(check: dict, text: str) -> tuple[bool, str, float, list[dict]]:
    """Each expected item scored on its own, by the citations at the end of the briefing's paragraphs."""
    paras = [(body, *citations(body)) for body in paragraphs(text)]
    results = [_score_cited(item, paras, text) for item in check["items"]]
    return _summarize(results)

# --------------------------------------------------------------------------
# Time options and session tool calls (the calendar tasks)
# --------------------------------------------------------------------------
#
# `time_options` scores a block of proposed meeting times against the mock calendar dataset the task
# ran on. The set of right answers is computed from the dataset (the server's free_starts()), never
# written out by hand in the task. Each line of the block is `YYYY-MM-DD HH:MM <time zone>`; a line
# with no recognised zone, or no date and time, is an option that can't be valid. One result per item:
#
#     - id: options
#       type: time_options
#       header: OPTIONS
#       dataset: pair                     # fixtures/mock-calendar/pair.json
#       attendees: [alex@example.com, jamie@example.com]   # or `team: Platform`: every calendar in that team
#       until: "2026-09-05T00:00:00"      # the search window runs from the dataset's "now" to here
#       minutes: 60                       # meeting length; `step` is the start grid (default 30)
#       items:
#         - {id: valid, kind: in_set}                     # at least one option, each a distinct ground-truth start
#         - {id: count, kind: count, min: 2, max: 3}      # option lines in the block
#         - {id: handled, kind: includes_any,             # at least one VALID option matching a selector
#            match: [{weekday: fri}, {date: "2026-09-03", time: "13:00"}]}   # in the dataset's zone
#         - {id: not_past, kind: not_before_now}          # no option before the dataset's "now"
#         - {id: dates, kind: avoid, dates: ["2026-09-07"], ranges: [["2026-09-10", "2026-09-11"]]}
#         - {id: close, kind: latest_end, time: "16:00"}  # no option ends after 16:00 in the dataset's zone
#
# `tool_calls` scores what the agent did, read from the run's session record (session.json), not the
# answer: an item passes when the tool was called at least once, and with `covers: {dataset, team}`
# only when its `calendars` argument, over all calls, named every calendar in that team except the
# user's own (whose events list_events reads). Without a session record every item fails.

OPTION_LINE = re.compile(
    r"(?P<y>\d{4})-(?P<mo>\d{1,2})-(?P<d>\d{1,2})[ T]+(?P<h>\d{1,2}):(?P<m>\d{2})(?::\d{2})?[ \t]*(?P<ampm>[ap]\.?m\b\.?)?"
    r"[ \t]*\(?(?P<tz>[+-]\d{2}:?\d{2}\b|UTC[+-]\d{1,2}(?::\d{2})?|[A-Za-z]+(?:/[A-Za-z_]+)?)?", re.IGNORECASE)
# Zone names models write for the datasets' zones. CST/EST/MST/PST are read as the region's local time
# (people write them for "Central" all year round), so a September "CST" is still Chicago.
ZONE_ALIASES = {
    "America/Chicago": ["cdt", "cst", "ct", "central", "america/chicago", "chicago"],
    "America/New_York": ["edt", "est", "et", "eastern", "america/new_york", "new_york"],
    "America/Denver": ["mdt", "mst", "mt", "mountain", "america/denver"],
    "America/Los_Angeles": ["pdt", "pst", "pt", "pacific", "america/los_angeles"],
    "Europe/London": ["bst", "europe/london"],
    "UTC": ["utc", "gmt", "z"],
}


def _zone_offset(text: str | None):
    """A time zone as written ("CDT", "Central", "America/Chicago", "-05:00", "UTC-5") to a fixed offset, else None."""
    from datetime import timedelta
    from crucible.mcp_servers import calendar_server as cs
    if not text:
        return None
    word = text.strip().lower()
    for zone, names in ZONE_ALIASES.items():
        if word in names:
            return cs.fixed_offset(cs.ZONES[zone])
    found = re.fullmatch(r"(?:utc)?([+-])(\d{1,2}):?(\d{2})?", word)
    if found:
        sign = -1 if found.group(1) == "-" else 1
        return timezone(sign * timedelta(hours=int(found.group(2)), minutes=int(found.group(3) or 0)))
    return None


def _option(line: str) -> dict:
    """{line, start} for one block line; start is an aware datetime, or None when the line has no date, time
    and recognised zone."""
    found = OPTION_LINE.search(line)
    option = {"line": line, "start": None}
    if not found:
        return option
    hour, ampm = int(found.group("h")), (found.group("ampm") or "").lower().replace(".", "")
    if ampm == "pm" and hour < 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    tz = _zone_offset(found.group("tz"))
    try:
        if tz is not None:
            option["start"] = datetime(int(found.group("y")), int(found.group("mo")), int(found.group("d")),
                                       hour, int(found.group("m")), tzinfo=tz)
    except ValueError:
        pass
    return option


_TRUTH: dict = {}


def _dataset(name: str):
    from crucible.mcp_servers.calendar_server import Calendar
    if ("cal", name) not in _TRUTH:
        _TRUTH[("cal", name)] = Calendar.load(name)
    return _TRUTH[("cal", name)]


def _team_ids(cal, team: str) -> list[str]:
    return [cid for cid, c in cal.calendars.items() if c.get("team") == team]


def _truth(check: dict):
    """(dataset, the ground-truth start times): free_starts() for the check's attendees over its window."""
    from crucible.mcp_servers.calendar_server import free_starts, parse_time
    cal = _dataset(check["dataset"])
    attendees = check.get("attendees") or _team_ids(cal, check["team"])
    key = ("truth", check["dataset"], tuple(attendees), check["until"], check["minutes"], check.get("step", 30))
    if key not in _TRUTH:
        starts = free_starts(cal, attendees, cal.now.isoformat(), check["until"], check["minutes"], check.get("step", 30))
        _TRUTH[key] = set(starts)
    return cal, _TRUTH[key]


def _matches(selector: dict, local: datetime) -> bool:
    """A selector's weekday (mon..sun), date and time, each only when it states them, against a local time."""
    if "weekday" in selector and local.strftime("%a").lower() != str(selector["weekday"])[:3].lower():
        return False
    if "date" in selector and local.date().isoformat() != str(selector["date"]):
        return False
    return "time" not in selector or local.strftime("%H:%M") == str(selector["time"])


def _time_item(item: dict, check: dict, options: list[dict]) -> dict:
    kind, label = item["kind"], item.get("label")
    parsed = [o for o in options if o["start"] is not None]

    def result(passed: bool, detail: str, default_label: str) -> dict:
        return {"id": item["id"], "label": label or default_label, "passed": passed, "detail": detail}

    def judged(default_label: str, bad_option) -> dict:
        """Passes when at least one option parsed and none is rejected by bad_option(local_start)."""
        if not parsed:
            return result(False, "no option with a date, time and time zone", default_label)
        bad = [o["line"] for o in parsed if bad_option(o["start"])]
        return result(not bad, "none found" if not bad else "found: " + "; ".join(bad[:3]), default_label)

    if kind == "count":
        n, low, high = len(options), item.get("min", 1), item.get("max")
        want = f"exactly {low}" if high == low else (f"{low} to {high}" if high is not None else f"at least {low}")
        return result(n >= low and (high is None or n <= high), f"{n} options (want {want})", f"{want} options")
    cal, truth = (_truth(check) if kind in ("in_set", "includes_any") else (_dataset(check["dataset"]), set()))
    local = lambda o: o["start"].astimezone(cal.tz)   # noqa: E731
    valid = [o for o in parsed if o["start"] in truth]
    if kind == "in_set":
        starts = [o["start"] for o in valid]
        bad = [o["line"] for o in options if o["start"] is None or o["start"] not in truth]
        if len(set(starts)) < len(starts):
            bad.append("an option repeated")
        return result(bool(options) and not bad, "all valid" if options and not bad else
                      ("no options" if not options else "not valid: " + "; ".join(bad[:3])), "Every option is a free time")
    if kind == "includes_any":
        hit = [o["line"] for o in valid if any(_matches(s, local(o)) for s in item["match"])]
        return result(bool(hit), f"matched {hit[0]}" if hit else "no valid option matches", "Includes a time that needs the event status")
    if kind == "not_before_now":
        return judged("No option is in the past", lambda start: start < cal.now)
    if kind == "avoid":
        dates, ranges = {str(d) for d in item.get("dates") or []}, item.get("ranges") or []

        def hits(start: datetime) -> bool:
            day = start.astimezone(cal.tz).date().isoformat()
            return day in dates or any(str(a) <= day <= str(b) for a, b in ranges)
        return judged("No option on an excluded day", hits)
    if kind == "latest_end":
        from datetime import timedelta
        cutoff = _minutes_of(item["time"])

        def late(start: datetime) -> bool:
            end = start.astimezone(cal.tz) + timedelta(minutes=check["minutes"])
            return end.date() != start.astimezone(cal.tz).date() or end.hour * 60 + end.minute > cutoff
        return judged(f"No meeting ends after {item['time']}", late)
    raise ValueError(f"unknown time_options item kind: {kind}")


def _minutes_of(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def _time_options_check(check: dict, text: str) -> tuple[bool, str, float, list[dict]]:
    """Each rule about the proposed times scored on its own; share = items passed / all items."""
    header = check.get("header", "OPTIONS")
    if not text.strip():
        return False, NO_ANSWER, 0.0, _all_failed(check, NO_ANSWER)
    lines = answer_block(text, header)
    if lines is None:
        name = header if isinstance(header, str) else header[0]
        return False, f"no {name.rstrip(':')}: block", 0.0, _all_failed(check, "no answer block")
    options = [_option(line) for line in lines]
    results = [_time_item(item, check, options) for item in check["items"]]
    return _summarize(results)


def session_tool_calls(run_dir: Path) -> list[dict] | None:
    """[{name, args}] for every tool the agent called, from session.json; None without a readable session.

    Reads both session formats (pi's normalized events, opencode's export). The model's answer is never
    part of it: a model can claim it checked the calendar without having called anything."""
    path = run_dir / "session.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    calls = []
    if isinstance(data, list):
        calls = [{"name": e.get("name", ""), "args": e.get("args") or {}} for e in data
                 if isinstance(e, dict) and e.get("type") == "toolCall"]
    elif isinstance(data, dict):
        for msg in data.get("messages", []):
            for part in (msg.get("parts") or msg.get("content") or []) if isinstance(msg, dict) else []:
                if isinstance(part, dict) and part.get("type") in ("tool", "tool-invocation", "tool_use"):
                    state = part.get("state") if isinstance(part.get("state"), dict) else {}
                    calls.append({"name": part.get("name") or part.get("tool") or "",
                                  "args": state.get("input") or part.get("input") or part.get("args") or {}})
    return calls


def _is_tool(called: str, tool: str) -> bool:
    """The tool's own name, or one a harness prefixes with the server's ("mock-calendar_list_events")."""
    return called == tool or any(called.endswith(sep + tool) for sep in ("_", "__", ".", "/", ":"))


def _calendar_ids(args) -> set[str]:
    """The calendar ids a get_freebusy call named: [{"id": ...}], ["..."] or a JSON string of either."""
    if isinstance(args, dict):
        args = args.get("calendars")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return set()
    if not isinstance(args, list):
        return set()
    return {str(c.get("id") if isinstance(c, dict) else c) for c in args}


def _tool_calls_check(check: dict, text: str) -> tuple[bool, str, float, list[dict]]:
    """Each expected tool call scored on its own; share = items passed / all items."""
    calls = check.get("_tool_calls")
    if calls is None:
        return False, "no session record", 0.0, _all_failed(check, "no session record")
    results = []
    for item in check["items"]:
        mine = [c for c in calls if _is_tool(str(c["name"]), item["tool"])]
        label = item.get("label", f"Called {item['tool']}")
        if not mine:
            results.append({"id": item["id"], "label": label, "passed": False, "detail": "not called"})
        elif item.get("covers"):
            cal = _dataset(item["covers"]["dataset"])
            need = set(_team_ids(cal, item["covers"]["team"])) - {cal.owner}
            seen = set().union(*(_calendar_ids(c["args"]) for c in mine))
            missing = sorted(need - seen)
            results.append({"id": item["id"], "label": label, "passed": not missing,
                            "detail": f"{len(need) - len(missing)}/{len(need)} calendars"
                                      + (f"; missing {', '.join(m.split('@')[0] for m in missing[:5])}" if missing else "")})
        else:
            results.append({"id": item["id"], "label": label, "passed": True, "detail": f"{len(mine)} call(s)"})
    return _summarize(results)


# --------------------------------------------------------------------------
# Workspace state: the app's audit log and the seeded commit
# --------------------------------------------------------------------------
#
# Some tasks can be scored from what the app recorded, not from what the model says. The app appends one
# JSON line per event to a log in the workspace (login-service: .crucible/audit.jsonl); each line carries
# `seq` and `prev`, the sha256 of the line before it ("genesis" for the first), so a line that was edited,
# dropped or hand-written breaks the chain and the log counts for nothing.
#
#     - id: session
#       type: audit_log
#       log: .crucible/audit.jsonl
#       sequence:                                      # these events, in this order (others may lie between)
#       - {event: login_success, user: testuser, session: $s}
#       - {event: dashboard_ok, session: $s}           # $name: the same value everywhere it appears
#       then_none: [{event: logout, session: $s}]      # and none of these after the last step
#
#     - id: code_untouched
#       type: workspace_unchanged
#       paths: [server.js, public]                     # exactly as in the seeded commit (git)
#       log: .crucible/audit.jsonl                     # optional, with any_event: the app was really used,
#       any_event: [login_failed, login_success]       # so doing nothing doesn't earn "unchanged"
#
# Like every check, both fail an empty answer.

def _workspace(check: dict) -> Path | None:
    run_dir = check.get("_run_dir")
    return Path(run_dir) / "workspace" if run_dir else None


def read_audit_log(workspace: Path, log: str) -> tuple[list[dict] | None, str]:
    """(events, detail): the log's events when its hash chain holds, else None and why."""
    import hashlib
    path = workspace / log
    if not path.is_file():
        return None, f"no {log}"
    previous, seq, events = "genesis", 0, []
    for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").split("\n"), 1):
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return None, f"{log} line {number} isn't JSON"
        if not isinstance(event, dict) or event.get("seq") != seq + 1 or event.get("prev") != previous:
            return None, f"{log} was altered (chain breaks at line {number})"
        previous, seq = hashlib.sha256(line.encode("utf-8")).hexdigest(), seq + 1
        events.append(event)
    return (events, "") if events else (None, f"{log} is empty")


def _bind(step: dict, event: dict, binds: dict) -> dict | None:
    """The bindings after matching an event against a step, or None when it doesn't match."""
    out = dict(binds)
    for key, want in step.items():
        if key not in event:
            return None
        if isinstance(want, str) and want.startswith("$"):
            if out.setdefault(want, event[key]) != event[key]:
                return None
        elif event[key] != want:
            return None
    return out


def _sequence(steps: list[dict], events: list[dict], none: list[dict], start: int = 0, binds: dict | None = None,
              depth: list[int] | None = None, level: int = 0) -> bool:
    binds = binds or {}
    depth = depth if depth is not None else [0]
    if not steps:
        return True
    for i in range(start, len(events)):
        matched = _bind(steps[0], events[i], binds)
        if matched is None:
            continue
        depth[0] = max(depth[0], level + 1)
        if len(steps) == 1:
            if any(_bind(rule, e, matched) is not None for e in events[i + 1:] for rule in none):
                continue
            return True
        if _sequence(steps[1:], events, none, i + 1, matched, depth, level + 1):
            return True
    return False


def _audit_log_check(check: dict, text: str) -> tuple[bool, str]:
    workspace = _workspace(check)
    if workspace is None or not workspace.is_dir():
        return False, "no workspace to read the audit log from"
    events, problem = read_audit_log(workspace, check["log"])
    if events is None:
        return False, problem
    steps, depth = check["sequence"], [0]
    if _sequence(steps, events, check.get("then_none") or [], depth=depth):
        return True, " then ".join(s["event"] for s in steps)
    if depth[0] >= len(steps) and check.get("then_none"):
        return False, f"{steps[-1]['event']} was followed by {', '.join(r['event'] for r in check['then_none'])}"
    return False, f"never got to {steps[depth[0]]['event']}" + (f" after {steps[depth[0] - 1]['event']}" if depth[0] else "")


def _workspace_unchanged(check: dict, text: str) -> tuple[bool, str]:
    import subprocess
    workspace = _workspace(check)
    if workspace is None or not (workspace / ".git").exists():
        return False, "no seeded commit to compare against"
    if check.get("any_event"):
        events, problem = read_audit_log(workspace, check["log"])
        if events is None or not any(e.get("event") in check["any_event"] for e in events):
            return False, "the app was never used" if events else problem
    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=workspace, capture_output=True, text=True, timeout=60)
    root = git("rev-list", "--max-parents=0", "HEAD")
    if root.returncode or not root.stdout.split():
        return False, "no seeded commit to compare against"
    paths = check["paths"]
    changed = git("diff", "--name-only", root.stdout.split()[0], "--", *paths).stdout.split() + \
        git("ls-files", "--others", "--exclude-standard", "--", *paths).stdout.split()
    return (not changed), ("as seeded" if not changed else "changed: " + ", ".join(sorted(set(changed))[:5]))


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
    "cited_paragraphs": _cited_paragraphs_check,
    "time_options": _time_options_check,
    "tool_calls": _tool_calls_check,
    "audit_log": _audit_log_check,
    "workspace_unchanged": _workspace_unchanged,
}


def run_checks(prompt_def: dict, text: str, run_dir: Path | None = None, tool_calls: list[dict] | None = None) -> list[dict]:
    """[{id, type, passed, detail, rule}] for every check the prompt declares.

    A check runs on the final answer, or with `file:` on that file in the run's workspace
    (e.g. a postmortem the model was asked to write). `tool_calls` ([{name, args}]) is what a `tool_calls`
    check reads; without it they come from the run's session record."""
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
                            **({"share": 0.0, "items": _all_failed(check, NO_ANSWER)} if check["type"] in ITEM_CHECKS else {})})
            continue
        if check["type"] == "tool_calls" and tool_calls is None and run_dir:
            tool_calls = session_tool_calls(run_dir)
        passed, detail, *extra = CHECKS[check["type"]](
            {**check, "_source": prompt_def.get("prompt", ""), "_tool_calls": tool_calls, "_run_dir": run_dir}, subject)
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
