"""`crucible site-data`: turn a published bundle into the static JSON files the dashboard loads.

Layer 2 of the dashboard rewrite: this resolves identity (registry) and run state (the page's rules), and never
scores. The output format is documented in docs/site-data-format.md and checked by crucible/schemas/site-data/.
"""
from __future__ import annotations

import itertools
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from crucible import registry as registry_mod
from crucible.sitedata import guard, rules
from crucible.sitedata.catalog import build_catalog, slim_task, suite_label, suite_sort_key
from crucible.sitedata.reader import read_bundle, suite_id
from crucible.sitedata.rules import d, mean, median, num, s, sig

SITE_DATA_FORMAT = 1
MAX_SUBSET_TIERS = 5
OTHER_STATES = ("older", "harness", "invalid", "retired", "unknown_task", "withdrawn")
UNRECORDED = registry_mod.UNRECORDED


# --------------------------------------------------------------------------- small helpers

def dump(path: Path, obj) -> int:
    """Write minified, key-sorted JSON; returns the bytes written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    path.write_bytes(data)
    return len(data)


def file_key(text: str) -> str:
    """A file name for an ID: '/' becomes '__' and anything unsafe '_'."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(text).replace("/", "__"))


def load_yaml(path) -> dict:
    if not path:
        return {}
    import yaml
    try:
        return d(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, yaml.YAMLError):
        return {}


def crucible_version() -> str:
    from crucible.cli import _get_version
    return _get_version()


def safe_resolve(reg, run: dict):
    """The registry's resolution of a run; a record too broken to resolve gets an `unknown` one, never an error."""
    try:
        return reg.resolve_run(run)
    except Exception as exc:  # noqa: BLE001 - a bad record must not stop the build
        return registry_mod.Resolution(
            run_uuid=s(run.get("run_uuid")), model_id="unknown/" + UNRECORDED, maker=None, packager=None, format=None,
            quant=None, where=None, provider=None, machine=None, hardware_key=None, reasoning_level="default",
            harness=None, sources={"model_from": "unknown"}, notes=[f"the record could not be resolved: {exc}"])


def machine_label(reg, res):
    """The registry label of the machine that served a local run (display only: never an ID, filter or grouping key).
    A format-4 run credits its own `hardware.nickname`; an older run, the registry machine its host resolved to.
    None otherwise; raw host names are never emitted."""
    if res.machine:
        return (reg.machines.get(res.machine) or {}).get("label")
    return res.nickname


def safe_cost(reg, run: dict, res):
    try:
        return sig(reg.energy_cost(run, res))
    except Exception:  # noqa: BLE001
        return None


def unrecorded_fields(res) -> list:
    """The setup fields a run left unrecorded (what makes its setup id contain `unrecorded`)."""
    out = []
    if res.model_id.startswith("unknown/"):
        out.append("model")
    if not res.harness:
        out.append("harness")
    if not res.where:
        out.append("where")
    if res.where == "cloud":
        if not res.provider:
            out.append("provider")
    else:
        out += [name for name, v in (("packager", res.packager), ("format", res.format), ("quant", res.quant),
                                     ("hw", res.hardware_key)) if not v]
    return out


HW_FILLED = re.compile(r"^hardware key not recorded; read as (\S+) from machine .+$")
HW_DIFFERS = re.compile(r"^recorded hardware (\S+) differs from .+'s (\S+)$")


def public_notes(notes: list) -> list:
    """The resolver's notes without machine names: hardware class is the only public machine identity."""
    out = []
    for note in notes:
        m = HW_FILLED.match(note)
        if m:
            out.append(f"hardware key not recorded; filled in from the registry as {m.group(1)}")
        elif HW_DIFFERS.match(note):
            m = HW_DIFFERS.match(note)
            out.append(f"recorded hardware {m.group(1)} differs from the registry's {m.group(2)}")
        elif "machine" not in note.lower():
            out.append(note)
    return out


def resolution_json(res) -> dict:
    sources = {k: v for k, v in res.sources.items() if k != "machine_from"}
    return {
        "model": res.model_id, "maker": res.maker, "packager": res.packager, "format": res.format, "quant": res.quant,
        "where": res.where, "provider": res.provider, "hardware_key": res.hardware_key,
        "reasoning": res.reasoning_level, "harness": res.harness, "artifact": res.artifact_id, "variant": res.variant_id,
        "deployment": res.deployment_id, "setup": res.setup_id, "unrecorded": unrecorded_fields(res),
        "sources": sources, "notes": public_notes(res.notes)}


def run_summary(run: dict) -> dict:
    """The fields of a run record worth showing on the run page (the rest is dead weight or in the registry)."""
    m, e, hw, o, prov = d(run.get("model")), d(run.get("endpoint")), d(run.get("hardware")), d(run.get("outcome")), d(run.get("provenance"))
    t, h = d(run.get("task")), d(run.get("harness"))
    return {
        "format_version": run.get("format_version"), "started_at": run.get("started_at"), "ended_at": run.get("ended_at"),
        "elapsed_s": num(run.get("elapsed_s")), "legacy_run_id": run.get("legacy_run_id"),
        "task": {k: t.get(k) for k in ("id", "version", "rubric_version", "alias", "content_hash", "rubric_hash")},
        "harness": {"id": h.get("id"), "version": h.get("version")},
        "model": {"id": m.get("id"), "base": m.get("base"), "raw_base": m.get("raw_base"), "maker": m.get("maker"),
                  "packager": m.get("packager") or m.get("publisher"), "format": m.get("format"),
                  "format_source": m.get("format_source"), "quant": m.get("quant"), "reasoning": d(m.get("reasoning")),
                  "context_loaded": m.get("context_loaded")},
        "endpoint": {k: e.get(k) for k in ("where", "provider", "served_via", "upstream", "resolved_model")},
        "hardware": {"key": hw.get("key"),
                     **{k: hw[k] for k in ("chip", "memory_gb", "accelerators", "served_remotely") if k in hw}},
        "outcome": {k: o.get(k) for k in ("status", "harness_status", "returncode", "timed_out", "invalid")},
        "metrics": d(run.get("metrics")),
        "provenance": {k: prov.get(k) for k in ("crucible_version", "crucible_commit", "source", "content_hash")},
    }


# --------------------------------------------------------------------------- per-suite computation

class Info:
    """One run as one suite sees it."""
    __slots__ = ("uuid", "setup", "task", "task_ref", "tier", "state", "score", "rec", "outcome", "elapsed", "tps", "cost",
                 "started", "tools", "model", "machine")


def block(infos: list):
    """A cell's aggregate over the runs in one state (docs/site-data-format.md: Cell block)."""
    if not infos:
        return None
    scored = [i for i in infos if i.score is not None]
    finished = [i for i in scored if i.outcome == "finished"]
    scores = [i.score for i in scored]
    return {
        "n": len(infos), "n_scored": len(scored), "mean": sig(mean(scores)),
        "min": min(scores) if scores else None, "max": max(scores) if scores else None,
        "n_finished": len(finished), "mean_finished": sig(mean([i.score for i in finished])),
        "timeouts": sum(1 for i in infos if i.outcome == "timed_out"), "errors": sum(1 for i in infos if i.outcome == "error")}


def run_stats(infos: list) -> dict:
    """time (median elapsed_s), tps (median, n), cost (mean) over a setup's counted runs (core 1740-1770)."""
    tps = [i.tps for i in infos if i.tps is not None]
    return {"runs": len(infos), "time": sig(median([i.elapsed for i in infos])),
            "tps": {"median": sig(median(tps)), "n": len(tps)}, "cost": sig(mean([i.cost for i in infos]))}


def tier_subsets(tier_ids: list) -> list:
    """Every non-empty subset of the tiers, all tiers first, each as a list in suite order."""
    n = len(tier_ids)
    masks = sorted(range(1, 2 ** n), key=lambda m: (-bin(m).count("1"), -m))
    return [[t for i, t in enumerate(tier_ids) if m >> i & 1] for m in masks]


def stats_key(subset: list, provisional: bool) -> str:
    return "+".join(subset) + (":p1" if provisional else ":p0")


def setup_stats(infos_by_setup: dict, tier_ids: list) -> dict:
    """Per setup, time/tps/cost for every included-tier subset x provisional on/off, deduplicated: each setup
    lists its distinct stats objects and, per key, the index of the one that applies."""
    scored = {sid: [i for i in infos if i.score is not None and i.state in ("counted", "provisional")]
              for sid, infos in infos_by_setup.items()}
    if len(tier_ids) > MAX_SUBSET_TIERS:
        by_setup = {}
        for sid, infos in sorted(scored.items()):
            cells = {}
            for i in infos:
                cells.setdefault(i.task, {}).setdefault(i.state, []).append([i.elapsed, i.tps, i.cost])
            by_setup[sid] = cells
        return {"format": "cells", "tiers": tier_ids, "by_setup": by_setup}
    subsets = tier_subsets(tier_ids)
    keys = [(stats_key(sub, p), sub, p) for p in (False, True) for sub in subsets]
    by_setup = {}
    for sid, infos in sorted(scored.items()):
        distinct, index, where = [], [], {}
        for _key, sub, p in keys:
            chosen = [i for i in infos if i.tier in sub and (i.state == "counted" or p)]
            if not chosen:
                index.append(-1)
                continue
            st = run_stats(chosen)
            sk = json.dumps(st, sort_keys=True)
            if sk not in where:
                where[sk] = len(distinct)
                distinct.append(st)
            index.append(where[sk])
        by_setup[sid] = {"stats": distinct, "index": index}
    return {"format": "subsets", "tiers": tier_ids, "keys": [k for k, _, _ in keys], "by_setup": by_setup}


def build_suite(sid, catalog, resolved, rules_for, facts, bundle, reg) -> dict:
    """Everything one suite decides: per-run infos, cells, counts, other, entities."""
    suite = rules.SuiteRules(catalog)
    tier_ids = [t["id"] for t in resolved["tiers"]]
    infos, cells, other, counts = {}, {}, {}, {k: 0 for k in rules.STATES}
    counts.update({"runs": 0, "unscored": 0, "counted_scored": 0})
    for uuid in sorted(bundle.runs):
        f = facts[uuid]
        state, task = rules.classify(f["run"], f["valid"], suite)
        rec = rules.pick_score(bundle.scores.get(uuid, []), task, state) if task else None
        info = Info()
        info.uuid, info.setup, info.state, info.rec = uuid, f["res"].setup_id, state, rec
        info.task = task["id"] if task else None
        info.task_ref = s(d(f["run"].get("task")).get("id")) or s(d(f["run"].get("task")).get("alias"))
        info.tier = task.get("tier") if task else None
        info.score = rules.score_value(rec)
        info.outcome, info.elapsed, info.tps, info.cost = f["outcome"], f["elapsed"], f["tps"], f["cost"]
        info.started, info.tools, info.model = f["started"], f["tools"], f["res"].model_id
        info.machine = f["machine"]
        infos[uuid] = info
        counts["runs"] += 1
        counts[state] += 1
        if state == "counted" and info.score is None:
            counts["unscored"] += 1
            other.setdefault(info.model, {}).setdefault("unscored", 0)
            other[info.model]["unscored"] += 1
        elif state == "counted":
            counts["counted_scored"] += 1
        if state in OTHER_STATES:
            other.setdefault(info.model, {}).setdefault(state, 0)
            other[info.model][state] += 1
        if state in ("counted", "provisional", "older", "harness", "invalid"):
            cell = cells.setdefault((info.setup, info.task), {"runs": 0, "counted": [], "provisional": [], "mode": task.get("mode")})
            cell["runs"] += 1
            if state in ("counted", "provisional"):
                cell[state].append(info)
    cell_list = []
    for (setup, task), c in sorted(cells.items()):
        row = {"setup": setup, "task": task, "runs": c["runs"]}
        for name in ("counted", "provisional"):
            b = block(c[name])
            if b:
                row[name] = b
        cell_list.append(row)
    by_setup = {}
    modes = {}
    for (setup, task), c in cells.items():
        modes.setdefault(setup, set()).add(c["mode"])
    for info in infos.values():
        if (info.setup, info.task) in cells and info.state in ("counted", "provisional"):
            by_setup.setdefault(info.setup, []).append(info)
    for setup in modes:
        by_setup.setdefault(setup, [])
    return {"infos": infos, "cells": cell_list, "other": other, "counts": counts, "modes": modes,
            "stats": setup_stats(by_setup, tier_ids)}


def slim_run(info: Info, with_task: bool = False) -> dict:
    out = {"run_uuid": info.uuid, "setup": info.setup, "state": info.state, "score": info.score, "outcome": info.outcome,
           "elapsed_s": info.elapsed, "tps": sig(info.tps), "cost": info.cost, "started_at": info.started, "tool_calls": info.tools,
           "machine": info.machine}
    if with_task:
        out["task"] = info.task or info.task_ref
    return out


def slim_sort(items: list) -> list:
    return sorted(items, key=lambda r: (str(r["started_at"] or ""), r["run_uuid"]), reverse=True)


# --------------------------------------------------------------------------- entities

def entities_for(setups: dict, models_other: set, modes: dict, runs_per_setup: dict, credit: dict, reg) -> dict:
    """Entity tables for the setups in a suite. `setups` maps setup id -> a Resolution of one of its runs."""
    makers, models, artifacts, variants, deployments, out_setups = {}, {}, {}, {}, {}, {}

    def add_model(model_id, maker):
        if model_id in models:
            return
        entry = reg.models.get(model_id)
        maker = (entry or {}).get("maker") or maker or "unknown"
        models[model_id] = {"id": model_id, "label": (entry or {}).get("label") or model_id.split("/", 1)[-1], "maker": maker,
                            "family": (entry or {}).get("family"), "params": (entry or {}).get("params"),
                            "active_params": (entry or {}).get("active_params"), "known": bool(entry)}
        if maker not in makers:
            m = reg.makers.get(maker) or {}
            makers[maker] = {"id": maker, "label": m.get("label") or ("Unknown" if maker == "unknown" else maker),
                             "url": m.get("url")}

    for sid, res in sorted(setups.items()):
        add_model(res.model_id, res.maker)
        maker = models[res.model_id]["maker"] if res.maker is None else res.maker
        if maker not in makers:
            makers[maker] = {"id": maker, "label": (reg.makers.get(maker) or {}).get("label") or maker,
                             "url": (reg.makers.get(maker) or {}).get("url")}
        artifacts.setdefault(res.artifact_id, {"id": res.artifact_id, "model": res.model_id, "packager": res.packager,
                                               "format": res.format, "quant": res.quant, "api": res.where == "cloud"})
        variants.setdefault(res.variant_id, {"id": res.variant_id, "artifact": res.artifact_id, "reasoning": res.reasoning_level,
                                             "harness": res.harness})
        hw = reg.hardware.get(res.hardware_key) or {}
        credited = [{"label": k, "runs": n} for k, n in sorted(credit.get(res.deployment_id, {}).items())]
        names = ", ".join(c["label"] for c in credited)
        deployments.setdefault(res.deployment_id, {
            "id": res.deployment_id, "where": res.where, "provider": res.provider if res.where == "cloud" else None,
            "hw": res.hardware_key if res.where != "cloud" else None, "hw_label": hw.get("label"),
            "label": (hw.get("label") or res.hardware_key or res.provider or UNRECORDED) + (f" ({names})" if names else ""),
            "machines": credited, "watts": hw.get("watts") if res.where != "cloud" else None})
        cloud = res.where == "cloud"
        packager = reg.packagers.get(res.packager) or {}
        out_setups[sid] = {
            "id": sid, "variant": res.variant_id, "artifact": res.artifact_id, "deployment": res.deployment_id,
            "model": res.model_id, "maker": maker,
            "packager": res.packager or (None if cloud else UNRECORDED), "format": res.format or (None if cloud else UNRECORDED),
            "quant": None if cloud else (res.quant or UNRECORDED), "reasoning": res.reasoning_level,
            "harness": res.harness or UNRECORDED, "where": res.where or UNRECORDED,
            "hw": None if cloud else (res.hardware_key or UNRECORDED), "provider": (res.provider or UNRECORDED) if cloud else None,
            "modes": sorted(modes.get(sid, [])), "runs": runs_per_setup.get(sid, 0),
            "labels": {"model": models[res.model_id]["label"], "maker": makers[maker]["label"],
                       "packager": packager.get("label") or res.packager, "hw": hw.get("label") or res.hardware_key,
                       "machines": [c["label"] for c in credited], "provider": res.provider if cloud else None},
            "unrecorded": unrecorded_fields(res)}
    for model_id in sorted(models_other):
        add_model(model_id, None)
    return {"makers": makers, "models": models, "artifacts": artifacts, "variants": variants,
            "deployments": deployments, "setups": out_setups}


# --------------------------------------------------------------------------- the build

def built_at_value(explicit, latest: str) -> str:
    if explicit:
        return explicit
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch and epoch.isdigit():
        return datetime.fromtimestamp(int(epoch), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (latest or "1970-01-01T00:00:00") + "Z"


def clean(out: Path) -> None:
    """Remove what an earlier build wrote here (never anything else)."""
    meta = out / "meta.json"
    if not meta.exists():
        return
    try:
        old = json.loads(meta.read_text(encoding="utf-8"))
    except ValueError:
        return
    if not isinstance(old, dict) or "site_data_format" not in old:
        return
    for name in [x.get("id") for x in old.get("suites") or [] if isinstance(x, dict)] + ["runs", "recent", "outputs"]:
        if isinstance(name, str) and (out / name).is_dir():
            shutil.rmtree(out / name)
    meta.unlink()


def build(bundle_dir, outputs_dir, out_dir, display=None, fallbacks=None, built_at=None, reg=None) -> dict:
    """Write the site data; returns {'sizes': {relative path: bytes}, 'counts': {suite: counts}, ...}."""
    bundle_dir, out = Path(bundle_dir), Path(out_dir)
    bundle = read_bundle(bundle_dir)
    if reg is None:
        reg = registry_mod.load(bundle_dir) if (bundle_dir / "registry").is_dir() else registry_mod.load()
    display, fb = load_yaml(display), load_yaml(fallbacks)
    hidden = [str(x) for x in display.get("hidden_suites") or []]
    cats = sorted(bundle.catalogs.values(), key=suite_sort_key)
    visible = [c for c in cats if suite_id(c) not in hidden] or cats
    clean(out)
    sizes = {}

    # facts per run, computed once
    facts = {}
    for uuid, run in bundle.runs.items():
        res = safe_resolve(reg, run)
        st = bundle.status.get(uuid, [])
        facts[uuid] = {
            "run": run, "res": res, "valid": rules.validity(st, run), "reason": rules.invalid_reason(st, run),
            "outcome": rules.outcome_of(run), "elapsed": num(run.get("elapsed_s")), "tps": rules.tps_of(run),
            "machine": machine_label(reg, res), "cost": safe_cost(reg, run, res), "started": run.get("started_at") if isinstance(run.get("started_at"), str) else None,
            "tools": num(d(run.get("metrics")).get("tool_calls"))}

    suites_meta, per_suite, counts_by_suite = [], {}, {}
    for cat in visible:
        sid = suite_id(cat)
        resolved = build_catalog(cat, fb, suite_label(sid))
        result = build_suite(sid, cat, resolved, None, facts, bundle, reg)
        per_suite[sid] = (cat, resolved, result)
        counts_by_suite[sid] = result["counts"]
        su = resolved["suite"]
        suites_meta.append({"id": sid, "version": su["version"], "label": su["name"], "status": su["status"], "cut_at": su["cut_at"]})

    for sid, (cat, resolved, result) in per_suite.items():
        infos = result["infos"]
        setup_res, per_setup_runs, credit = {}, {}, {}
        cell_setups = {c["setup"] for c in result["cells"]}
        for uuid in sorted(infos):
            info = infos[uuid]
            if info.setup in cell_setups and info.state in ("counted", "provisional", "older", "harness", "invalid"):
                setup_res.setdefault(info.setup, facts[uuid]["res"])
                per_setup_runs[info.setup] = per_setup_runs.get(info.setup, 0) + 1
                if facts[uuid]["machine"]:
                    by = credit.setdefault(facts[uuid]["res"].deployment_id, {})
                    by[facts[uuid]["machine"]] = by.get(facts[uuid]["machine"], 0) + 1
        entities = entities_for(setup_res, set(result["other"]), result["modes"], per_setup_runs, credit, reg)
        index = {"suite": sid, "counts": result["counts"], "catalog": resolved, "entities": entities, "cells": result["cells"],
                 "setup_stats": result["stats"], "other": result["other"]}
        sizes[f"{sid}/index.json"] = dump(out / sid / "index.json", index)

        by_task, by_model = {}, {}
        for info in infos.values():
            if info.task:
                by_task.setdefault(info.task, []).append(slim_run(info))
            by_model.setdefault(info.model, []).append(slim_run(info, True))
        full_tasks = {t["id"]: t for t in cat.get("tasks") or [] if isinstance(t, dict) and s(t.get("id"))}
        for tid, task in sorted(full_tasks.items()):
            body = dict(slim_task(task), **{k: task.get(k) for k in ("prompt", "rules", "criteria", "summary")})
            sizes[f"{sid}/tasks/{file_key(tid)}.json"] = dump(out / sid / "tasks" / f"{file_key(tid)}.json",
                                                              {"suite": sid, "task": body, "runs": slim_sort(by_task.get(tid, []))})
        for model, runs in sorted(by_model.items()):
            sizes[f"{sid}/models/{file_key(model)}.json"] = dump(out / sid / "models" / f"{file_key(model)}.json",
                                                                 {"suite": sid, "model": model, "runs": slim_sort(runs)})

    # runs and recent
    recent = {}
    for uuid in sorted(bundle.runs):
        f = facts[uuid]
        run, res = f["run"], f["res"]
        states = {}
        for sid, (_cat, _resolved, result) in per_suite.items():
            i = result["infos"][uuid]
            states[sid] = {"state": i.state, "task": i.task, "score": i.score,
                           "score_ref": {"rubric_version": i.rec.get("rubric_version"), "method": i.rec.get("method")} if i.rec else None}
        out_name = Path(str(run.get("output_ref") or f"outputs/{uuid}.txt")).name
        src = Path(outputs_dir) / out_name if outputs_dir else None
        output = None
        if src and src.is_file():
            (out / "outputs").mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, out / "outputs" / f"{uuid}.txt")
            output = f"outputs/{uuid}.txt"
        body = {"run_uuid": uuid, "summary": run_summary(run), "resolution": dict(resolution_json(res), machine=f["machine"]), "setup": res.setup_id,
                "validity": {"state": f["valid"], "reason": f["reason"]}, "suites": states, "cost": f["cost"],
                "outcome": f["outcome"], "scores": bundle.scores.get(uuid, []), "status": bundle.status.get(uuid, []),
                "output": output}
        sizes[f"runs/{uuid}.json"] = dump(out / "runs" / f"{uuid}.json", body)
        month = str(f["started"] or "")[:7]
        month = month if re.match(r"^\d{4}-\d{2}$", month) else "unknown"
        recent.setdefault(month, []).append({
            "run_uuid": uuid, "started_at": f["started"], "setup": res.setup_id, "model": res.model_id,
            "task": s(d(run.get("task")).get("id")) or s(d(run.get("task")).get("alias")), "harness": res.harness,
            "outcome": f["outcome"], "elapsed_s": f["elapsed"], "cost": f["cost"], "tps": sig(f["tps"]), "machine": f["machine"], "validity": f["valid"],
            "states": {k: {"state": v["state"], "task": v["task"], "score": v["score"]} for k, v in states.items()}})
    for month, runs in sorted(recent.items()):
        sizes[f"recent/{month}.json"] = dump(out / "recent" / f"{month}.json", {"month": month, "runs": slim_sort(runs)})

    current = next((c for c in visible if d(c.get("suite")).get("status") == "current"), visible[0] if visible else None)
    meta = {"site_data_format": SITE_DATA_FORMAT, "built_at": built_at_value(built_at, bundle.latest),
            "crucible_version": crucible_version(), "bundle_hash": bundle.hash,
            "current_suite": suite_id(current) if current else None, "suites": suites_meta}
    sizes["meta.json"] = dump(out / "meta.json", meta)
    try:
        guard.enforce(out)
    except guard.PrivacyError:
        (out / "meta.json").unlink()    # an unfinished build must not look like a finished one
        raise
    return {"sizes": sizes, "counts": counts_by_suite, "meta": meta, "skipped": bundle.skipped}
