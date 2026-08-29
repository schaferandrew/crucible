#!/usr/bin/env python3
"""Interactive selector using curses with fallback for non-TTY."""
import curses
import sys
from typing import Optional


def select_from_list(items: list[str], prompt: str) -> Optional[str]:
    """Display arrow-key navigable list. Returns selected item or None if cancelled."""
    if not items:
        return None
    if len(items) == 1:
        return items[0]

    # Check if we have a proper TTY for curses
    if not sys.stdin.isatty():
        return _fallback_select(items, prompt)

    def _selector(stdscr):
        curses.curs_set(0)
        stdscr.keypad(True)

        selected_idx = 0
        while True:
            stdscr.clear()
            h, w = stdscr.getmaxyx()

            # Title
            stdscr.addstr(0, 0, prompt[:w - 1])
            stdscr.addstr(1, 0, "↑/↓ navigate, Enter select, q/Esc cancel"[:w - 1])

            # List items
            for i, item in enumerate(items):
                y = i + 3
                if y >= h - 1:
                    break
                prefix = "> " if i == selected_idx else "  "
                line = f"{prefix}{item}"[:w - 1]
                if i == selected_idx:
                    stdscr.addstr(y, 0, line, curses.A_REVERSE)
                else:
                    stdscr.addstr(y, 0, line)

            stdscr.refresh()

            key = stdscr.getch()
            if key in (curses.KEY_UP, ord('k')):
                selected_idx = (selected_idx - 1) % len(items)
            elif key in (curses.KEY_DOWN, ord('j')):
                selected_idx = (selected_idx + 1) % len(items)
            elif key in (curses.KEY_ENTER, 10, 13):
                return items[selected_idx]
            elif key in (27, ord('q')):
                return None

    try:
        return curses.wrapper(_selector)
    except (KeyboardInterrupt, curses.error):
        return _fallback_select(items, prompt)


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