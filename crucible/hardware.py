"""The machines that run inference: what each is called and what hardware it has.

A run records the device that ran the weights, under the name you gave it. That's this machine, or
an LM Link peer serving the model to it. LM Link names each device and gives it a stable identifier
but reports no hardware, so Crucible keeps a devices file, local to each person and never part of the
repo: `~/.crucible/devices.yaml` (or `CRUCIBLE_DEVICES_FILE`).

    devices:
      gpu-box:                      # the name runs are stamped with
        cpu: AMD Ryzen 9 7950X
        gpu: NVIDIA RTX 4090 24GB   # discrete GPU with its memory; null on Apple silicon
        ram_gb: 64
        ids: [lmlink:6f2c...]       # how Crucible recognizes it (LM Link device ID, this machine's ID)
        aliases: [desktop-a1b2c3]   # other names LM Link has reported for it

A device is recognized by its ID first, then by name or alias (and then its ID is remembered).
`crucible run` asks about a serving device it doesn't recognize before the first run, and
`crucible devices setup` names every device up front. This machine's own hardware is always read from
the machine; a peer's comes from the file.
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
# The machines that run models for Crucible here: this one and its LM Link peers. Runs are stamped
# with these names and specs. Local to this machine; never committed or published.
# Edit it, or use `crucible devices setup` / `crucible devices add`.
"""

_cache: dict = {}


def devices_file() -> Path:
    return Path(os.environ.get("CRUCIBLE_DEVICES_FILE") or Path.home() / ".crucible" / "devices.yaml")


def lmlink_id(identifier: str | None) -> str | None:
    return f"lmlink:{identifier}" if identifier else None


def machine_ref(machine_id: str | None) -> str | None:
    return f"machine:{machine_id}" if machine_id else None


def devices() -> dict[str, dict]:
    """name -> {cpu, gpu, ram_gb, ids, aliases} from the devices file; empty when there is none.

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


def _strings(value) -> list[str]:
    return [str(v) for v in ([value] if isinstance(value, str) else value or [])]


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
            parsed[str(name)] = {"cpu": entry.get("cpu") or None, "gpu": entry.get("gpu") or None,
                                 "ram_gb": float(ram) if ram is not None else None,
                                 "ids": _strings(entry.get("ids")), "aliases": _strings(entry.get("aliases"))}
        return parsed
    except (OSError, ValueError, TypeError, AttributeError, yaml.YAMLError) as exc:
        print(f"Warning: ignoring {path}: {exc}", file=sys.stderr)
        return {}


def _short(name: str) -> str:
    return name.split(".")[0]


def resolve(name: str | None = None, ids: list[str | None] | tuple = ()) -> str | None:
    """The listed device with one of these IDs, else the one with this name or alias; None if neither."""
    listed = devices()
    for ref in filter(None, ids):
        found = next((device for device, entry in listed.items() if ref in entry["ids"]), None)
        if found:
            return found
    if not name:
        return None
    key = _short(name).lower()
    return next((device for device, entry in listed.items()
                 if key == device.lower() or key in (_short(a).lower() for a in entry["aliases"])), None)


def canonical(name: str | None, ids: list[str | None] | tuple = ()) -> str | None:
    """The device's name in the devices file, or the reported short name when it isn't listed."""
    found = resolve(name, ids)
    return found or (_short(name) if name else None)


def specs(name: str | None, ids: list[str | None] | tuple = ()) -> dict | None:
    """hostname, cpu, gpu, ram_gb for a listed device with specs; None otherwise."""
    device = resolve(name, ids)
    entry = devices().get(device) if device else None
    if not entry or not (entry["cpu"] or entry["gpu"]):
        return None
    return {"hostname": device, **{k: entry[k] for k in FIELDS}}


def unlisted(inference: dict) -> str | None:
    """The LM Link peer that served a run when the devices file has no specs for it."""
    if inference.get("same_machine") is not False or inference.get("served_via") != "LM Link":
        return None
    device = inference.get("device")
    return device if device and not specs(device, [inference.get("device_id")]) else None


def _load_raw() -> dict:
    try:
        data = yaml.safe_load(devices_file().read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        data = {}
    if not isinstance(data.get("devices"), dict):
        data["devices"] = {}
    return data


def _save_raw(data: dict) -> Path:
    path = devices_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HEADER + yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    _cache.clear()
    return path


def add_device(name: str, cpu: str | None = None, gpu: str | None = None, ram_gb: float | None = None,
               aliases: list[str | None] | None = None, ids: list[str | None] | None = None,
               keep_specs: bool = False) -> Path:
    """Add a device, or update it: new specs replace old ones (unless `keep_specs` and none are
    given), and IDs and aliases are added to the ones it has. Returns the file's path."""
    data = _load_raw()
    entry = data["devices"].get(name) or {}
    if not (keep_specs and not (cpu or gpu or ram_gb)):
        entry.update(cpu=cpu or None, gpu=gpu or None, ram_gb=float(ram_gb) if ram_gb else None)
    for field, new in (("ids", ids), ("aliases", aliases)):
        merged = _strings(entry.get(field))
        merged += [v for v in dict.fromkeys(filter(None, new or [])) if v not in merged and v != name]
        if merged:
            entry[field] = merged
    data["devices"][name] = {k: entry.get(k) for k in (*FIELDS, "ids", "aliases") if k in entry}
    return _save_raw(data)


def remember(name: str, ids: list[str | None], reported: str | None = None) -> None:
    """Link IDs (and the name LM Link reported) to a device found by name, so it's found by ID next time."""
    entry = devices().get(name)
    if entry is None:
        return
    new_ids = [i for i in filter(None, ids) if i not in entry["ids"]]
    alias = _short(reported) if reported and _short(reported).lower() != name.lower() else None
    new_alias = [alias] if alias and alias.lower() not in (a.lower() for a in entry["aliases"]) else []
    if new_ids or new_alias:
        try:
            add_device(name, ids=new_ids, aliases=new_alias, keep_specs=True)
        except OSError:
            pass


def serving(machine: dict, inference: dict) -> dict | None:
    """hostname, cpu, gpu, ram_gb of the device that ran inference: this machine (its specs read from
    it, under the name it was given if any), or the LM Link peer that served the model (its specs from
    the devices file). Hostname is the device's name, never the endpoint address."""
    if inference.get("same_machine") is False:
        device = inference.get("device")
        return specs(device, [inference.get("device_id")]) or (
            {"hostname": device, "cpu": None, "gpu": None, "ram_gb": None} if device else None)
    if not machine:
        return None
    return {"hostname": machine.get("name") or machine.get("hostname"), **{k: machine.get(k) for k in FIELDS}}


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
# Naming devices, and `crucible devices`
# --------------------------------------------------------------------------

def describe(found: dict | None) -> str:
    """"Apple M5 Pro, 48 GB unified memory" or "AMD Ryzen 7 7700, NVIDIA RTX 5070 Ti 16GB, 32 GB RAM"."""
    if not found or not (found.get("cpu") or found.get("gpu")):
        return "unknown hardware"
    ram = found.get("ram_gb")
    apple = bool(found.get("cpu") and APPLE_SILICON.match(_slug(found["cpu"])) and not found.get("gpu"))
    memory = f"{ram:g} GB {'unified memory' if apple else 'RAM'}" if ram else None
    gpu = ", ".join(f"{n.strip()} {round(m)}GB" if m and not IN_NAME_MEMORY.search(n.lower()) else n.strip()
                    for n, m in _gpus(found["gpu"])) if found.get("gpu") else None
    text = ", ".join(p for p in (found.get("cpu"), gpu, memory) if p)
    k = key(found.get("cpu"), found.get("gpu"), ram)
    return f"{text} ({k})" if k else text


def _ram(text: str) -> float | None:
    text = text.strip().lower().removesuffix("gb").strip()
    try:
        return float(text) if text else None
    except ValueError:
        return None


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _label(device: dict) -> str:
    return device.get("name") or _short(device.get("reported") or "") or "this machine"


def hint(device: dict) -> None:
    """Off a terminal (or mid-suite): say what's missing and how to fix it, without asking."""
    if device["this_machine"]:
        print(f"Note: this machine ({describe(device['specs'])}) has no name in {devices_file()}; runs are "
              "stamped with its hostname. Name it with `crucible devices setup`.")
    else:
        print(f"Note: {_label(device)} serves models over LM Link but has no hardware listed in {devices_file()}, "
              "so its runs record no CPU, GPU or memory. Add it with `crucible devices setup`.")


def ask_to_name(device: dict, for_run: bool = True) -> str | None:
    """Ask for a device's name (and a peer's hardware, which LM Link doesn't report) and save it.

    Returns the name saved, or None when skipped. Only call on a terminal.
    """
    default = _label(device)
    reported = _short(device["reported"]) if device.get("reported") else None
    try:
        if device["this_machine"]:
            print(f"\n{'This model runs on this machine' if for_run else 'This machine'}: {describe(device['specs'])}.")
            name = input(f"Give it a name for your results [{default}]: ").strip() or default
            found = device["specs"] or {}
            cpu, gpu, ram = found.get("cpu"), found.get("gpu"), found.get("ram_gb")
        else:
            where = f"{reported} (LM Link)" if reported else "An LM Link peer"
            print(f"\n{where} {'serves this model' if for_run else 'is an LM Link peer'}. LM Link doesn't report a machine's hardware, so tell Crucible "
                  "once (or run `crucible devices this` on that machine and paste its entry into "
                  f"{devices_file()}).")
            name = device.get("name") or input(f"  Name for your results [{default}]: ").strip() or default
            cpu = input("  CPU (e.g. AMD Ryzen 7 7700, Apple M5 Pro): ").strip()
            gpu = input("  Discrete GPU with its memory (e.g. NVIDIA RTX 5070 Ti 16GB; blank for none): ").strip()
            ram = _ram(input("  System RAM in GB (unified memory on Apple silicon): "))
    except (EOFError, KeyboardInterrupt):
        print("\nSkipped; runs record it without a name or hardware.")
        return None
    add_device(name, cpu, gpu, ram, aliases=[reported], ids=device["ids"], keep_specs=not (cpu or gpu))
    print(f"Saved {name}: {describe({'cpu': cpu, 'gpu': gpu, 'ram_gb': ram})}."
          + ("" if (cpu or gpu) else " No hardware given; you'll be asked again."))
    return name


def check_devices(found: list[dict], ask: bool = True, seen: set | None = None) -> None:
    """Ask about (or point out) each device the devices file doesn't fully know, once per `seen`."""
    from crucible import environment
    for device in found:
        token = tuple(device["ids"])
        if not environment.needs_naming(device) or (seen is not None and token in seen):
            continue
        if seen is not None:
            seen.add(token)
        ask_to_name(device) if ask and _interactive() else hint(device)


def devices_main() -> None:
    parser = argparse.ArgumentParser(
        prog="crucible devices",
        description="The machines that run models for Crucible here (this one and its LM Link peers), "
                    "from this machine's devices file: local, never committed. With no command, lists them.",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("setup", help="Name this machine and every LM Link peer (asks for each one not known yet)")
    add = sub.add_parser("add", help="Add or update a device by hand")
    add.add_argument("name", help="The name runs are stamped with")
    add.add_argument("--cpu", help="CPU, e.g. 'AMD Ryzen 7 7700' or 'Apple M5 Pro'")
    add.add_argument("--gpu", help="Discrete GPU with its memory, e.g. 'NVIDIA RTX 5070 Ti 16GB'")
    add.add_argument("--ram-gb", type=float, help="System RAM in GB (unified memory on Apple silicon)")
    add.add_argument("--alias", action="append", default=[], help="Another name LM Link reports for it")
    add.add_argument("--id", action="append", default=[], dest="ids",
                     help="An ID to recognize it by (lmlink:<deviceIdentifier> from `lms link status --json`)")
    sub.add_parser("this", help="Print this machine's entry, to paste into the devices file of a machine it serves")
    args = parser.parse_args()
    from crucible import environment

    if args.command == "add":
        if not (args.cpu or args.gpu or args.ids or args.alias):
            parser.error("give --cpu or --gpu (or --id/--alias to link an existing device)")
        path = add_device(args.name, args.cpu, args.gpu, args.ram_gb, args.alias, args.ids,
                          keep_specs=not (args.cpu or args.gpu))
        print(f"Saved {args.name}: {describe(specs(args.name))} in {path}.")
    elif args.command == "this":
        here = environment.machine()
        link = environment._link()
        name = environment.this_machine_name({}, here.get("hostname")) or here.get("hostname") or "this-machine"
        entry = {k: here.get(k) for k in FIELDS}
        if link:
            entry["ids"] = [lmlink_id(link["deviceIdentifier"])]
        print(f"# {describe(here)}; paste under `devices:` in the other machine's {devices_file().name}")
        print(yaml.safe_dump({name: entry}, sort_keys=False), end="")
    elif args.command == "setup":
        found = environment.known_devices()
        todo = [d for d in found if environment.needs_naming(d)]
        if not todo:
            print(f"Every device is named in {devices_file()}:")
        elif not _interactive():
            parser.error("setup asks questions; run it in a terminal")
        for device in todo:
            ask_to_name(device, for_run=False)
        _list(environment.known_devices() if todo else found)
    else:
        _list(environment.known_devices())


def _list(found: list[dict]) -> None:
    from crucible import environment
    listed = devices()
    print(f"{devices_file()}:" if listed else f"No devices in {devices_file()} yet.")
    for name, entry in listed.items():
        here = next((d for d in found if d.get("name") == name and d["this_machine"]), None)
        hw = describe(here["specs"]) if here else describe(entry)
        print(f"  {name}{' (this machine)' if here else ''}: {hw}")
    missing = [d for d in found if environment.needs_naming(d)]
    for device in missing:
        what = "this machine" if device["this_machine"] else f"LM Link peer {_label(device)}"
        print(f"  Not set up: {what}" + ("" if device["this_machine"] else " (no hardware listed)"))
    if missing:
        print("Run `crucible devices setup` to name them.")
