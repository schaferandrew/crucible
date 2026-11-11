"""The run rules the dashboard page applied in the browser, as pure functions (layer 2 of the dashboard
rewrite; docs/site-data-format.md). Each rule cites the page code it reproduces, so parity can be checked
against assets/js/crucible-core.js of the portfolio site.

Nothing here raises on odd input: a missing field is None, a non-dict where a dict belongs is {}.
"""
from __future__ import annotations

# States a run can have in one suite. `counted` and `provisional` feed scores; the rest only feed notes.
STATES = ("counted", "provisional", "older", "harness", "invalid", "retired", "unknown_task", "withdrawn")
OUTCOMES = ("finished", "timed_out", "error")


def d(value) -> dict:
    """value if it is a dict, else {} (records are read defensively)."""
    return value if isinstance(value, dict) else {}


def s(value):
    """value if it is a string, else None (a safe dictionary key)."""
    return value if isinstance(value, str) else None


def truthy(value) -> bool:
    """JavaScript truthiness for JSON values: {} and [] are true, None, False, 0 and "" are false."""
    return value is not None and value is not False and value != 0 and value != ""


def num(value, fallback=None):
    """A finite JSON number (never a bool), else the fallback (the page's `num`)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return fallback
    return value if value == value and value not in (float("inf"), float("-inf")) else fallback


def mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def median(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def sig(value, digits: int = 9):
    """A float rounded to `digits` significant digits (None stays None); keeps the files small and stable."""
    if value is None:
        return None
    return float(f"{value:.{digits}g}")


# --------------------------------------------------------------------------- run facts

def validity(statuses: list, run: dict) -> str:
    """'withdrawn' | 'invalid' | 'valid' (core 957): the last status record wins (withdrawn, then invalid, then
    valid === true); with none, a harness mark `outcome.invalid` makes it invalid. `statuses` is sorted by `at`."""
    last = d(statuses[-1]) if statuses else None
    if last:
        if truthy(last.get("withdrawn")):
            return "withdrawn"
        if truthy(last.get("invalid")):
            return "invalid"
        if last.get("valid") is True:
            return "valid"
    return "invalid" if truthy(d(run.get("outcome")).get("invalid")) else "valid"


def invalid_reason(statuses: list, run: dict):
    """Why a run is invalid (core 967), from the last status record or the harness mark."""
    last = d(statuses[-1]) if statuses else {}
    inv = d(last.get("invalid") if truthy(last.get("invalid")) else d(run.get("outcome")).get("invalid"))
    return inv.get("reason") or inv.get("detail") or None


def outcome_of(run: dict) -> str:
    """finished | timed_out | error (core 702)."""
    o = d(run.get("outcome"))
    if truthy(o.get("timed_out")) or o.get("status") == "timeout":
        return "timed_out"
    return "finished" if o.get("status") == "completed" else "error"


def tps_of(run: dict):
    """Decode speed, output tokens per second, when recorded and positive (core 94)."""
    v = num(d(run.get("metrics")).get("output_tokens_per_s"))
    return v if v is not None and v > 0 else None


# --------------------------------------------------------------------------- suite lookup

class SuiteRules:
    """A catalog's task table and the harnesses each mode allows (core 1006-1020, 1090)."""

    def __init__(self, catalog: dict):
        tasks = [t for t in (catalog.get("tasks") or []) if isinstance(t, dict) and s(t.get("id"))]
        self.tasks = tasks
        self.by_id = {t["id"]: t for t in tasks}
        self.alias_of = {}
        for t in tasks:
            for alias in t.get("aliases") or []:
                if s(alias):
                    self.alias_of[alias] = t["id"]
        self.harness_modes = {h["id"]: h.get("modes") or [] for h in (catalog.get("harnesses") or [])
                              if isinstance(h, dict) and s(h.get("id"))}

    def task(self, ref):
        """The catalog task a run's task reference means: by id, else by an alias of the id or of task.alias."""
        ref = d(ref)
        tid, alias = s(ref.get("id")), s(ref.get("alias"))
        return (self.by_id.get(tid) or self.by_id.get(self.alias_of.get(tid))
                or self.by_id.get(self.alias_of.get(alias)))

    def harness_counts(self, harness, mode) -> bool:
        """A harness the catalog doesn't declare for the task's mode never counts."""
        return mode in self.harness_modes.get(s(harness) or "unknown", [])


def scoring_method(task: dict):
    sc = task.get("scoring")
    return sc.get("method") if isinstance(sc, dict) else sc


def classify(run: dict, valid: str, suite: SuiteRules):
    """(state, task) for one run in one suite, in the page's order (core 1093-1105): withdrawn, unknown task,
    retired, invalid, older task version, harness not allowed for the mode, then active -> counted, else provisional."""
    if valid == "withdrawn":
        return "withdrawn", None
    ref = d(run.get("task"))
    task = suite.task(ref)
    if task is None:
        return "unknown_task", None
    if task.get("status") == "retired":
        return "retired", task
    if valid == "invalid":
        return "invalid", task
    version = task.get("version")
    if version is not None and ref.get("version") != version:
        return "older", task
    if not suite.harness_counts(d(run.get("harness")).get("id"), task.get("mode")):
        return "harness", task
    return ("counted" if task.get("status") == "active" else "provisional"), task


def pick_score(scores: list, task: dict, state: str):
    """The score record a suite uses for a run (core 1107-1111). `scores` is the run's score records in a stable
    order. Preference: the record at the task's pinned rubric_version and scoring method; else any record at that
    rubric_version; else, for runs that don't count, the newest rubric_version. None when there is none."""
    rubric, method = task.get("rubric_version"), scoring_method(task)
    at_rubric = [r for r in scores if r.get("rubric_version") == rubric]
    rec = next((r for r in at_rubric if r.get("method") == method), None) or (at_rubric[0] if at_rubric else None)
    if rec is None and state != "counted" and scores:
        rec = sorted(scores, key=lambda r: -(num(r.get("rubric_version"), 0)))[0]
    return rec


def score_value(rec):
    """A record's numeric score, else None (a counted run without one is `unscored`)."""
    return num(d(rec).get("score")) if rec else None
