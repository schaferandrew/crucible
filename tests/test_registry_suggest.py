"""Model defaults, the reasoning override, and `crucible registry suggest`."""
import copy
import glob
import json
from pathlib import Path

import pytest
import yaml

from crucible import bundle, cli, hostnames, registry, registry_suggest
from tests.test_registry import REG, SITE, _tweak, run


def _with_defaults(*defaults, overrides=None):
    data = copy.deepcopy(REG.data)
    for m in data["models"]["models"]:
        if m["id"] == "qwen/qwen3.5-9b":
            m["defaults"] = list(defaults)
    if overrides:
        data["overrides"] = {"runs": overrides}
    return registry.Registry(data)


DEFAULT = {"match": {"quant": "Q4_0"}, "packager": "unsloth", "format": "gguf", "reasoning": "on", "reason": "evidence"}


def test_a_model_default_fills_only_what_the_run_recorded_nothing_for():
    reg = _with_defaults(DEFAULT)
    assert reg.problems() == []
    blank = reg.resolve_run(run(publisher=None, fmt=None, quant="q4_0"))
    assert (blank.packager, blank.format, blank.reasoning_level) == ("unsloth", "gguf", "on")
    assert {blank.sources[k] for k in ("packager_from", "format_from", "reasoning_from")} == {"registry"}
    assert sum("registry's default" in n for n in blank.notes) == 3 and "evidence" in blank.notes[0]
    # Recorded values stay; a run that requested a level keeps it; another quant doesn't match
    kept = reg.resolve_run(run(publisher="bartowski", fmt="mlx", quant="q4_0", requested="off"))
    assert (kept.packager, kept.format, kept.reasoning_level) == ("bartowski", "mlx", "off")
    assert kept.sources["packager_from"] == "recorded" and kept.sources["reasoning_from"] == "recorded"
    other = reg.resolve_run(run(publisher=None, fmt=None, quant="q8_0"))
    assert (other.packager, other.reasoning_level) == (None, "default")
    resolved = reg.resolve_run(run(publisher=None, quant="q4_0", resolved="low"))
    assert resolved.reasoning_level == "low" and resolved.sources["reasoning_from"] == "recorded"
    # A default never reaches another model
    assert REG.resolve_run(run(publisher=None, fmt=None, quant="q4_0")).packager is None


def test_default_problems_and_the_reasoning_override():
    def bad(d):
        d["models"]["models"][0]["defaults"] = [{"match": {"colour": "x"}, "reason": ""},
                                                {"match": {"quant": "q4_0"}, "packager": "nobody", "reason": "r"}]
    found = _tweak(bad)
    assert any("no reason" in p for p in found) and any("can't match on 'colour'" in p for p in found)
    assert any("sets nothing" in p for p in found) and any("isn't in packagers.yaml" in p for p in found)
    reg = _with_defaults(overrides=[{"run_uuids": ["u1"], "set": {"reasoning": "High"}, "reason": "checked the log"}])
    res = reg.resolve_run(run(requested="off"))
    assert reg.problems() == [] and res.reasoning_level == "high" and res.sources["reasoning_from"] == "override"
    assert any("reasoning level set to high by an override: checked the log" in n for n in res.notes)
    models = {**REG.files()["models"], "models": [
        {"id": "a/b", "maker": "a", "defaults": [{"match": {"quant": "q"}, "packager": "p", "reason": "r"}]}]}
    assert bundle.record_problems("registry-models", models) == []


def _gap(uuid, base="qwen/qwen3.5-9b", **kw):
    r = run(base=base, requested=kw.pop("requested", "default"), **kw)
    r["run_uuid"] = uuid
    return r


def test_suggest_proposes_defaults_only_for_unanimous_evidence():
    evidence = [_gap(f"e{i}", publisher="unsloth", fmt="gguf", quant="Q4_0", resolved="on") for i in range(2)]
    gaps = [_gap(f"g{i}", publisher=None, fmt=None, quant="Q4_0") for i in range(3)]
    found = registry_suggest.suggest(evidence + gaps, REG)
    entry, = found["defaults"]["qwen/qwen3.5-9b"]
    assert entry["match"] == {"quant": "q4_0"} and entry["packager"] == "unsloth" and entry["reasoning"] == "on"
    # The format is already read from the quant (Q4_0), so no default is proposed for it
    assert "format" not in entry and "all 2 runs" in entry["reason"] and "3 runs recorded none" in entry["reason"]
    # Applying it moves the gaps into the evidence's setup
    after = registry_suggest.applied(REG, found)
    assert after.problems() == []
    assert {after.resolve_run(r).setup_id for r in evidence + gaps} == {after.resolve_run(evidence[0]).setup_id}
    # One run of evidence, or a disagreement, proposes nothing
    assert registry_suggest.suggest(evidence[:1] + gaps, REG)["defaults"] == {}
    split = [evidence[0], _gap("x", publisher="bartowski", fmt="gguf", quant="Q4_0", resolved="off")] + gaps
    assert registry_suggest.suggest(split, REG)["defaults"] == {}
    # Evidence that requested a fixed level says nothing about the default level
    fixed = [_gap(f"f{i}", publisher="unsloth", fmt="gguf", quant="Q4_0", requested="off", resolved="off") for i in range(3)]
    entry, = registry_suggest.suggest(fixed + gaps, REG)["defaults"]["qwen/qwen3.5-9b"]
    assert "reasoning" not in entry and entry["packager"] == "unsloth"


def test_suggest_overrides_need_exactly_one_artifact_or_machine():
    full = [_gap(f"f{i}", publisher="bartowski", fmt="gguf", quant="Q4_K_S") for i in range(2)]
    blank = _gap("b1", publisher=None, fmt=None, quant=None)
    override, = registry_suggest.suggest(full + [blank], REG)["overrides"]
    assert override["run_uuids"] == ["b1"] and override["set"] == {"packager": "bartowski", "format": "gguf", "quant": "q4_k_s"}
    assert "only artifact" in override["reason"]
    # Two artifacts on that hardware and harness: nothing is proposed
    two = full + [_gap("t1", publisher="bartowski", fmt="gguf", quant="Q8_0")]
    assert registry_suggest.suggest(two + [blank], REG)["overrides"] == []
    # A hardware-less run served by the machine that ran it already resolves through its machine_id, so
    # nothing is proposed; one served over a link carries the harness machine's id and is never guessed
    ghost = _gap("m1", device=None, label=None, key=None, machine_id="m_09df208c24c5")
    linked = _gap("m2", device=None, label=None, key=None, machine_id="m_09df208c24c5", served_via="LM Link")
    unknown = _gap("m3", device=None, label=None, key=None, machine_id="m_unknown")
    assert REG.resolve_run(ghost).machine == "ironwood" and REG.resolve_run(linked).machine is None
    assert registry_suggest.suggest([ghost, linked, unknown], REG)["overrides"] == []


def test_the_suggest_command_prints_yaml_without_addresses(capsys, monkeypatch, tmp_path):
    site = tmp_path / "site"
    records = [_gap(f"e{i}", publisher="unsloth", fmt="gguf", quant="Q4_0", resolved="on") for i in range(2)]
    records.append(_gap("g1", publisher=None, fmt=None, quant="Q4_0", label="ip-10-0-0-1"))
    for r in records:
        path = site / "runs" / "2026-01" / f"{r['run_uuid']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(r), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["crucible", "registry", "suggest", "--bundle", str(site)])
    cli.main()
    out = capsys.readouterr().out
    parsed = yaml.safe_load(out)
    assert parsed["defaults"]["qwen/qwen3.5-9b"]["defaults"][0]["packager"] == "unsloth"
    assert not hostnames.contains_ip(out)
    assert not (site / "registry").exists()   # it only prints


@pytest.mark.skipif(not (SITE / "runs").exists(), reason="the site repo's published bundle isn't here")
def test_suggestions_on_the_published_runs_are_valid_and_reunify_some():
    runs = [json.loads(Path(p).read_text(encoding="utf-8")) for p in glob.glob(str(SITE / "runs" / "*" / "*.json"))]
    found = registry_suggest.suggest(runs, REG)
    after = registry_suggest.applied(REG, found)
    assert after.problems() == []
    before = {r["run_uuid"]: REG.resolve_run(r).setup_id for r in runs}
    now = {r["run_uuid"]: after.resolve_run(r).setup_id for r in runs}
    # The first round of suggestions is already in registry/; what's left is small and still valid
    assert len(set(now.values())) <= len(set(before.values()))
