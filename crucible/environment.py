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


def lmstudio_device(model_id: str, loaded: list | None, link: dict | None) -> dict:
    """Which device LM Studio ran the model on, from `lms ps` and `lms link status`.

    LM Link serves models from another machine through the same local API, and the
    API doesn't say which device answered; the CLI does. Each loaded instance names
    its device, and the link status names every device. Unknown (the CLI missing, the
    model not loaded, or loaded on two devices) records nothing rather than a guess.
    """
    devices = {m.get("deviceIdentifier") for m in loaded or []
               if model_id in (m.get("identifier"), m.get("modelKey"))}
    if len(devices) != 1 or link is None:
        return {}
    (device,) = devices
    if device in (None, link.get("deviceIdentifier")):
        return {"device": hardware.canonical(link.get("deviceName")), "same_machine": True}
    peer = next((p for p in link.get("peers") or [] if p.get("deviceIdentifier") == device), {})
    return {"device": hardware.canonical(peer.get("deviceName")), "same_machine": False, "served_via": "LM Link"}


def _lmstudio(model_id: str) -> dict:
    base = providers.LMSTUDIO_BASE_URL.rsplit("/v1", 1)[0]
    info = _get(f"{base}/api/v0/models/{model_id}") or {}
    record = {"quantization": info.get("quantization"), "context_length": info.get("loaded_context_length"),
              "max_context_length": info.get("max_context_length"), "arch": info.get("arch")}
    # The CLI talks to this machine's LM Studio, so it only describes a server on localhost
    if urlparse(base).hostname in LOCAL_HOSTS:
        record.update(lmstudio_device(model_id, _lms_json("ps"), _lms_json("link", "status")))
    return record


def _ollama(model_id: str) -> dict:
    show = _get(f"{providers.OLLAMA_BASE_URL}/api/show", {"model": model_id}) or {}
    loaded = next((m for m in (_get(f"{providers.OLLAMA_BASE_URL}/api/ps") or {}).get("models", [])
                   if m.get("name") == model_id or m.get("model") == model_id), {})
    details = show.get("details") or {}
    return {"quantization": details.get("quantization_level"), "context_length": loaded.get("context_length"),
            "max_context_length": None, "arch": details.get("family")}


PROVIDER_BASE_URLS = {
    "lmstudio": lambda: providers.LMSTUDIO_BASE_URL,
    "ollama": lambda: providers.OLLAMA_BASE_URL,
}
PROVIDER_DETAILS = {"lmstudio": _lmstudio, "ollama": _ollama}


def inference(model: str | None) -> dict:
    """Provider, whether it runs on this machine, and what the server reports about the model."""
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
        record.update(PROVIDER_DETAILS[provider](model_id))
    return record


def harness_version(executable: str | None) -> str | None:
    """The agent CLI's own version string (agents auto-update, and a new version can move scores)."""
    if not executable:
        return None
    out = _run([executable, "--version"])
    return out.splitlines()[0].strip() if out else None


def capture(model: str | None, executable: str | None = None) -> dict:
    return {"machine": machine(), "inference": inference(model), "harness_version": harness_version(executable)}
