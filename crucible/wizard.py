#!/usr/bin/env python3
"""`crucible run` with no test: asks what to run, one question at a time.

Menus take arrow keys, the number shown next to an option, or its first letter, then Enter. They
are drawn with prompt_toolkit (the library behind IPython), which works the same on macOS, Linux
and Windows terminals; where it can't draw a menu, the questions fall back to typed numbers.
Flags given on the command line answer their question, so it isn't asked.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from collections import Counter
from pathlib import Path

from crucible import plan as planner
from crucible.agents import AGENTS
from crucible.model_picker import pick_model
from crucible.providers import LMSTUDIO_BASE_URL
from crucible.taxonomy import AREAS, MODE_BLURBS, MODE_HARNESSES, MODE_LABELS, MODES, TIERS, mode_for

TIER_BLURBS = {"spark": "the basics, a pass/fail gate", "temper": "everyday work, the headline score",
               "forge": "frontier-level work, slow"}


class Cancelled(Exception):
    pass


# --------------------------------------------------------------------------
# Asking
# --------------------------------------------------------------------------

_warned = False


def _no_menus(reason: str) -> None:
    global _warned
    if not _warned:
        print(f"(Arrow-key menus are off: {reason}. Reinstall crucible with `uv tool install --editable .` "
              "or `pip install -e .` to get them. Typing numbers works meanwhile.)")
        _warned = True


def choose(question: str, options: list[tuple[str, object]], default: int = 0) -> object:
    """One answer from a menu: arrows (or j/k) move, a number or an option's first letter jumps
    to it, Enter answers. Falls back to typed numbers where a menu can't be drawn."""
    try:
        from prompt_toolkit.application import Application
        from prompt_toolkit.formatted_text import FormattedText
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import Layout, Window
        from prompt_toolkit.layout.controls import FormattedTextControl
    except ImportError:
        _no_menus("prompt_toolkit isn't installed for this Python")
        return _choose_typed(question, options, default)
    if not sys.stdout.isatty():
        return _choose_typed(question, options, default)
    # Some terminals (and pseudo-terminals) don't answer cursor-position requests; the menu doesn't need them
    os.environ.setdefault("PROMPT_TOOLKIT_NO_CPR", "1")

    state = {"i": default, "done": False}

    def render():
        lines = [("bold", f"? {question}"), ("", "  (arrows, number or first letter, then Enter)\n")]
        for n, (label, _) in enumerate(options):
            here = n == state["i"]
            lines.append(("fg:ansicyan bold" if here else "", f" {'›' if here else ' '} {n + 1}) {label}\n"))
        return FormattedText(lines)

    keys = KeyBindings()

    @keys.add("up")
    @keys.add("k")
    @keys.add("s-tab")
    def _(event):
        state["i"] = (state["i"] - 1) % len(options)

    @keys.add("down")
    @keys.add("j")
    @keys.add("tab")
    def _(event):
        state["i"] = (state["i"] + 1) % len(options)

    @keys.add("enter")
    def _(event):
        state["done"] = True
        event.app.exit()

    @keys.add("c-c")
    @keys.add("escape")
    def _(event):
        event.app.exit(exception=KeyboardInterrupt)

    @keys.add("<any>")
    def _(event):
        key = event.data
        if key.isdigit() and 1 <= int(key) <= len(options):
            state["i"] = int(key) - 1
        elif key.isalpha():
            # The next option (after the current one) whose label starts with that letter
            for step in range(1, len(options) + 1):
                n = (state["i"] + step) % len(options)
                if options[n][0].lower().startswith(key.lower()):
                    state["i"] = n
                    break

    app = Application(layout=Layout(Window(FormattedTextControl(render), always_hide_cursor=True)),
                      key_bindings=keys, full_screen=False, erase_when_done=True)
    try:
        app.run()
    except KeyboardInterrupt:
        raise Cancelled from None
    except Exception as exc:  # a terminal prompt_toolkit can't drive
        _no_menus(f"this terminal can't draw them ({type(exc).__name__})")
        return _choose_typed(question, options, default)
    label, value = options[state["i"]]
    print(f"? {question} {label}")
    return value


def _choose_typed(question: str, options: list[tuple[str, object]], default: int) -> object:
    print(question)
    for i, (label, _) in enumerate(options, 1):
        print(f"  {i}) {label}")
    while True:
        raw = _input(f"Choice [{default + 1}]: ")
        if not raw:
            return options[default][1]
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][1]
        matches = [v for label, v in options if label.lower().startswith(raw.lower())]
        if len(matches) == 1:
            return matches[0]
        print(f"  Type a number from 1 to {len(options)}.")


def ask_text(question: str, default: str = "", completions: list[str] | None = None) -> str:
    try:
        from prompt_toolkit import prompt
        from prompt_toolkit.completion import WordCompleter
    except ImportError:
        return _input(f"{question} " + (f"[{default}] " if default else "")) or default
    try:
        completer = WordCompleter(completions, ignore_case=True, sentence=False) if completions else None
        return prompt(f"{question} ", default=default, completer=completer).strip()
    except (KeyboardInterrupt, EOFError):
        raise Cancelled from None


def confirm(question: str, default: bool = True) -> bool:
    """y/n, Enter takes the default."""
    while True:
        raw = _input(f"{question} [{'Y/n' if default else 'y/N'}] ").lower()
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Type y or n.")


def _input(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        raise Cancelled from None


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------

def lmstudio_loaded() -> list[tuple[str, int | None]]:
    base = LMSTUDIO_BASE_URL.removesuffix("/v1")
    try:
        with urllib.request.urlopen(f"{base}/api/v0/models", timeout=3) as resp:
            data = json.load(resp).get("data", [])
    except Exception:
        return []
    return [(m["id"], m.get("loaded_context_length")) for m in data
            if m.get("state") == "loaded" and m.get("type") in ("llm", "vlm")]


def recent_models(runs_dir: Path, limit: int = 6) -> list[str]:
    """provider/model names from the newest runs, most recent first."""
    seen: dict[str, float] = {}
    for meta_file in runs_dir.glob("*/*/*/*/meta.json"):
        try:
            model = json.loads(meta_file.read_text(encoding="utf-8")).get("model")
        except (OSError, json.JSONDecodeError):
            continue
        if model:
            seen[model] = max(seen.get(model, 0), meta_file.stat().st_mtime)
    return sorted(seen, key=seen.get, reverse=True)[:limit]


def ask_model(runs_dir: Path) -> str:
    """Type-to-filter over every provider's live model list; loaded and recently run models first."""
    pinned = [(f"lmstudio/{model_id}", f"loaded in LM Studio, context {ctx or '?'}")
              for model_id, ctx in lmstudio_loaded()]
    pinned += [(model, "run before") for model in recent_models(runs_dir)
               if "/" in model and model not in {v for v, _ in pinned}]
    model = pick_model("Which model?", pinned=pinned)
    if model is None:
        raise Cancelled
    return model


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

def _count(prompts: dict[str, dict], **match) -> int:
    return sum(all((mode_for(p) if k == "mode" else p.get(k)) == v for k, v in match.items())
               for p in prompts.values() if p.get("status") != "retired")


def ask_tests(prompts: dict[str, dict]) -> dict:
    """{selectors, mode, area, tier} describing what to run."""
    what = choose("What do you want to run?", [
        (f"Everything ({_count(prompts)}): both modes, run as two separate groups", "all"),
        *[(f"{MODE_LABELS[m]} tests ({_count(prompts, mode=m)}): {MODE_BLURBS[m]} ({', '.join(AREAS[m].values())})", m) for m in MODES],
        ("Pick individual tests", "pick"),
    ])
    if what == "pick":
        return {"selectors": ask_test_ids(prompts), "mode": None, "area": None, "tier": None}
    if what == "all":
        tier = choose("Which tiers?", [("All tiers", None), *[
            (f"{t.title()}: {TIER_BLURBS[t]} ({_count(prompts, tier=t)})", t) for t in TIERS]])
        return {"selectors": [], "mode": None, "area": None, "tier": tier}
    area = choose(f"Which {MODE_LABELS[what]} area?", [
        (f"All {MODE_LABELS[what]} areas ({_count(prompts, mode=what)})", None),
        *[(f"{label} ({_count(prompts, area=a)})", a) for a, label in AREAS[what].items() if _count(prompts, area=a)],
    ])
    scope = {"mode": what, **({"area": area} if area else {})}
    tiers = [(t, _count(prompts, tier=t, **scope)) for t in TIERS]
    tier = choose("Which tiers?", [(f"All tiers ({_count(prompts, **scope)})", None),
                                   *[(f"{t.title()}: {TIER_BLURBS[t]} ({n})", t) for t, n in tiers if n]])
    return {"selectors": [], "mode": what, "area": area, "tier": tier}


def ask_test_ids(prompts: dict[str, dict]) -> list[str]:
    print()
    for mode in MODES:
        print(f"  {MODE_LABELS[mode]}")
        for area, label in AREAS[mode].items():
            ids = planner.sort_tests([t for t, p in prompts.items() if p.get("area") == area
                                      and p.get("status") != "retired"], prompts)
            if ids:
                print(f"    {label:<14}" + " ".join(f"{t}({prompts[t]['tier'][0]})" for t in ids))
    print("  (s) spark  (t) temper  (f) forge\n")
    while True:
        raw = ask_text("Test IDs, separated by spaces:", completions=list(prompts))
        ids = [t for t in raw.replace(",", " ").split() if t]
        try:
            return planner.select(ids) and ids
        except ValueError as exc:
            print(f"  {exc}")


def ask_harness() -> str:
    options = [(name, name) for name in MODE_HARNESSES["agentic"]]
    return choose("Which agent harness for the agentic tests? (chat tests always run with direct)", options)


# --------------------------------------------------------------------------
# The whole conversation
# --------------------------------------------------------------------------

def run_wizard(args) -> tuple[planner.Plan, dict] | None:
    """Ask for whatever the flags didn't say; returns the plan and the answers, or None if cancelled."""
    if not sys.stdin.isatty():
        print("crucible run needs a test (or suite) when it isn't run in a terminal. See: crucible run --help")
        return None
    try:
        prompts = planner.all_prompts()
        model = args.model or ask_model(args.output)
        picked = ({"selectors": args.test, "mode": args.mode, "area": args.area, "tier": args.tier}
                  if (args.test or args.mode or args.area or args.tier) else ask_tests(prompts))
        tests = planner.select(picked["selectors"], picked["mode"], picked["area"], picked["tier"])
        if not tests:
            print("No tests match that.")
            return None
        agentic = [t for t in tests if mode_for(prompts[t]) == "agentic"]
        harness = args.agent or (ask_harness() if agentic else None)
        watch = args.watch
        if agentic and not watch and len(agentic) <= 3:
            watch = confirm("Watch the agent work in its TUI? (for debugging; you quit the TUI to finish each test)",
                            default=False)
        done = sum(planner.has_current_run(args.output, model, t, prompts[t],
                                           "direct" if mode_for(prompts[t]) == "chat" else harness or "opencode")
                   for t in tests)
        skip_done = args.skip_done or (done > 0 and not confirm(
            f"{done} of these already have a run on their current version. Run them again?", default=False))
        plan = planner.build(model, tests, harness, args.timeout, skip_done, args.output, args.allow_long)
        if not plan.steps:
            print("Everything selected has already been run on its current version.")
            return None
        print()
        for line in planner.describe(plan):
            print(f"  {line}")
        limits = ", ".join(f"{n} x {secs // 60} min" for secs, n in sorted(Counter(s.timeout for s in plan.steps).items()))
        print(f"  Time limits: {limits} (most tests finish well inside them)")
        command = planner.command_line(plan, picked["selectors"], picked["mode"], picked["area"], picked["tier"],
                                       harness, args.timeout, skip_done)
        print(f"  Same thing next time: {command}{' --watch' if watch else ''}\n")
        if not confirm("Start?"):
            return None
        return plan, {"watch": watch}
    except Cancelled:
        print("\nCancelled.")
        return None
