"""The bundle manifest and its rules, `publish --from-bundle`, and format-4 run records."""
import json
import shutil
from pathlib import Path

import pytest

from crucible import bundle, manifest, registry, runrecord, workspace
from tests.records import run_meta, write_run
from tests.test_bundle import _runs, _tree

# The published bundle, read only: next to this checkout (or its worktree), else under ~/Developer
_HERE = Path(__file__).resolve()
REAL_BUNDLE = next((d / "schaferandrew.github.io" / "_data" / "crucible"
                    for d in [*_HERE.parents, Path.home() / "Developer"]
                    if (d / "schaferandrew.github.io" / "_data" / "crucible" / "runs").is_dir()),
                   _HERE.parents[2] / "schaferandrew.github.io" / "_data" / "crucible")
REAL_OUTPUTS = REAL_BUNDLE.parents[1] / "crucible-data" / "outputs"


# --------------------------------------------------------------------------
# The rules (pure)
# --------------------------------------------------------------------------

def test_decide_rules():
    known = manifest.entry("sha256:a", "runs/2026-01/x.json")
    assert manifest.decide(None, "sha256:a")[0] == manifest.ADD
    assert manifest.decide(known, "sha256:a") == (manifest.NOOP, None)
    verdict, why = manifest.decide(known, "sha256:b")
    assert verdict == manifest.REJECT and "sha256:a" in why and "sha256:b" in why
    assert manifest.decide(known, None)[0] == manifest.REJECT


def test_decide_null_hash_is_the_same_only_by_bytes():
    legacy = manifest.entry(None, "runs/2026-01/x.json")
    assert manifest.decide(legacy, None, identical_bytes=True)[0] == manifest.NOOP
    assert manifest.decide(legacy, None, identical_bytes=False)[0] == manifest.REJECT
    assert manifest.decide(legacy, None)[0] == manifest.REJECT
    assert manifest.decide(legacy, "sha256:a", identical_bytes=True)[0] == manifest.REJECT


def test_dump_is_sorted_and_stable():
    a = {**manifest.empty(), "runs": {"b": manifest.entry("h", "p", scores=["r2.checks", "r1.checks"]), "a": manifest.entry(None, "q")}}
    b = {**manifest.empty(), "runs": {"a": manifest.entry(None, "q"), "b": manifest.entry("h", "p", scores=["r1.checks", "r2.checks"])}}
    assert manifest.dump(a) == manifest.dump(b)
    assert list(json.loads(manifest.dump(a))["runs"]) == ["a", "b"]


def test_problems_names_missing_extra_and_mismatched_runs():
    listed = {**manifest.empty(), "runs": {"a": manifest.entry("h1", "runs/a.json"), "b": manifest.entry("h2", "runs/b.json"),
                                          "c": manifest.entry("h3", "runs/c.json", scores=["r1.checks"])}}
    found = {"a": manifest.entry("h1", "runs/a.json"), "c": manifest.entry("hX", "runs/c.json"), "d": manifest.entry("h4", "runs/d.json")}
    text = "\n".join(manifest.problems(listed, found))
    assert "b is listed but its run file is missing" in text
    assert "d has a run file but isn't listed" in text
    assert "c content hash" in text and "c score records differ" in text
    assert manifest.problems(listed, {k: v for k, v in listed["runs"].items()}) == []


# --------------------------------------------------------------------------
# publish writes and keeps the manifest
# --------------------------------------------------------------------------

def test_publish_writes_a_manifest_and_republishing_changes_nothing(tmp_path):
    runs, to = _runs(tmp_path), tmp_path / "bundle"
    outputs = bundle.default_outputs(to)
    first = bundle.publish(runs, to, outputs, submitter="andrew")
    assert first.errors == []
    data = json.loads((to / manifest.FILE).read_text(encoding="utf-8"))
    assert data["record"] == "manifest" and list(data["runs"]) == sorted(data["runs"]) and len(data["runs"]) == 2
    entry = data["runs"]["00000000-0000-4000-8000-000000000000"]
    assert entry["path"] == "runs/2026-01/00000000-0000-4000-8000-000000000000.json" and entry["submitter"] == "andrew"
    assert entry["content_hash"].startswith("sha256:") and len(entry["scores"]) == 1 and entry["status_count"] == 0
    before = _tree(tmp_path)
    second = bundle.publish(runs, to, outputs, submitter="someone-else")
    assert second.errors == [] and second.rejected == [] and not any(second.counts.values())
    assert _tree(tmp_path) == before
    assert bundle.check_folder(to, outputs) == []


def test_rescoring_and_status_update_the_manifest_without_touching_the_run(tmp_path):
    runs, to = _runs(tmp_path, 1), tmp_path / "bundle"
    outputs = bundle.default_outputs(to)
    bundle.publish(runs, to, outputs)
    (run_dir,) = runrecord.run_dirs(runs)
    score = runrecord.scores(run_dir)[0]
    runrecord.write_score(run_dir, {**score, "rubric_version": score["rubric_version"] + 1})
    runrecord.add_status(run_dir, score["run_uuid"], invalid={"reason": "stale"})
    run_file = next((to / "runs").rglob("*.json"))
    run_bytes = run_file.read_bytes()
    pub = bundle.publish(runs, to, outputs)
    assert pub.errors == [] and (pub.counts["scores"], pub.counts["status"]) == (1, 1)
    assert run_file.read_bytes() == run_bytes
    (entry,) = json.loads((to / manifest.FILE).read_text())["runs"].values()
    assert len(entry["scores"]) == 2 and entry["status_count"] == 1
    assert bundle.check_folder(to, outputs) == []


def test_a_changed_run_is_rejected_with_the_hash_in_the_message(tmp_path):
    runs, to = _runs(tmp_path, 1), tmp_path / "bundle"
    outputs = bundle.default_outputs(to)
    bundle.publish(runs, to, outputs)
    before = _tree(tmp_path / "bundle")
    (run_dir,) = runrecord.run_dirs(runs)
    (run_dir / "stdout.txt").write_text("a different answer", encoding="utf-8")
    pub = bundle.publish(runs, to, outputs)
    assert len(pub.rejected) == 1 and "sha256:" in pub.rejected[0] and "never overwritten" in pub.rejected[0]
    assert _tree(tmp_path / "bundle") == before


def test_publish_adopts_a_folder_that_has_no_manifest_yet(tmp_path):
    runs, to = _runs(tmp_path), tmp_path / "bundle"
    outputs = bundle.default_outputs(to)
    bundle.publish(runs, to, outputs)
    (to / manifest.FILE).unlink()
    pub = bundle.publish(runs, to, outputs)
    assert pub.errors == [] and not any(pub.counts.values()) and (to / manifest.FILE).exists()


def test_check_reports_manifest_drift(tmp_path):
    runs, to = _runs(tmp_path), tmp_path / "bundle"
    outputs = bundle.default_outputs(to)
    bundle.publish(runs, to, outputs)
    path = to / manifest.FILE
    data = json.loads(path.read_text())
    gone, kept = sorted(data["runs"])
    data["runs"]["ffffffff-0000-4000-8000-000000000000"] = data["runs"][gone]      # listed, no file
    data["runs"][kept]["content_hash"] = "sha256:" + "0" * 64                        # hash differs from its file
    del data["runs"][gone]                                                          # file, but unlisted
    path.write_text(json.dumps(data))
    text = "\n".join(bundle.check_folder(to, outputs))
    assert "ffffffff-0000-4000-8000-000000000000 is listed but its run file is missing" in text
    assert f"{gone} has a run file but isn't listed" in text
    assert f"{kept} content hash" in text


# --------------------------------------------------------------------------
# publish --from-bundle
# --------------------------------------------------------------------------

def test_from_bundle_copies_byte_for_byte(tmp_path):
    runs, old = _runs(tmp_path), tmp_path / "site" / "_data" / "crucible"
    bundle.publish(runs, old, bundle.default_outputs(old))
    (old / manifest.FILE).unlink()
    new = tmp_path / "dash" / "bundle"
    report = bundle.copy_bundle(old, new, bundle.default_outputs(old), bundle.default_outputs(new))
    assert report["errors"] == [] and report["runs"] == 2 and report["verified"] == 2 and report["outputs"] == 2
    for path in old.rglob("*.json"):
        assert (new / path.relative_to(old)).read_bytes() == path.read_bytes()
    assert set(json.loads((new / manifest.FILE).read_text())["runs"]) == {p.stem for p in (old / "runs").rglob("*.json")}
    assert bundle.check_folder(new, bundle.default_outputs(new)) == []
    before = _tree(tmp_path / "dash")
    again = bundle.copy_bundle(old, new, bundle.default_outputs(old), bundle.default_outputs(new))
    assert again["errors"] == [] and again["runs"] == 0 and _tree(tmp_path / "dash") == before


def test_from_bundle_refuses_an_edited_run_and_a_missing_output(tmp_path):
    runs, old = _runs(tmp_path), tmp_path / "site" / "_data" / "crucible"
    outputs = bundle.default_outputs(old)
    bundle.publish(runs, old, outputs)
    first, second = sorted(old.rglob("runs/*/*.json"))
    record = json.loads(first.read_text())
    record["elapsed_s"] = 77.0
    first.write_text(json.dumps(record))
    (outputs / f"{second.stem}.txt").unlink()
    new = tmp_path / "dash" / "bundle"
    report = bundle.copy_bundle(old, new, outputs, bundle.default_outputs(new))
    assert len(report["errors"]) == 2 and report["runs"] == 0
    assert not (new / manifest.FILE).exists() and not list(new.rglob("runs/*/*.json"))


@pytest.mark.skipif(not (REAL_BUNDLE / "runs").is_dir(), reason="the published bundle isn't checked out next to this repo")
def test_from_bundle_on_the_real_bundle(tmp_path):
    new = tmp_path / "bundle"
    report = bundle.copy_bundle(REAL_BUNDLE, new, REAL_OUTPUTS, new / "outputs")
    run_files = sorted((REAL_BUNDLE / "runs").glob("*/*.json"))
    assert report["errors"] == [] and report["runs"] == len(run_files)
    assert report["verified"] + report["unverifiable"] == len(run_files)
    for path in REAL_BUNDLE.rglob("*.json"):
        assert (new / path.relative_to(REAL_BUNDLE)).read_bytes() == path.read_bytes()
    listed = json.loads((new / manifest.FILE).read_text())["runs"]
    assert set(listed) == {p.stem for p in run_files}
    assert {u for u, e in listed.items() if e["content_hash"] is None} == {
        p.stem for p in run_files if bundle.unverifiable(json.loads(p.read_text()))}
    assert bundle.check_folder(new, new / "outputs") == []


# --------------------------------------------------------------------------
# Format 4
# --------------------------------------------------------------------------

INFERENCE = {"provider": "lmstudio", "local": True, "same_machine": True, "quantization": "Q4_K_M",
             "format": "gguf", "publisher": "lmstudio-community"}


def _v4_runs(tmp_path, inference=INFERENCE):
    p = workspace.load_task("capitals-not-largest-city")
    meta = run_meta(p["id"], p["version"], p["rubric_version"], model="lmstudio/qwen/qwen3.5-9b", inference=inference,
                    run_uuid="00000000-0000-4000-8000-0000000000a4")
    meta["model"] = runrecord.model_record("lmstudio/qwen/qwen3.5-9b", "default", None, inference)
    meta["provenance"]["machine_label"] = "Ironwood"
    v4 = runrecord.record_v4(meta, registry.default())
    runs = tmp_path / "runs"
    write_run(runs / v4["run_path"], v4, "Australia: Canberra")
    return runs, v4


def test_record_format_is_3_unless_opted_in(monkeypatch):
    monkeypatch.delenv("CRUCIBLE_RECORD_FORMAT", raising=False)
    assert runrecord.record_format() == 3
    monkeypatch.setenv("CRUCIBLE_RECORD_FORMAT", "4")
    assert runrecord.record_format() == 4
    monkeypatch.setenv("CRUCIBLE_RECORD_FORMAT", "5")
    with pytest.raises(SystemExit):
        runrecord.record_format()


def test_format_4_record_fields(tmp_path):
    _, v4 = _v4_runs(tmp_path)
    assert v4["format_version"] == 4 and "serving_host" not in v4 and "harness_host" not in v4
    model = v4["model"]
    assert (model["id"], model["maker"], model["packager"]) == ("qwen/qwen3.5-9b", "qwen", "lmstudio-community")
    assert (model["raw_base"], model["format"], model["format_source"], model["quant"]) == ("qwen/qwen3.5-9b", "gguf", "runtime", "Q4_K_M")
    assert v4["hardware"] == {"key": "m1-pro-32gb", "chip": "Apple M1 Pro", "memory_gb": 32.0, "accelerators": [],
                              "served_remotely": False}
    assert "app" not in v4["endpoint"] and "device" not in v4["endpoint"]
    for gone in ("variant_key", "display", "publisher"):
        assert gone not in model
    assert not {"submitter", "verification", "machine_label", "machine_id"} & set(v4["provenance"])
    assert "local" in v4  # in the local meta.json only


def test_format_source_says_where_the_format_came_from():
    assert runrecord.format_and_source("lmstudio/x", {"provider": "lmstudio", "local": True, "format": "MLX"}) == ("mlx", "runtime")
    assert runrecord.format_and_source("lmstudio/x", {"provider": "lmstudio", "local": True,
                                                      "model_path": "/m/x-Q4.gguf"}) == ("gguf", "runtime")
    assert runrecord.format_and_source("lmstudio/mlx-community/x", {"provider": "lmstudio", "local": True}) == ("mlx", "filename")
    assert runrecord.format_and_source("lmstudio/qwen/x", {"provider": "lmstudio", "local": True}) == (None, "unknown")
    assert runrecord.format_and_source("openrouter/a/b", {"provider": "openrouter", "local": False}) == (None, "unknown")


def test_format_4_end_to_end_write_publish_check(tmp_path):
    runs, v4 = _v4_runs(tmp_path)
    to = tmp_path / "bundle"
    outputs = bundle.default_outputs(to)
    pub = bundle.publish(runs, to, outputs)
    assert pub.errors == [] and pub.counts["runs"] == 1
    (path,) = (to / "runs").rglob("*.json")
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["format_version"] == 4 and "local" not in record and "run_path" not in record
    assert record["provenance"]["content_hash"].startswith("sha256:") and "submitter" not in record["provenance"]
    assert bundle.record_problems("run", record) == []
    assert bundle.check_folder(to, outputs) == []
    resolved = registry.default().resolve_run(record)
    assert (resolved.model_id, resolved.maker, resolved.packager, resolved.format, resolved.hardware_key) == (
        "qwen/qwen3.5-9b", "qwen", "lmstudio-community", "gguf", "m1-pro-32gb")
    assert "Ironwood" not in path.read_text(encoding="utf-8")
    again = bundle.publish(runs, to, outputs)
    assert again.errors == [] and not any(again.counts.values())


def test_format_4_cloud_run(tmp_path):
    p = workspace.load_task("capitals-not-largest-city")
    inference = {"provider": "openrouter", "local": False}
    meta = run_meta(p["id"], p["version"], p["rubric_version"], model="openrouter/qwen/qwen3.5-9b", inference=inference)
    v4 = runrecord.record_v4(meta, registry.default())
    assert v4["hardware"] is None and v4["model"]["format_source"] is None
    assert v4["model"]["id"] == "qwen/qwen3.5-9b"
    write_run(tmp_path / "runs" / v4["run_path"], v4, "ok")
    to = tmp_path / "bundle"
    assert bundle.publish(tmp_path / "runs", to, bundle.default_outputs(to)).errors == []


def test_a_local_key_is_rejected_in_either_format(tmp_path):
    runs, v4 = _v4_runs(tmp_path)
    leaked = {**v4, "local": {"x": 1}, "run_path": None}
    assert any("local" in p for p in bundle.record_problems("run", leaked, strict=True))
    assert any("local" in p for p in bundle.record_problems("run", leaked))        # format 4: always
    v3 = run_meta("capitals-not-largest-city")
    assert bundle.record_problems("run", {**bundle.published_run(v3, None), "local": {}}) == []   # legacy bundle runs
    assert any("local" in p for p in bundle.record_problems("run", {**bundle.published_run(v3, None), "local": {}}, strict=True))
    # and --check fails a format-4 file that carries one
    to = tmp_path / "bundle"
    bundle.publish(runs, to, bundle.default_outputs(to))
    (path,) = (to / "runs").rglob("*.json")
    record = json.loads(path.read_text())
    path.write_text(json.dumps({**record, "local": {}}))
    assert any("local" in p for p in bundle.check_folder(to, bundle.default_outputs(to)))


def test_format_4_schema_rejects_dropped_fields():
    v3 = run_meta("capitals-not-largest-city")
    v4 = bundle.published_run(runrecord.record_v4(v3, registry.default()), None)
    assert bundle.record_problems("run", v4) == []
    leaked = {**v4, "model": {**v4["model"], "variant_key": "a|b"}, "endpoint": {**v4["endpoint"], "app": None}}
    found = "\n".join(bundle.record_problems("run", leaked))
    assert "model.variant_key" in found and "endpoint.app" in found
    for field in ("serving_host", "harness_host"):
        assert any(field in p for p in bundle.record_problems("run", {**v4, field: "Ironwood"}))
    hw = v4["hardware"]
    assert any("hardware.label" in p for p in bundle.record_problems("run", {**v4, "hardware": {**hw, "label": "Ironwood"}}))
    assert any("machine_id" in p for p in bundle.record_problems(
        "run", {**v4, "provenance": {**v4["provenance"], "machine_id": "m_1234"}}))
    assert any("format_source" in p for p in bundle.record_problems("run", {**v4, "model": {**v4["model"], "format_source": "guess"}}))


def test_the_nickname_is_optional_chosen_and_display_only(tmp_path, monkeypatch):
    monkeypatch.delenv("CRUCIBLE_MACHINE_NAME", raising=False)
    _, plain = _v4_runs(tmp_path)
    assert "nickname" not in plain["hardware"]            # never the OS hostname by default
    monkeypatch.setenv("CRUCIBLE_MACHINE_NAME", "Basement Box")
    _, named = _v4_runs(tmp_path / "named")
    assert named["hardware"]["nickname"] == "Basement Box"
    assert {k: v for k, v in named["hardware"].items() if k != "nickname"} == plain["hardware"]   # not part of the key
    published = bundle.published_run(named, None)
    assert bundle.record_problems("run", published) == []
    for bad in ("192.168.1.5", "ip-192-168-1-5", "fe80::1", "", "x" * 41, "two\nlines"):
        assert any("nickname" in p for p in bundle.record_problems(
            "run", {**published, "hardware": {**published["hardware"], "nickname": bad}})), bad
    monkeypatch.setenv("CRUCIBLE_MACHINE_NAME", "ip-10-0-0-1")
    with pytest.raises(SystemExit):
        runrecord.machine_nickname()


# --------------------------------------------------------------------------
# No IP addresses in records
# --------------------------------------------------------------------------

def test_publish_refuses_a_new_run_with_an_ip_in_it(tmp_path):
    runs, to = _runs(tmp_path, 1), tmp_path / "bundle"
    (run_dir,) = runrecord.run_dirs(runs)
    meta = json.loads((run_dir / "meta.json").read_text())
    meta["provenance"]["machine_label"] = "ip-192-168-1-162"
    (run_dir / "meta.json").write_text(json.dumps(meta))
    pub = bundle.publish(runs, to, bundle.default_outputs(to))
    assert pub.counts["runs"] == 0 and not list(to.glob("runs/*/*.json"))
    assert "IP address" in pub.errors[0] and "provenance.machine_label" in pub.errors[0] and "ip-192-168-1-162" in pub.errors[0]


def test_check_warns_about_published_runs_with_an_ip_but_does_not_fail(tmp_path):
    runs, to = _runs(tmp_path, 1), tmp_path / "bundle"
    bundle.publish(runs, to, bundle.default_outputs(to))
    (path,) = to.glob("runs/*/*.json")
    record = json.loads(path.read_text())
    record["hardware"]["label"] = "ip-192-168-1-162"
    path.write_text(json.dumps(record))
    bundle.write_manifest(to)
    assert not any("IP address" in p for p in bundle.check_folder(to, bundle.default_outputs(to)))  # format 3: a warning only
    (warning,) = [w for w in bundle.legacy_warnings(to) if "IP" in w]
    assert record["run_uuid"][:8] in warning
