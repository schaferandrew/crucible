"""model.origin: who trained a model, read from the source itself (crucible/origin.py)."""
import json
import struct

from crucible import bundle, environment, origin, providers, runrecord
from tests.records import run_meta

B = 10**9


# --------------------------------------------------------------------------
# A tiny synthetic GGUF header
# --------------------------------------------------------------------------

def _s(text: str) -> bytes:
    data = text.encode("utf-8")
    return struct.pack("<Q", len(data)) + data


def _kv(key: str, kind: int, value) -> bytes:
    out = _s(key) + struct.pack("<I", kind)
    if kind == 8:
        return out + _s(value)
    if kind == 9:
        item, items = value
        out += struct.pack("<IQ", item, len(items))
        return out + b"".join(_s(i) if item == 8 else struct.pack(origin.GGUF_SCALARS[item], i) for i in items)
    return out + struct.pack(origin.GGUF_SCALARS[kind], value)


def write_gguf(path, kvs, version=3):
    count = "<I" if version == 1 else "<Q"
    body = b"".join(_kv(*kv) for kv in kvs)
    path.write_bytes(b"GGUF" + struct.pack("<I", version) + struct.pack(count, 0) + struct.pack(count, len(kvs))
                     + body + b"\0" * 64)   # tensor info would follow; never read
    return path


QWEN_KVS = [
    ("general.architecture", 8, "qwen3moe"),
    ("general.organization", 8, "Lmstudio Community"),
    ("general.size_label", 8, "35B-A3B"),
    ("general.base_model.count", 4, 1),
    ("general.base_model.0.organization", 8, "Qwen"),
    ("general.base_model.0.repo_url", 8, "https://huggingface.co/Qwen/Qwen3.6-35B-A3B-Base"),
    ("qwen3moe.expert_count", 4, 128),
    ("tokenizer.ggml.tokens", 9, (8, ["a", "b", "<|im_end|>"])),
    ("tokenizer.ggml.scores", 9, (6, [0.0, 1.5, -2.0])),
    ("general.parameter_count", 10, 35_100_000_000),   # after the arrays: they're skipped, not stopped at
]


def test_gguf_header_general_keys(tmp_path):
    kv = origin.gguf_general(write_gguf(tmp_path / "m.gguf", QWEN_KVS))
    assert kv["general.base_model.0.organization"] == "Qwen" and kv["general.parameter_count"] == 35_100_000_000
    assert not any(k.startswith(("tokenizer.", "qwen3moe.")) for k in kv)
    assert origin.from_general(kv) == {"maker": "qwen", "base_repo": "Qwen/Qwen3.6-35B-A3B-Base",
                                       "params": 35_100_000_000, "active_params": 3 * B}


def test_gguf_version_1_and_unreadable_files(tmp_path):
    v1 = write_gguf(tmp_path / "v1.gguf", [("general.organization", 8, "Google"), ("general.size_label", 8, "12B")],
                    version=1)
    assert origin.from_general(origin.gguf_general(v1)) == {"maker": "google", "base_repo": None,
                                                           "params": 12 * B, "active_params": None}
    (tmp_path / "junk.gguf").write_bytes(b"not a gguf")
    truncated = tmp_path / "cut.gguf"
    truncated.write_bytes((tmp_path / "v1.gguf").read_bytes()[:40])
    assert origin.gguf_general(tmp_path / "junk.gguf") == {}
    assert origin.gguf_general(tmp_path / "missing.gguf") == {}
    assert origin.gguf_general(truncated) == {}   # what was read before the cut isn't trusted
    assert origin.from_file(tmp_path / "junk.gguf") == (None, {})


def test_model_folder_with_a_gguf(tmp_path):
    folder = tmp_path / "lmstudio-community" / "Qwen3.6-35B-A3B-GGUF"
    folder.mkdir(parents=True)
    write_gguf(folder / "Qwen3.6-35B-A3B-Q4_K_M.gguf", QWEN_KVS)
    source, fields = origin.from_file(folder)
    assert source == "gguf" and fields["maker"] == "qwen"


# --------------------------------------------------------------------------
# MLX model card
# --------------------------------------------------------------------------

def _card(folder, front: str):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "config.json").write_text("{}")
    (folder / "README.md").write_text(f"---\n{front}\n---\n\n# A model\n")
    return folder


def test_mlx_card_base_model(tmp_path):
    folder = _card(tmp_path / "mlx-community" / "Qwen3.5-9B-4bit",
                   "library_name: mlx\nbase_model: Qwen/Qwen3.5-9B\ntags: [mlx]")
    assert origin.from_file(folder) == ("mlx-card", {"maker": "qwen", "base_repo": "Qwen/Qwen3.5-9B",
                                                     "params": None, "active_params": None})
    listed = _card(tmp_path / "b", "base_model:\n- google/gemma-4-e4b-it\n- other/thing")
    assert origin.from_card(listed)["base_repo"] == "google/gemma-4-e4b-it"
    # A card naming another packager's copy keeps the repo but finds no maker
    repack = _card(tmp_path / "c", "base_model: mlx-community/muse-glimmer-30b-8bit")
    assert origin.from_card(repack) == {"maker": None, "base_repo": "mlx-community/muse-glimmer-30b-8bit",
                                        "params": None, "active_params": None}
    for front in ("license: mit", "base_model: [", ""):
        assert origin.from_card(_card(tmp_path / "d", front))["base_repo"] is None
    (tmp_path / "e").mkdir()
    (tmp_path / "e" / "README.md").write_text("# No front matter\nbase_model: Qwen/Qwen3.5-9B\n")
    assert origin.card_base_model(tmp_path / "e") is None


# --------------------------------------------------------------------------
# Ollama, OpenRouter, the LM Studio key
# --------------------------------------------------------------------------

OLLAMA_SHOW = {
    "details": {"format": "gguf", "family": "qwen3", "parameter_size": "8.2B", "quantization_level": "Q4_K_M"},
    "model_info": {"general.architecture": "qwen3", "general.basename": "Qwen3", "general.parameter_count": 8190735360,
                   "general.size_label": "8B", "general.base_model.0.organization": "Qwen",
                   "general.base_model.0.repo_url": "https://huggingface.co/Qwen/Qwen3-8B-Base",
                   "general.tags": ["text-generation"], "qwen3.block_count": 36,
                   "tokenizer.ggml.tokens": None},
}


def test_ollama_model_info(monkeypatch):
    monkeypatch.setattr(environment, "_get", lambda url, body=None: OLLAMA_SHOW if url.endswith("/api/show") else {})
    info = environment._ollama("qwen3:8b")
    assert info["model_info"]["general.base_model.0.organization"] == "Qwen"
    assert "qwen3.block_count" not in info["model_info"] and "general.tags" not in info["model_info"]
    assert info["parameter_size"] == "8.2B" and info["artifact"] is None
    assert origin.from_ollama(info["model_info"], info["parameter_size"]) == {
        "maker": "qwen", "base_repo": "Qwen/Qwen3-8B-Base", "params": 8190735360, "active_params": None}
    # A library model with no general.* metadata: only Ollama's own size string
    assert origin.from_ollama({}, "8.2B") == {"maker": None, "base_repo": None, "params": 8_200_000_000,
                                              "active_params": None}
    assert environment.ollama_artifact("hf.co/unsloth/Qwen3-8B-GGUF:Q4_K_M") == "unsloth/Qwen3-8B-GGUF"
    assert environment.ollama_artifact("qwen3:8b") is None


def test_openrouter_author_and_hugging_face_id(monkeypatch):
    entry = {"id": "qwen/qwen3.5-9b", "canonical_slug": "qwen/qwen3.5-9b-20260301", "hugging_face_id": "Qwen/Qwen3.5-9B",
             "name": "Qwen: Qwen3.5 9B", "pricing": {"prompt": "0.0000001", "completion": "0.0000002"}}
    assert origin.capture("openrouter/qwen/qwen3.5-9b", {}, entry) == {
        "maker": "qwen", "base_repo": "Qwen/Qwen3.5-9B", "params": None, "active_params": None, "source": "openrouter"}
    assert origin.capture("openrouter/~openai/gpt-luna-latest", {})["maker"] == "openai"
    assert origin.capture("openrouter/anthropic/claude-opus-5.5", {}, {"hugging_face_id": ""})["base_repo"] is None
    # The entry is read only when Crucible already fetched the list (opencode's pricing), never fetched for it
    monkeypatch.setattr(providers, "_OPENROUTER_ENTRIES", {})
    calls = []
    monkeypatch.setattr(providers, "_get_json", lambda url, headers=None: calls.append(url) or {"data": [entry]})
    assert providers.openrouter_model_if_fetched("qwen/qwen3.5-9b") is None and calls == []
    assert [round(x, 6) for x in providers.fetch_openrouter_pricing("qwen/qwen3.5-9b")] == [0.1, 0.2]
    assert providers.openrouter_model_if_fetched("qwen/qwen3.5-9b") == entry
    providers.fetch_openrouter_pricing("qwen/qwen3.5-9b")
    assert len(calls) == 1


def test_lmstudio_key_and_packagers():
    assert origin.capture("lmstudio/qwen/qwen3.5-9b", {})["maker"] == "qwen"
    assert origin.capture("lmstudio/qwen/qwen3.5-9b", {})["source"] == "lmstudio-key"
    assert origin.capture("lmstudio/mlx-community/muse-glimmer-30b", {}) == origin.empty()
    assert origin.capture("lmstudio/gpt-oss-20b", {}) == origin.empty()        # no prefix: no maker
    assert origin.capture("opencode/deepseek-v4.1-flash-free", {}) == origin.empty()
    assert origin.capture(None, None) == origin.empty()
    for packager in origin.PACKAGERS:
        assert origin.maker_id(packager) is None and origin.maker_id("~" + packager) is None
    assert origin.maker_id("Qwen") == "qwen" and origin.maker_id("~openai") == "openai"
    assert origin.maker_id("Meta Llama") == "meta-llama" and origin.maker_id("") is None
    # The same list decides the publisher (packager) for the variant key
    assert runrecord.implied_variant("lmstudio/bartowski/x-GGUF", None)["publisher"] == "bartowski"


def test_size_labels():
    assert origin.parse_size("9B") == (9 * B, None)
    assert origin.parse_size("35B-A3B") == (35 * B, 3 * B)
    assert origin.parse_size("1.5B") == (1_500_000_000, None)
    assert origin.parse_size("270M") == (270_000_000, None)
    for label in ("8x7B", "E4B", "", None, "large"):
        assert origin.parse_size(label) == (None, None)


# --------------------------------------------------------------------------
# Trust order
# --------------------------------------------------------------------------

def test_the_file_outranks_the_key_field_by_field(tmp_path):
    # The file says the maker and size; the key would say a repackager's org (no maker) or another lab
    gguf = write_gguf(tmp_path / "m.gguf", [("general.base_model.0.repo_url", 8, "https://huggingface.co/Qwen/Qwen3-8B"),
                                            ("general.size_label", 8, "8B")])
    result = origin.capture("lmstudio/someone/qwen3-8b-tuned", {"model_path": str(gguf)})
    assert result == {"maker": "qwen", "base_repo": "Qwen/Qwen3-8B", "params": 8 * B, "active_params": None,
                      "source": "gguf"}
    # The file has only a size; the key fills the maker, and both are named
    sized = write_gguf(tmp_path / "s.gguf", [("general.size_label", 8, "12B")])
    assert origin.capture("lmstudio/google/gemma-4-12b", {"model_path": str(sized)}) == {
        "maker": "google", "base_repo": None, "params": 12 * B, "active_params": None, "source": "gguf+lmstudio-key"}
    # No file on this machine (LM Link): the key alone
    assert origin.capture("lmstudio/google/gemma-4-12b", {"model_path": str(tmp_path / "gone.gguf")})["source"] \
        == "lmstudio-key"


def test_merge_takes_the_first_answer():
    merged = origin.merge([("gguf", {"maker": None, "params": 9}), ("ollama", {"maker": "a", "params": 1}),
                           ("openrouter", {"maker": "b", "base_repo": "b/x"})])
    assert merged == {"maker": "a", "base_repo": "b/x", "params": 9, "active_params": None,
                      "source": "gguf+ollama+openrouter"}
    assert origin.merge([("gguf", {}), ("lmstudio-key", {"maker": None})])["source"] == "none"


# --------------------------------------------------------------------------
# LM Studio's file on this machine, and model.artifact
# --------------------------------------------------------------------------

def test_lmstudio_model_file_and_artifact(tmp_path):
    root = tmp_path / "models"
    folder = root / "lmstudio-community" / "Qwen3.5-9B-GGUF"
    folder.mkdir(parents=True)
    write_gguf(folder / "Qwen3.5-9B-Q4_K_M.gguf", QWEN_KVS)
    listed = [{"type": "llm", "modelKey": "google/gemma-4-e4b", "path": "lmstudio-community/gemma-4-e4b-GGUF/x.gguf"},
              {"type": "llm", "modelKey": "qwen/qwen3.5-9b", "path": "lmstudio-community/Qwen3.5-9B-GGUF/Qwen3.5-9B-Q4_K_M.gguf"}]
    found = environment.lmstudio_model_file("qwen/qwen3.5-9b", listed, [tmp_path / "elsewhere", root])
    assert found == {"model_path": str(folder / "Qwen3.5-9B-Q4_K_M.gguf"), "artifact": "lmstudio-community/Qwen3.5-9B-GGUF"}
    assert environment.lmstudio_model_file("google/gemma-4-e4b", listed, [root]) == {}   # listed, not on disk
    assert environment.lmstudio_model_file("other", listed, [root]) == {}
    assert environment.lmstudio_model_file("qwen/qwen3.5-9b", None, [root]) == {}


def test_lmstudio_reads_the_file_only_when_this_machine_ran_it(monkeypatch, tmp_path):
    monkeypatch.setattr(environment, "_get", lambda url, body=None: {"publisher": "lmstudio-community",
                                                                   "compatibility_type": "gguf"})
    ps = [{"identifier": "qwen/qwen3.5-9b", "modelKey": "qwen/qwen3.5-9b", "deviceIdentifier": "peer",
           "path": "lmstudio-community/Qwen3.5-9B-GGUF/q.gguf"}]
    link = {"deviceIdentifier": "me", "deviceName": "Ironwood", "peers": [{"deviceIdentifier": "peer", "deviceName": "Whitehall"}]}
    asked = []
    monkeypatch.setattr(environment, "_lms_json", lambda *a: asked.append(a) or (ps if a == ("ps",) else link if a[0] == "link" else []))
    monkeypatch.setattr(environment, "lmstudio_models_dirs", lambda: [tmp_path])
    (tmp_path / "lmstudio-community" / "Qwen3.5-9B-GGUF").mkdir(parents=True)
    write_gguf(tmp_path / "lmstudio-community" / "Qwen3.5-9B-GGUF" / "q.gguf", QWEN_KVS)
    served = environment._lmstudio("qwen/qwen3.5-9b")
    assert served["served_via"] == "LM Link" and "model_path" not in served and ("ls",) not in asked
    ps[0]["deviceIdentifier"] = "me"
    here = environment._lmstudio("qwen/qwen3.5-9b")
    assert here["artifact"] == "lmstudio-community/Qwen3.5-9B-GGUF" and here["model_path"].endswith("q.gguf")
    record = runrecord.model_record("lmstudio/qwen/qwen3.5-9b", "default", None, {"local": True, **here})
    assert record["artifact"] == "lmstudio-community/Qwen3.5-9B-GGUF"
    assert record["variant_key"] == "qwen/qwen3.5-9b|lmstudio-community|gguf|-"   # identity unchanged
    assert origin.capture("lmstudio/qwen/qwen3.5-9b", here)["source"] == "gguf"


# --------------------------------------------------------------------------
# The run record
# --------------------------------------------------------------------------

def test_origin_is_an_optional_run_field():
    meta = run_meta("capitals-not-largest-city")
    assert "origin" not in meta["model"] and meta["model"]["artifact"] is None
    assert bundle.record_problems("run", bundle.published_run(meta, None)) == []   # runs from before 3.6.0
    meta["model"]["origin"] = origin.capture("openrouter/qwen/qwen3.5-9b", {})
    assert bundle.record_problems("run", bundle.published_run(meta, None)) == []
    meta["model"]["origin"] = {"maker": "qwen", "params": "9B"}
    found = bundle.record_problems("run", meta)
    assert any("origin: missing 'source'" in p for p in found) and any("origin.params" in p for p in found)
    json.dumps(origin.empty())

