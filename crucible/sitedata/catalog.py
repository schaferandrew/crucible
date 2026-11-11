"""A suite catalog, resolved for the page: ordered modes, areas and tiers with their display text, and tasks
without their prompt, rules or criteria (those go to tasks/<task>.json). Display text a catalog lacks is filled
from the fallbacks file, so the page needs no fallback layer. Reproduces buildSuite (core 1018-1085).
"""
from __future__ import annotations

from crucible.sitedata.rules import d, num, s, scoring_method

# Labels for scoring methods the fallbacks file doesn't carry
DEFAULT_METHODS = {
    "checks": {"label": "automatic checks", "blurb": "fixed rules applied to the model's answer",
               "criteria_label": "Criteria"},
    "hidden_tests": {"label": "hidden tests", "blurb": "a test suite the agent never sees, run on the repo it leaves behind",
                     "criteria_label": "Test groups"},
    "judge": {"label": "AI judge", "blurb": "an AI judge reviews the answer against the task's rubric",
              "criteria_label": "Criteria"},
}
TASK_DETAIL = ("prompt", "rules", "criteria", "summary")


def cap(text) -> str:
    text = str(text)
    return text[:1].upper() + text[1:]


def _ids(items) -> list:
    return [x if isinstance(x, str) else d(x).get("id") for x in items or [] if (x if isinstance(x, str) else d(x).get("id"))]


def task_scoring(task: dict) -> dict:
    sc = task.get("scoring")
    sc = sc if isinstance(sc, dict) else {"method": sc}
    return {"method": sc.get("method"), "unit": sc.get("unit"), "total": sc.get("total"), "scale": sc.get("scale")}


def slim_task(task: dict) -> dict:
    out = {k: v for k, v in task.items() if k not in TASK_DETAIL and k != "scoring"}
    out["scoring"] = task_scoring(task)
    out["aliases"] = [a for a in task.get("aliases") or [] if s(a)]
    return out


def build_catalog(cat: dict, fb: dict, suite_label: str) -> dict:
    fb = d(fb)
    fb_modes, fb_tiers, fb_areas = d(fb.get("modes")), d(fb.get("tiers")), d(fb.get("areas"))
    tasks = [t for t in cat.get("tasks") or [] if isinstance(t, dict) and s(t.get("id"))]
    suite = d(cat.get("suite"))
    policy, fb_policy = d(cat.get("scoring_policy")), d(fb.get("scoring_policy"))
    scoring_policy = dict(policy)
    scoring_policy["coverage_min"] = num(policy.get("coverage_min"), num(fb_policy.get("coverage_min"), 0.75))
    scoring_policy["in_progress_below"] = num(policy.get("in_progress_below"), num(fb_policy.get("in_progress_below"), 0.75))

    # tiers: the catalog's order and roles; a tier only tasks mention is appended with no role
    def tier_info(tid, o, pos):
        f = d(fb_tiers.get(tid))
        return {"id": tid, "label": o.get("label") or f.get("label") or cap(tid), "blurb": o.get("blurb") or f.get("blurb") or "",
                "detail": o.get("detail") or f.get("detail") or "", "role": o.get("role") or f.get("role") or None,
                "gate": o.get("gate") or f.get("gate") or None,
                "order": num(o.get("order"), num(f.get("order"), 1000 + pos)), "pos": pos}
    tiers, seen = [], set()
    for t in cat.get("tiers") or []:
        tid = t if isinstance(t, str) else d(t).get("id")
        if s(tid) and tid not in seen:
            seen.add(tid)
            tiers.append(tier_info(tid, d(t), len(tiers)))
    for t in tasks:
        if s(t.get("tier")) and t["tier"] not in seen:
            seen.add(t["tier"])
            tiers.append(tier_info(t["tier"], {}, len(tiers)))
    if not tiers:
        tiers.append(tier_info("all", {"label": "Score"}, 0))
    tiers.sort(key=lambda t: (t["order"], t["pos"]))
    tiers = [{k: v for k, v in t.items() if k != "pos"} for t in tiers]

    # harnesses and modes
    harnesses = [{"id": h["id"], "label": h.get("label") or h["id"], "modes": [m for m in h.get("modes") or [] if s(m)]}
                 for h in cat.get("harnesses") or [] if isinstance(h, dict) and s(h.get("id"))]
    modes, mode_seen = [], set()

    def add_mode(mid, o):
        if not s(mid) or mid in mode_seen:
            return
        mode_seen.add(mid)
        f = d(fb_modes.get(mid))
        modes.append({"id": mid, "label": o.get("label") or f.get("label") or cap(mid), "blurb": o.get("blurb") or f.get("blurb") or "",
                      "order": num(o.get("order"), num(f.get("order"), 1000 + len(modes))), "pos": len(modes)})
    for m in cat.get("modes") or []:
        if isinstance(m, dict):
            add_mode(m.get("id"), m)
    for t in tasks:
        add_mode(t.get("mode"), {})
    modes.sort(key=lambda m: (m["order"], m["pos"]))

    # areas: the catalog's, then any a task mentions; each mode lists its areas in order
    areas, area_ids = [], set()
    for i, a in enumerate(cat.get("areas") or []):
        if isinstance(a, dict) and s(a.get("id")) and a["id"] not in area_ids:
            area_ids.add(a["id"])
            f = d(fb_areas.get(a["id"]))
            areas.append({"id": a["id"], "label": a.get("label") or f.get("label") or cap(a["id"]), "mode": a.get("mode"),
                          "order": num(a.get("order"), i), "blurb": a.get("blurb") or f.get("blurb") or "",
                          "examples": a.get("examples") or f.get("examples") or ""})
    for t in tasks:
        if s(t.get("area")) and t["area"] not in area_ids:
            area_ids.add(t["area"])
            f = d(fb_areas.get(t["area"]))
            areas.append({"id": t["area"], "label": f.get("label") or cap(t["area"]), "mode": t.get("mode"), "order": 1000,
                          "blurb": f.get("blurb") or "", "examples": f.get("examples") or ""})
    areas.sort(key=lambda a: (a["order"], a["id"]))
    for m in modes:
        m["areas"] = [a["id"] for a in areas if a["mode"] == m["id"]]
        m["harnesses"] = [h["id"] for h in harnesses if m["id"] in h["modes"]]
    modes = [{k: v for k, v in m.items() if k != "pos"} for m in modes]

    # scoring methods: every one a task uses, with text from the fallbacks, else the defaults, else the raw id
    methods = {}
    fb_methods = d(fb.get("scoring_methods"))
    for t in tasks:
        mid = scoring_method(t)
        if s(mid) and mid not in methods:
            f = {**d(DEFAULT_METHODS.get(mid)), **d(fb_methods.get(mid))}
            methods[mid] = {"label": f.get("label") or mid.replace("_", " "), "blurb": f.get("blurb") or "",
                            "criteria_label": f.get("criteria_label") or "Criteria"}

    return {
        "suite": {"id": s(suite.get("id")) or str(suite.get("version") or "?"), "version": suite.get("version"),
                  "cut_at": suite.get("cut_at"), "status": suite.get("status"), "changelog_url": suite.get("changelog_url"),
                  "name": suite_label, "format_revision": cat.get("format_revision")},
        "modes": modes, "areas": areas,
        "categories": [{"id": c["id"], "label": c.get("label") or cap(c["id"]), "weight": num(c.get("weight"))}
                       for c in cat.get("categories") or [] if isinstance(c, dict) and s(c.get("id"))],
        "tiers": tiers, "harnesses": harnesses, "scoring_policy": scoring_policy, "scoring_methods": methods,
        "labels": {"overall": d(fb.get("aggregate")).get("label") or "Overall",
                   "combined": {"label": d(fb.get("combined")).get("label") or "Combined",
                                "blurb": d(fb.get("combined")).get("blurb") or ""}},
        "tasks": [slim_task(t) for t in tasks],
    }


def suite_label(sid: str) -> str:
    """'Suite v4' (core 122)."""
    return "Suite " + (sid if sid[:1] in ("v", "V") else "v" + sid)


def suite_sort_key(cat: dict):
    """Newest suite first: by version parts descending, then cut date descending (core 435-447)."""
    suite = d(cat.get("suite"))
    parts = []
    for p in str(suite.get("version") or suite.get("id") or "").lstrip("vV").split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    parts += [0] * (8 - len(parts))
    return ([-p for p in parts], [-ord(c) for c in str(suite.get("cut_at") or "")])
