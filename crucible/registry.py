"""The registry: reviewed data about makers, models, packagers and machines, and the one resolver that says
what a published run *is* from its record plus that data.

The repo's `registry/*.yaml` is the source of truth (hand-reviewed; docs/bundle-format.md#registry).
`crucible publish` copies it into a bundle as `registry/<name>.json`, and `load()` reads either form.

`Registry.resolve_run(run)` is a pure function of one run record and the registry: no other run is
consulted, so the answer never depends on what else was published. It reads format 3 records and the
format 4 shape planned in the dashboard rewrite (model.packager, model.maker, model.id, model.raw_base,
model.format_source, serving_host, harness_host, hardware.key). It never parses `model.variant_key`.

Derived IDs (`Resolution.artifact_id` and friends) are composed from resolved parts, URL-safe and
deterministic; a missing part is the literal `unrecorded`, and nothing merges by inference.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

REGISTRY_DIR = Path(__file__).resolve().parents[1] / "registry"
NAMES = ("makers", "models", "packagers", "machines", "overrides")
FORMAT_VERSION = 3
OVERRIDE_KEYS = ("model", "packager", "format", "quant", "machine")
UNRECORDED = "unrecorded"

GGUF_QUANT = re.compile(r"^i?q\d(_[a-z0-9]+)*$", re.IGNORECASE)
MLX_QUANT = re.compile(r"^(mlx-)?\d+bit$", re.IGNORECASE)
LOCAL_PROVIDERS = ("lmstudio", "ollama")


# An IPv4/IPv6 address or a host name derived from one (ip-192-168-1-5, 192-168-1-5)
IP_LIKE = re.compile(r"(?<![\w.])(?:\d{1,3}[.-]){3}\d{1,3}(?![\w])|(?:^|[^\w])ip-\d{1,3}-\d{1,3}-\d{1,3}-\d{1,3}"
                     r"|(?:[0-9a-f]{1,4}:){2,7}[0-9a-f]{1,4}", re.I)


def slug(text, keep_slash: bool = False) -> str:
    """Lowercase, URL-safe (a-z0-9._-, and / when asked); anything else becomes a hyphen."""
    pattern = r"[^a-z0-9._/-]+" if keep_slash else r"[^a-z0-9._-]+"
    return re.sub(pattern, "-", str(text).strip().lower()).strip("-")


def format_from_quant(quant: str | None) -> str | None:
    """The format a quant name implies: GGUF's Q4_K_M and IQ2_XS, MLX's 4bit; None for anything else (MXFP4)."""
    if not quant:
        return None
    if GGUF_QUANT.match(quant):
        return "gguf"
    if MLX_QUANT.match(quant):
        return "mlx"
    return None


@dataclass(frozen=True)
class Resolution:
    run_uuid: str | None
    model_id: str
    maker: str | None
    packager: str | None
    format: str | None
    quant: str | None
    where: str | None
    provider: str | None
    machine: str | None
    hardware_key: str | None
    reasoning_level: str
    harness: str | None
    sources: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)

    @property
    def artifact_id(self) -> str:
        """The weights: <model>~<packager>~<format>~<quant>, or <model>~api for a cloud run."""
        if self.where == "cloud":
            return f"{self.model_id}~api"
        return "~".join([self.model_id] + [slug(p) if p else UNRECORDED for p in (self.packager, self.format, self.quant)])

    @property
    def variant_id(self) -> str:
        """What changes the answer: <artifact>~r-<reasoning level>~<harness>."""
        return f"{self.artifact_id}~r-{slug(self.reasoning_level) or UNRECORDED}~{slug(self.harness) if self.harness else UNRECORDED}"

    @property
    def deployment_id(self) -> str:
        """Where it ran: local~<hardware key> or cloud~<provider>."""
        if self.where == "cloud":
            return f"cloud~{slug(self.provider) if self.provider else UNRECORDED}"
        return f"{self.where or UNRECORDED}~{slug(self.hardware_key) if self.hardware_key else UNRECORDED}"

    @property
    def setup_id(self) -> str:
        return f"{self.variant_id}@{self.deployment_id}"

    @property
    def unrecorded(self) -> bool:
        """True when any part of the setup id is unrecorded."""
        parts = [self.harness, self.where]
        parts += [self.provider] if self.where == "cloud" else [self.packager, self.format, self.quant, self.hardware_key]
        return self.model_id.startswith("unknown/") or any(not p for p in parts)


def _norm(value) -> str | None:
    return value.strip().lower() if isinstance(value, str) and value.strip() else None


def _by_id(entries, key: str = "id") -> dict:
    return {e[key]: e for e in entries if isinstance(e, dict) and isinstance(e.get(key), str)}


class Registry:
    def __init__(self, data: dict):
        self.data = {name: data.get(name) or {} for name in NAMES}
        d = self.data
        self.makers = _by_id(d["makers"].get("makers") or [])
        self.models = _by_id(d["models"].get("models") or [])
        self.packagers = _by_id(d["packagers"].get("packagers") or [])
        machines = d["machines"]
        self.energy = machines.get("energy") or {}
        self.hardware = _by_id(machines.get("hardware") or [], "key")
        self.machines = _by_id(machines.get("machines") or [])
        self.overrides = d["overrides"].get("runs") or []
        self._lower_models = {k.lower(): k for k in self.models}
        self._aliases = {}
        for model in self.models.values():
            for alias in model.get("aliases") or []:
                if isinstance(alias, dict) and isinstance(alias.get("base"), str):
                    self._aliases.setdefault(alias["base"], (model["id"], alias))
        self._spellings = {}
        for pid, p in self.packagers.items():
            self._spellings[pid.lower()] = pid
        for pid, p in self.packagers.items():
            for spelling in p.get("spellings") or []:
                self._spellings.setdefault(_norm(spelling).lstrip("~"), pid)
        self._hosts = {}
        self._machine_ids = {}
        for mid, m in self.machines.items():
            for host in m.get("host_aliases") or []:
                self._hosts.setdefault(host.strip().lower(), mid)
            for machine_id in m.get("machine_ids") or []:
                self._machine_ids.setdefault(machine_id, mid)
        self._overrides = {}
        for entry in self.overrides:
            for uuid in entry.get("run_uuids") or []:
                self._overrides.setdefault(uuid, entry)

    # ------------------------------------------------------------------ checks

    def problems(self) -> list[str]:
        found = []

        def dupes(label, values):
            seen = set()
            for v in values:
                if v in seen:
                    found.append(f"{label} {v!r} appears more than once")
                seen.add(v)

        dupes("maker id", [e.get("id") for e in self.data["makers"].get("makers") or []])
        dupes("model id", [e.get("id") for e in self.data["models"].get("models") or []])
        dupes("packager id", [e.get("id") for e in self.data["packagers"].get("packagers") or []])
        dupes("hardware key", [e.get("key") for e in self.data["machines"].get("hardware") or []])
        dupes("machine id", [e.get("id") for e in self.data["machines"].get("machines") or []])
        for label, entries in (("maker", self.data["makers"].get("makers")), ("model", self.data["models"].get("models")),
                               ("packager", self.data["packagers"].get("packagers")),
                               ("machine", self.data["machines"].get("machines"))):
            found += [f"a {label} entry has no id" for e in entries or [] if not isinstance(e, dict) or not e.get("id")]
        found += ["a hardware entry has no key" for e in self.data["machines"].get("hardware") or [] if not e.get("key")]

        aliases, hosts, ids, spellings = [], [], [], []
        for model in self.models.values():
            mid, maker = model["id"], model.get("maker")
            if mid != mid.lower() or mid.count("/") != 1:
                found.append(f"model {mid!r}: the id must be lowercase <maker>/<name>")
            if maker not in self.makers:
                found.append(f"model {mid}: maker {maker!r} isn't in makers.yaml")
            if mid.split("/")[0] != maker:
                found.append(f"model {mid}: the id's maker prefix doesn't match its maker {maker!r}")
            if model.get("packager") and model["packager"] not in self.packagers:
                found.append(f"model {mid}: packager {model['packager']!r} isn't in packagers.yaml")
            for alias in model.get("aliases") or []:
                base = alias.get("base") if isinstance(alias, dict) else None
                if not base:
                    found.append(f"model {mid}: an alias has no base")
                    continue
                aliases.append(base)
                if not str(alias.get("reason") or "").strip():
                    found.append(f"model {mid}: alias {base!r} has no reason")
                if base.lower() in self._lower_models and self._lower_models[base.lower()] != mid:
                    found.append(f"model {mid}: alias {base!r} is another model's id")
                if alias.get("packager") and alias["packager"] not in self.packagers:
                    found.append(f"model {mid}: alias {base!r} packager {alias['packager']!r} isn't in packagers.yaml")
        dupes("alias", aliases)
        for p in self.packagers.values():
            if p.get("kind") not in ("repackager", "maker"):
                found.append(f"packager {p['id']}: kind must be repackager or maker")
            spellings += [_norm(s).lstrip("~") for s in p.get("spellings") or []]
        dupes("packager spelling", spellings)
        for p in self.packagers.values():
            for s in p.get("spellings") or []:
                key = _norm(s).lstrip("~")
                if key in self.packagers and key != p["id"]:
                    found.append(f"packager {p['id']}: spelling {s!r} is packager {key}'s id")
        for m in self.machines.values():
            if m.get("hardware") is not None and m["hardware"] not in self.hardware:
                found.append(f"machine {m['id']}: hardware {m['hardware']!r} isn't in the hardware list")
            hosts += [h.strip().lower() for h in m.get("host_aliases") or []]
            for h in m.get("host_aliases") or []:
                if IP_LIKE.search(str(h)):
                    found.append(f"machine {m.get('id')}: host alias {h!r} looks like an IP address; "
                                 "the registry is published, so never list one")
            ids += list(m.get("machine_ids") or [])
        dupes("host alias", hosts)
        dupes("machine_id", ids)
        for key, hw in self.hardware.items():
            if not isinstance(hw.get("watts"), (int, float)):
                found.append(f"hardware {key}: watts must be a number")
        seen_runs = set()
        for i, entry in enumerate(self.overrides):
            where = f"override {i}"
            if not str(entry.get("reason") or "").strip():
                found.append(f"{where}: no reason")
            for uuid in entry.get("run_uuids") or []:
                if uuid in seen_runs:
                    found.append(f"{where}: run {uuid} is in more than one override")
                seen_runs.add(uuid)
            if not entry.get("run_uuids"):
                found.append(f"{where}: no run_uuids")
            keys = entry.get("set") or {}
            found += [f"{where}: can't set {k!r} (allowed: {', '.join(OVERRIDE_KEYS)})" for k in keys if k not in OVERRIDE_KEYS]
            if keys.get("model") and keys["model"] not in self.models:
                found.append(f"{where}: model {keys['model']!r} isn't in models.yaml")
            if keys.get("packager") and keys["packager"] not in self.packagers:
                found.append(f"{where}: packager {keys['packager']!r} isn't in packagers.yaml")
            if keys.get("machine") and keys["machine"] not in self.machines:
                found.append(f"{where}: machine {keys['machine']!r} isn't in machines.yaml")
        return found

    # ------------------------------------------------------------------ lookups

    def model_for_base(self, raw: str | None) -> tuple[str, str, dict | None] | None:
        """(model id, how, alias) for a raw model.base: 'alias' for a listed alias, 'recorded' for the id itself."""
        if not isinstance(raw, str) or not raw:
            return None
        if raw in self._aliases:
            mid, alias = self._aliases[raw]
            return mid, "alias", alias
        mid = self._lower_models.get(raw.strip().lower())
        return (mid, "recorded", None) if mid else None

    def maker_for_base(self, raw: str | None) -> str | None:
        found = self.model_for_base(raw)
        return self.models[found[0]]["maker"] if found else None

    def packager_id(self, recorded) -> str | None:
        """A recorded packager spelling as its registry id (Qwen -> qwen, ~openai -> openai); else slugged as it is."""
        if not isinstance(recorded, str) or not recorded.strip():
            return None
        key = recorded.strip().lower().lstrip("~")
        return self._spellings.get(key) or (slug(key) or None)

    def machine_for_host(self, host) -> str | None:
        return self._hosts.get(host.strip().lower()) if isinstance(host, str) and host.strip() else None

    # ------------------------------------------------------------------ resolution

    def resolve_run(self, run: dict) -> Resolution:
        run = run or {}
        model, endpoint = run.get("model") or {}, run.get("endpoint") or {}
        hardware, prov, harness = run.get("hardware") or {}, run.get("provenance") or {}, run.get("harness") or {}
        uuid = run.get("run_uuid")
        version = run.get("format_version") if isinstance(run.get("format_version"), int) else 3
        override = (self._overrides.get(uuid) or {}).get("set") or {}
        override_reason = (self._overrides.get(uuid) or {}).get("reason")
        sources, notes = {}, []

        provider = endpoint.get("provider")
        where = endpoint.get("where") or (None if not provider else ("local" if provider in LOCAL_PROVIDERS else "cloud"))

        # model
        raw = model.get("raw_base") or model.get("base")
        found = None
        if override.get("model") in self.models:
            model_id, sources["model_from"] = override["model"], "override"
            notes.append(f"model set to {model_id} by an override: {override_reason}")
        else:
            if version >= 4 and model.get("id") in self.models:
                found = (model["id"], "recorded", None)
            else:
                found = self.model_for_base(raw)
            if found:
                model_id, how, alias = found
                sources["model_from"] = how
                if how == "alias":
                    notes.append(f"recorded as model {raw}; corrected to {model_id}: {alias['reason'].strip()}")
            else:
                model_id = "unknown/" + ((slug(str(raw).lstrip("~"), keep_slash=True) if raw else "") or UNRECORDED)
                sources["model_from"] = "unknown"
                notes.append(f"model {raw!r} isn't in the registry")
        entry = self.models.get(model_id)

        # maker
        origin = model.get("origin") or {}
        recorded_maker = _norm(model.get("maker")) or _norm(origin.get("maker"))
        # One model has one maker: a known model takes the registry's, so a run can't split it.
        if entry:
            maker = entry["maker"]
            sources["maker_from"] = "recorded" if recorded_maker == maker else "registry"
            if recorded_maker and recorded_maker != maker:
                notes.append(f"recorded maker {recorded_maker}; the registry's maker for {model_id} is {maker}")
        elif recorded_maker:
            maker, sources["maker_from"] = recorded_maker, "recorded"
        else:
            maker, sources["maker_from"] = None, "unknown"

        # packager
        recorded = model.get("packager") or model.get("publisher")
        alias_packager = found[2].get("packager") if found and found[2] else None
        if override.get("packager"):
            packager, sources["packager_from"] = override["packager"], "override"
            notes.append(f"packager set to {packager} by an override: {override_reason}")
        elif recorded:
            packager, sources["packager_from"] = self.packager_id(recorded), "recorded"
            if packager != recorded:
                notes.append(f"packager recorded as {recorded}; read as {packager}")
        elif alias_packager or (entry or {}).get("packager"):
            packager, sources["packager_from"] = alias_packager or entry["packager"], "registry"
            notes.append(f"no packager recorded; the registry says {packager}")
        else:
            packager, sources["packager_from"] = None, "none"

        # format and quant
        quant = model.get("quant")
        quant = quant.strip().lower() if isinstance(quant, str) and quant.strip() else None
        if override.get("quant"):
            quant = str(override["quant"]).lower()
        recorded_format = _norm(model.get("format"))
        if override.get("format"):
            fmt, sources["format_from"] = str(override["format"]).lower(), "override"
            notes.append(f"format set to {fmt} by an override: {override_reason}")
        elif recorded_format:
            fmt, sources["format_from"] = recorded_format, "recorded"
        elif where == "cloud":
            fmt, sources["format_from"] = "api", "cloud"
        else:
            fmt = format_from_quant(quant) if where == "local" else None
            sources["format_from"] = "quant" if fmt else "none"
            if fmt:
                notes.append(f"format not recorded; read as {fmt} from the quant {quant}")

        # machine and hardware
        machine, machine_from = None, "none"
        if where == "local":
            if override.get("machine") in self.machines:
                machine, machine_from = override["machine"], "override"
                notes.append(f"machine set to {machine} by an override: {override_reason}")
            else:
                for source, host in (("serving_host", run.get("serving_host")), ("device", endpoint.get("device")),
                                     ("label", hardware.get("label"))):
                    machine = self.machine_for_host(host)
                    if machine:
                        machine_from = source
                        break
                if machine is None and not endpoint.get("device") and not endpoint.get("served_via") \
                        and not run.get("serving_host"):
                    machine = self._machine_ids.get(prov.get("machine_id"))
                    if machine:
                        machine_from = "machine_id"
                        notes.append("served by the machine that ran it; machine read from its machine_id")
        hardware_key, hardware_from = None, "none"
        if where == "local":
            recorded_key = hardware.get("key") or None
            machine_key = (self.machines.get(machine) or {}).get("hardware") if machine else None
            if recorded_key:
                hardware_key, hardware_from = recorded_key, "recorded"
                if machine_key and machine_key != recorded_key:
                    notes.append(f"recorded hardware {recorded_key} differs from {machine}'s {machine_key}")
            elif machine_key:
                hardware_key, hardware_from = machine_key, "machine"
                notes.append(f"hardware key not recorded; read as {machine_key} from machine {machine}")
        sources["machine_from"], sources["hardware_from"] = machine_from, hardware_from

        reasoning = model.get("reasoning") or {}
        requested, resolved = reasoning.get("requested"), reasoning.get("resolved")
        level = requested if requested not in (None, "", "default") else (resolved or "default")

        return Resolution(run_uuid=uuid, model_id=model_id, maker=maker, packager=packager, format=fmt, quant=quant,
                          where=where, provider=provider, machine=machine, hardware_key=hardware_key,
                          reasoning_level=level, harness=harness.get("id"), sources=sources, notes=notes)

    def energy_cost(self, run: dict, resolution: Resolution | None = None) -> float | None:
        """What a run cost in USD: a local run's time x its machine's watts x the price per kWh (an estimate
        of the electricity used), a cloud run's billed metrics.cost_usd. None when it can't be told."""
        resolution = resolution or self.resolve_run(run)
        if resolution.where == "cloud":
            cost = (run.get("metrics") or {}).get("cost_usd")
            return cost if isinstance(cost, (int, float)) else None
        watts = (self.hardware.get(resolution.hardware_key) or {}).get("watts")
        elapsed, price = run.get("elapsed_s"), self.energy.get("usd_per_kwh")
        if resolution.where != "local" or watts is None or not isinstance(elapsed, (int, float)) or price is None:
            return None
        return watts * elapsed / 3.6e6 * price

    # ------------------------------------------------------------------ files

    def files(self) -> dict:
        """The registry as published: <name> -> the record written to registry/<name>.json."""
        return {name: {"record": "registry", "format_version": FORMAT_VERSION, "name": name, **self.data[name]}
                for name in NAMES}


def load(source=None) -> Registry:
    """A Registry from the repo's registry/*.yaml, or from a published bundle's registry/*.json.

    `source` is a folder holding makers.yaml (the repo's registry/), a bundle folder with a registry/
    folder of JSON files, or the folder of those JSON files; None is the repo's own registry/.
    """
    import yaml
    from crucible import runrecord
    folder = Path(source) if source else REGISTRY_DIR
    data = {}
    if (folder / "makers.yaml").exists():
        for name in NAMES:
            path = folder / f"{name}.yaml"
            data[name] = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}
    else:
        folder = folder / "registry" if (folder / "registry").is_dir() else folder
        for name in NAMES:
            record = runrecord.read_json(folder / f"{name}.json")
            if record is None and name != "overrides":
                raise FileNotFoundError(f"{folder / (name + '.json')}: no registry file")
            data[name] = {k: v for k, v in (record or {}).items() if k not in ("record", "format_version", "name")}
    return Registry(data)


_default: Registry | None = None


def default() -> Registry | None:
    """The repo's registry, loaded once; None when there's none (an installed copy has no registry/ folder)."""
    global _default
    if _default is None and (REGISTRY_DIR / "makers.yaml").exists():
        _default = load()
    return _default
