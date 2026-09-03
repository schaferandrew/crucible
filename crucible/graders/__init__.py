#!/usr/bin/env python3
"""Deterministic, code-driven auto-graders for benchmark scores.

Graders are **declared in the prompt YAML itself** via an ``auto_grader``
section, so adding a new test only requires adding a prompt file (+ optionally
a small Python module for complex logic).  There is no central monolith —
each test carries its own grading rules.

YAML schema for ``auto_grader``
-------------------------------
Simple checks (declarative, no Python needed):

.. code-block:: yaml

   auto_grader:
     - type: regex
       pattern: '\\bred\\b'
       flags: [IGNORECASE]
       criterion: "Correct answer"
       max_score: 10
     - type: all_of
       criterion: "Correct answer"
       max_score: 4
       rules:
         - {type: regex, pattern: '\\bdave\\b', flags: [IGNORECASE]}
         - {type: regex, pattern: 'chair\\s*3|3rd\\s*chair|third', flags: [IGNORECASE]}

Complex checks (Python module):

.. code-block:: yaml

   auto_grader:
     type: module
     module: "crucible.graders.g2_calendar"

Module contract
---------------
A grader module must expose ``grade(prompt_def, run_dir, model_output) ->
dict[str, float]`` returning ``{criterion: score}`` for criteria it can verify.

Public API
----------
has_grader(test_id) -> bool
get_grader(test_id) -> Callable[[dict, Path, str], dict[str, float]] | None
get_model_output(run_dir) -> str
"""
from __future__ import annotations

import importlib
import re

from crucible.graders.helpers import (
    FIXTURES_DIR,
    PROMPTS_DIR,
    REPO_ROOT,
    RUNS_DIR,
    _extract_json_block,
    _extract_json_objects,
    get_model_output,
    load_prompt,
)


# --------------------------------------------------------------------------
# Declarative rule engine
# --------------------------------------------------------------------------

def _flags_from_list(flag_names: list[str]) -> int:
    """Convert YAML flag names like ['IGNORECASE'] to re.RegexFlag."""
    flags = 0
    for name in flag_names:
        flags |= getattr(re, name.upper(), 0)
    return flags


def _evaluate_rule(rule: dict, run_dir, model_output: str) -> bool:
    """Evaluate a single declarative rule. Returns True/False."""
    rule_type = rule.get("type", "regex")

    if rule_type in ("regex", "contains"):
        pattern = rule.get("pattern", "")
        text = model_output
        field = rule.get("field", "model_output")
        if field == "model_output":
            text = model_output
        elif field == "run_name":
            text = run_dir.name
        flags = _flags_from_list(rule.get("flags", ["IGNORECASE"]))
        if rule_type == "regex":
            return bool(re.search(pattern, text, flags))
        return pattern.lower() in text.lower()

    if rule_type == "all_of":
        return all(_evaluate_rule(r, run_dir, model_output) for r in rule.get("rules", []))

    if rule_type == "any_of":
        return any(_evaluate_rule(r, run_dir, model_output) for r in rule.get("rules", []))

    if rule_type == "not":
        sub = rule.get("rules", [])
        return not _evaluate_rule(sub[0], run_dir, model_output) if len(sub) == 1 else True

    if rule_type == "file_exists":
        target = run_dir / rule.get("path", "")
        return target.exists()

    if rule_type == "json_contains":
        json_obj = _extract_json_block(model_output)
        if json_obj is None:
            return False
        text = json.dumps(json_obj, default=str)
        return rule.get("contains", "").lower() in text.lower()

    return False


def _run_declarative_rules(rules: list[dict], prompt_def: dict,
                           run_dir, model_output: str) -> dict[str, float]:
    """Evaluate declarative rules from the YAML auto_grader section."""
    rubric = {item["criterion"]: item["max_score"]
              for item in prompt_def.get("rubric", [])}
    scores: dict[str, float] = {}

    for rule in rules:
        criterion = rule.get("criterion")
        if not criterion:
            continue
        max_score = rule.get("max_score", rubric.get(criterion, 0))
        pass_score = rule.get("pass_score", max_score)
        fail_score = rule.get("fail_score", 0.0)

        passed = _evaluate_rule(rule, run_dir, model_output)

        if passed:
            current = scores.get(criterion, 0.0)
            if pass_score > current:
                scores[criterion] = float(pass_score)
        else:
            if criterion not in scores:
                scores[criterion] = float(fail_score)

    return scores


# --------------------------------------------------------------------------
# Graders registry — discovers graders from prompt YAML's auto_grader section
# --------------------------------------------------------------------------

GRADERS: dict[str, callable] = {}  # populated below + lazily for declarative


def _has_grader_config(prompt_def: dict) -> bool:
    """Check if the prompt YAML has an auto_grader section."""
    return prompt_def.get("auto_grader") is not None


def _build_declarative_grader(rules: list[dict]):
    """Return a callable that evaluates *rules* against model output."""
    def _grade(prompt_def, run_dir, model_output):
        return _run_declarative_rules(rules, prompt_def, run_dir, model_output)
    return _grade


def _build_module_grader(module_path: str):
    """Import a grader module and return its grade() function."""
    module = importlib.import_module(module_path)
    return module.grade


def _build_grader(test_id: str) -> callable | None:
    """Load the YAML for *test_id* and build its grader from auto_grader section."""
    try:
        prompt = load_prompt(test_id)
    except (FileNotFoundError, KeyError):
        return None

    config = prompt.get("auto_grader")
    if config is None:
        return None

    if isinstance(config, list):
        return _build_declarative_grader(config)
    elif isinstance(config, dict) and config.get("type") == "module":
        return _build_module_grader(config["module"])

    return None


def has_grader(test_id: str) -> bool:
    """Check whether a deterministic grader exists for this test."""
    if test_id in GRADERS:
        return True
    return _build_grader(test_id) is not None  # will register via get_grader


def get_grader(test_id: str) -> callable | None:
    """Return the deterministic grader function for a test, or None.

    Graders are discovered from the prompt YAML's ``auto_grader`` section:
    - List of rules → declarative grader built on the fly.
    - ``{type: module, module: "..."}`` → Python module imported.
    """
    if test_id in GRADERS:
        return GRADERS[test_id]
    grader = _build_grader(test_id)
    if grader is not None:
        GRADERS[test_id] = grader
    return grader


# --------------------------------------------------------------------------
# Eagerly register module-based graders (complex tests with Python modules)
# --------------------------------------------------------------------------

# G2 — calendar scheduling
from crucible.graders.g2_calendar import grade as grade_g2
GRADERS["G2"] = grade_g2

# C1 / C1b — compound interest calculator
from crucible.graders.c1_compound import grade as grade_c1
GRADERS["C1"] = grade_c1
GRADERS["C1b"] = grade_c1  # C1b uses the same grader as C1

# E6 — weather research
from crucible.graders.e6_research import grade as grade_e6
GRADERS["E6"] = grade_e6


# --------------------------------------------------------------------------
# Backward-compat named functions
# --------------------------------------------------------------------------

def grade_e5(prompt_def, run_dir, model_output) -> dict[str, float]:
    """E5: Firetruck color — delegates to YAML declarative rules."""
    grader = get_grader("E5")
    if grader is None:
        return _grade_e5_fallback(prompt_def, model_output)
    return grader(prompt_def, run_dir, model_output)


def grade_g1(prompt_def, run_dir, model_output) -> dict[str, float]:
    """G1: Logic puzzle — delegates to YAML declarative rules."""
    grader = get_grader("G1")
    if grader is None:
        return _grade_g1_fallback(prompt_def, model_output)
    return grader(prompt_def, run_dir, model_output)


# C1b is an alias for C1 (same grader module)
grade_c1b = grade_c1


# --------------------------------------------------------------------------
# Fallback implementations (used only if YAML auto_grader section is missing)
# --------------------------------------------------------------------------

def _grade_e5_fallback(prompt_def, model_output: str) -> dict[str, float]:
    """Fallback: regex check for 'red' in firetruck color answer."""
    rubric = {item["criterion"]: item["max_score"]
              for item in prompt_def.get("rubric", [])}
    max_score = rubric.get("Correct answer", 10)
    if re.search(r'\bred\b', model_output, re.IGNORECASE):
        return {"Correct answer": float(max_score)}
    return {"Correct answer": 0.0}


def _grade_g1_fallback(prompt_def, model_output: str) -> dict[str, float]:
    """Fallback: G1 logic puzzle answer + ambiguity check."""
    scores = {}
    rubric = {item["criterion"]: item["max_score"]
              for item in prompt_def.get("rubric", [])}
    max_answer = rubric.get("Correct answer", 4)
    max_ambiguity = rubric.get("Handles ambiguity", 2)
    max_clear = rubric.get("Final answer clearly stated", 1)

    out_lower = model_output.lower()
    has_dave = "dave" in out_lower
    has_chair3 = bool(re.search(r'chair\s*3|3rd\s*chair|third', out_lower))
    if has_dave and has_chair3:
        scores["Correct answer"] = float(max_answer)
    else:
        scores["Correct answer"] = 0.0

    if re.search(r'\b(assumption|ambiguit|could be|may |possibly|without loss of|clarif)', out_lower):
        scores["Handles ambiguity"] = float(max_ambiguity)
    else:
        scores["Handles ambiguity"] = 0.0

    if re.search(r'chair\s*3.*dave|dave.*chair\s*3|chair 3 is dave', out_lower):
        scores["Final answer clearly stated"] = float(max_clear)
    elif has_dave and has_chair3:
        scores["Final answer clearly stated"] = float(max_clear)
    else:
        scores["Final answer clearly stated"] = 0.0

    return scores
