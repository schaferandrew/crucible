#!/usr/bin/env python3
"""What a `crucible run` will do: which tests, in what order, with which harness and timeout.

Shared by the command-line flags and the interactive wizard, so both build the same plan.
Chat tests always run with `direct`; agentic tests run with the chosen agent harness. The two
modes are never mixed in one score, so a plan lists them as separate groups.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from crucible import versioning, workspace
from crucible.taxonomy import AREAS, MODE_HARNESSES, MODE_LABELS, MODES, TIERS, mode_for

DEFAULT_AGENTIC_HARNESS = "opencode"
# Per-tier time limits when --timeout isn't given: forge tasks read a whole repo first
TIER_TIMEOUTS = {"spark": 300, "temper": 900, "forge": 1200}
# Safety switch: no test runs longer than this, so a runaway agent can't burn tokens for an hour.
# --allow-long lifts it for a deliberate long run.
MAX_TIMEOUT = 1200


@dataclass
class Step:
    task_id: str
    mode: str
    area: str
    tier: str
    harness: str
    timeout: int


@dataclass
class Plan:
    model: str
    steps: list[Step] = field(default_factory=list)
    reasoning: str = "default"   # one level for the whole run; each level is its own model
    skipped_done: list[str] = field(default_factory=list)

    def groups(self) -> list[tuple[str, list[Step]]]:
        return [(mode, [s for s in self.steps if s.mode == mode]) for mode in MODES
                if any(s.mode == mode for s in self.steps)]


def all_prompts() -> dict[str, dict]:
    return {t: workspace.load_task(t) for t in workspace.all_task_ids()}


def select(selectors: list[str], mode: str | None = None, area: str | None = None,
           tier: str | None = None, include_provisional: bool = True) -> list[str]:
    """Test IDs matching the selectors (test IDs, modes, areas, tiers or 'all'), narrowed by the filters.

    Selectors add up ("W2 G1"); filters narrow ("chat --tier spark"). No selector means all.
    """
    prompts = {t: p for t, p in all_prompts().items() if p.get("status") != "retired"}
    by_lower = {t.lower(): t for t in prompts}
    aliases = workspace.aliases()
    chosen: set[str] = set()
    for sel in selectors or ["all"]:
        key = sel.lower()
        if key == "all":
            chosen |= set(prompts)
        elif key in MODES:
            chosen |= {t for t, p in prompts.items() if mode_for(p) == key}
        elif key in TIERS:
            chosen |= {t for t, p in prompts.items() if p.get("tier") == key}
        elif any(key in areas for areas in AREAS.values()):
            chosen |= {t for t, p in prompts.items() if p.get("area") == key}
        elif key in by_lower:
            chosen.add(by_lower[key])
        elif aliases.get(key) in prompts:
            # Old IDs keep working; say once what the task is called now
            print(f"Note: {sel} is now {aliases[key]}")
            chosen.add(aliases[key])
        else:
            raise ValueError(f"'{sel}' isn't a task, mode ({', '.join(MODES)}), area or tier")
    keep = [t for t in chosen
            if (not mode or mode_for(prompts[t]) == mode)
            and (not area or prompts[t].get("area") == area)
            and (not tier or prompts[t].get("tier") == tier)
            and (include_provisional or prompts[t].get("status") != "provisional")]
    return sort_tasks(keep, prompts)


def sort_tasks(task_ids: list[str], prompts: dict[str, dict]) -> list[str]:
    """Chat before agentic, then by area menu order, tier (easiest first) and ID."""
    def key(t: str):
        p = prompts[t]
        mode = mode_for(p)
        areas = list(AREAS[mode])
        num = [int(n) if n.isdigit() else n for n in re.split(r"(\d+)", t)]
        return (MODES.index(mode), areas.index(p["area"]) if p.get("area") in areas else 99,
                TIERS.index(p.get("tier", "temper")), num)
    return sorted(task_ids, key=key)


def build(model: str, task_ids: list[str], harness: str | None = None, timeout: int | None = None,
          skip_done: bool = False, runs_dir: Path = Path("runs"), allow_long: bool = False,
          reasoning: str = "default") -> Plan:
    """A plan for these tests. `harness` is the agentic harness; chat tests always use direct."""
    prompts = all_prompts()
    plan = Plan(model=model, reasoning=reasoning)
    for t in task_ids:
        p = prompts[t]
        mode = mode_for(p)
        h = MODE_HARNESSES[mode][0] if mode == "chat" else (harness or DEFAULT_AGENTIC_HARNESS)
        if skip_done and has_current_run(runs_dir, model, t, p, h, reasoning):
            plan.skipped_done.append(t)
            continue
        limit = timeout or TIER_TIMEOUTS.get(p.get("tier"), 900)
        plan.steps.append(Step(t, mode, p.get("area"), p.get("tier"), h, limit if allow_long else min(limit, MAX_TIMEOUT)))
    return plan


model_slug = workspace.model_slug


def has_current_run(runs_dir: Path, model: str, task_id: str, prompt_def: dict, harness: str,
                    reasoning: str = "default") -> bool:
    """A valid run of this task's current version, by this model, harness and reasoning level, already exists."""
    from crucible import runrecord
    current = versioning.content_hash(prompt_def)
    for run_dir in sorted((runs_dir / model_slug(model, reasoning) / task_id).glob("*")):
        meta = runrecord.read(run_dir)
        if (meta and meta["task"].get("content_hash") == current and meta["harness"].get("id") == harness
                and meta["model"]["reasoning"].get("requested") == reasoning
                and not runrecord.invalid(run_dir, meta) and meta["outcome"].get("status") != "harness_error"):
            return True
    return False


def command_line(plan: Plan, selectors: list[str], mode: str | None, area: str | None, tier: str | None,
                 harness: str | None, timeout: int | None, skip_done: bool) -> str:
    """The one-line command that repeats this plan without the questions."""
    parts = ["crucible run", *selectors, f"--model {plan.model}"]
    parts += [f"--mode {mode}"] if mode else []
    parts += [f"--area {area}"] if area else []
    parts += [f"--tier {tier}"] if tier else []
    if harness and any(s.mode == "agentic" for s in plan.steps):
        parts.append(f"--agent {harness}")
    parts += [f"--timeout {timeout}"] if timeout else []
    parts += [f"--reasoning {plan.reasoning}"] if plan.reasoning != "default" else []
    parts += ["--skip-done"] if skip_done else []
    return " ".join(parts)


def reasoning_problem(plan: Plan) -> str | None:
    """Why this plan can't run at its reasoning level (a harness that can't set it), or None."""
    from crucible.agents import AGENTS
    stuck = sorted({s.harness for s in plan.steps if plan.reasoning not in AGENTS[s.harness].reasoning_levels})
    if not stuck:
        return None
    return (f"{', '.join(stuck)} can't set the reasoning level, so --reasoning {plan.reasoning} can't run its tests. "
            f"Use --agent pi for agentic tests, or leave reasoning at the model default.")


def describe(plan: Plan) -> list[str]:
    lines = [] if plan.reasoning == "default" else [f"Reasoning: {plan.reasoning}"]
    for mode, steps in plan.groups():
        harnesses = sorted({s.harness for s in steps})
        lines.append(f"{MODE_LABELS[mode]} ({', '.join(harnesses)}): {len(steps)} test{'' if len(steps) == 1 else 's'}")
        lines.append("  " + " ".join(s.task_id for s in steps))
    if plan.skipped_done:
        lines.append(f"Already run on the current version, skipped: {' '.join(plan.skipped_done)}")
    return lines
