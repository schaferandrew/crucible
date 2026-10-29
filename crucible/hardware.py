"""The machines that serve inference, by the name LM Link reports for them.

LM Link names a peer but doesn't report its hardware, so a run served by another
machine gets its specs from here. Add a machine when it starts serving models.
"""
from __future__ import annotations

import re

DEVICES = {
    "Ironwood": {"cpu": "Apple M1 Pro", "gpu": None, "ram_gb": 32.0},
    # DDR5 runs without EXPO, so models spilling out of VRAM run slower than the RAM allows
    "Whitehall": {"cpu": "AMD Ryzen 7 7700", "gpu": "NVIDIA RTX 5070 Ti 16GB", "ram_gb": 32.0},
}

# LM Link device names that aren't the machine's name (rename with `lms link set-device-name`)
ALIASES = {
    "desktop-d2j5pm9": "Whitehall",
}


def canonical(name: str | None) -> str | None:
    """The machine's name in DEVICES, or the reported name when it isn't listed."""
    if not name:
        return None
    short = name.split(".")[0]
    key = short.lower()
    return ALIASES.get(key) or next((d for d in DEVICES if d.lower() == key), short)


def specs(name: str | None) -> dict | None:
    """hostname, cpu, gpu, ram_gb for a listed machine; None for one that isn't."""
    device = canonical(name)
    return {"hostname": device, **DEVICES[device]} if device in DEVICES else None


def serving(machine: dict, inference: dict) -> dict | None:
    """hostname, cpu, gpu, ram_gb of the machine that ran inference: this one, or the LM Link
    device that served the model. Hostname is the machine's short name, never the endpoint address."""
    if inference.get("same_machine") is False:
        device = inference.get("device")
        return specs(device) or ({"hostname": device, "cpu": None, "gpu": None, "ram_gb": None}
                                 if device else None)
    return {k: machine.get(k) for k in ("hostname", "cpu", "gpu", "ram_gb")} if machine else None


# --------------------------------------------------------------------------
# Hardware key: the accelerator that ran the weights, plus its memory
# --------------------------------------------------------------------------

# Vendor and marketing words that don't tell two devices apart
NOISE = re.compile(r"\((?:tm|r)\)|@.*$|\b(?:apple|nvidia|geforce|amd|radeon|intel|core|cpu|processor|\d+-core)\b")
IN_NAME_MEMORY = re.compile(r"\b\d+(?:\.\d+)?\s*(?:gb|gib|mb|mib)\b")
# nvidia-smi's "name, memory.total" lines: "NVIDIA GeForce RTX 3090, 24576 MiB"
SMI_MEMORY = re.compile(r",\s*(\d+(?:\.\d+)?)\s*(MiB|GiB|MB|GB)\s*$", re.IGNORECASE)
NAME_MEMORY_GB = re.compile(r"\b(\d+(?:\.\d+)?)\s*GB\b", re.IGNORECASE)
APPLE_SILICON = re.compile(r"^m\d+(?:-|$)")
# Normalized names that still aren't the device's usual name
KEY_ALIASES = {
    "apple-m1-pro": "m1-pro",
}


def _slug(name: str) -> str:
    text = IN_NAME_MEMORY.sub(" ", NOISE.sub(" ", name.lower()))
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return KEY_ALIASES.get(slug, slug)


def _gb(value: float | None) -> str:
    return f"-{round(value)}gb" if value else ""


def _gpus(gpu: str) -> list[tuple[str, float | None]]:
    """(name, memory in GB) per card, from nvidia-smi lines or a "NVIDIA RTX 5070 Ti 16GB" name."""
    cards = []
    for line in filter(None, (line.strip() for line in gpu.splitlines())):
        smi = SMI_MEMORY.search(line)
        if smi:
            amount = float(smi.group(1))
            memory = amount / 1024 if smi.group(2).lower() in ("mib", "mb") else amount
            cards.append((line[:smi.start()], memory))
        else:
            named = NAME_MEMORY_GB.search(line)
            cards.append((line, float(named.group(1)) if named else None))
    return cards


def key(cpu: str | None, gpu: str | None = None, ram_gb: float | None = None) -> str | None:
    """`m1-pro-32gb`, `rtx-5070-ti-16gb`, `2x-rtx-3090-24gb`, `rtx-4090-24gb+rtx-3090-24gb`,
    `cpu-ryzen-7-7700-32gb`: a discrete GPU with its VRAM, else Apple silicon with its unified
    memory, else the CPU with system RAM. None when there's nothing to name."""
    cards = _gpus(gpu) if gpu else []
    if cards:
        counts: dict[tuple[str, str], int] = {}
        order: dict[tuple[str, str], float] = {}
        for name, memory in cards:
            card = (_slug(name), _gb(memory))
            counts[card] = counts.get(card, 0) + 1
            order[card] = round(memory or 0)  # whole GB, as the key shows it
        ranked = sorted(counts, key=lambda c: (order[c], c[0]), reverse=True)
        return "+".join(f"{counts[c]}x-" * (counts[c] > 1) + c[0] + c[1] for c in ranked)
    if not cpu:
        return None
    chip = _slug(cpu)
    if not chip:
        return None
    return f"{chip}{_gb(ram_gb)}" if APPLE_SILICON.match(chip) else f"cpu-{chip}{_gb(ram_gb)}"
