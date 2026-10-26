"""Type-to-filter model picker, like the /model picker in Claude Code or pi.

The picker opens already full from the last model lists saved on disk, then fetches every
provider's list live, in parallel, and swaps each one in as it answers. Typing narrows the list
(space-separated words, each a fuzzy match against 'provider/model', matched letters
highlighted), arrows move, Tab copies the highlighted model into the input, Enter picks it.
With nothing matching, Enter takes the typed text when it is a full 'provider/model'.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

from crucible import providers

VISIBLE = 12

# Synchronized output (DEC mode 2026): the terminal shows each redraw whole, never half-painted.
# Terminals without it (e.g. macOS Terminal.app) ignore the sequence.
SYNC_BEGIN, SYNC_END = "\x1b[?2026h", "\x1b[?2026l"


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------

BOUNDARY = "/-_.: "


def _match_word(word: str, text: str) -> tuple[int, list[int]] | None:
    """(score, matched positions) for one lowercase word in lowercase text, or None.

    Best is a substring at a word boundary, then a substring anywhere, then a subsequence (its
    letters in order, e.g. 'k2t' finds 'kimi-k2-thinking') with letters on boundaries or next to
    each other scoring higher, as in fzf.
    """
    best = None
    at = text.find(word)
    while at >= 0:
        boundary = at == 0 or text[at - 1] in BOUNDARY
        s = 1000 + (200 if boundary else 0) - min(at, 100)
        if best is None or s > best[0]:
            best = (s, list(range(at, at + len(word))))
        at = text.find(word, at + 1)
    if best:
        return best
    positions, pos = [], -1
    for ch in word:
        pos = text.find(ch, pos + 1)
        if pos < 0:
            return None
        positions.append(pos)
    s = 500
    for n, p in enumerate(positions):
        if p == 0 or text[p - 1] in BOUNDARY:
            s += 30
        if n and p == positions[n - 1] + 1:
            s += 20
        elif n:
            s -= min(p - positions[n - 1] - 1, 30)
    return s, positions


def match(query: str, text: str) -> tuple[int, set[int]] | None:
    """(score, matched positions) for every word of the query in text; None if any word misses."""
    lowered = text.lower()
    total, hits = 0, set()
    for word in query.lower().split():
        found = _match_word(word, lowered)
        if found is None:
            return None
        total += found[0]
        hits.update(found[1])
    return total, hits


def score(query: str, text: str) -> int | None:
    found = match(query, text)
    return found[0] if found else None


def filter_models(query: str, items: list[tuple[str, str]]) -> list[tuple[str, str, set[int]]]:
    """(value, detail, matched positions) for items matching query, best first; ties keep order."""
    if not query.strip():
        return [(v, d, set()) for v, d in items]
    scored = []
    for i, (value, detail) in enumerate(items):
        found = match(query, value)
        if found:
            scored.append((-found[0], i, (value, detail, found[1])))
    return [row for _, _, row in sorted(scored, key=lambda t: t[:2])]


# --------------------------------------------------------------------------
# Model lists: cached on disk, refreshed live
# --------------------------------------------------------------------------

def cache_file() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "crucible" / "models.json"


def _read_cache() -> dict:
    try:
        return json.loads(cache_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_cache(name: str, models: list[tuple[str, str]]) -> None:
    path = cache_file()
    try:
        data = _read_cache()
        data[name] = {"fetched": time.time(), "models": models}
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass   # a picker without a cache is only slower to fill


class _Catalog:
    """Models from the disk cache at once, then from each provider on a background thread."""

    def __init__(self, names: list[str], pinned: list[tuple[str, str]], on_change=lambda: None):
        self.lock = threading.Lock()
        self.pinned = pinned
        self.on_change = on_change
        self.version = 0   # bumped whenever a provider's list is swapped in
        cached = _read_cache()
        self.models: dict[str, list[tuple[str, str]]] = {}
        self.status: dict[str, str] = {}
        for name in names:
            rows = cached.get(name, {}).get("models") or []
            self.models[name] = [(f"{name}/{m}", d) for m, d in rows]
            self.status[name] = "refreshing" if rows else "loading"
        self.threads = [threading.Thread(target=self._load, args=(n,), daemon=True) for n in names]
        for thread in self.threads:
            thread.start()

    def _load(self, name: str) -> None:
        try:
            fetched = [tuple(row) for row in providers.PROVIDERS[name].catalog()]
        except Exception:
            fetched = None
        if fetched is None:
            # A provider that doesn't answer can't run its models either, so its cached ones go
            found, status = [], "offline"
        else:
            _write_cache(name, fetched)
            found, status = [(f"{name}/{m}", d) for m, d in fetched], f"{len(fetched)}"
            if name == "openrouter" and fetched and not os.environ.get("OPENROUTER_API_KEY"):
                status += ", no OPENROUTER_API_KEY"
        with self.lock:
            self.models[name], self.status[name] = found, status
            self.version += 1
        self.on_change()

    def wait(self, timeout: float = 15) -> None:
        end = time.monotonic() + timeout
        for thread in self.threads:
            thread.join(max(0, end - time.monotonic()))

    def items(self) -> list[tuple[str, str]]:
        with self.lock:
            pinned_values = {v for v, _ in self.pinned}
            rest = [m for name in self.status for m in self.models[name] if m[0] not in pinned_values]
            return self.pinned + rest

    def loading(self) -> bool:
        with self.lock:
            return any(s == "loading" for s in self.status.values())

    def summary(self) -> str:
        with self.lock:
            return "  ".join(f"{n}: {s}" for n, s in self.status.items())


# --------------------------------------------------------------------------
# The picker
# --------------------------------------------------------------------------

def _typed_model(text: str) -> str | None:
    """The typed text as a model, if it names a known provider and a model."""
    name, _, model_id = text.strip().partition("/")
    return text.strip() if name in providers.PROVIDERS and model_id else None


def _highlighted(value: str, hits: set[int], base: str, hit: str) -> list[tuple[str, str]]:
    """value split into styled runs, the matched letters in the hit style."""
    runs: list[tuple[str, str]] = []
    for n, ch in enumerate(value):
        style = hit if n in hits else base
        if runs and runs[-1][0] == style:
            runs[-1] = (style, runs[-1][1] + ch)
        else:
            runs.append((style, ch))
    return runs


def _synchronize(output) -> None:
    """Wrap every flush of a prompt_toolkit Vt100 output in synchronized-output markers."""
    flush = getattr(output, "flush", None)
    if flush is None or not hasattr(output, "_buffer"):
        return

    def synced_flush():
        if output._buffer:
            output._buffer.insert(0, SYNC_BEGIN)
            output._buffer.append(SYNC_END)
        flush()

    output.flush = synced_flush


def pick_model(question: str = "Which model?", initial: str = "",
               provider_names: list[str] | None = None,
               pinned: list[tuple[str, str]] | None = None) -> str | None:
    """Open the picker; returns 'provider/model', or None when cancelled.

    pinned: (value, detail) rows shown first, e.g. models run before.
    """
    names = provider_names or list(providers.PROVIDERS)
    try:
        from prompt_toolkit.application import Application
        from prompt_toolkit.buffer import Buffer
        from prompt_toolkit.formatted_text import FormattedText
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import HSplit, Layout, Window
        from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
        from prompt_toolkit.layout.processors import BeforeInput
    except ImportError:
        return _pick_typed(question, initial, names, pinned or [])
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return _pick_typed(question, initial, names, pinned or [])
    os.environ.setdefault("PROMPT_TOOLKIT_NO_CPR", "1")

    state = {"i": 0, "top": 0, "app": None}
    catalog = _Catalog(names, pinned or [], on_change=lambda: state["app"] and state["app"].invalidate())
    buffer = Buffer(multiline=False)
    buffer.text = initial
    buffer.cursor_position = len(initial)
    memo = {"key": None, "rows": []}

    def matches() -> list[tuple[str, str, set[int]]]:
        # Rendering and key handlers all ask; filter once per change of text or model list
        key = (buffer.text, catalog.version)
        if memo["key"] != key:
            memo["key"], memo["rows"] = key, filter_models(buffer.text, catalog.items())
        return memo["rows"]

    def on_text_changed(_):
        state["i"] = state["top"] = 0

    buffer.on_text_changed += on_text_changed

    def render():
        rows = matches()
        state["i"] = min(state["i"], max(len(rows) - 1, 0))
        if state["i"] < state["top"]:
            state["top"] = state["i"]
        elif state["i"] >= state["top"] + VISIBLE:
            state["top"] = state["i"] - VISIBLE + 1
        window = rows[state["top"]:state["top"] + VISIBLE]
        width = max((len(v) for v, _, _ in window), default=0)
        lines = []
        for n, (value, detail, hits) in enumerate(window, state["top"]):
            here = n == state["i"]
            base = "fg:ansicyan bold" if here else ""
            lines.append((base, f" {'›' if here else ' '} "))
            lines += _highlighted(value, hits, base, "fg:ansiyellow bold underline" if here else "fg:ansiyellow bold")
            lines.append(("fg:ansibrightblack", " " * (width - len(value)) + (f"  {detail}\n" if detail else "\n")))
        if not rows:
            typed = _typed_model(buffer.text)
            lines.append(("fg:ansibrightblack",
                          "   loading models...\n" if catalog.loading() and not typed else
                          f"   no match; Enter uses '{typed}'\n" if typed else "   no match\n"))
        # A steady height keeps the prompt from jumping as the list shrinks and grows
        lines.append(("", "\n" * max(0, VISIBLE - max(len(window), 1))))
        position = f"{state['i'] + 1}/{len(rows)}" if rows else "0"
        lines.append(("fg:ansibrightblack", f"  {position}   {catalog.summary()}\n"
                                            "  type to filter · ↑/↓ move · Tab complete · Enter pick · Esc cancel"))
        return FormattedText(lines)

    keys = KeyBindings()

    def move(step: int):
        def handler(event):
            count = len(matches())
            if count:
                state["i"] = max(0, min(count - 1, state["i"] + step))
        return handler

    for key, step in (("up", -1), ("c-p", -1), ("down", 1), ("c-n", 1),
                      ("pageup", -VISIBLE), ("pagedown", VISIBLE)):
        keys.add(key)(move(step))

    @keys.add("tab")
    def _(event):
        rows = matches()
        if rows:
            buffer.text = rows[state["i"]][0]
            buffer.cursor_position = len(buffer.text)

    @keys.add("enter")
    def _(event):
        rows = matches()
        chosen = rows[state["i"]][0] if rows else _typed_model(buffer.text)
        if chosen:
            event.app.exit(result=chosen)

    @keys.add("c-c")
    @keys.add("escape", eager=True)
    def _(event):
        event.app.exit(result=None)

    header = Window(FormattedTextControl(FormattedText([("bold", f"? {question}")])), height=1)
    field = Window(BufferControl(buffer, input_processors=[BeforeInput("  › ", style="fg:ansicyan")]), height=1)
    body = Window(FormattedTextControl(render), always_hide_cursor=True)
    app = Application(layout=Layout(HSplit([header, field, body]), focused_element=field),
                      key_bindings=keys, full_screen=False, erase_when_done=True)
    _synchronize(app.output)
    state["app"] = app
    try:
        result = app.run()
    except Exception:  # a terminal prompt_toolkit can't drive
        return _pick_typed(question, initial, names, pinned or [])
    if result:
        print(f"? {question} {result}")
    return result


def _pick_typed(question: str, initial: str, names: list[str], pinned: list[tuple[str, str]]) -> str | None:
    """Without a drawable terminal: fetch everything, then filter by typed text and number."""
    catalog = _Catalog(names, pinned)
    catalog.wait()
    query = initial
    while True:
        rows = filter_models(query, catalog.items())
        if len(rows) == 1:
            return rows[0][0]
        print(question if not query else f"{question} (matching '{query}')")
        for n, (value, detail, _) in enumerate(rows[:20], 1):
            print(f"  {n}) {value}" + (f"  {detail}" if detail else ""))
        if len(rows) > 20:
            print(f"  ... {len(rows) - 20} more; type more to narrow")
        try:
            raw = input("Number, filter text, or provider/model (q quits): ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if raw.lower() == "q":
            return None
        if raw.isdigit() and 1 <= int(raw) <= min(len(rows), 20):
            return rows[int(raw) - 1][0]
        if _typed_model(raw) and not filter_models(raw, catalog.items()):
            return raw
        query = raw
