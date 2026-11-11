"""crucible site-data: the run rules, the readers, determinism, the file schemas, and parity with the page."""
import json
import sys
from pathlib import Path

import pytest

from crucible import registry
from crucible.sitedata import build as sd_build, rules, schema
from crucible.sitedata.build import build
from crucible.sitedata.reader import read_bundle

sys.path.insert(0, str(Path(__file__).parent))
SITE = Path("/Users/schafer/Developer/schaferandrew.github.io")
GOLDEN = Path("/Users/schafer/Developer/crucible-dashboard/docs/rewrite/golden-numbers.json")


# ----------------------------------------------------------------------------- synthetic bundle

def task(tid, status="active", version=1, rubric=1, mode="chat", tier="temper", method="checks", aliases=()):
    return {"id": tid, "name": tid.title(), "aliases": list(aliases), "mode": mode, "area": "writing", "category": "c",
            "tier": tier, "status": status, "version": version, "rubric_version": rubric, "weight": 0.1,
            "scoring": {"method": method, "unit": "points", "total": 6, "scale": 10}, "criteria": [{"id": "x"}],
            "prompt": "do it", "rules": ["r"], "summary": "s"}


CATALOG = {
    "record": "catalog", "format_version": 3, "format_revision": 2,
    "suite": {"id": "v9", "version": "9.0", "cut_at": "2026-01-01", "status": "current"},
    "scoring_policy": {"coverage_min": 0.75}, "modes": [{"id": "chat", "label": "Chat"}, {"id": "agentic"}],
    "areas": [{"id": "writing", "label": "Writing", "mode": "chat", "order": 1}],
    "tiers": [{"id": "spark", "label": "Spark", "role": "gate", "gate": {"mean": 8, "min": 5}}, {"id": "temper", "role": "headline"}],
    "harnesses": [{"id": "direct", "modes": ["chat"]}, {"id": "pi", "modes": ["agentic"]}],
    "tasks": [task("t-active", aliases=["OLD-1"]), task("t-prov", status="provisional", tier="spark"),
              task("t-retired", status="retired"), task("t-judge", method="judge", rubric=2),
              task("t-agent", mode="agentic")],
}


def run(uuid, tid="t-active", version=1, model="qwen/qwen3.5-9b", harness="direct", started="2026-01-02T00:00:00+00:00",
        elapsed=10.0, status="completed", **extra):
    r = {"record": "run", "format_version": 3, "run_uuid": uuid, "started_at": started, "elapsed_s": elapsed,
         "task": {"id": tid, "version": version, "rubric_version": 1, "alias": None}, "harness": {"id": harness},
         "model": {"id": "lmstudio/" + model, "base": model, "publisher": "Qwen", "format": "gguf", "quant": "Q4_K_M",
                   "reasoning": {"requested": "default", "resolved": "on"}},
         "endpoint": {"where": "local", "provider": "lmstudio", "device": "Duskfall"},
         "hardware": {"key": "m5-pro-48gb", "label": "Duskfall"},
         "outcome": {"status": status, "timed_out": False, "invalid": None}, "metrics": {"output_tokens_per_s": 50.0, "tool_calls": 3},
         "output_ref": f"outputs/{uuid}.txt", "provenance": {"crucible_version": "3.9.0"}}
    r.update(extra)
    return r


def score(uuid, value, rubric=1, method="checks", **extra):
    return {"record": "score", "format_version": 3, "run_uuid": uuid, "rubric_version": rubric, "method": method,
            "scored_at": "2026-01-03T00:00:00+00:00", "score": value, "scale": 10, "items": [{"id": "i", "passed": True}],
            "groups": [], **extra}


def write(folder: Path, runs, scores=(), statuses=(), catalog=CATALOG):
    (folder / "catalog").mkdir(parents=True, exist_ok=True)
    (folder / "catalog" / "v9.json").write_text(json.dumps(catalog))
    for r in runs:
        p = folder / "runs" / "2026-01" / f"{r['run_uuid']}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(r))
    for i, s in enumerate(scores):
        p = folder / "scores" / "2026-01" / f"{i}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(s))
    for s in statuses:
        p = folder / "status" / f"{s['run_uuid']}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps([s]))
    return folder


def states(tmp_path, runs, scores=(), statuses=(), catalog=CATALOG):
    bundle = write(tmp_path / "bundle", runs, scores, statuses, catalog)
    out = tmp_path / "out"
    result = build(bundle, None, out)
    index = json.loads((out / "v9" / "index.json").read_text())
    return result, out, index


def state_of(out, uuid):
    return json.loads((out / "runs" / f"{uuid}.json").read_text())["suites"]["v9"]


# ----------------------------------------------------------------------------- run-state rules, one by one

def classify(r, valid="valid", cat=CATALOG):
    return rules.classify(r, valid, rules.SuiteRules(cat))


def test_counted_and_provisional():
    assert classify(run("a"))[0] == "counted"
    assert classify(run("a", "t-prov"))[0] == "provisional"


def test_withdrawn_precedes_everything():
    assert classify(run("a", "nope"), "withdrawn")[0] == "withdrawn"
    assert classify(run("a", "t-retired"), "withdrawn")[0] == "withdrawn"


def test_unknown_task_and_aliases():
    assert classify(run("a", "nope"))[0] == "unknown_task"
    r = run("a", "OLD-1")
    assert classify(r) == ("counted", CATALOG["tasks"][0])
    r = run("a", "renamed")
    r["task"]["alias"] = "OLD-1"
    assert classify(r)[1]["id"] == "t-active"


def test_retired_precedes_invalid_older_and_harness():
    assert classify(run("a", "t-retired"), "invalid")[0] == "retired"
    assert classify(run("a", "t-retired", version=0))[0] == "retired"


def test_invalid_precedes_older_and_harness():
    assert classify(run("a", version=0), "invalid")[0] == "invalid"
    assert classify(run("a", harness="pi"), "invalid")[0] == "invalid"


def test_older_version_and_null_catalog_version():
    assert classify(run("a", version=0))[0] == "older"
    cat = dict(CATALOG, tasks=[task("t-active", version=None)])
    assert classify(run("a", version=7), cat=cat)[0] == "counted"


def test_harness_must_be_allowed_for_the_tasks_mode():
    assert classify(run("a", harness="pi"))[0] == "harness"
    assert classify(run("a", harness="mystery"))[0] == "harness"
    assert classify(run("a", "t-agent", harness="pi"))[0] == "counted"
    assert classify(run("a", "t-agent", harness="direct"))[0] == "harness"


def test_validity_last_status_wins_then_harness_mark():
    bad = {"invalid": {"reason": "x"}}
    r = run("a")
    assert rules.validity([], r) == "valid"
    assert rules.validity([bad], r) == "invalid"
    assert rules.validity([bad, {"valid": True}], r) == "valid"
    assert rules.validity([{"valid": True}, {"withdrawn": {"reason": "y"}}], r) == "withdrawn"
    assert rules.validity([{"withdrawn": {}, "invalid": {}}], r) == "withdrawn"
    marked = run("a", outcome={"status": "completed", "invalid": {"reason": "bad host"}})
    assert rules.validity([], marked) == "invalid"
    assert rules.validity([{"valid": True}], marked) == "valid"       # a status record overrides the mark
    assert rules.validity([{"note": "no verdict"}], marked) == "invalid"   # one with no verdict falls through
    assert rules.invalid_reason([bad], r) == "x"
    assert rules.invalid_reason([], marked) == "bad host"


def test_outcome_classes():
    assert rules.outcome_of(run("a")) == "finished"
    assert rules.outcome_of(run("a", outcome={"status": "timeout"})) == "timed_out"
    assert rules.outcome_of(run("a", outcome={"status": "completed", "timed_out": True})) == "timed_out"
    assert rules.outcome_of(run("a", outcome={"status": "harness_error"})) == "error"
    assert rules.outcome_of({}) == "error"


def test_tps_only_when_positive():
    assert rules.tps_of(run("a")) == 50.0
    assert rules.tps_of(run("a", metrics={"output_tokens_per_s": 0})) is None
    assert rules.tps_of(run("a", metrics={})) is None


# ----------------------------------------------------------------------------- score selection

def test_score_selection_fallbacks():
    t = task("x", rubric=2, method="checks")
    exact = score("u", 9, 2, "checks")
    other_method = score("u", 7, 2, "judge")
    old = score("u", 5, 1, "checks")
    assert rules.pick_score([old, other_method, exact], t, "counted") is exact
    assert rules.pick_score([old, other_method], t, "counted") is other_method     # any record at the rubric version
    assert rules.pick_score([old], t, "counted") is None                           # a counted run never falls back
    assert rules.pick_score([old], t, "provisional") is old                        # an uncounted one shows its newest
    newest = score("u", 3, 4, "checks")
    assert rules.pick_score([old, newest], t, "older") is newest
    assert rules.pick_score([], t, "older") is None
    judge = task("j", method="judge", rubric=1)       # judge tasks: no judge record, the rubric-version fallback
    assert rules.pick_score([score("u", 6, 1, "checks")], judge, "counted")["score"] == 6


def test_unscored_counted_run_is_counted_not_scored(tmp_path):
    result, out, index = states(tmp_path, [run("a"), run("b")], [score("a", 10.0), score("b", None)])
    assert result["counts"]["v9"]["counted"] == 2
    assert result["counts"]["v9"]["counted_scored"] == 1 and result["counts"]["v9"]["unscored"] == 1
    cell = [c for c in index["cells"] if c["task"] == "t-active"][0]
    assert cell["counted"]["n"] == 2 and cell["counted"]["n_scored"] == 1 and cell["counted"]["mean"] == 10.0
    assert sum(m.get("unscored", 0) for m in index["other"].values()) == 1


# ----------------------------------------------------------------------------- cells, stats, other

def test_cells_stats_and_other(tmp_path):
    runs = [run("a", elapsed=10), run("b", elapsed=30, status="timeout"), run("c", "t-prov", elapsed=100), run("d", version=0),
            run("e", "t-retired"), run("f", "nope"), run("g", harness="pi")]
    scores = [score(u, v) for u, v in (("a", 10.0), ("b", 4.0), ("c", 6.0), ("d", 9.0), ("g", 8.0))]
    result, out, index = states(tmp_path, runs, scores, [{"record": "status", "run_uuid": "g", "at": "x", "invalid": {"reason": "r"}}])
    c = result["counts"]["v9"]
    assert (c["counted"], c["provisional"], c["older"], c["retired"], c["unknown_task"], c["invalid"]) == (2, 1, 1, 1, 1, 1)
    direct = [s for s in index["entities"]["setups"] if s.endswith("direct@local~m5-pro-48gb")][0]
    cells = {x["task"]: x for x in index["cells"] if x["setup"] == direct}
    counted = cells["t-active"]["counted"]
    assert counted["n"] == 2 and counted["mean"] == 7.0 and (counted["min"], counted["max"]) == (4.0, 10.0)
    assert counted["timeouts"] == 1 and counted["n_finished"] == 1 and counted["mean_finished"] == 10.0
    assert cells["t-active"]["runs"] == 3          # counted x2, older (the invalid run is another setup)
    assert "counted" not in cells["t-prov"] and cells["t-prov"]["provisional"]["mean"] == 6.0
    assert "t-retired" not in cells and "nope" not in cells
    stats = index["setup_stats"]
    by = stats["by_setup"][direct]
    all_p0 = by["stats"][by["index"][stats["keys"].index("spark+temper:p0")]]
    all_p1 = by["stats"][by["index"][stats["keys"].index("spark+temper:p1")]]
    assert all_p0 == {"runs": 2, "time": 20.0, "tps": {"median": 50.0, "n": 2}, "cost": all_p0["cost"]}
    assert all_p1["runs"] == 3 and all_p1["time"] == 30.0
    spark_p1 = by["stats"][by["index"][stats["keys"].index("spark:p1")]]
    assert spark_p1["runs"] == 1 and spark_p1["time"] == 100.0
    assert by["index"][stats["keys"].index("spark:p0")] == -1      # no counted spark run
    assert index["other"]["qwen/qwen3.5-9b"] == {"older": 1, "retired": 1, "unknown_task": 1, "invalid": 1, "harness": 0} or index["other"]["qwen/qwen3.5-9b"] == {"older": 1, "retired": 1, "unknown_task": 1, "invalid": 1}


def test_many_tiers_fall_back_to_cell_arrays(tmp_path):
    cat = dict(CATALOG, tiers=[{"id": f"t{i}"} for i in range(6)], tasks=[task("t-active", tier="t1")])
    result, out, index = states(tmp_path, [run("a")], [score("a", 10.0)], catalog=cat)
    s = index["setup_stats"]
    assert s["format"] == "cells" and list(s["by_setup"].values())[0]["t-active"]["counted"] == [[10.0, 50.0, s["by_setup"] and list(s["by_setup"].values())[0]["t-active"]["counted"][0][2]]]


# ----------------------------------------------------------------------------- readers

def test_format_4_record(tmp_path):
    r = run("v4", "t-active", model="qwen3.5-9b", format_version=4,
            model_={})
    r.pop("model_")
    r["format_version"] = 4
    r["model"] = {"id": "qwen/qwen3.5-9b", "maker": "qwen", "raw_base": "qwen3.5-9b", "packager": "lmstudio-community",
                  "format": "gguf", "format_source": "runtime", "quant": "Q4_K_M",
                  "reasoning": {"requested": "default", "resolved": "on"}}
    r["serving_host"], r["harness_host"] = "Duskfall", "Ironwood"
    r["hardware"] = {"key": "m5-pro-48gb"}
    r["endpoint"] = {"where": "local", "provider": "lmstudio"}
    result, out, index = states(tmp_path, [r], [score("v4", 10.0)])
    detail = json.loads((out / "runs" / "v4.json").read_text())
    assert detail["setup"] == "qwen/qwen3.5-9b~lmstudio-community~gguf~q4_k_m~r-on~direct@local~m5-pro-48gb"
    assert detail["resolution"]["sources"]["model_from"] == "recorded"
    assert detail["summary"]["model"]["raw_base"] == "qwen3.5-9b" and "serving_host" not in detail["summary"]
    assert detail["suites"]["v9"]["state"] == "counted"
    setup = index["entities"]["setups"][detail["setup"]]
    assert setup["packager"] == "lmstudio-community" and setup["labels"]["machines"] == ["Duskfall"] and setup["unrecorded"] == []


def test_records_newer_than_format_4_are_skipped(tmp_path):
    bundle = write(tmp_path / "b", [run("ok"), run("new", format_version=5)])
    assert list(read_bundle(bundle).runs) == ["ok"] and read_bundle(bundle).skipped == 1


def test_duplicate_run_keeps_first_and_duplicate_score_keeps_last(tmp_path):
    bundle = write(tmp_path / "b", [run("a")], [score("a", 1.0), score("a", 2.0)])
    got = read_bundle(bundle)
    assert [s["score"] for s in got.scores["a"]] == [2.0]


def test_status_sorted_by_time(tmp_path):
    bundle = write(tmp_path / "b", [run("a")])
    (bundle / "status").mkdir()
    (bundle / "status" / "a.json").write_text(json.dumps([{"record": "status", "run_uuid": "a", "at": "2", "valid": True},
                                                          {"record": "status", "run_uuid": "a", "at": "1", "invalid": {}}]))
    assert [s["at"] for s in read_bundle(bundle).status["a"]] == ["1", "2"]


# ----------------------------------------------------------------------------- never raise

def test_odd_records_never_raise(tmp_path):
    odd = [{"record": "run", "run_uuid": "n1"},
           {"record": "run", "run_uuid": "n2", "task": "just-a-string", "model": "nope", "harness": [], "endpoint": 5,
            "hardware": "x", "outcome": None, "metrics": [1], "elapsed_s": "fast", "started_at": 12},
           run("n3", model="never-heard-of-it"),
           run("n4", "nope", model="another-unknown")]
    result, out, index = states(tmp_path, odd, [score("n3", 7.0), {"record": "score", "run_uuid": "n4"}])
    assert result["counts"]["v9"]["runs"] == 4
    assert result["counts"]["v9"]["unknown_task"] >= 3
    models = index["entities"]["models"]
    assert any(m.startswith("unknown/") and not models[m]["known"] for m in models)
    for uuid in ("n1", "n2", "n3", "n4"):
        assert (out / "runs" / f"{uuid}.json").exists()


def test_no_catalogs_and_empty_bundle(tmp_path):
    (tmp_path / "bundle").mkdir()
    result = build(tmp_path / "bundle", None, tmp_path / "out")
    meta = json.loads((tmp_path / "out" / "meta.json").read_text())
    assert meta["suites"] == [] and meta["current_suite"] is None


def test_hidden_suites_are_omitted(tmp_path):
    bundle = write(tmp_path / "b", [run("a")])
    (tmp_path / "display.yml").write_text("hidden_suites: [v8]\n")
    old = dict(CATALOG, suite={"id": "v8", "version": "8.0", "status": "past"})
    (bundle / "catalog" / "v8.json").write_text(json.dumps(old))
    build(bundle, None, tmp_path / "out", display=tmp_path / "display.yml")
    meta = json.loads((tmp_path / "out" / "meta.json").read_text())
    assert [x["id"] for x in meta["suites"]] == ["v9"] and not (tmp_path / "out" / "v8").exists()


def test_fallback_text_fills_the_catalog(tmp_path):
    bundle = write(tmp_path / "b", [run("a")])
    (tmp_path / "fb.yml").write_text(
        "modes: {chat: {blurb: One call}}\ntiers: {spark: {detail: the basics}}\nareas: {writing: {blurb: B, examples: E}}\n"
        "scoring_methods: {checks: {label: automatic checks}}\naggregate: {label: Total}\ncombined: {label: All}\n")
    build(bundle, None, tmp_path / "out", fallbacks=tmp_path / "fb.yml")
    cat = json.loads((tmp_path / "out" / "v9" / "index.json").read_text())["catalog"]
    assert cat["modes"][0]["blurb"] == "One call" and cat["tiers"][0]["detail"] == "the basics"
    assert cat["areas"][0]["examples"] == "E" and cat["labels"]["overall"] == "Total"
    assert cat["scoring_methods"]["checks"]["label"] == "automatic checks"
    assert cat["scoring_methods"]["judge"]["label"] == "AI judge"
    assert all("prompt" not in t and "rules" not in t and "criteria" not in t for t in cat["tasks"])
    full = json.loads((tmp_path / "out" / "v9" / "tasks" / "t-active.json").read_text())["task"]
    assert full["prompt"] == "do it" and full["criteria"]


# ----------------------------------------------------------------------------- determinism and schemas

def tree(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def test_two_builds_are_byte_identical(tmp_path):
    bundle = write(tmp_path / "b", [run("a"), run("b", "t-prov"), run("c", elapsed=3)], [score("a", 10.0), score("c", 5.0)])
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "a.txt").write_text("answer")
    build(bundle, outputs, tmp_path / "o1")
    build(bundle, outputs, tmp_path / "o2")
    assert tree(tmp_path / "o1") == tree(tmp_path / "o2")
    assert (tmp_path / "o1" / "outputs" / "a.txt").read_text() == "answer"
    meta = json.loads((tmp_path / "o1" / "meta.json").read_text())
    assert meta["built_at"] == "2026-01-03T00:00:00Z"        # the latest record, not the clock


def test_rebuild_removes_stale_files(tmp_path):
    bundle = write(tmp_path / "b", [run("a"), run("b")])
    build(bundle, None, tmp_path / "o")
    assert (tmp_path / "o" / "runs" / "b.json").exists()
    (bundle / "runs" / "2026-01" / "b.json").unlink()
    build(bundle, None, tmp_path / "o")
    assert not (tmp_path / "o" / "runs" / "b.json").exists()


def test_every_file_matches_its_schema(tmp_path):
    runs = [run("a"), run("b", "t-prov"), run("c", "nope"), run("d", version=0)]
    result, out, index = states(tmp_path, runs, [score("a", 10.0), score("b", 5.0)])
    kinds = {"meta.json": "meta", "v9/index.json": "index"}
    for rel in result["sizes"]:
        parts = rel.split("/")
        kind = kinds.get(rel) or {"tasks": "task", "models": "model"}.get(parts[1] if len(parts) > 2 else "") \
            or {"runs": "run", "recent": "recent"}.get(parts[0])
        if kind:
            assert schema.check(kind, json.loads((out / rel).read_text())) == [], rel


def test_schema_checker_catches_problems():
    assert schema.check("meta", {"site_data_format": "1"})
    assert schema.check("recent", {"month": "x", "runs": [{"run_uuid": 1}]})


@pytest.mark.skipif(not SITE.exists(), reason="the portfolio site isn't checked out here")
def test_real_bundle_files_match_their_schemas(tmp_path):
    out = tmp_path / "out"
    build(SITE / "_data" / "crucible", SITE / "crucible-data" / "outputs", out, SITE / "_data" / "crucible_display.yml",
          SITE / "_data" / "crucible_fallbacks.yml")
    for rel, kind in (("meta.json", "meta"), ("v4/index.json", "index"), ("v3/index.json", "index")):
        assert schema.check(kind, json.loads((out / rel).read_text())) == [], rel
    for folder, kind in (("v4/tasks", "task"), ("v4/models", "model"), ("recent", "recent")):
        for p in sorted((out / folder).glob("*.json"))[:5]:
            assert schema.check(kind, json.loads(p.read_text())) == [], p
    for p in sorted((out / "runs").glob("*.json"))[:50]:
        assert schema.check("run", json.loads(p.read_text())) == [], p


# ----------------------------------------------------------------------------- golden parity

@pytest.fixture(scope="module")
def real_build(tmp_path_factory):
    if not (SITE.exists() and GOLDEN.exists()):
        pytest.skip("the portfolio site or the golden numbers aren't available here")
    out = tmp_path_factory.mktemp("site-data")
    result = build(SITE / "_data" / "crucible", SITE / "crucible-data" / "outputs", out, SITE / "_data" / "crucible_display.yml",
                   SITE / "_data" / "crucible_fallbacks.yml")
    return result, out


def test_golden_v4_state_counts(real_build):
    result, out = real_build
    c = result["counts"]["v4"]
    assert (c["counted"], c["counted_scored"], c["unscored"]) == (1674, 1666, 8)
    assert (c["older"], c["retired"], c["invalid"], c["provisional"], c["harness"], c["withdrawn"]) == (166, 92, 62, 54, 4, 1)
    assert c["unknown_task"] == 0 and c["runs"] == 2053
    assert json.loads((out / "meta.json").read_text())["suites"][0]["id"] == "v4"


def test_hidden_suites_are_not_built(real_build):
    result, out = real_build
    assert sorted(result["counts"]) == ["v3", "v4"] and not (out / "v1").exists()


def test_golden_leaderboard_numbers(real_build):
    """Time, cost, tps, run counts and task means of every legacy configuration that maps to exactly one setup."""
    import golden_compare
    result, out = real_build
    golden = json.loads(GOLDEN.read_text())
    pairs = {}
    for p in (out / "runs").glob("*.json"):
        r = json.loads(p.read_text())
        pairs[r["run_uuid"]] = r["setup"]
    for suite in ("v4", "v3"):
        res = golden_compare.compare(SITE / "_data" / "crucible", out, golden, suite, pairs)
        one = sum(1 for r in res["rows"] if r["one_to_one"])
        assert one >= 100, (suite, one)
        assert all(e["field"] == "cost" for e in res["expected"])
        assert res["mismatches"] == [], (suite, res["mismatches"][:5])


def test_b03_delta_is_small_and_listed(real_build):
    import golden_compare
    result, out = real_build
    pairs = {}
    for p in (out / "runs").glob("*.json"):
        r = json.loads(p.read_text())
        pairs[r["run_uuid"]] = r["setup"]
    delta = golden_compare.delta(SITE / "_data" / "crucible", pairs)
    assert delta["legacy"] == 144 and delta["setups"] == 145
    assert len(delta["split"]) == 4 and len(delta["merged"]) == 3


def test_machine_names_are_display_only(real_build):
    """Registry labels appear as `machine` / `machines`; raw host names never do; IDs and facets never carry a machine."""
    import re
    result, out = real_build
    hosts = re.compile(r"mac-168|ip-192-168|\\.local\\b", re.IGNORECASE)
    for rel in ("v4/index.json", "v3/index.json", "recent"):
        paths = [out / rel] if rel.endswith(".json") else sorted((out / rel).glob("*.json"))
        for p in paths:
            assert not hosts.search(p.read_text()), p
    for p in sorted((out / "runs").glob("*.json"))[:300]:
        text = p.read_text()
        assert "serving_host" not in text and "machine_label" not in text and not hosts.search(text.replace("outputs/", "")), p
    index = json.loads((out / "v4" / "index.json").read_text())
    names = {m["label"] for d in index["entities"]["deployments"].values() for m in d["machines"]}
    assert {"Duskfall", "Eclipse"} <= names
    assert not any(n.lower() in sid.lower() for sid in index["entities"]["setups"] for n in names)
    assert all("machine" not in s and set(s) >= {"hw"} for s in index["entities"]["setups"].values())
    dep = index["entities"]["deployments"]["local~m5-pro-48gb"]
    assert dep["label"].startswith("Apple M5 Pro, 48 GB (") and "Duskfall" in dep["label"]


def test_no_ip_addresses_anywhere_in_the_real_output(real_build):
    """Every JSON file and every copied model output: no IPv4/IPv6 address and no ip-<a>-<b>-<c>-<d> host name."""
    from crucible.sitedata import guard
    result, out = real_build
    assert (out / "outputs").is_dir() and any((out / "outputs").iterdir())
    hits = guard.scan(out)
    assert hits == [], hits[:10]


def test_guard_patterns():
    from crucible.sitedata import guard
    for bad in ("host 192.168.1.162 up", "ip-192-168-1-162", "IP-10-0-0-5", "fe80::1", "2001:db8::8a2e:370:7334", "::1",
                "1:2:3:4:5:6:7:8"):
        assert guard.scan_text(bad), bad
    for ok in ("version 1.2.3", "12:30:45", "std::string", "1.2.3.4.5", "Duskfall", "ip-address", "0.5 seconds"):
        assert not guard.scan_text(ok), ok


def test_build_refuses_to_finish_when_output_has_an_ip(tmp_path):
    from crucible.sitedata import guard
    bundle = write(tmp_path / "b", [run("a")], [score("a", 10.0)])
    (bundle / "status").mkdir()
    (bundle / "status" / "a.json").write_text(json.dumps([{"record": "status", "run_uuid": "a", "at": "1", "valid": True,
                                                           "note": "served from ip-192-168-1-162"}]))
    with pytest.raises(guard.PrivacyError):
        build(bundle, None, tmp_path / "out")
    assert not (tmp_path / "out" / "meta.json").exists()
