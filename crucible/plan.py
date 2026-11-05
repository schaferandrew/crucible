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

from crucible import environment, runrecord, versioning, workspace
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
    weights_note: str | None = None   # why nothing was skipped when runs exist on other weights

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
          reasoning: str = "default", variant: dict | None = None) -> Plan:
    """A plan for these tests. `harness` is the agentic harness; chat tests always use direct."""
    prompts = all_prompts()
    plan = Plan(model=model, reasoning=reasoning)
    if skip_done and variant is None and (runs_dir / model_slug(model, reasoning)).is_dir():
        # One probe for the whole sweep, not one per test; no runs means nothing to skip
        variant = current_variant(model, reasoning)
    for t in task_ids:
        p = prompts[t]
        mode = mode_for(p)
        h = MODE_HARNESSES[mode][0] if mode == "chat" else (harness or DEFAULT_AGENTIC_HARNESS)
        if skip_done and has_current_run(runs_dir, model, t, p, h, reasoning, variant):
            plan.skipped_done.append(t)
            continue
        limit = timeout or TIER_TIMEOUTS.get(p.get("tier"), 900)
        plan.steps.append(Step(t, mode, p.get("area"), p.get("tier"), h, limit if allow_long else min(limit, MAX_TIMEOUT)))
    if skip_done and not plan.skipped_done and variant:
        plan.weights_note = weights_note(runs_dir, model, reasoning, variant)
    return plan


model_slug = workspace.model_slug


def current_variant(model: str, reasoning: str = "default") -> dict:
    """What the server says the current weights and reasoning level are, for `--skip-done`.

    Only the local server can tell: cloud models, an unreachable server, and servers that don't
    report these leave the fields None. `variants` lists every loaded instance that can serve the key,
    so one sibling's presence can't hide another's. When LM Studio says the key is unloaded, use the
    exact variant on its preferred LM-Link device if the inventory makes that unique; an ambiguous
    unloaded route is unknown and must not cause a run to be skipped.
    """
    inference = environment.inference(model, device=False)
    raw_variants = inference.get("variants")
    variants = [{"quant": runrecord.normalize_quant(w.get("quant")), "artifact": w.get("artifact"),
                 "bits": w.get("bits"), "device": w.get("device")}
                for w in raw_variants if w.get("quant")] if raw_variants is not None else []
    reasoning_level = (reasoning if reasoning != "default"
                       else environment.reasoning_resolved(model, "default")[0])
    if inference.get("state") == "not-loaded" and not variants:
        expected = inference.get("expected_variant")
        if expected:
            expected = {**expected, "quant": runrecord.normalize_quant(expected.get("quant")),
                        "publisher": (expected.get("publisher") or "").lower() or None}
        return {
            "quant": expected.get("quant") if expected else None,
            "variants": [],
            "publisher": expected.get("publisher") if expected else None,
            "reasoning": reasoning_level,
            "unloaded": True,
            "expected_variant": expected,
        }
    return {
        "quant": runrecord.normalize_quant(inference.get("quantization")),
        "variants": variants,
        "publisher": (inference.get("publisher") or "").lower() or None,
        "reasoning": reasoning_level,
    }


def _variant_matches(meta: dict, variant: dict) -> bool:
    """No field known on both the run and the server differs (see `current_variant`)."""
    model = meta.get("model") or {}
    stored_quant = runrecord.normalize_quant(model.get("quant"))
    # With more than one instance loaded for this key, the run counts when its own weights are among
    # them: the sibling being loaded elsewhere says nothing about whether these weights are loaded.
    loaded = {runrecord.normalize_quant(w.get("quant")) for w in variant.get("variants") or []}
    loaded.discard(None)
    if stored_quant and loaded:
        if stored_quant not in loaded:
            return False
        stored_publisher = (model.get("publisher") or "").lower() or None
        live_publisher = (variant.get("publisher") or "").lower() or None
        if stored_publisher and live_publisher and stored_publisher != live_publisher:
            return False
        return _reasoning_matches(model, variant)
    # For an unloaded LM Studio model, the API's advertised quant is only a default and may belong
    # to a different device. Match only the uniquely resolved next-load variant; unknown routing is
    # deliberately conservative so it cannot hide a run on the wrong sibling.
    if variant.get("unloaded"):
        expected = variant.get("expected_variant")
        if not expected:
            return False
        live_quant = runrecord.normalize_quant(expected.get("quant"))
        if stored_quant and live_quant and stored_quant != live_quant:
            return False
        stored_publisher = (model.get("publisher") or "").lower() or None
        live_publisher = (expected.get("publisher") or "").lower() or None
        if stored_publisher and live_publisher and stored_publisher != live_publisher:
            return False
        return _reasoning_matches(model, variant)
    live_quant = runrecord.normalize_quant(variant.get("quant"))
    if stored_quant and live_quant and stored_quant != live_quant:
        return False
    stored_publisher = (model.get("publisher") or "").lower() or None
    live_publisher = (variant.get("publisher") or "").lower() or None
    if stored_publisher and live_publisher and stored_publisher != live_publisher:
        return False
    return _reasoning_matches(model, variant)


def _reasoning_matches(model: dict, variant: dict) -> bool:
    stored_reasoning = (model.get("reasoning") or {}).get("resolved")
    return not (stored_reasoning and variant.get("reasoning") and stored_reasoning != variant["reasoning"])


def weights_note(runs_dir: Path, model: str, reasoning: str, variant: dict) -> str | None:
    """Why nothing was skipped: the runs this model already has are on weights it doesn't have loaded.

    `--skip-done` matching per run means a sibling variant being loaded elsewhere never hides these,
    so a key whose only loaded instance is another variant reads as "nothing has been run" without a
    word. This says which weights the runs are on and which are loaded, so the reason is visible.
    """
    if variant.get("unloaded"):
        expected = variant.get("expected_variant")
        if not expected:
            return ("Nothing skipped: LM Studio reports this model as unloaded, and its next-load "
                    "variant could not be resolved from the available device catalog.")
        target = runrecord.normalize_quant(expected.get("quant"))
        if not target:
            return ("Nothing skipped: the model is unloaded and its next-load weights are unknown.")
        stored = set()
        for run_dir in sorted((runs_dir / model_slug(model, reasoning)).glob("*/*")):
            meta = runrecord.read(run_dir)
            if not meta or runrecord.invalid(run_dir, meta) or meta["outcome"].get("status") == "harness_error":
                continue
            quant = runrecord.normalize_quant((meta.get("model") or {}).get("quant"))
            if quant and quant != target:
                stored.add(quant)
        if not stored:
            return None
        where = f" on {expected['device_name']}" if expected.get("device_name") else ""
        runs_on = ", ".join(sorted(stored))
        return (f"Nothing skipped: the runs here are on {runs_on}; the unloaded model will resolve to "
                f"{target}{where}.")

    loaded = {runrecord.normalize_quant(w.get("quant")) for w in variant.get("variants") or []}
    loaded.discard(None)
    stored: dict[str, str | None] = {}
    for run_dir in sorted((runs_dir / model_slug(model, reasoning)).glob("*/*")):
        meta = runrecord.read(run_dir)
        if not meta or runrecord.invalid(run_dir, meta) or meta["outcome"].get("status") == "harness_error":
            continue
        weights = meta.get("model") or {}
        quant = runrecord.normalize_quant(weights.get("quant"))
        if quant and quant not in loaded:
            stored[quant] = weights.get("artifact")
    if not stored:
        return None
    runs_on = ", ".join(q + (f" ({a})" if a else "") for q, a in sorted(stored.items()))
    server_has = ", ".join(w.get("quant", "?") + (f" ({w['artifact']})" if w.get("artifact") else "")
                           for w in variant.get("variants") or []) or "unknown weights"
    return (f"Nothing skipped: the runs here are on {runs_on}; the server has {server_has} loaded. "
            f"Load the runs' weights to skip them, or run these on the loaded ones.")


def has_current_run(runs_dir: Path, model: str, task_id: str, prompt_def: dict, harness: str,
                    reasoning: str = "default", variant: dict | None = None) -> bool:
    """A valid run of this task's current version, by this model, harness and reasoning level, on
    the same weights (quant and publisher) and effective reasoning level, when the server can tell,
    already exists."""
    current = versioning.content_hash(prompt_def)
    for run_dir in sorted((runs_dir / model_slug(model, reasoning) / task_id).glob("*")):
        meta = runrecord.read(run_dir)
        if (meta and meta["task"].get("content_hash") == current and meta["harness"].get("id") == harness
                and meta["model"]["reasoning"].get("requested") == reasoning
                and not runrecord.invalid(run_dir, meta) and meta["outcome"].get("status") != "harness_error"):
            if variant is None:
                variant = current_variant(model, reasoning)
            if _variant_matches(meta, variant):
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
        lines.append(f"Already run on the current version with these weights, skipped: {' '.join(plan.skipped_done)}")
    elif plan.weights_note:
        lines.append(plan.weights_note)
    return lines
