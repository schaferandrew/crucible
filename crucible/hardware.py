"""The machines that serve inference, by the name LM Link reports for them.

LM Link names a peer but doesn't report its hardware, so a run served by another
machine gets its specs from here. Add a machine when it starts serving models.
"""
from __future__ import annotations

DEVICES = {
    "Ironwood": {"cpu": "Apple M1 Pro", "gpu": None, "ram_gb": 32.0},
    # Specs to fill in: run on Whitehall itself, or read from its system information
    "Whitehall": {"cpu": None, "gpu": None, "ram_gb": None},
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
