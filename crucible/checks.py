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


def _forbidden_patterns(check: dict, text: str) -> tuple[bool, str]:
    hits = []
    for pattern in check.get("patterns", []):
        hits += [m.group(0) for m in re.finditer(pattern, text, re.IGNORECASE)]
    if not text.strip():
        return False, "no answer to check"
    return (not hits), ("none found" if not hits else "found: " + ", ".join(sorted(set(h.lower() for h in hits))))


def _line_count(check: dict, text: str) -> tuple[bool, str]:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return len(lines) == check["lines"], f"{len(lines)} non-empty lines (want {check['lines']})"


def _non_empty(check: dict, text: str) -> tuple[bool, str]:
    words = len(text.split())
    want = check.get("min_words", 1)
    return words >= want, f"{words} words" + ("" if words >= want else f" (want at least {want})")


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
        return False, "no answer to check"
    allowed = _numbers(check["_source"]) | {str(n) for n in check.get("allow", [])}
    small = check.get("ignore_below", 11)
    invented = sorted(n for n in _numbers(text) - allowed if not (n.isdigit() and int(n) < small))
    return (not invented), ("every figure is in the sources" if not invented else "not in the sources: " + ", ".join(invented[:8]))


# A check returns (passed, detail), or (passed, detail, share) when it earns partial credit
CHECKS: dict[str, Callable[[dict, str], tuple]] = {
    "grade_closeness": evals.grade_closeness,
    "grounded_numbers": _grounded_numbers,
    "non_empty": _non_empty,
    "required_patterns": _required_patterns,
    "forbidden_patterns": _forbidden_patterns,
    "line_count": _line_count,
    "list_items": _list_items,
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
        passed, detail, *share = CHECKS[check["type"]]({**check, "_source": prompt_def.get("prompt", "")}, subject)
        results.append({"id": check["id"], "type": check["type"], "passed": passed, "detail": detail,
                        "rule": check.get("rule"), **({"share": share[0]} if share else {})})
    return results


def check_results(run_dir: Path, prompt_def: dict) -> list[dict]:
    return run_checks(prompt_def, final_answer(run_dir), run_dir) if prompt_def.get("checks") else []


# --------------------------------------------------------------------------
# Deterministic scoring: tests whose every rubric criterion is a check or hidden tests
# --------------------------------------------------------------------------

RESULTS_FILENAME = "check_results.json"


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


def _cap(prompt_def: dict, scores: dict[str, float]) -> float | None:
    """The lowest `cap_if_failed` among criteria that earned nothing (e.g. a modified contract suite)."""
    caps = [item["cap_if_failed"] for item in prompt_def.get("rubric", [])
            if "cap_if_failed" in item and not scores.get(item["criterion"])]
    return min(caps) if caps else None


def save_check_score(run_dir: Path, prompt_def: dict, results: list[dict], grader: dict | None = None) -> dict | None:
    """For a fully deterministic test, write check_results.json: a score no judge or human is needed for."""
    if not fully_checked(prompt_def):
        return None
    from crucible import versioning
    from crucible.graders import criterion_result
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
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
        "run_id": meta.get("run_id"),
        "test_id": meta.get("test_id"),
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
    (run_dir / RESULTS_FILENAME).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


# --------------------------------------------------------------------------
# Rules documentation
# --------------------------------------------------------------------------

def rules_markdown() -> str:
    """Every test's programmatic rules, for docs/checks.md."""
    from crucible import workspace
    out = ["# Programmatic checks", "",
           "Generated by `crucible checks --doc`; do not edit by hand. Each check runs on the model's final "
           "answer (its last reply, never tool output) after every run. A test whose rubric criteria are all "
           "checks is scored with no judge at all; elsewhere a check overrides the judge for its criterion.", ""]
    for test_id in workspace.all_test_ids():
        p = workspace.load_prompt(test_id)
        if not p.get("checks"):
            continue
        scoring = "fully deterministic" if fully_checked(p) else "checks plus judge"
        out += [f"## {test_id} ({p.get('tier')}, {scoring})", "", "| Check | Rule | Criterion (points) |", "|---|---|---|"]
        criteria = {item.get("check"): f"{item['criterion']} ({item['max_score']})" for item in p.get("rubric", [])}
        for check in p["checks"]:
            out.append(f"| `{check['id']}` | {check.get('rule', check['type'])} | {criteria.get(check['id'], 'not scored')} |")
        out.append("")
    return "\n".join(out)


def main() -> None:
    """`crucible checks`: re-run checks and hidden tests on existing runs (scoring fully deterministic tests), or write the rules doc."""
    import argparse
    from crucible import graders, workspace
    parser = argparse.ArgumentParser(prog="crucible checks", description=main.__doc__)
    parser.add_argument("--runs", type=Path, default=Path("runs"))
    parser.add_argument("--test", help="Only this test ID")
    parser.add_argument("--no-hidden", action="store_true", help="Skip the hidden tests (they take a while per run)")
    parser.add_argument("--doc", type=Path, metavar="PATH", help="Write the rules doc (e.g. docs/checks.md) and exit")
    args = parser.parse_args()
    if args.doc:
        args.doc.parent.mkdir(parents=True, exist_ok=True)
        args.doc.write_text(rules_markdown() + "\n", encoding="utf-8")
        print(f"Wrote {args.doc}")
        return
    counts = {"checked": 0, "graded": 0, "full": 0}
    for meta_path in sorted(args.runs.glob("*/*/*/*/meta.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        test_id = meta.get("test_id")
        if (args.test and test_id != args.test) or meta.get("invalid") or test_id not in workspace.all_test_ids():
            continue
        prompt_def = workspace.load_prompt(test_id)
        run_version = (meta.get("test") or {}).get("version")
        wants_grader = prompt_def.get("grader") and not args.no_hidden
        if not (prompt_def.get("checks") or wants_grader) or (run_version is not None and run_version != prompt_def.get("version")):
            continue
        run_dir = meta_path.parent
        results = check_results(run_dir, prompt_def)
        if results:
            meta["checks"] = results
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            counts["checked"] += 1
        grader = None
        if wants_grader:
            print(f"  hidden tests: {meta.get('run_id')}")
            grader = graders.run(run_dir, prompt_def)
            counts["graded"] += bool(grader)
        record = save_check_score(run_dir, prompt_def, results, grader)
        counts["full"] += bool(record and record["passed"])
    print(f"Checked {counts['checked']} runs, ran hidden tests on {counts['graded']}; {counts['full']} earned full marks.")
