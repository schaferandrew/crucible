"""The machines that serve inference, by the name LM Link reports for them.

LM Link names a peer but doesn't report its hardware, so a run served by another machine gets
its specs from the devices file: `~/.crucible/devices.yaml` (or `CRUCIBLE_DEVICES_FILE`). It's
local to each person running Crucible, never part of the repo, since everyone's machines differ.
A run on this machine needs no entry: its specs are read from the machine itself.
`crucible devices` lists and adds entries; the format is

    devices:
      gpu-box:
        cpu: AMD Ryzen 9 7950X
        gpu: NVIDIA RTX 4090 24GB
        ram_gb: 64
        aliases: [desktop-a1b2c3]   # other names LM Link reports for it
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import yaml

FIELDS = ("cpu", "gpu", "ram_gb")
HEADER = """\
# Machines that serve models to this one over LM Link, so runs they serve record their hardware.
# Local to this machine; Crucible never commits or publishes it. Edit it, or `crucible devices add`.
"""

_cache: dict = {}


def devices_file() -> Path:
    return Path(os.environ.get("CRUCIBLE_DEVICES_FILE") or Path.home() / ".crucible" / "devices.yaml")


def devices() -> dict[str, dict]:
    """name -> {cpu, gpu, ram_gb, aliases} from the devices file; empty when there is none.

    A malformed file reads as empty with a warning, never failing a run.
    """
    path = devices_file()
    try:
        stamp = (str(path), path.stat().st_mtime_ns)
    except OSError:
        return {}
    if _cache.get("stamp") != stamp:
        _cache.update(stamp=stamp, devices=_parse(path))
    return _cache["devices"]


def _parse(path: Path) -> dict[str, dict]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        entries = data.get("devices") or {}
        if not isinstance(entries, dict):
            raise ValueError("`devices` must be a mapping of machine name to specs")
        parsed = {}
        for name, entry in entries.items():
            entry = entry or {}
            if not isinstance(entry, dict):
                raise ValueError(f"{name}: expected cpu, gpu, ram_gb")
            ram = entry.get("ram_gb")
            aliases = entry.get("aliases") or []
            parsed[str(name)] = {"cpu": entry.get("cpu") or None, "gpu": entry.get("gpu") or None,
                                 "ram_gb": float(ram) if ram is not None else None,
                                 "aliases": [str(a) for a in ([aliases] if isinstance(aliases, str) else aliases)]}
        return parsed
    except (OSError, ValueError, TypeError, AttributeError, yaml.YAMLError) as exc:
        print(f"Warning: ignoring {path}: {exc}", file=sys.stderr)
        return {}


def canonical(name: str | None) -> str | None:
    """The machine's name in the devices file, or the reported name when it isn't listed."""
    if not name:
        return None
    short = name.split(".")[0]
    key = short.lower()
    for device, entry in devices().items():
        if key == device.lower() or key in (a.lower() for a in entry["aliases"]):
            return device
    return short


def specs(name: str | None) -> dict | None:
    """hostname, cpu, gpu, ram_gb for a listed machine; None for one that isn't."""
    device = canonical(name)
    entry = devices().get(device) if device else None
    return {"hostname": device, **{k: entry[k] for k in FIELDS}} if entry else None


def unlisted(inference: dict) -> str | None:
    """The LM Link device that served (or will serve) a model when the devices file doesn't list it."""
    if inference.get("same_machine") is not False or inference.get("served_via") != "LM Link":
        return None
    device = inference.get("device")
    return device if device and not specs(device) else None


def add_device(name: str, cpu: str | None, gpu: str | None, ram_gb: float | None,
               aliases: list[str] | None = None) -> Path:
    """Add or replace a machine in the devices file; returns the file's path."""
    path = devices_file()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        data = {}
    entries = data.setdefault("devices", {}) or {}
    data["devices"] = entries
    entry = {"cpu": cpu or None, "gpu": gpu or None, "ram_gb": ram_gb}
    if aliases:
        entry["aliases"] = list(aliases)
    entries[name] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HEADER + yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    _cache.clear()
    return path


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


# --------------------------------------------------------------------------
# Asking for a device that isn't listed, and `crucible devices`
# --------------------------------------------------------------------------

def _ram(text: str) -> float | None:
    text = text.strip().lower().removesuffix("gb").strip()
    try:
        return float(text) if text else None
    except ValueError:
        return None


def ask_to_add(device: str, ask: bool = True) -> bool:
    """Offer to add an unlisted LM Link device before runs it serves are recorded without specs.

    Asks only when `ask` and on a terminal; otherwise prints how to add it. True when it was added.
    """
    print(f"\n{device} serves this model over LM Link, but it isn't in {devices_file()}, so runs "
          "record no hardware for it (no CPU, GPU or memory, so no hardware key).")
    if not (ask and sys.stdin.isatty() and sys.stdout.isatty()):
        print(f"Add it with: crucible devices add {device} --cpu ... --gpu ... --ram-gb ...")
        return False
    try:
        if input(f"Add {device} now? [Y/n] ").strip().lower() in ("n", "no"):
            print("Running without its hardware.")
            return False
        cpu = input("  CPU (e.g. AMD Ryzen 7 7700, Apple M1 Pro): ").strip()
        gpu = input("  Discrete GPU with its memory (e.g. NVIDIA RTX 5070 Ti 16GB; blank for none): ").strip()
        ram = _ram(input("  System RAM in GB (unified memory on Apple silicon): "))
    except (EOFError, KeyboardInterrupt):
        print("\nRunning without its hardware.")
        return False
    if not (cpu or gpu):
        print("No CPU or GPU given; running without its hardware.")
        return False
    path = add_device(device, cpu, gpu, ram)
    print(f"Added {device} ({key(cpu, gpu, ram) or 'no key'}) to {path}.")
    return True


def devices_main() -> None:
    parser = argparse.ArgumentParser(
        prog="crucible devices",
        description="The machines that serve models to this one over LM Link, from this machine's "
                    "devices file (local, never committed). With no command, lists them.",
    )
    sub = parser.add_subparsers(dest="command")
    add = sub.add_parser("add", help="Add or replace a machine")
    add.add_argument("name", help="The name LM Link reports for it (lms link status)")
    add.add_argument("--cpu", help="CPU, e.g. 'AMD Ryzen 7 7700' or 'Apple M1 Pro'")
    add.add_argument("--gpu", help="Discrete GPU with its memory, e.g. 'NVIDIA RTX 5070 Ti 16GB'")
    add.add_argument("--ram-gb", type=float, help="System RAM in GB (unified memory on Apple silicon)")
    add.add_argument("--alias", action="append", default=[], help="Another name LM Link reports for it")
    sub.add_parser("this", help="Print this machine's entry, to paste into the devices file of a machine it serves")
    args = parser.parse_args()

    if args.command == "add":
        if not (args.cpu or args.gpu):
            parser.error("give at least --cpu or --gpu")
        path = add_device(args.name, args.cpu, args.gpu, args.ram_gb, args.alias)
        print(f"Added {args.name} ({key(args.cpu, args.gpu, args.ram_gb) or 'no key'}) to {path}.")
    elif args.command == "this":
        from crucible import environment
        here = environment.machine()
        entry = {k: here.get(k) for k in FIELDS}
        print(yaml.safe_dump({"devices": {here.get("hostname") or "this-machine": entry}}, sort_keys=False), end="")
    else:
        path, listed = devices_file(), devices()
        if not listed:
            print(f"No devices listed in {path}. Runs served by this machine record its hardware on their own;\n"
                  "add the machines that serve models to it over LM Link with `crucible devices add`.")
            return
        print(f"{path}:")
        for name, entry in listed.items():
            parts = [entry["cpu"], entry["gpu"], f"{entry['ram_gb']:g} GB" if entry["ram_gb"] else None]
            aliases = f"  (also {', '.join(entry['aliases'])})" if entry["aliases"] else ""
            print(f"  {name}: {key(entry['cpu'], entry['gpu'], entry['ram_gb']) or 'no key'}  "
                  f"[{', '.join(p for p in parts if p)}]{aliases}")
