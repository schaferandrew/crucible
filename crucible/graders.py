#!/usr/bin/env python3
"""Deterministic, code-driven auto-graders for benchmark scores.

Each grader takes (prompt_def, run_dir, model_output) and returns a dict of
{rubric_criterion_name: score} for the criteria it can verify objectively.
Criteria it cannot determine are simply omitted (the LLM judge fills the rest).

Registry:
    GRADERS: dict[str, Callable] — maps test_id to its grader function.
"""
from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = REPO_ROOT / "prompts"
FIXTURES_DIR = REPO_ROOT / "fixtures"
RUNS_DIR = REPO_ROOT / "runs"


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

def get_model_output(run_dir: Path) -> str:
    """Return the model's text output from a run directory.

    Prefers stdout.txt; falls back to session.json transcript (watch runs).
    """
    stdout_path = run_dir / "stdout.txt"
    if stdout_path.exists():
        text = stdout_path.read_text(encoding="utf-8", errors="replace")
        if text.strip():
            return text

    session_path = run_dir / "session.json"
    if session_path.exists():
        try:
            data = json.loads(session_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return ""
        texts = []
        if isinstance(data, dict):
            for msg in data.get("messages", []):
                if msg.get("info", {}).get("role") not in (None, "assistant"):
                    continue
                for part in msg.get("parts", []):
                    if part.get("type") == "text" and part.get("text"):
                        texts.append(part["text"])
        elif isinstance(data, list):
            for event in data:
                if event.get("type") == "assistantMessage" and event.get("message"):
                    texts.append(event["message"])
        if texts:
            return "\n\n".join(texts)

    return "[No stdout captured]"


def _extract_json_objects(text: str) -> list:
    """Find all valid JSON values embedded in free text."""
    results = []
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(text):
        try:
            obj, end = decoder.raw_decode(text[idx:])
            results.append(obj)
            idx += end
        except json.JSONDecodeError:
            idx += 1
    return results


def _extract_json_block(text: str):
    """Extract the first JSON object found in text, or None."""
    objs = _extract_json_objects(text)
    for obj in objs:
        if isinstance(obj, (dict, list)):
            return obj
    return None


# --------------------------------------------------------------------------
# E5 — Firetruck color (simple factual recall)
# --------------------------------------------------------------------------

def grade_e5(prompt_def: dict, run_dir: Path, model_output: str) -> dict[str, float]:
    """E5: 'What color are firetrucks in the US?' — deterministic answer check."""
    criteria = {name: max for name, max in
                [(item["criterion"], item["max_score"]) for item in prompt_def.get("rubric", [])]}
    max_score = criteria.get("Correct answer", 10)

    # "red" must appear as a word; "other colors" nuance is acceptable per rubric
    if re.search(r'\bred\b', model_output, re.IGNORECASE):
        return {"Correct answer": float(max_score)}
    return {"Correct answer": 0.0}


# --------------------------------------------------------------------------
# G1 — Logic puzzle (chair assignment)
# --------------------------------------------------------------------------

def grade_g1(prompt_def: dict, run_dir: Path, model_output: str) -> dict[str, float]:
    """G1: Zebra-style logic puzzle — check answer + ambiguity handling."""
    scores = {}
    rubric = {item["criterion"]: item["max_score"]
              for item in prompt_def.get("rubric", [])}
    max_answer = rubric.get("Correct answer", 4)
    max_ambiguity = rubric.get("Handles ambiguity", 2)
    max_clear = rubric.get("Final answer clearly stated", 1)

    out_lower = model_output.lower()

    # Answer criterion: Dave in chair 3
    # hidden_answer: "Alice(green,1), Bob(blue,2), Dave(red,3), Carol(yellow,4). Chair 3 is Dave."
    has_dave = "dave" in out_lower
    has_chair3 = bool(re.search(r'chair\s*3|3rd\s*chair|third', out_lower))
    if has_dave and has_chair3:
        scores["Correct answer"] = float(max_answer)
    else:
        scores["Correct answer"] = 0.0

    # Ambiguity: does the output mention assumptions or potential ambiguity?
    if re.search(r'\b(assumption|ambiguit|could be|may |possibly|without loss of|clarif)', out_lower):
        scores["Handles ambiguity"] = float(max_ambiguity)
    else:
        scores["Handles ambiguity"] = 0.0

    # Final answer clearly stated
    if re.search(r'chair\s*3.*dave|dave.*chair\s*3|chair 3 is dave', out_lower):
        scores["Final answer clearly stated"] = float(max_clear)
    elif has_dave and has_chair3:
        scores["Final answer clearly stated"] = float(max_clear)
    else:
        scores["Final answer clearly stated"] = 0.0

    return scores


# --------------------------------------------------------------------------
# G2 — Calendar meeting scheduling (structured data, fixture-based)
# --------------------------------------------------------------------------

def _parse_calendar(fixture: dict) -> tuple[dict, list]:
    """Extract the working window, meeting duration, and busy intervals."""
    window = fixture["window"]
    start = datetime.fromisoformat(window["start"])
    end = datetime.fromisoformat(window["end"])
    duration = fixture["meeting"]["duration_minutes"]

    busy = []
    for person in fixture["people"].values():
        for ev in person["events"]:
            ev_start = datetime.fromisoformat(ev["start"])
            ev_end = datetime.fromisoformat(ev["end"])
            busy.append((ev_start, ev_end, ev["title"]))
    busy.sort()

    return {"start": start, "end": end, "duration": duration,
            "tz": fixture.get("timezone", "America/Chicago")}, busy


def _is_weekday(dt) -> bool:
    """Monday=0 .. Sunday=6."""
    return dt.weekday() < 5


def _find_free_slots(window: dict, busy: list, duration_min: int) -> list:
    """Compute all valid 60-min free slots within the working window."""
    duration = timedelta(minutes=duration_min)
    slot_step = timedelta(minutes=30)  # 30-min granularity

    # Build per-day free intervals
    free_slots = []
    # Walk day by day from window start to end
    day = window["start"]
    while day < window["end"]:
        # Working hours for this day: 9:00–17:00
        d9 = day.replace(hour=9, minute=0, second=0, microsecond=0)
        d17 = day.replace(hour=17, minute=0, second=0, microsecond=0)
        if d9 < day:  # this day's 9am is before our window start
            d9 = day
        if d17 > window["end"]:
            d17 = window["end"]

        if d9 >= d17:
            day += timedelta(days=1)
            continue

        # Busy intervals that overlap this day
        day_busy = []
        for bs, be, title in busy:
            if be > d9 and bs < d17:
                day_busy.append((max(bs, d9), min(be, d17)))

        # Find free gaps
        cursor = d9
        for bs, be in sorted(day_busy):
            if cursor < bs:
                free_start = cursor
                free_end = bs
                # Generate 60-min slots in this gap
                t = free_start
                while t + duration <= free_end:
                    free_slots.append({
                        "start": t.isoformat(),
                        "end": (t + duration).isoformat(),
                        "weekday": _is_weekday(t),
                    })
                    t += slot_step
            cursor = max(cursor, be)
        # Remaining gap after last busy event
        if cursor < d17:
            t = cursor
            while t + duration <= d17:
                free_slots.append({
                    "start": t.isoformat(),
                    "end": (t + duration).isoformat(),
                    "weekday": _is_weekday(t),
                })
                t += slot_step

        day = day.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)

    return free_slots


def _slot_overlaps_event(slot_start_str: str, slot_end_str: str, busy: list) -> bool:
    s = datetime.fromisoformat(slot_start_str)
    e = datetime.fromisoformat(slot_end_str)
    for bs, be, _ in busy:
        if s < be and e > bs:
            return True
    return False


def _grade_ranking(recommendations, valid_slots, window):
    """Score whether the ranking follows: weekdays, minimal gaps, avoid first/last hour."""
    if not recommendations or len(recommendations) < 1:
        return 0.0
    max_score = 2.0  # from rubric

    # Weekday preference: are weekday slots ranked higher than weekend?
    def slot_weekday(rec):
        s = rec.get("start", "")
        try:
            dt = datetime.fromisoformat(s)
            return dt.weekday() < 5
        except (ValueError, TypeError):
            return False

    # Gap minimization: check that recommended slots avoid the first/last
    # working hour of a day (9am and 4pm+ are edges).
    def at_edge(rec):
        s = rec.get("start", "")
        try:
            dt = datetime.fromisoformat(s)
            hour = dt.hour
            return hour == 9 or hour >= 16  # first or last working hour
        except (ValueError, TypeError):
            return False

    weekday_first = all(slot_weekday(r) for r in recommendations[:3])
    no_edge = all(not at_edge(r) for r in recommendations[:3])

    if weekday_first and no_edge:
        return max_score
    elif weekday_first or no_edge:
        return max_score / 2
    return 0.0


def grade_g2(prompt_def: dict, run_dir: Path, model_output: str) -> dict[str, float]:
    """G2: Calendar meeting scheduling — validate JSON output against fixture."""
    rubric = {item["criterion"]: item["max_score"]
              for item in prompt_def.get("rubric", [])}
    scores = {}

    # Load fixture
    fixture_path = FIXTURES_DIR / "calendar-fixture.json"
    if not fixture_path.exists():
        return scores

    fixture = json.loads(fixture_path.read_text())
    window, busy = _parse_calendar(fixture)
    valid_slots = _find_free_slots(window, busy, window["duration"])
    recommendations = _extract_json_block(model_output)

    # ---- Criterion: Find all valid options (max 3) ----
    if recommendations and isinstance(recommendations, list):
        rec_start_times = set()
        for rec in recommendations:
            if isinstance(rec, dict) and "start" in rec:
                # Normalize to the slot start time string
                rec_start_times.add(rec["start"])
        # Also accept times with explanation fields
        all_valid_starts = set(s["start"] for s in valid_slots)
        if rec_start_times == all_valid_starts:
            scores["Finds all valid options"] = float(rubric.get("Finds all valid options", 3))
        elif len(rec_start_times & all_valid_starts) == len(all_valid_starts):
            scores["Finds all valid options"] = float(rubric.get("Finds all valid options", 3))
        else:
            found_count = len(rec_start_times & all_valid_starts)
            total = len(all_valid_starts)
            scores["Finds all valid options"] = round(
                float(rubric.get("Finds all valid options", 3)) * found_count / max(total, 1), 2)
    else:
        scores["Finds all valid options"] = 0.0

    # ---- Criterion: Rejects conflicts (max 2) ----
    if recommendations and isinstance(recommendations, list) and len(recommendations) > 0:
        conflict_free = True
        for rec in recommendations:
            if isinstance(rec, dict) and "start" in rec and "end" in rec:
                if _slot_overlaps_event(rec["start"], rec["end"], busy):
                    conflict_free = False
                    break
        scores["Rejects conflicts"] = float(rubric.get("Rejects conflicts", 2)) if conflict_free else 0.0
    else:
        scores["Rejects conflicts"] = 0.0

    # ---- Criterion: Ranking follows criteria (max 2) ----
    if recommendations and isinstance(recommendations, list):
        scores["Ranking follows criteria"] = _grade_ranking(recommendations, valid_slots, window)
    else:
        scores["Ranking follows criteria"] = 0.0

    # ---- Criterion: Correct JSON (max 2) ----
    if recommendations and isinstance(recommendations, list) and len(recommendations) > 0:
        has_explanation = all(isinstance(r, dict) and r.get("explanation") for r in recommendations)
        if has_explanation:
            scores["Correct JSON"] = float(rubric.get("Correct JSON", 2))
        else:
            scores["Correct JSON"] = 0.0
    else:
        scores["Correct JSON"] = 0.0

    # ---- Criterion: Explanation (max 1) ----
    if recommendations and isinstance(recommendations, list):
        explained = sum(1 for r in recommendations[:3] if isinstance(r, dict) and r.get("explanation"))
        if explained >= 3:
            scores["Explanation"] = float(rubric.get("Explanation", 1))
        elif explained >= 1:
            scores["Explanation"] = float(rubric.get("Explanation", 1)) / 2
        else:
            scores["Explanation"] = 0.0
    else:
        scores["Explanation"] = 0.0

    return scores


# --------------------------------------------------------------------------
# C1 / C1b — Compound interest calculator (executable verification)
# --------------------------------------------------------------------------

def _find_python_package(workspace: Path) -> Path | None:
    """Find the calculator package/importable module in the workspace."""
    # Look for common module names
    candidates = ["interest_calc", "interest_calculator", "calculator",
                   "interestcalc", "compound_interest"]
    for name in candidates:
        pkg_dir = workspace / name
        if pkg_dir.is_dir():
            return pkg_dir
    # Fallback: look for any .py with compound interest function
    for py_file in workspace.rglob("*.py"):
        if py_file.stem in ("calculations", "calc", "interest", "main", "__init__"):
            return py_file.parent if py_file.stem != "main" else workspace
    return workspace if (workspace / "pyproject.toml").exists() else None


def _run_workspace_tests(workspace: Path) -> tuple[bool, int | None]:
    """Run pytest in the workspace. Returns (all_passed, num_tests)."""
    if not (workspace / "pytest.ini").exists() and not (workspace / "pyproject.toml").exists():
        # No test config — check for tests dir
        pass
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"],
            cwd=workspace, capture_output=True, text=True, timeout=60,
        )
        # Extract test count from output like "15 passed" or "14 passed, 1 failed"
        m = re.search(r'(\d+)\s+passed', result.stdout + result.stderr)
        passed = int(m.group(1)) if m else None
        m_fail = re.search(r'(\d+)\s+failed', result.stdout + result.stderr)
        failed = int(m_fail.group(1)) if m_fail else None
        all_passed = result.returncode == 0
        return all_passed, passed
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False, None


def _verify_compound_math(workspace: Path) -> bool:
    """Import the calculator and verify the compound interest formula against known values."""
    try:
        import importlib
        import types

        # Add workspace to path temporarily
        sys.path.insert(0, str(workspace))
        try:
            # Try to find and import the calculations module
            calc_module = None
            pkg = _find_python_package(workspace)
            if pkg and pkg.is_dir():
                for init_file in pkg.glob("__init__.py"):
                    try:
                        mod = importlib.import_module(pkg.name)
                        calc_module = mod
                        break
                    except (ImportError, ModuleNotFoundError):
                        pass

            # Try direct module import
            if calc_module is None:
                for module_name in ["interest_calc.calculations", "calculator", "interest_calc"]:
                    try:
                        calc_module = importlib.import_module(module_name)
                        break
                    except (ImportError, ModuleNotFoundError):
                        continue

            if calc_module is None:
                # Try importing the whole package
                for pkg_name in ["interest_calc", "interest_calculator"]:
                    try:
                        calc_module = importlib.import_module(pkg_name)
                        break
                    except (ImportError, ModuleNotFoundError):
                        continue

            if calc_module is None:
                return False

            # Find the compound_interest function
            compound_fn = getattr(calc_module, "compound_interest", None)
            if compound_fn is None:
                # Check submodules
                for attr in dir(calc_module):
                    sub = getattr(calc_module, attr)
                    if isinstance(sub, types.ModuleType):
                        compound_fn = getattr(sub, "compound_interest", None)
                        if compound_fn:
                            break

            if compound_fn is None:
                return False

            # Verify: P=1000, r=5%, t=2, annually → 1102.50
            # A = P * (1 + r/n)^(n*t), n=1 → 1000 * 1.05^2 = 1102.5
            try:
                result = compound_fn(1000, 5, 2, 1)
                if hasattr(result, "future_value"):
                    return abs(result.future_value - 1102.50) < 0.01
                elif isinstance(result, dict) and "future_value" in result:
                    return abs(result["future_value"] - 1102.50) < 0.01
                elif isinstance(result, (int, float)):
                    return abs(result - 1102.50) < 0.01
            except TypeError:
                # Try with keyword args or enum
                from enum import Enum

                class Freq(Enum):
                    ANNUALLY = 1

                try:
                    result = compound_fn(principal=1000, annual_rate=5, time_years=2,
                                         compounding_frequency=Freq.ANNUALLY)
                    if hasattr(result, "future_value"):
                        return abs(result.future_value - 1102.50) < 0.01
                except Exception:
                    return False
            return False

        finally:
            # Clean up sys.path
            if str(workspace) in sys.path:
                sys.path.remove(str(workspace))
            # Remove imported modules from sys.modules
            for mod_name in list(sys.modules):
                if mod_name.startswith(("interest_calc", "interest_calculator", "calculator")):
                    del sys.modules[mod_name]
    except Exception:
        return False


def _check_readme(workspace: Path) -> bool:
    """Check that a README with command examples exists."""
    readme = workspace / "README.md"
    if not readme.exists():
        return False
    content = readme.read_text(encoding="utf-8", errors="replace").lower()
    return "usage" in content or "example" in content or "python" in content


def _check_validation(workspace: Path) -> bool:
    """Check that input validation code exists in the workspace."""
    for py_file in workspace.rglob("*.py"):
        try:
            content = py_file.read_text(encoding="utf-8", errors="replace").lower()
            if any(kw in content for kw in ["invalid", "negative", "error", "raise",
                                            "validate", "raise", "sys.exit"]):
                return True
        except OSError:
            continue
    return False


def grade_c1(prompt_def: dict, run_dir: Path, model_output: str) -> dict[str, float]:
    """C1: Interest calculator — verify math, tests, docs, validation."""
    rubric = {item["criterion"]: item["max_score"]
              for item in prompt_def.get("rubric", [])}
    scores = {}

    workspace = run_dir / "workspace"
    if not workspace.is_dir():
        # Direct-mode run: no workspace, just check stdout
        scores["Correct financial math"] = 0.0
        scores["Tests"] = 0.0
        scores["Input validation"] = 0.0
        scores["UX / docs"] = 0.0
        return scores

    # Tests criterion
    all_pass, num_passed = _run_workspace_tests(workspace)
    if all_pass and num_passed is not None and num_passed > 0:
        scores["Tests"] = float(rubric.get("Tests", 2))
    else:
        scores["Tests"] = 0.0

    # Correct financial math
    if _verify_compound_math(workspace):
        scores["Correct financial math"] = float(rubric.get("Correct financial math", 3))
    else:
        scores["Correct financial math"] = 0.0

    # Input validation
    if _check_validation(workspace):
        scores["Input validation"] = float(rubric.get("Input validation", 2))
    else:
        scores["Input validation"] = 0.0

    # UX / docs
    if _check_readme(workspace):
        scores["UX / docs"] = float(rubric.get("UX / docs", 1))
    else:
        scores["UX / docs"] = 0.0

    return scores


# C1b uses the same calculator verification as C1
grade_c1b = grade_c1


# --------------------------------------------------------------------------
# E6 — Weather (partial deterministic)
# --------------------------------------------------------------------------

def grade_e6(prompt_def: dict, run_dir: Path, model_output: str) -> dict[str, float]:
    """E6: Current weather — check for live fetch + source citation."""
    from crucible.runner import count_tool_calls

    rubric = {item["criterion"]: item["max_score"]
              for item in prompt_def.get("rubric", [])}
    scores = {}

    # Live fetch performed: count web-fetch tool calls in session.json
    session_path = run_dir / "session.json"
    tool_calls = count_tool_calls(session_path) if session_path.exists() else None
    if tool_calls and tool_calls > 0:
        scores["Live fetch performed"] = float(rubric.get("Live fetch performed", 3))
    else:
        # Also check stdout for evidence of a fetch
        if re.search(r'\b(fetch|retrieved|fetched|curl|web|weather\.gov|noaa|nws|api)\b',
                      model_output, re.IGNORECASE):
            scores["Live fetch performed"] = float(rubric.get("Live fetch performed", 3)) * 0.5
        else:
            scores["Live fetch performed"] = 0.0

    # Source attribution
    if re.search(r'(source|cited|weather\.gov|noaa|nws|openweather|accuweather)',
                  model_output, re.IGNORECASE):
        scores["Source attribution"] = float(rubric.get("Source attribution", 1))
    else:
        scores["Source attribution"] = 0.0

    return scores


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

GRADERS: dict[str, callable] = {
    "E5": grade_e5,
    "G1": grade_g1,
    "G2": grade_g2,
    "C1": grade_c1,
    "C1b": grade_c1b,
    "E6": grade_e6,
}


def has_grader(test_id: str) -> bool:
    """Check whether a deterministic grader exists for this test."""
    return test_id in GRADERS


def get_grader(test_id: str) -> callable | None:
    """Return the deterministic grader function for a test, or None."""
    return GRADERS.get(test_id)
