"""The registry (registry/*.yaml): loading, checks, the resolver, derived IDs and publish integration."""
import collections
import copy
import glob
import json
import re
from pathlib import Path

import pytest
import yaml

from crucible import bundle, origin, registry

REG = registry.load()
SITE = Path(__file__).resolve().parents[2] / "schaferandrew.github.io" / "_data" / "crucible"
if not SITE.exists():
    SITE = Path("/Users/schafer/Developer/schaferandrew.github.io/_data/crucible")


def run(base="qwen/qwen3.5-9b", where="local", provider=None, publisher="lmstudio-community", fmt="gguf", quant="Q4_K_M",
        requested="default", resolved=None, harness="direct", device="Duskfall", label="Duskfall", key="m5-pro-48gb",
        machine_id=None, served_via=None, origin_maker=None, version=3, **extra):
    cloud = where == "cloud"
    record = {
        "record": "run", "format_version": version, "run_uuid": "u1", "elapsed_s": 3600.0,
        "harness": {"id": harness},
        "model": {"base": base, "publisher": publisher, "format": fmt, "quant": quant,
                  "variant_key": "ignored|ignored|ignored|ignored",
                  "reasoning": {"requested": requested, "resolved": resolved},
                  "origin": {"maker": origin_maker, "source": "none"}},
        "endpoint": {"where": where, "provider": provider or ("openrouter" if cloud else "lmstudio"),
                     "device": None if cloud else device, "served_via": served_via},
        "hardware": None if cloud else {"key": key, "label": label},
        "metrics": {"cost_usd": 0.5 if cloud else 0.0},
        "provenance": {"machine_id": machine_id},
    }
    record.update(extra)
    return record


# --------------------------------------------------------------------------
# Loading and checks
# --------------------------------------------------------------------------

def test_the_repo_registry_has_no_problems():
    assert REG.problems() == []
    assert len(REG.models) >= 40 and "ibm-granite" in REG.makers


def test_publish_writes_the_registry_and_the_bundle_form_loads_the_same(tmp_path):
    pub = bundle.Publisher(tmp_path, tmp_path / "outputs")
    pub.add_registry()
    assert pub.errors == [] and pub.counts["registry"] == 5
    for name in registry.NAMES:
        data = json.loads((tmp_path / "registry" / f"{name}.json").read_text())
        assert data["record"] == "registry" and data["format_version"] == 3 and data["name"] == name
    for source in (tmp_path, tmp_path / "registry"):
        loaded = registry.load(source)
        assert loaded.data == REG.data and loaded.problems() == []
    # Publishing again changes nothing
    again = bundle.Publisher(tmp_path, tmp_path / "outputs")
    again.add_registry()
    assert again.counts["registry"] == 0


def test_registry_files_validate_against_their_schemas():
    for name, data in REG.files().items():
        assert bundle.record_problems(f"registry-{name}", data) == []
    assert bundle.record_problems("registry-models", {"record": "registry", "format_version": 3, "name": "models",
                                                      "models": [{"id": 3}]})


def _tweak(fn):
    data = copy.deepcopy(REG.data)
    fn(data)
    return registry.Registry(data).problems()


def test_problems_name_each_kind_of_mistake():
    assert any("more than once" in p for p in _tweak(lambda d: d["models"]["models"].append(dict(d["models"]["models"][0]))))
    assert any("more than once" in p for p in _tweak(lambda d: d["makers"]["makers"].append({"id": "qwen", "label": "Q"})))

    def dup_alias(d):
        models = {m["id"]: m for m in d["models"]["models"]}
        models["qwen/qwen3.5-9b"]["aliases"] = [{"base": "laguna-xs-2.1", "reason": "x"}]
    assert any("alias 'laguna-xs-2.1' appears more than once" in p for p in _tweak(dup_alias))

    def no_reason(d):
        d["models"]["models"][0]["aliases"] = [{"base": "olmo", "reason": " "}]
    assert any("has no reason" in p for p in _tweak(no_reason))

    def bad_maker(d):
        d["models"]["models"][0]["maker"] = "nobody"
    assert any("isn't in makers.yaml" in p for p in _tweak(bad_maker))

    def prefix(d):
        d["models"]["models"][0]["maker"] = "qwen"
    assert any("prefix doesn't match" in p for p in _tweak(prefix))

    def bad_hardware(d):
        d["machines"]["machines"][0]["hardware"] = "nope"
    assert any("isn't in the hardware list" in p for p in _tweak(bad_hardware))

    def bad_packager(d):
        d["models"]["models"][0]["packager"] = "nobody"
    assert any("isn't in packagers.yaml" in p for p in _tweak(bad_packager))

    def host_clash(d):
        d["machines"]["machines"][1]["host_aliases"].append("duskfall")
    assert any("host alias" in p for p in _tweak(host_clash))

    def alias_is_id(d):
        d["models"]["models"][0]["aliases"] = [{"base": "Qwen/Qwen3.5-9B", "reason": "x"}]
    assert any("another model's id" in p for p in _tweak(alias_is_id))

    def overrides(d):
        d["overrides"] = {"runs": [{"run_uuids": ["a"], "set": {"nonsense": 1}, "reason": ""},
                                   {"run_uuids": ["a"], "set": {"model": "no/such"}, "reason": "r"}]}
    found = _tweak(overrides)
    assert any("no reason" in p for p in found) and any("can't set 'nonsense'" in p for p in found)
    assert any("more than one override" in p for p in found) and any("isn't in models.yaml" in p for p in found)


# --------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------

def test_a_plain_local_run_resolves_from_what_it_recorded():
    res = REG.resolve_run(run(origin_maker="qwen"))
    assert (res.model_id, res.maker, res.packager, res.format, res.quant) == (
        "qwen/qwen3.5-9b", "qwen", "lmstudio-community", "gguf", "q4_k_m")
    assert (res.where, res.provider, res.machine, res.hardware_key, res.harness) == (
        "local", "lmstudio", "duskfall", "m5-pro-48gb", "direct")
    assert res.sources == {"model_from": "recorded", "maker_from": "recorded", "packager_from": "recorded",
                           "format_from": "recorded", "machine_from": "device", "hardware_from": "recorded"}
    assert res.notes == []


def test_variant_key_is_never_read():
    a = REG.resolve_run(run())
    b = REG.resolve_run(run(**{"model": {**run()["model"], "variant_key": "x/y|z|mlx|4bit"}}))
    assert a == b


def test_an_alias_corrects_the_model_and_says_why():
    res = REG.resolve_run(run(base="ornith-1.5-9b", publisher=None, fmt=None, quant=None))
    assert res.model_id == "ornith-ai/ornith-1.5-9b" and res.maker == "ornith-ai"
    assert res.sources["model_from"] == "alias" and res.sources["maker_from"] == "registry"
    assert res.notes[0].startswith("recorded as model ornith-1.5-9b; corrected to ornith-ai/ornith-1.5-9b: ")


def test_aliases_match_exactly_and_the_id_matches_in_any_case():
    assert REG.resolve_run(run(base="Qwen/Qwen3.5-9B")).sources["model_from"] == "recorded"
    unknown = REG.resolve_run(run(base="Some Lab/New Model:7b", publisher=None))
    assert unknown.model_id == "unknown/some-lab/new-model-7b"
    assert (unknown.sources["model_from"], unknown.maker, unknown.sources["maker_from"]) == ("unknown", None, "unknown")
    assert REG.resolve_run(run(base=None)).model_id == "unknown/unrecorded"


def test_a_known_model_keeps_the_registry_maker_and_a_disagreement_is_noted():
    res = REG.resolve_run(run(origin_maker="somebody"))
    assert res.maker == "qwen" and res.sources["maker_from"] == "registry"
    assert any("recorded maker somebody" in n for n in res.notes)
    assert REG.resolve_run(run()).sources["maker_from"] == "registry"


def test_packager_spellings_normalise_and_the_registry_fills_a_blank():
    assert REG.resolve_run(run(base="qwen2.5-0.5b-instruct", publisher="Qwen")).packager == "qwen"
    res = REG.resolve_run(run(base="~openai/gpt-luna-latest", where="cloud", publisher="~openai", fmt=None, quant=None))
    assert res.packager == "openai" and any("read as openai" in n for n in res.notes)
    # The alias's packager fills a run that recorded none, and only that alias's runs get it
    splash = REG.resolve_run(run(base="qwen3.8-27b-splash", publisher=None, fmt="splash", quant=None))
    assert (splash.packager, splash.sources["packager_from"]) == ("incoai", "registry")
    plain = REG.resolve_run(run(base="qwen/qwen3.8-27b", publisher=None))
    assert (plain.packager, plain.sources["packager_from"]) == (None, "none")
    assert REG.resolve_run(run(publisher="Some-Packager")).packager == "some-packager"


@pytest.mark.parametrize("quant,fmt", [
    ("Q4_K_M", "gguf"), ("q4_0", "gguf"), ("Q8_0", "gguf"), ("IQ2_XS", "gguf"), ("Q6_K", "gguf"), ("q4", "gguf"),
    ("4bit", "mlx"), ("mlx-8bit", "mlx"), ("6BIT", "mlx"),
    ("MXFP4", None), ("bf16", None), ("Q4_K_M_", None), ("4-bit", None), ("q", None), (None, None), ("", None),
])
def test_format_is_read_from_the_quant_only_for_local_runs_without_one(quant, fmt):
    res = REG.resolve_run(run(fmt=None, quant=quant))
    assert res.format == fmt
    assert res.sources["format_from"] == ("quant" if fmt else "none")
    assert (res.quant == quant.lower()) if quant else res.quant is None
    assert registry.format_from_quant(quant) == fmt
    assert (any("read as" in n for n in res.notes)) == bool(fmt)


def test_a_recorded_format_beats_the_quant_and_cloud_runs_are_api():
    res = REG.resolve_run(run(fmt="splash", quant="Q4_K_M"))
    assert (res.format, res.sources["format_from"]) == ("splash", "recorded")
    cloud = REG.resolve_run(run(where="cloud", fmt=None, quant="Q4_K_M", publisher="qwen"))
    assert (cloud.format, cloud.sources["format_from"], cloud.machine, cloud.hardware_key) == ("api", "cloud", None, None)
    assert cloud.sources["machine_from"] == "none" and cloud.sources["hardware_from"] == "none"


def test_the_serving_machine_comes_from_the_device_then_the_hardware_label():
    assert REG.resolve_run(run(device="Whitehall", label="Whitehall", key="rtx-5070-ti-16gb")).machine == "whitehall"
    res = REG.resolve_run(run(device=None, label="Mac-168"))
    assert (res.machine, res.sources["machine_from"]) == ("duskfall", "label")
    # The machine that ran the harness (provenance.machine_label) is not the serving machine
    res = REG.resolve_run(run(device="Whitehall", label="Whitehall", key=None,
                              provenance={"machine_label": "Ironwood", "machine_id": "m_f554f42a74a5"}))
    assert res.machine == "whitehall"


def test_machine_id_only_names_the_serving_machine_when_it_served_itself():
    alone = REG.resolve_run(run(device=None, label=None, key=None, machine_id="m_09df208c24c5"))
    assert (alone.machine, alone.sources["machine_from"], alone.hardware_key) == ("ironwood", "machine_id", "m1-pro-32gb")
    assert alone.sources["hardware_from"] == "machine"
    linked = REG.resolve_run(run(device=None, label=None, key=None, machine_id="m_09df208c24c5", served_via="LM Link"))
    assert (linked.machine, linked.hardware_key) == (None, None)


def test_the_hardware_key_is_recorded_else_the_machines():
    res = REG.resolve_run(run(key=None))
    assert (res.hardware_key, res.sources["hardware_from"]) == ("m5-pro-48gb", "machine")
    # Eclipse has no hardware in the registry, so it stays unrecorded
    eclipse = REG.resolve_run(run(device="Eclipse", label="Eclipse", key=None))
    assert (eclipse.machine, eclipse.hardware_key) == ("eclipse", None)
    clash = REG.resolve_run(run(device="Duskfall", key="m1-pro-32gb"))
    assert clash.hardware_key == "m1-pro-32gb" and any("differs from duskfall's" in n for n in clash.notes)


@pytest.mark.parametrize("requested,resolved,level", [
    ("default", None, "default"), (None, None, "default"), ("default", "on", "on"), ("off", "on", "off"),
    ("high", None, "high"), ("default", "xhigh", "xhigh"), ("low", "low", "low")])
def test_reasoning_level_rule(requested, resolved, level):
    assert REG.resolve_run(run(requested=requested, resolved=resolved)).reasoning_level == level


def test_overrides_apply_per_run_with_their_reason():
    data = copy.deepcopy(REG.data)
    data["overrides"] = {"runs": [{"run_uuids": ["u1"], "reason": "checked the GGUF header",
                                   "set": {"format": "gguf", "quant": "MXFP4", "packager": "unsloth",
                                           "machine": "ironwood", "model": "qwen/qwen3.6-35b-a3b"}}]}
    reg = registry.Registry(data)
    assert reg.problems() == []
    res = reg.resolve_run(run(fmt=None, quant=None, publisher=None, device="Whitehall", key=None))
    assert (res.model_id, res.format, res.quant, res.packager, res.machine, res.hardware_key) == (
        "qwen/qwen3.6-35b-a3b", "gguf", "mxfp4", "unsloth", "ironwood", "m1-pro-32gb")
    assert {res.sources[k] for k in ("model_from", "format_from", "packager_from", "machine_from")} == {"override"}
    assert any("checked the GGUF header" in n for n in res.notes)
    assert REG.resolve_run(run()).sources["model_from"] == "recorded"


def test_a_format_4_record_resolves():
    record = {
        "record": "run", "format_version": 4, "run_uuid": "u4", "elapsed_s": 1800,
        "harness": {"id": "pi"},
        "model": {"id": "qwen/qwen3.5-9b", "raw_base": "qwen/qwen3.5-9b", "maker": "qwen", "packager": "bartowski",
                  "format": "mlx", "format_source": "runtime", "quant": "4bit",
                  "reasoning": {"requested": "default", "resolved": "on"}},
        "endpoint": {"where": "local", "provider": "lmstudio"},
        "serving_host": "Ironwood", "harness_host": "Duskfall",
        "hardware": {"key": "m1-pro-32gb"},
    }
    res = REG.resolve_run(record)
    assert res.setup_id == "qwen/qwen3.5-9b~bartowski~mlx~4bit~r-on~pi@local~m1-pro-32gb"
    assert (res.machine, res.sources["machine_from"], res.sources["model_from"], res.sources["maker_from"]) == (
        "ironwood", "serving_host", "recorded", "recorded")
    # A canonical id the registry doesn't know falls back to the raw base
    assert REG.resolve_run({**record, "model": {**record["model"], "id": "nope/x"}}).model_id == "qwen/qwen3.5-9b"


# --------------------------------------------------------------------------
# IDs
# --------------------------------------------------------------------------

def test_ids_compose_from_resolved_parts():
    res = REG.resolve_run(run(publisher="lmstudio-community"))
    assert res.artifact_id == "qwen/qwen3.5-9b~lmstudio-community~gguf~q4_k_m"
    assert res.variant_id == "qwen/qwen3.5-9b~lmstudio-community~gguf~q4_k_m~r-default~direct"
    assert res.deployment_id == "local~m5-pro-48gb"
    assert res.setup_id == res.variant_id + "@" + res.deployment_id and not res.unrecorded
    cloud = REG.resolve_run(run(base="openai/gpt-6-luna", where="cloud", fmt=None, quant=None, publisher="openai",
                                harness="opencode", requested="high"))
    assert cloud.artifact_id == "openai/gpt-6-luna~api"
    assert cloud.setup_id == "openai/gpt-6-luna~api~r-high~opencode@cloud~openrouter" and not cloud.unrecorded


def test_unrecorded_parts_are_named_never_guessed():
    res = REG.resolve_run(run(publisher=None, fmt=None, quant=None, device=None, label=None, key=None))
    assert res.artifact_id == "qwen/qwen3.5-9b~unrecorded~unrecorded~unrecorded"
    assert res.deployment_id == "local~unrecorded" and res.unrecorded
    assert REG.resolve_run(run(where="cloud", provider=None, publisher=None, fmt=None, quant=None)
                           ).deployment_id == "cloud~openrouter"
    assert REG.resolve_run(run(harness=None)).variant_id.endswith("~r-default~unrecorded")


def test_ids_are_url_safe_and_deterministic():
    odd = run(base="Odd Lab/Model v1:7B@x", publisher="Some Packager!", fmt="GGUF", quant="Q4 K/M", harness="My Harness")
    a, b = REG.resolve_run(odd), REG.resolve_run(copy.deepcopy(odd))
    assert a.setup_id == b.setup_id
    assert re.fullmatch(r"[a-z0-9._/~@-]+", a.setup_id), a.setup_id


# --------------------------------------------------------------------------
# Energy cost
# --------------------------------------------------------------------------

def test_energy_cost_rules():
    r = run(key="m5-pro-48gb")
    assert REG.energy_cost(r) == pytest.approx(60 * 3600 / 3.6e6 * 0.183)
    # A local run's recorded cost (0) is ignored; a missing key is read from the machine
    assert REG.energy_cost(run(key=None)) == pytest.approx(60 * 3600 / 3.6e6 * 0.183)
    assert REG.energy_cost(run(device="Eclipse", label="Eclipse", key=None)) is None
    assert REG.energy_cost(run(where="cloud", fmt=None, quant=None)) == 0.5
    cloud = run(where="cloud")
    cloud["metrics"] = {}
    assert REG.energy_cost(cloud) is None


# --------------------------------------------------------------------------
# corrections.json is generated from the registry
# --------------------------------------------------------------------------

def test_generated_corrections_match_the_old_corrections_yaml():
    legacy = yaml.safe_load((Path(__file__).parent / "fixtures" / "corrections.legacy.yaml").read_text(encoding="utf-8"))
    made = bundle.corrections(REG)
    assert made["record"] == "corrections" and made["format_version"] == 3
    key = lambda m: m["base"]
    assert sorted(made["models"], key=key) == sorted(legacy["models"], key=key)
    assert sorted(made["publishers"], key=lambda p: p["from"]) == sorted(legacy["publishers"], key=lambda p: p["from"])
    assert bundle.record_problems("corrections", made) == []


def test_publish_check_reports_registry_gaps(tmp_path):
    site = tmp_path / "site"
    for i, (base, device, label, key) in enumerate([("qwen/qwen3.5-9b", "Duskfall", "Duskfall", "m5-pro-48gb"),
                                                    ("mystery/model-1", "Eclipse", "Eclipse", None),
                                                    ("qwen/qwen3.5-9b", None, "ip-10-0-0-1", None)]):
        record = run(base=base, device=device, label=label, key=key, run_uuid=f"u{i}", started_at="2026-01-01")
        record["run_uuid"] = f"u{i}"
        record["provenance"] = {"content_hash": None, "machine_id": None}
        if i == 2:
            record["local"] = {}
        path = site / "runs" / "2026-01" / f"u{i}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record), encoding="utf-8")
    assert "model.base 'mystery/model-1' (1 runs) isn't a registry model" in bundle.base_warnings(site)[0]
    assert len(bundle.base_warnings(site)) == 1
    machines = " ".join(bundle.machine_warnings(site))
    assert "2 local runs resolve to no hardware key" in machines and "1 local runs resolve to no machine" in machines
    assert "Eclipse (1)" in machines and "ip-10-0-0-1 (1)" in machines
    legacy = " ".join(bundle.legacy_warnings(site))
    assert "1 runs carry a `local` key" in legacy and "3 runs have a null content_hash" in legacy


# --------------------------------------------------------------------------
# Record time
# --------------------------------------------------------------------------

def test_origin_fills_a_missing_maker_from_the_registry():
    # The model key says no maker and nothing else answers: the registry knows this base
    result = origin.capture("lmstudio/laguna-xs-2.1", {"provider": "lmstudio"})
    assert result["maker"] == "poolside" and result["source"] == "registry"
    # A maker another source gave is kept, and the registry isn't named
    assert origin.capture("lmstudio/qwen/qwen3.5-9b", {})["source"] == "lmstudio-key"
    # An unknown base stays unknown
    assert origin.capture("lmstudio/mystery-9b", {})["maker"] is None


# --------------------------------------------------------------------------
# All published runs
# --------------------------------------------------------------------------

@pytest.mark.skipif(not (SITE / "runs").exists(), reason="the site repo's published bundle isn't here")
def test_every_published_run_resolves():
    runs = [json.loads(Path(p).read_text(encoding="utf-8")) for p in glob.glob(str(SITE / "runs" / "*" / "*.json"))]
    resolutions = [REG.resolve_run(r) for r in runs]
    n = len(resolutions)
    assert n > 2000
    recorded = sum(1 for r in runs if (r["model"].get("origin") or {}).get("maker")) / n
    resolved = sum(1 for x in resolutions if x.maker) / n
    assert resolved >= 0.61 and resolved >= recorded
    assert all(x.setup_id for x in resolutions)
    assert all(re.fullmatch(r"[a-z0-9._/~@-]+", x.setup_id) for x in resolutions)
    local = [x for x in resolutions if x.where == "local"]
    setups = {x.setup_id for x in resolutions}
    loose = [x for x in resolutions if x.unrecorded]
    dist = lambda key: dict(collections.Counter(x.sources[key] for x in resolutions))
    print(f"\nmaker coverage: recorded {recorded:.1%} -> resolved {resolved:.1%} of {n} runs"
          f"\nmodel_from {dist('model_from')}\nmaker_from {dist('maker_from')}\npackager_from {dist('packager_from')}"
          f"\nformat_from {dist('format_from')}\nmachine_from {dist('machine_from')}\nhardware_from {dist('hardware_from')}"
          f"\nlocal runs with a machine: {sum(1 for x in local if x.machine)}/{len(local)}, with a hardware key: "
          f"{sum(1 for x in local if x.hardware_key)}/{len(local)}"
          f"\n{len(setups)} setups; {len(loose)} runs in {len({x.setup_id for x in loose})} setups with an unrecorded part")
    assert dist("model_from").get("unknown", 0) == 0
