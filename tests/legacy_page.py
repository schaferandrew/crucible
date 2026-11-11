"""The portfolio page's old setup identity (assets/js/crucible-core.js: applyCorrections 453-490, identityOf 549-
rawKey 574, buildConfigs 596-): variant_key-based keys with fuzzy merging of unrecorded fields. Only the parity
tests and the stage 2b report use it, to measure what `crucible site-data` deliberately changes (B-03).
"""
from __future__ import annotations

import copy
import re

FIELDS = ["publisher", "format", "quant", "reasoning", "provider", "hwKey", "device"]


def _format_of_quant(q):
    q = str(q or "").lower()
    if re.match(r"^i?q\d(_[a-z0-9]+)*$", q):
        return "gguf"
    if re.match(r"^(mlx-)?\d+bit$", q):
        return "mlx"
    return None


def apply_corrections(runs: dict, corr: dict) -> dict:
    by_base = {c["base"]: c for c in (corr or {}).get("models", []) if c.get("base") and c.get("to_base")}
    pubs = {c["from"]: c["to"] for c in (corr or {}).get("publishers", []) if c.get("from") and c.get("to")}
    out = copy.deepcopy(runs)
    for run in out.values():
        m = run.get("model")
        if not m:
            continue
        vk = str(m["variant_key"]).split("|") if m.get("variant_key") else None
        c = by_base.get(m.get("base"))
        if c:
            m["base"] = c["to_base"]
            if vk:
                vk[0] = c["to_base"]
            if c.get("publisher") and not m.get("publisher"):
                m["publisher"] = c["publisher"]
                if vk:
                    vk[1] = c["publisher"]
        if m.get("publisher") and m["publisher"] in pubs:
            m["publisher"] = pubs[m["publisher"]]
            if vk:
                vk[1] = m["publisher"]
        local = not (m.get("variant_key") and vk and vk[2] == "api")
        if not m.get("format") and local:
            f = _format_of_quant(m.get("quant"))
            if f:
                m["format"] = f
                if vk and (vk[2] == "-" or not vk[2]):
                    vk[2] = f
        if vk:
            m["variant_key"] = "|".join(vk)
    return out


def _known(v):
    return None if v in (None, "", "-") else str(v)


def identity_of(r: dict) -> dict:
    m, e, hw = r.get("model") or {}, r.get("endpoint") or {}, r.get("hardware") or None
    vk = str(m["variant_key"]).split("|") if m.get("variant_key") else []
    where = e.get("where") or ("local" if hw and hw.get("key") else "cloud")
    local = where == "local"
    rs = m.get("reasoning") or {}
    requested, resolved = _known(rs.get("requested")), _known(rs.get("resolved"))
    explicit = bool(requested) and requested != "default"
    quant = m.get("quant")
    return {
        "base": m.get("base") or (vk[0] if vk else None) or m.get("id") or "unknown", "where": where, "local": local,
        "harness": (r.get("harness") or {}).get("id") or "unknown",
        "publisher": _known(vk[1] if len(vk) > 1 else m.get("publisher")) if vk else _known(m.get("publisher")),
        "format": _known(vk[2] if len(vk) > 2 else None) if vk else _known(m.get("format")),
        "quant": _known(vk[3] if len(vk) > 3 else None) if vk else _known(str(quant).lower() if quant else None),
        "reasoning": requested if explicit else resolved, "reqDefault": not explicit,
        "provider": None if local else _known(e.get("provider")),
        "hwKey": _known(hw and hw.get("key")) if local else None,
        "device": _known(e.get("device") or (hw and hw.get("label"))) if local else None,
    }


def raw_key(i: dict) -> str:
    return "|".join([i["base"], i["where"], i["harness"], "d" if i["reqDefault"] else "x"] +
                    ["?" if i[f] is None else i[f] for f in FIELDS])


def _unknowns(i):
    return [f for f in FIELDS if i[f] is None]


def _compatible(a, b):
    if a["base"] != b["base"] or a["where"] != b["where"] or a["harness"] != b["harness"]:
        return False
    if a["reasoning"] is None and not b["reqDefault"]:
        return False
    if b["reasoning"] is None and not a["reqDefault"]:
        return False
    return all(a[f] is None or b[f] is None or a[f] == b[f] for f in FIELDS)


def _strictly_more_known(b, a):
    ua, ub = _unknowns(a), _unknowns(b)
    return len(ub) < len(ua) and all(f in ua for f in ub)


def legacy_configs(runs: dict, corrections: dict) -> dict:
    """run_uuid -> the legacy config key the page grouped it under (after fuzzy merging)."""
    runs = apply_corrections(runs, corrections)
    groups, order = {}, []
    for uuid in runs:
        i = identity_of(runs[uuid])
        k = raw_key(i)
        if k not in groups:
            groups[k] = {"id": i, "runs": []}
            order.append(k)
        groups[k]["runs"].append(uuid)
    target = {}
    for k in order:
        g = groups[k]
        if not _unknowns(g["id"]):
            continue
        cands = [o for o in order if o != k and _compatible(g["id"], groups[o]["id"]) and _strictly_more_known(groups[o]["id"], g["id"])]
        top = [c for c in cands if not any(x != c and _compatible(groups[c]["id"], groups[x]["id"]) and
                                           _strictly_more_known(groups[x]["id"], groups[c]["id"]) for x in cands)]
        if len(top) == 1:
            target[k] = top[0]

    def resolve(k):
        seen = set()
        while k in target and k not in seen:
            seen.add(k)
            k = target[k]
        return k
    out = {}
    for k in order:
        for uuid in groups[k]["runs"]:
            out[uuid] = resolve(k)
    return out
