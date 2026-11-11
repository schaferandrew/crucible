"""`crucible registry suggest --bundle DIR`: candidate registry entries for runs whose record leaves a gap.

The resolver never infers (docs/bundle-format.md#registry): a run that recorded no packager, format or
resolved reasoning level lands in its own setup until a reviewed registry entry says otherwise. This
command makes those entries cheap to write. It reads the published runs, applies only rules that the
data itself proves, and prints YAML to review and paste into `registry/models.yaml` (`defaults`) and
`registry/overrides.yaml`. It writes nothing.

  defaults   for each (model, quant): when every run that did record a packager, a format or a resolved
             reasoning level (requested default) agrees, and at least two did, propose it for the runs
             that didn't
  overrides  a run that recorded no packager, format or quant: when exactly one artifact of that model
             ran on that hardware with that harness, propose it for the run; and for a local run with
             no hardware key, the machine whose machine_id the run carries, if exactly one registry
             machine has it and the run was served by the machine that ran it (a run served over LM
             Link has the harness machine's id, not the serving machine's, so it is never proposed)
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

from crucible import registry as reg_mod

MIN_EVIDENCE = 2
FIELDS = ("packager", "format", "reasoning")


def _runs(bundle: Path):
    from crucible import runrecord
    for path in sorted(bundle.glob("runs/*/*.json")):
        run = runrecord.read_json(path)
        if isinstance(run, dict):
            yield run


def _recorded_reasoning(run: dict):
    r = (run.get("model") or {}).get("reasoning") or {}
    return r.get("resolved") if r.get("requested") in (None, "", "default") else None


def _missing_reasoning(run: dict) -> bool:
    r = (run.get("model") or {}).get("reasoning") or {}
    return r.get("requested") in (None, "", "default") and not r.get("resolved")


def suggest(runs: list, reg: reg_mod.Registry) -> dict:
    """{"defaults": {model id: [default entry]}, "overrides": [override entry]} for runs with gaps."""
    rows = [(r, reg.resolve_run(r)) for r in runs]
    local = [(r, x) for r, x in rows if x.where == "local"]

    # --- model defaults, per (model, quant)
    groups: dict = {}
    for r, x in local:
        if x.quant and not x.model_id.startswith("unknown/"):
            groups.setdefault((x.model_id, x.quant), []).append((r, x))
    defaults: dict = {}
    for (model_id, quant), members in sorted(groups.items()):
        entry = {"match": {"quant": quant}}
        reasons = []
        for field in FIELDS:
            evidence, missing = [], []
            for r, x in members:
                if field == "packager":
                    (evidence if x.sources["packager_from"] == "recorded" else missing if x.packager is None else []).append(x.packager)
                elif field == "format":
                    (evidence if x.sources["format_from"] == "recorded" else missing if x.format is None else []).append(x.format)
                else:
                    if _recorded_reasoning(r):
                        evidence.append(_recorded_reasoning(r))
                    elif _missing_reasoning(r):
                        missing.append(None)
            values = set(evidence)
            if missing and len(evidence) >= MIN_EVIDENCE and len(values) == 1:
                value = values.pop()
                entry[field] = value
                reasons.append(f"all {len(evidence)} runs of {model_id} at {quant} that recorded "
                               f"{'a resolved reasoning level' if field == 'reasoning' else field} say {value}; "
                               f"{len(missing)} runs recorded none")
        if any(f in entry for f in FIELDS):
            entry["reason"] = "; ".join(reasons)
            defaults.setdefault(model_id, []).append(entry)

    # --- per-run overrides
    artifacts: dict = {}
    for r, x in local:
        if x.quant and x.packager and x.format:
            artifacts.setdefault((x.model_id, x.hardware_key, x.harness), set()).add((x.packager, x.format, x.quant))
        elif x.quant and x.format:
            artifacts.setdefault((x.model_id, x.hardware_key, x.harness), set()).add((None, x.format, x.quant))
    grouped: dict = {}
    for r, x in local:
        uuid = r.get("run_uuid")
        if not uuid:
            continue
        if x.packager is None and x.format is None and x.quant is None and not x.model_id.startswith("unknown/"):
            found = artifacts.get((x.model_id, x.hardware_key, x.harness)) or set()
            if len(found) == 1:
                packager, fmt, quant = next(iter(found))
                s = {k: v for k, v in (("packager", packager), ("format", fmt), ("quant", quant)) if v}
                reason = (f"recorded no weights; the only artifact of {x.model_id} that ran on "
                          f"{x.hardware_key or 'this hardware'} with {x.harness} is {packager or 'unrecorded'} {fmt} {quant}")
                grouped.setdefault((tuple(sorted(s.items())), reason), []).append(uuid)
        if x.hardware_key is None and x.machine is None and not (r.get("endpoint") or {}).get("served_via"):
            owners = [m for m, e in reg.machines.items() if (r.get("provenance") or {}).get("machine_id") in (e.get("machine_ids") or [])]
            if len(owners) == 1:
                reason = (f"no host or hardware key recorded and served by the machine that ran it; "
                          f"its machine_id belongs to {owners[0]} alone")
                grouped.setdefault((tuple([("machine", owners[0])]), reason), []).append(uuid)
    overrides = [{"run_uuids": sorted(uuids), "set": dict(s), "reason": reason}
                 for (s, reason), uuids in sorted(grouped.items(), key=lambda kv: (kv[0][1], kv[0][0]))]
    return {"defaults": defaults, "overrides": overrides}


def applied(reg: reg_mod.Registry, found: dict) -> reg_mod.Registry:
    """A copy of the registry with the suggestions added (for measuring them; never saved)."""
    data = copy.deepcopy(reg.data)
    for model in data["models"]["models"]:
        if model["id"] in found["defaults"]:
            model["defaults"] = list(model.get("defaults") or []) + found["defaults"][model["id"]]
    data["overrides"] = {"runs": list(data["overrides"].get("runs") or []) + found["overrides"]}
    return reg_mod.Registry(data)


def render(found: dict) -> str:
    import yaml
    dump = lambda data: yaml.safe_dump(data, sort_keys=False, default_flow_style=False, allow_unicode=True, width=100)
    lines = ["# Suggested registry entries, derived from the published runs. Review each one; nothing here is applied.",
             "#", "# registry/models.yaml: add each `defaults` list to the model entry with that id.",
             "defaults:"]
    for model_id, entries in found["defaults"].items():
        lines.append(f"  # {model_id}")
        lines.append("  " + dump({model_id: {"defaults": entries}}).rstrip().replace("\n", "\n  "))
    if not found["defaults"]:
        lines[-1] = "defaults: {}"
    lines += ["", "# registry/overrides.yaml: append these to `runs`.", "overrides:"]
    lines.append(("  " + dump(found["overrides"]).rstrip().replace("\n", "\n  ")) if found["overrides"] else "  []")
    text = "\n".join(lines) + "\n"
    # The registry is published: never print anything that looks like an address
    return "\n".join(line for line in text.splitlines() if not reg_mod.IP_LIKE.search(line)) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(prog="crucible registry", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("suggest", help="print candidate defaults and overrides for runs with gaps (writes nothing)")
    one.add_argument("--bundle", type=Path, required=True, metavar="DIR", help="a published folder (its runs/)")
    args = parser.parse_args()
    runs = list(_runs(args.bundle))
    if not runs:
        sys.exit(f"{args.bundle}: no runs/*/*.json")
    reg = reg_mod.load()
    found = suggest(runs, reg)
    print(render(found), end="")
    after = applied(reg, found)
    changed = sum(1 for r in runs if reg.resolve_run(r).setup_id != after.resolve_run(r).setup_id)
    n_default = sum(len(v) for v in found["defaults"].values())
    print(f"# {n_default} defaults, {len(found['overrides'])} overrides; "
          f"{changed} of {len(runs)} runs would change setup", file=sys.stderr)


if __name__ == "__main__":
    main()
