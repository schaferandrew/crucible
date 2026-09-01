#!/usr/bin/env python3
"""Interactive selector with curses support when available."""
import sys
from typing import Optional

try:
    import curses
except ImportError:  # pragma: no cover - Windows doesn't provide curses
    curses = None

try:
    import msvcrt  # type: ignore
except ImportError:  # pragma: no cover - non-Windows
    msvcrt = None


def select_from_list(items: list[str], prompt: str) -> Optional[str]:
    """Display arrow-key navigable list. Returns selected item or None if cancelled."""
    if not items:
        return None
    if len(items) == 1:
        return items[0]

    if sys.platform.startswith("win") and msvcrt is not None and sys.stdin.isatty():
        return _windows_select(items, prompt)

    # Check if we have a proper TTY for curses.
    if curses is not None and sys.stdin.isatty():
        return _curses_select(items, prompt)

    return _fallback_select(items, prompt)


def _curses_select(items: list[str], prompt: str) -> Optional[str]:
    def _selector(stdscr):
        curses.curs_set(0)
        stdscr.keypad(True)

        selected_idx = 0
        while True:
            stdscr.clear()
            h, w = stdscr.getmaxyx()

            stdscr.addstr(0, 0, prompt[: w - 1])
            stdscr.addstr(1, 0, "↑/↓ navigate, Enter select, q/Esc cancel"[: w - 1])

            for i, item in enumerate(items):
                y = i + 3
                if y >= h - 1:
                    break
                prefix = "> " if i == selected_idx else "  "
                line = f"{prefix}{item}"[: w - 1]
                if i == selected_idx:
                    stdscr.addstr(y, 0, line, curses.A_REVERSE)
                else:
                    stdscr.addstr(y, 0, line)

            stdscr.refresh()

            key = stdscr.getch()
            if key in (curses.KEY_UP, ord("k")):
                selected_idx = (selected_idx - 1) % len(items)
            elif key in (curses.KEY_DOWN, ord("j")):
                selected_idx = (selected_idx + 1) % len(items)
            elif key in (curses.KEY_ENTER, 10, 13):
                return items[selected_idx]
            elif key in (27, ord("q")):
                return None

    try:
        return curses.wrapper(_selector)
    except (KeyboardInterrupt, AttributeError, curses.error):
        return _fallback_select(items, prompt)


def _windows_select(items: list[str], prompt: str) -> Optional[str]:
    """Windows-native keyboard selector using msvcrt and arrow keys."""
    selected_idx = 0
    while True:
        print("\r" + prompt, end="", flush=True)
        print("\r", end="", flush=True)
        for i, item in enumerate(items):
            prefix = "> " if i == selected_idx else "  "
            print(f"\r{prefix}{item}", end="")
            if i != len(items) - 1:
                print()
        print("\rUse ↑/↓, Enter to select, q to quit", flush=True)

        key = msvcrt.getwch()

        if key in ("\x00", "\xe0"):
            key = msvcrt.getwch()
            if key == "H":
                selected_idx = (selected_idx - 1) % len(items)
            elif key == "P":
                selected_idx = (selected_idx + 1) % len(items)
            continue

        if key in ("\r", "\n"):
            return items[selected_idx]
        if key in ("q", "Q", "\x1b"):
            return None
        if key in ("k", "K"):
            selected_idx = (selected_idx - 1) % len(items)
        elif key in ("j", "J"):
            selected_idx = (selected_idx + 1) % len(items)


def _fallback_select(items: list[str], prompt: str) -> Optional[str]:
    """Simple numbered selector for non-TTY environments."""
    print(prompt, file=sys.stderr)
    for i, item in enumerate(items):
        print(f"  {i + 1}. {item}", file=sys.stderr)
    print("Enter number (or q to quit): ", end="", flush=True, file=sys.stderr)
    try:
        choice = sys.stdin.readline()
        choice = choice.strip()
        if choice.lower() == 'q':
            return None
        idx = int(choice) - 1
        if 0 <= idx < len(items):
            return items[idx]
    except (ValueError, EOFError, KeyboardInterrupt):
        pass
    return None