"""Where a run happened: the machine running crucible and the inference endpoint.

Recorded in meta.json so results can be grouped by hardware, and so odd scores
have an explanation (a 4k loaded context fails a long-context test by
construction). Everything is best effort: an unreachable endpoint or an
unknown OS field records None, never fails the run.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from crucible import hardware, providers

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _run(cmd: list[str]) -> str | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _total_ram_gb() -> float | None:
    try:
        if sys.platform == "darwin":
            return round(int(_run(["sysctl", "-n", "hw.memsize"]) or 0) / 2**30, 1) or None
        if sys.platform.startswith("linux"):
            return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1)
    except (ValueError, OSError):
        pass
    return None


def _cpu() -> str | None:
    if sys.platform == "darwin":
        return _run(["sysctl", "-n", "machdep.cpu.brand_string"])
    # platform.processor() is often empty on Linux (or just the arch); /proc/cpuinfo names the chip
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace").splitlines():
            label, _, value = line.partition(":")
            if label.strip() == "model name" and value.strip():
                return value.strip()
    except OSError:
        pass
    return platform.processor() or None


def _gpu() -> str | None:
    if sys.platform.startswith("linux"):
        return _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"])
    return None  # Apple silicon: the GPU is the CPU's, with unified memory


def machine() -> dict:
    return {
        "hostname": socket.gethostname().split(".")[0],
        "os": f"{platform.system()} {platform.release()}",
        "arch": platform.machine(),
        "cpu": _cpu(),
        "gpu": _gpu(),
        "ram_gb": _total_ram_gb(),
    }


def _get(url: str, body: dict | None = None) -> dict | None:
    try:
        req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                     headers={"Content-Type": "application/json"},
                                     method="POST" if body else "GET")
        return json.loads(urllib.request.urlopen(req, timeout=5).read())
    except Exception:
        return None


def _lms() -> str | None:
    found = shutil.which("lms")
    fallback = Path.home() / ".lmstudio" / "bin" / "lms"
    return found or (str(fallback) if fallback.is_file() else None)


def _lms_json(*args: str):
    exe = _lms()
    out = _run([exe, *args, "--json"]) if exe else None
    try:
        return json.loads(out) if out else None
    except ValueError:
        return None


def lmstudio_device(model_id: str, loaded: list | None, link: dict | None,
                    quant: str | None = None) -> dict:
    """Which device LM Studio ran the model on, from `lms ps` and `lms link status`.

    LM Link serves models from another machine through the same local API, and the
    API doesn't say which device answered; the CLI does. Each loaded instance names
    its device, and the link status names every device. `quant` picks between two
    variants of one key loaded on different devices. Unknown (the CLI missing, the
    model not loaded, or loaded on two devices) records nothing rather than a guess.
    """
    matches = [m for m in loaded or []
               if model_id in (m.get("identifier"), m.get("modelKey"))]
    if quant:
        matches = [m for m in matches if (quant_name(m) or "").lower() == quant.lower()] or matches
    devices = {m.get("deviceIdentifier") for m in matches}
    if len(devices) != 1 or link is None:
        return {}
    (device,) = devices
    if device in (None, link.get("deviceIdentifier")):
        ref = hardware.lmlink_id(link.get("deviceIdentifier"))
        return {"device": hardware.canonical(link.get("deviceName"), [ref]), "same_machine": True,
                "device_id": ref, "device_reported": link.get("deviceName")}
    peer = next((p for p in link.get("peers") or [] if p.get("deviceIdentifier") == device), {})
    ref = hardware.lmlink_id(device)
    return {"device": hardware.canonical(peer.get("deviceName"), [ref]), "same_machine": False, "served_via": "LM Link",
            "device_id": ref, "device_reported": peer.get("deviceName")}


def quant_name(entry: dict) -> str | None:
    """A loaded model's quant: `lms ps` uses {"name": "6bit", "bits": 6}, the API uses a string."""
    quant = entry.get("quantization")
    return (quant.get("name") if isinstance(quant, dict) else quant) or None


def lmstudio_loaded(model_id: str, loaded: list | None) -> dict | None:
    """The `lms ps` entry serving this model, which can name a loaded variant
    (`qwen/qwen3.6-35b-a3b@6bit`). None when nothing matches or its quants disagree."""
    matches = lmstudio_variants(model_id, loaded)
    quants = {quant_name(m) for m in matches}
    return matches[0] if matches and len(quants) == 1 else None


def lmstudio_variants(model_id: str, loaded: list | None) -> list[dict]:
    """Every `lms ps` instance that can serve this key, base instance and loaded variants alike.

    A variant instance (`qwen/qwen3.6-35b-a3b@6bit`) carries the base key in `identifier`, so a base
    key's list includes its loaded variants: which one answers depends on what's loaded elsewhere, and
    matching each run against all of them is what keeps a sibling's presence from changing the answer.
    A variant key names itself, so only its own instance answers.
    """
    base = model_id.split("@", 1)[0]
    rows = [m for m in loaded or [] if isinstance(m, dict)]
    if "@" in model_id:
        return [m for m in rows if model_id in (m.get("modelKey"), m.get("selectedVariant"))]
    return [m for m in rows
            if m.get("identifier") == base or str(m.get("modelKey") or "").split("@", 1)[0] == base]


def lmstudio_weights(entry: dict) -> dict:
    """The weights a loaded instance runs: precision, container, size and the repo they came from.

    `lms ps` names the repo in `indexedModelIdentifier` (`<device hash>:<key>@<repo>`, e.g.
    `...:qwen/qwen3.6-35b-a3b@lmstudio-community/Qwen3.6-35B-A3B-MLX-6bit`), so the repo is known even
    when LM Link serves the instance and the file lives on the peer. `bits` matches the `/api/v1/models`
    `bits_per_weight` for the same variant, and the quant name is the string the runs record.
    """
    indexed = str(entry.get("indexedModelIdentifier") or "")
    repo = indexed.split(":", 1)[1] if ":" in indexed else indexed
    repo = repo.rsplit("@", 1)[1] if "@" in repo else repo
    quant = entry.get("quantization")
    return {
        "key": entry.get("modelKey"),
        "quant": quant.get("name") if isinstance(quant, dict) else quant,
        "bits": quant.get("bits") if isinstance(quant, dict) else None,
        "format": entry.get("format"),
        "publisher": entry.get("publisher"),
        "artifact": repo or None,
        "size_bytes": entry.get("sizeBytes"),
        "device": entry.get("deviceIdentifier"),
    }


def lmstudio_expected_variant(model_id: str, available: list | None, link: dict | None) -> dict | None:
    """The weights an unloaded model key will resolve to, when LM-Link makes that unambiguous.

    The REST model catalog describes a default quantization even when the model is not loaded; that
    value need not be the copy LM-Link will choose. `/api/v1/models` exposes variants but no device,
    so join the per-device `lms ls` inventory to LM-Link's preferred device. If the preferred device
    has more than one distinct candidate, don't guess. With no preferred-device copy, a single unique
    available weight set is still safe to identify (for example, a model available only locally).
    """
    if not isinstance(available, list) or not isinstance(link, dict):
        return None
    base = model_id.split("@", 1)[0]
    rows = [m for m in available if isinstance(m, dict)]
    if "@" in model_id:
        rows = [m for m in rows if model_id in (m.get("modelKey"), m.get("selectedVariant"))]
    else:
        rows = [m for m in rows
                if m.get("identifier") == base or str(m.get("modelKey") or "").split("@", 1)[0] == base]
    if not rows:
        return None

    local_id = link.get("deviceIdentifier")
    preferred_id = link.get("preferredDeviceIdentifier")
    peers = {p.get("deviceIdentifier"): p for p in link.get("peers") or [] if isinstance(p, dict)}
    connected = {device for device, peer in peers.items() if peer.get("status") == "connected"}
    if preferred_id and preferred_id != local_id:
        peer = peers.get(preferred_id)
        if not peer or peer.get("status") != "connected":
            return None

    def device_id(entry: dict):
        # lms ls represents this machine with null; LM Link status gives it an identifier.
        return entry.get("deviceIdentifier") or local_id

    # Do not infer a route from an inventory row whose peer is disconnected.
    rows = [m for m in rows if device_id(m) == local_id or device_id(m) in connected]
    if not rows:
        return None
    preferred_rows = ([m for m in rows if device_id(m) == preferred_id]
                      if preferred_id else [])
    candidates = preferred_rows or rows
    distinct: dict[tuple, dict] = {}
    for entry in candidates:
        weights = lmstudio_weights(entry)
        if not weights.get("quant"):
            continue
        weights["publisher"] = (weights.get("publisher") or "").lower() or None
        # Keep same-quant builds distinct when their packaged artifacts differ.
        identity = (str(weights.get("key") or "").lower(),
                    str(weights.get("quant") or "").lower(),
                    str(weights.get("publisher") or "").lower(),
                    str(weights.get("artifact") or "").lower())
        distinct.setdefault(identity, weights)
    if len(distinct) != 1:
        return None
    resolved = next(iter(distinct.values()))
    resolved["resolution"] = "preferred" if preferred_rows else "unique"
    resolved_devices = {device_id(m) for m in (preferred_rows or candidates)}
    resolved_device = preferred_id if preferred_rows else (next(iter(resolved_devices))
                                                            if len(resolved_devices) == 1 else None)
    if resolved_device:
        peer = peers.get(resolved_device) or {}
        resolved["device_id"] = hardware.lmlink_id(resolved_device)
        resolved["device_name"] = hardware.canonical(
            link.get("deviceName") if resolved_device == local_id else peer.get("deviceName"), [resolved["device_id"]])
    return resolved


def lmstudio_models_dirs() -> list[Path]:
    """Where LM Studio keeps downloaded models: LMSTUDIO_MODELS_DIR, else its default folders."""
    custom = os.environ.get("LMSTUDIO_MODELS_DIR")
    return ([Path(custom).expanduser()] if custom else []) + [
        Path.home() / ".lmstudio" / "models", Path.home() / ".cache" / "lm-studio" / "models"]


def lmstudio_model_file(model_id: str, entries: list | None, roots: list[Path] | None = None) -> dict:
    """The model's file or folder on this machine and the repo it was downloaded from, from `lms ls`/`lms ps`.

    LM Studio stores a download as <models dir>/<org>/<repo>/..., so the path's first two parts are the
    packaged repo (lmstudio-community/Qwen3.5-9B-GGUF). {} when the model or its file isn't found.
    """
    entry = next((m for m in entries or [] if isinstance(m, dict) and m.get("path")
                  and model_id in (m.get("modelKey"), m.get("identifier"), m.get("indexedModelIdentifier"))), None)
    if entry is None:
        return {}
    rel = Path(entry["path"])
    for root in roots if roots is not None else lmstudio_models_dirs():
        full = rel if rel.is_absolute() else root / rel
        if full.exists():
            try:
                parts = full.relative_to(root).parts
            except ValueError:
                parts = ()
            return {"model_path": str(full), **({"artifact": "/".join(parts[:2])} if len(parts) >= 2 else {})}
    return {}


def _lmstudio(model_id: str, device: bool = True) -> dict:
    base = providers.LMSTUDIO_BASE_URL.rsplit("/v1", 1)[0]
    local = urlparse(base).hostname in LOCAL_HOSTS
    info = _get(f"{base}/api/v0/models/{model_id}") or {}
    record = {"quantization": info.get("quantization"), "state": info.get("state"),
              "context_length": info.get("loaded_context_length"),
              "max_context_length": info.get("max_context_length"), "arch": info.get("arch"),
              # Who converted the weights, and into what (gguf, mlx): the same model in two variants
              "publisher": info.get("publisher"), "format": info.get("compatibility_type")}
    # `lms ps` says which variant is actually loaded: the base key's API entry reports its default
    # quant, so a loaded qwen/...@6bit behind qwen/... would otherwise read as 4bit.
    loaded = _lms_json("ps") if local else None
    # Every loaded instance that can serve this key, with the weights each one runs: the base key's
    # API entry describes one default variant, so a sibling variant being loaded elsewhere must not
    # change what a run's own weights are compared against.
    variants = [w for w in (lmstudio_weights(m) for m in lmstudio_variants(model_id, loaded)) if w.get("quant")]
    if variants:
        record["variants"] = variants
    instance = lmstudio_loaded(model_id, loaded)
    if instance and quant_name(instance):
        record["quantization"] = quant_name(instance)
    # A variant key (`...@6bit`) has no API entry of its own, so the loaded instance also fills in
    # the publisher the API would have named for the base key.
    record["publisher"] = record["publisher"] or (instance or {}).get("publisher")
    # The weights' packaged repo, when the loaded instance names it: the same answer whether the file
    # sits on this machine or on an LM Link peer, so provenance can name the weights it actually ran.
    if len(variants) == 1 and variants[0].get("artifact"):
        record["artifact"] = record.get("artifact") or variants[0]["artifact"]
    link = None
    # An unloaded model's API quant is a catalog default, not necessarily the variant the API will
    # load. LM-Link documents that REST requests use the preferred device; lms ls is the inventory
    # that identifies each variant's device. Use it only if that device has one distinct candidate.
    if local and info.get("state") == "not-loaded" and not variants:
        link = _lms_json("link", "status")
        record["expected_variant"] = lmstudio_expected_variant(model_id, _lms_json("ls", model_id), link)
    # The CLI talks to this machine's LM Studio, so it only describes a server on localhost.
    # `device` skips the serving-device and local-file lookups; an unloaded model still needs the
    # preferred-device catalog above for an accurate skip-done probe.
    if device and local:
        if link is None:
            link = _lms_json("link", "status")
        record.update(lmstudio_device(model_id, loaded, link,
                                      record["quantization"]))
        # The weights' file, for model.origin and model.artifact: only when this machine ran them
        # (a model served over LM Link lives on the peer, and a local copy may be another variant)
        if record.get("device") and record.get("same_machine") and not record.get("served_via"):
            listed = _lms_json("ls")
            record.update(lmstudio_model_file(model_id, [*(loaded or []), *(listed if isinstance(listed, list) else [])]))
    return record


def _ollama(model_id: str, device: bool = True) -> dict:
    show = _get(f"{providers.OLLAMA_BASE_URL}/api/show", {"model": model_id}) or {}
    loaded = next((m for m in (_get(f"{providers.OLLAMA_BASE_URL}/api/ps") or {}).get("models", [])
                   if m.get("name") == model_id or m.get("model") == model_id), {})
    details = show.get("details") or {}
    return {"quantization": details.get("quantization_level"), "context_length": loaded.get("context_length"),
            "max_context_length": None, "arch": details.get("family"),
            "publisher": ollama_publisher(model_id), "format": "gguf",
            # The GGUF's own general.* metadata, for model.origin (scalars only)
            "model_info": {k: v for k, v in (show.get("model_info") or {}).items()
                           if k.startswith("general.") and isinstance(v, (str, int, float, bool))},
            "parameter_size": details.get("parameter_size"), "artifact": ollama_artifact(model_id)}


def ollama_publisher(model_id: str) -> str | None:
    """The namespace an Ollama model was pulled from ("unsloth" in hf.co/unsloth/qwen3:Q4), if any."""
    namespace = model_id.split(":", 1)[0].split("/")[:-1]
    return namespace[-1] if namespace else None


def ollama_artifact(model_id: str) -> str | None:
    """The Hugging Face repo an Ollama model was pulled from (hf.co/unsloth/Qwen3-GGUF:Q4 -> unsloth/Qwen3-GGUF)."""
    parts = model_id.split(":", 1)[0].split("/")
    return "/".join(parts[1:3]) if len(parts) == 3 and parts[0] in ("hf.co", "huggingface.co") else None


PROVIDER_BASE_URLS = {
    "lmstudio": lambda: providers.LMSTUDIO_BASE_URL,
    "ollama": lambda: providers.OLLAMA_BASE_URL,
}
PROVIDER_DETAILS = {"lmstudio": _lmstudio, "ollama": _ollama}


def inference(model: str | None, device: bool = True) -> dict:
    """Provider, whether it runs on this machine, and what the server reports about the model.

    `device=False` skips the hardware and origin lookups (LM Studio's link and `lms ls` calls) for
    callers that only need the variant. `lms ps` is still read, since it names the loaded variant.
    """
    try:
        provider_def, model_id = providers.split_model(model or "")
    except ValueError:
        return {"provider": None, "local": None}
    provider = provider_def.name
    base_url = PROVIDER_BASE_URLS.get(provider, lambda: None)()
    host = urlparse(base_url).hostname if base_url else None
    record = {
        "provider": provider,
        # Local providers can serve from another box (OLLAMA_BASE_URL); then this machine isn't the hardware
        "local": provider in PROVIDER_DETAILS,
        "same_machine": host in LOCAL_HOSTS if host else None,
        "endpoint_host": None if host in LOCAL_HOSTS else host,
    }
    if provider in PROVIDER_DETAILS:
        record.update(PROVIDER_DETAILS[provider](model_id, device=device))
    return record


def reasoning_resolved(model: str | None, requested: str) -> tuple[str | None, str | None]:
    """The reasoning level the model actually ran at and its source.
    
    Returns: (resolved_level, source) where source is one of:
        "server" - reported by the server (LM Studio)
        "template" - reported by the chat template
        "inferred" - inferred from reasoning output (on/off only)
        "unknown" - cannot be determined
        "requested" - a named level was requested, so it is the level
    
    For "default" reasoning:
      - LM Studio: from server capabilities
      - Others: try to infer from output, otherwise unknown
    For non-default: the requested level is the resolved level.
    """
    if requested != "default":
        return requested, "requested"
    
    try:
        provider_def, model_id = providers.split_model(model or "")
    except ValueError:
        return None, "unknown"
    
    # LM Studio: get from server
    if provider_def.name == "lmstudio":
        base = providers.LMSTUDIO_BASE_URL.rsplit("/v1", 1)[0]
        for m in (_get(f"{base}/api/v1/models") or {}).get("models") or []:
            ids = {m.get("key"), *(m.get("variants") or []), *(i.get("id") for i in m.get("loaded_instances") or [])}
            if model_id in ids:
                level = ((m.get("capabilities") or {}).get("reasoning") or {}).get("default")
                if level:
                    return level, "server"
        return None, "unknown"
    
    # For other providers, we can't currently get the default level
    # In the future, we could check the chat template or infer from output
    return None, "unknown"


def endpoint(model: str | None, run_dir: Path) -> dict:
    """Who served a cloud request: OpenRouter's upstream provider and the dated model it resolved to.

    Read from the direct harness's response record, confirmed with OpenRouter's generation
    endpoint when it answers; anything unknown stays None and never fails the run.
    """
    record = {"upstream": None, "resolved_model": None}
    if not (model or "").startswith("openrouter/"):
        return record
    try:
        response = json.loads((run_dir / "direct-response.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return record
    generation = providers.fetch_openrouter_generation(response.get("generation_id")) or {}
    upstream = generation.get("provider_name") or response.get("served_provider")
    record["upstream"] = {"name": upstream, "quant": None} if upstream else None
    record["resolved_model"] = response.get("served_model") or generation.get("model")
    return record


def harness_version(executable: str | None) -> str | None:
    """The agent CLI's own version string (agents auto-update, and a new version can move scores)."""
    if not executable:
        return None
    out = _run([executable, "--version"])
    return out.splitlines()[0].strip() if out else None


def capture(model: str | None, executable: str | None = None) -> dict:
    found = inference(model)
    here = machine()
    here["name"] = this_machine_name(found, here.get("hostname"))
    return {"machine": here, "inference": found, "harness_version": harness_version(executable)}


# --------------------------------------------------------------------------
# Which devices a run would record, and whether the devices file knows them
# --------------------------------------------------------------------------

def this_machine_ids(link: dict | None = None) -> list[str]:
    """How this machine is recognized: its Crucible machine ID, and its LM Link ID when it has one."""
    from crucible import provenance
    return [i for i in (hardware.machine_ref(provenance.machine_id()),
                        hardware.lmlink_id((link or {}).get("deviceIdentifier"))) if i]


def this_machine_name(found: dict, hostname: str | None = None) -> str | None:
    """The name this machine was given in the devices file, if any."""
    ids = this_machine_ids()
    reported = hostname
    if found.get("same_machine") and found.get("device_id"):
        ids.append(found["device_id"])
        reported = found.get("device_reported") or hostname
    return hardware.resolve(reported, ids)


def _link() -> dict | None:
    link = _lms_json("link", "status")
    return link if isinstance(link, dict) and link.get("deviceIdentifier") else None


def known_devices(model: str | None = None) -> list[dict]:
    """The devices that would run `model` (every device this machine can use when None), each as
    {ids, reported, this_machine, specs, name}: `name` is its name in the devices file, or None.

    The serving device is the loaded instance's, else LM Link's preferred device for an unloaded model;
    when neither says, every connected device could serve it. A device found by name has its IDs
    remembered, so it's recognized by ID from then on. A server on another host (OLLAMA_BASE_URL)
    isn't identifiable and gives nothing.
    """
    if model is not None:
        try:
            provider = providers.split_model(model)[0].name
        except ValueError:
            return []
        if provider not in PROVIDER_DETAILS:
            return []
        host = urlparse(PROVIDER_BASE_URLS[provider]() or "").hostname
        if host and host not in LOCAL_HOSTS:
            return []
        link = _link() if provider == "lmstudio" else None
    else:
        link = _link()
    here_specs = machine()
    devices = [{"ids": this_machine_ids(link), "this_machine": True, "specs": here_specs,
                "reported": (link or {}).get("deviceName") or here_specs.get("hostname")}]
    peers = [{"ids": [hardware.lmlink_id(p.get("deviceIdentifier"))], "this_machine": False, "specs": None,
              "reported": p.get("deviceName"), "connected": p.get("status") in (None, "connected")}
             for p in (link or {}).get("peers") or [] if isinstance(p, dict) and p.get("deviceIdentifier")]
    if model is None:
        devices += peers
    elif link:
        found = inference(model)
        serving = found.get("device_id") or (found.get("expected_variant") or {}).get("device_id")
        if serving:
            devices = [d for d in devices + peers if serving in d["ids"]] or devices
        else:
            devices += [p for p in peers if p["connected"]]
    for device in devices:
        device["name"] = hardware.resolve(device["reported"], device["ids"])
        if device["name"]:
            hardware.remember(device["name"], device["ids"], device["reported"])
    return devices


def needs_naming(device: dict) -> bool:
    """Not in the devices file, or a peer listed without hardware (this machine's is read from it)."""
    return not device["name"] or (not device["this_machine"] and not hardware.specs(device["name"]))
