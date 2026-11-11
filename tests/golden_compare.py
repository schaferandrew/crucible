"""Compare generated site data with the page's golden numbers (crucible-dashboard/docs/rewrite/golden-numbers.json)
through the page's legacy configurations. Used by tests/test_sitedata.py and for the stage 2b report.

Run directly: python tests/golden_compare.py <bundle> <site-data out> <golden.json>
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from legacy_page import legacy_configs  # noqa: E402

ALL = "spark+temper+forge"


def load_runs(bundle: Path) -> dict:
    runs = {}
    for p in sorted(bundle.glob("runs/*/*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        runs[r["run_uuid"]] = r
    return runs


def golden_setups(golden_suite: dict) -> dict:
    """legacy cfg key -> {time, cost, runs, tps (best setups only), taskMeans (best setups only)} for prov off and on."""
    out = defaultdict(dict)
    for mode in ("chat", "agentic"):
        for sc in golden_suite["modes"][mode]["scenarios"]:
            if sc["exclude"] or not sc["showInProgress"]:
                continue
            prov = "p1" if sc["provisional"] else "p0"
            for row in sc["rows"]:
                for v in row.get("variants", []):
                    if (mode == "chat") != (v["cfg"]["harness"] == "direct"):
                        continue
                    out[v["cfg"]["key"]].setdefault(prov, {}).update(time=v["time"], cost=v["cost"], runs=v["runs"], mode=mode)
                best = row.get("bestSetup")
                if best and (mode == "chat") == (best["harness"] == "direct"):
                    out[best["key"]][prov].update(tps=row["tps"], taskMeans=row.get("taskMeans"))
    return out


def compare(bundle: Path, out: Path, golden: dict, suite: str, resolve_pairs: dict) -> dict:
    """resolve_pairs: run_uuid -> setup id (from runs/<uuid>.json). Returns the mapping and every mismatch."""
    index = json.loads((out / suite / "index.json").read_text(encoding="utf-8"))
    runs = load_runs(bundle)
    corrections = json.loads((bundle / "corrections.json").read_text(encoding="utf-8"))
    legacy = legacy_configs(runs, corrections)
    legacy_to_setups = defaultdict(Counter)
    setup_to_legacy = defaultdict(Counter)
    for uuid, key in legacy.items():
        legacy_to_setups[key][resolve_pairs[uuid]] += 1
        setup_to_legacy[resolve_pairs[uuid]][key] += 1
    stats = index["setup_stats"]
    cells = defaultdict(dict)
    for c in index["cells"]:
        cells[c["setup"]][c["task"]] = c

    def stat(setup, prov):
        s = stats["by_setup"].get(setup)
        if not s:
            return None
        i = s["index"][stats["keys"].index(f"{ALL}:{prov}")]
        return None if i < 0 else s["stats"][i]

    gold = golden_setups(golden["suites"][suite])
    rows, mismatches, expected = [], [], []
    for key, g in sorted(gold.items()):
        setups = legacy_to_setups.get(key, {})
        one = len(setups) == 1 and len(setup_to_legacy[next(iter(setups))]) == 1
        row = {"legacy": key, "setups": dict(setups), "one_to_one": one}
        rows.append(row)
        if not one:
            continue
        setup = next(iter(setups))
        for prov, vals in sorted(g.items()):
            st = stat(setup, "p1" if prov == "p1" else "p0") or {"runs": 0}
            for field, mine in (("time", st.get("time")), ("cost", st.get("cost")), ("runs", st.get("runs")),
                                ("tps", (st.get("tps") or {}).get("median"))):
                if field not in vals:
                    continue
                want = vals[field]
                tol = {"time": 0.0006, "cost": 6e-7, "tps": 0.006, "runs": 0}[field]
                same = (want is None and mine is None) or (want is not None and mine is not None and abs(want - mine) <= tol)
                if not same and field == "cost" and want is None and mine is not None and key.split("|")[9] == "?":
                    expected.append({"legacy": key, "setup": setup, "prov": prov, "field": field, "golden": want, "site_data": mine,
                                     "why": "the hardware key was filled in from the registry (Eclipse is an M5 Pro 48 GB)"})
                elif not same:
                    mismatches.append({"legacy": key, "setup": setup, "prov": prov, "field": field, "golden": want, "site_data": mine})
            if prov == "p0" and vals.get("taskMeans"):
                for task, want in vals["taskMeans"].items():
                    cell = cells[setup].get(task, {}).get("counted") or {}
                    mine = cell.get("mean")
                    if want is None or mine is None or abs(want - mine) > 0.0001:
                        if not (want is None and mine is None):
                            mismatches.append({"legacy": key, "setup": setup, "prov": prov, "field": f"mean:{task}",
                                               "golden": want, "site_data": mine})
    return {"rows": rows, "mismatches": mismatches, "expected": expected, "legacy_total": len(gold)}


def delta(bundle: Path, pairs: dict) -> dict:
    """B-03: legacy configurations against site-data setups over every run."""
    runs = load_runs(bundle)
    legacy = legacy_configs(runs, json.loads((bundle / "corrections.json").read_text(encoding="utf-8")))
    l2s, s2l = defaultdict(Counter), defaultdict(Counter)
    for uuid, key in legacy.items():
        l2s[key][pairs[uuid]] += 1
        s2l[pairs[uuid]][key] += 1
    return {"legacy": len(l2s), "setups": len(s2l),
            "split": {k: dict(v) for k, v in sorted(l2s.items()) if len(v) > 1},
            "merged": {k: dict(v) for k, v in sorted(s2l.items()) if len(v) > 1},
            "one_to_one": sum(1 for k, v in l2s.items() if len(v) == 1 and len(s2l[next(iter(v))]) == 1)}


if __name__ == "__main__":
    if len(sys.argv) > 4 and sys.argv[4] == "delta":
        pairs = {}
        for p in (Path(sys.argv[2]) / "runs").glob("*.json"):
            r = json.loads(p.read_text(encoding="utf-8"))
            pairs[r["run_uuid"]] = r["setup"]
        x = delta(Path(sys.argv[1]), pairs)
        print("legacy", x["legacy"], "setups", x["setups"], "one-to-one", x["one_to_one"], "split", len(x["split"]), "merged", len(x["merged"]))
        for title in ("split", "merged"):
            print(title.upper())
            for k, v in x[title].items():
                print(k)
                for name, n in v.items():
                    print("    ", n, name)
        raise SystemExit
    bundle, out, golden_path = map(Path, sys.argv[1:4])
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    pairs = {}
    for p in (out / "runs").glob("*.json"):
        r = json.loads(p.read_text(encoding="utf-8"))
        pairs[r["run_uuid"]] = r["setup"]
    for suite in ("v4", "v3"):
        res = compare(bundle, out, golden, suite, pairs)
        one = sum(1 for r in res["rows"] if r["one_to_one"])
        print(suite, "golden setups", res["legacy_total"], "one-to-one", one, "mismatches", len(res["mismatches"]), "expected", len(res["expected"]))
        for m in res["mismatches"][:40]:
            print("  ", m)
