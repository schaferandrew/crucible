"""The run record (meta.json), score records and status records: what a run is and how it scored.

Layout: runs/<model_slug>/<task>/<timestamp>/ holding meta.json (the run record), prompt.txt,
stdout.txt, stderr.txt, command.sh, session.json, workspace/ (agent runs), and:

  scores/r<rubric_version>.<method>.json   one score record per rubric version and method
  status.json                              status records (invalidations), an append-only list

The run record never changes after the run; a rescore adds a score record, an invalidation adds a
status record. Everything under `local` stays on this machine: `crucible publish` drops it.
See docs/data-model.md.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from crucible import hostnames, origin

FORMAT_VERSION = 3
# A run folder is <model_slug>/<task>/<timestamp>; before 3.0.0 it was <model_slug>/<category>/<test_id>/<timestamp>
RUN_GLOB = "*/*/*/meta.json"
LEGACY_GLOB = "*/*/*/*/meta.json"
SCORES_DIR = "scores"
STATUS_FILE = "status.json"
SCALE = 10

# Fixed namespace for every UUIDv5 crucible derives (legacy runs and machines)
NAMESPACE = uuid.UUID("6f0c1d2e-8a4b-5c3d-9e7f-c7a1b5e0d3f9")
LOCAL_PROVIDERS = ("lmstudio", "ollama")
DATE_SUFFIX = re.compile(r"-(?:\d{4}-\d{2}-\d{2}|\d{8})$")
# LM Studio addresses one loaded variant as model@quant (qwen/qwen3.6-35b-a3b@6bit)
VARIANT_SUFFIX = re.compile(r"@[^/]+$")

# Provider prefixes a model key can carry before its maker/model part
PROVIDER_PREFIXES = ("lmstudio", "ollama", "openrouter")
FORMAT_TAG = re.compile(r"[-_](mlx|gguf)$", re.I)
BIT_TAG = re.compile(r"[@-](\d+)bit$", re.I)


def clean_base_model(model_id: str | None) -> tuple[str | None, str | None, str | None, str | None]:
    """A model key split into (base, format, quant, publisher), keeping what names the model.

    Strips only what never names it: the provider prefix (lmstudio/, ollama/, openrouter/), a date
    suffix, OpenRouter's leading ~ (latest alias; the maker after it stays), the :free tier suffix,
    and trailing format and quant tags (-mlx, -gguf, @4bit, -8bit). A packager namespace in front
    (mlx-community/...) moves to the publisher; the maker it hides is not guessed (the published
    corrections map fills it). Training variants such as -qat are part of the model and stay.

        'lmstudio/granite-4.2-3b-mlx@4bit' -> ('granite-4.2-3b', 'mlx', '4bit', None)
        'mlx-community/muse-glimmer-30b'   -> ('muse-glimmer-30b', None, None, 'mlx-community')
        'openrouter/~openai/gpt-luna-latest' -> ('openai/gpt-luna-latest', None, None, None)
        'google/gemma-4-12b-qat'           -> ('google/gemma-4-12b-qat', None, None, None)
    """
    if not model_id:
        return None, None, None, None
    name = model_id
    prefix, _, rest = name.partition("/")
    if prefix in PROVIDER_PREFIXES and rest:
        name = rest
    name = name.lstrip("~")
    if name.endswith(":free"):
        name = name[:-len(":free")]
    name = DATE_SUFFIX.sub("", name)
    fmt = quant = None
    m = BIT_TAG.search(name)
    if m:
        quant, fmt, name = f"{m.group(1)}bit", "mlx", name[:m.start()]
    m = FORMAT_TAG.search(name)
    if m:
        fmt, name = m.group(1).lower(), name[:m.start()]
    publisher = None
    org, _, model = name.partition("/")
    if model and org.lower() in origin.PACKAGERS:
        publisher, name = org.lower(), model
    return name or None, fmt, quant, publisher


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def is_record(meta: dict | None) -> bool:
    return bool(meta) and meta.get("record") == "run"


def run_dirs(runs_dir: Path) -> list[Path]:
    """Every run folder in the 3.0.0 layout, sorted."""
    return sorted(p.parent for p in runs_dir.glob(RUN_GLOB))


def legacy_run_dirs(runs_dir: Path) -> list[Path]:
    """Run folders still in the pre-3.0.0 layout (`crucible migrate` moves them)."""
    return sorted(p.parent for p in runs_dir.glob(LEGACY_GLOB)
                  if not is_record(read_json(p)))


def require_migrated(runs_dir: Path) -> None:
    """Stop with a pointer to `crucible migrate` when runs_dir still has runs in the old layout."""
    old = legacy_run_dirs(runs_dir) if runs_dir.is_dir() else []
    if old:
        raise SystemExit(f"{len(old)} runs in {runs_dir} are from before Crucible 3.0.0 "
                         f"(e.g. {old[0].relative_to(runs_dir)}). Run `crucible migrate --runs {runs_dir}` first.")


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------

def host_name(hostname: str | None) -> str:
    """A hostname as legacy identities use it: its first label, lowercased (Ironwood.local -> ironwood)."""
    return re.sub(r"[^a-z0-9-]+", "-", (hostname or "").split(".")[0].lower()).strip("-")


def legacy_machine_id(hostname: str) -> str:
    """The machine ID of a run recorded before machines had one, derived from its hostname."""
    return "m_" + uuid.uuid5(NAMESPACE, f"host:{host_name(hostname)}").hex[:12]


def legacy_run_uuid(hostname: str, legacy_run_id: str) -> str:
    """A run recorded before run_uuid existed: the same UUID every time, on any machine."""
    return str(uuid.uuid5(NAMESPACE, f"{legacy_machine_id(hostname)}:{legacy_run_id}"))


# --------------------------------------------------------------------------
# Model, endpoint and hardware
# --------------------------------------------------------------------------

def provider_of(model: str | None) -> str | None:
    from crucible.providers import PROVIDERS
    name = (model or "").partition("/")[0]
    return name if name in PROVIDERS or name == "opencode" else None


def where(model: str | None, inference: dict | None) -> str | None:
    """local or cloud: what ran the weights. None when it can't be told (no provider)."""
    local = (inference or {}).get("local")
    if local is not None:
        return "local" if local else "cloud"
    provider = provider_of(model)
    if provider is None:
        return None
    return "local" if provider in LOCAL_PROVIDERS else "cloud"


def base_model(model: str | None) -> str | None:
    """The model without its provider prefix, a loaded variant suffix or a date suffix:
    qwen/qwen3.5-9b, openai/gpt-6-luna."""
    if not model:
        return None
    rest = model.split("/", 1)[1] if provider_of(model) and "/" in model else model
    return DATE_SUFFIX.sub("", VARIANT_SUFFIX.sub("", rest))


def normalize_quant(quant: str | None) -> str | None:
    """Q4_K_M -> q4_k_m, MLX's 4bit -> mlx-4bit, MXFP4 -> mxfp4."""
    if not quant:
        return None
    q = str(quant).strip().lower()
    return f"mlx-{q}" if re.fullmatch(r"\d+bit", q) else q


def implied_variant(model: str | None, quant: str | None) -> dict:
    """publisher and format where the model key or quant name says them; None where they don't."""
    _, fmt, _, publisher = clean_base_model(model)
    key = (base_model(model) or "").lower()
    if fmt is None:
        if publisher == "mlx-community" or re.search(r"[-:_]mlx\b", key) or re.fullmatch(r"\d+bit", str(quant or "").lower()):
            fmt = "mlx"
        elif re.search(r"[-_]gguf\b", key) or publisher == "lmstudio-community":
            fmt = "gguf"
    return {"publisher": publisher, "format": fmt}


def model_record(model: str | None, reasoning: str, resolved: str | None, inference: dict | None,
                 variant: dict | None = None, resolved_source: str | None = None) -> dict:
    inference = inference or {}
    variant = variant or {}
    base, _, quant_from_key, _ = clean_base_model(model)
    implied = implied_variant(model, inference.get("quantization"))
    cloud = where(model, inference) == "cloud"
    publisher = variant.get("publisher") or inference.get("publisher") or implied["publisher"]
    if publisher is None and cloud and base and "/" in base:
        publisher = base.split("/")[0]  # an OpenRouter slug's org
    fmt = variant.get("format") or inference.get("format") or implied["format"]
    fmt = fmt.lower() if isinstance(fmt, str) else None
    quant = variant.get("quant") or inference.get("quantization") or quant_from_key
    if resolved_source is None:
        resolved_source = "requested" if reasoning and reasoning != "default" else ("unknown" if resolved is None else None)
    nq = normalize_quant(quant)
    
    return {
        "id": model,
        "base": base,
        "publisher": publisher,
        # The packaged repo the weights were downloaded from, when the source names it
        "artifact": inference.get("artifact"),
        "format": fmt,
        "quant": quant,
        "reasoning": {
            "requested": reasoning or "default",
            "resolved": resolved,
            "resolved_source": resolved_source
        },
        "context_loaded": inference.get("context_length"),
        "variant_key": "|".join([base or "-", publisher or "-", fmt or ("api" if cloud else "-"), nq or "-"]),
        "display": " · ".join(filter(None, [(base or model or "unknown").split("/")[-1], quant])),
    }


def endpoint_record(model: str | None, inference: dict | None, endpoint: dict | None = None) -> dict:
    inference, endpoint = inference or {}, endpoint or {}
    return {
        "where": where(model, inference),
        "provider": inference.get("provider") or provider_of(model),
        "app": None,
        "served_via": inference.get("served_via"),
        "device": hostnames.public_label(inference.get("device")),
        "upstream": endpoint.get("upstream"),
        "resolved_model": endpoint.get("resolved_model"),
    }


def hardware_record(model: str | None, machine: dict | None, inference: dict | None) -> dict | None:
    """The device that ran the weights. None for cloud runs: the machine that sent the request didn't."""
    from crucible import hardware
    if where(model, inference) != "local":
        return None
    specs = hardware.serving(machine or {}, inference or {})
    if not specs or not any(specs.get(k) for k in ("cpu", "gpu", "ram_gb")):
        return {"key": None, "class": None, "accelerators": [], "system_memory_gb": None, "cpu": None,
                "offload": None, "label": hostnames.public_label((specs or {}).get("hostname"))}
    cards = hardware._gpus(specs["gpu"]) if specs.get("gpu") else []
    key = hardware.key(specs.get("cpu"), specs.get("gpu"), specs.get("ram_gb"))
    kind = "discrete_gpu" if cards else ("apple_silicon" if key and hardware.APPLE_SILICON.match(key) else "cpu")
    return {
        "key": key,
        "class": kind,
        "accelerators": [{"name": name, "memory_gb": round(mem) if mem else None, "count": 1} for name, mem in cards],
        "system_memory_gb": specs.get("ram_gb"),
        "cpu": specs.get("cpu"),
        "offload": None,
        "label": hostnames.public_label(specs.get("hostname")),
    }


def null_provenance() -> dict:
    return {"crucible_version": None, "crucible_commit": None, "crucible_dirty": None, "machine_id": None,
            "machine_label": None, "source": None, "content_hash": None, "submitter": None, "verification": None}


# --------------------------------------------------------------------------
# Format 4 (opt-in: CRUCIBLE_RECORD_FORMAT=4)
# --------------------------------------------------------------------------

# Fields format 4 drops (docs/bundle-format.md#format-4); a published format-4 record may not carry them
V4_DROPPED = ("run_path", "variant_key", "display", "model.variant_key", "model.display", "model.publisher",
              "model.origin.base_repo", "endpoint.app", "endpoint.device", "hardware.offload",
              "provenance.submitter", "provenance.verification", "provenance.machine_label",
              # Host names and machine ids never leave the machine in format 4 (community submissions)
              "serving_host", "harness_host", "hardware.label", "hardware.hostname", "provenance.machine_id")
# What hardware may carry in format 4: the serving machine's class, never its name
V4_HARDWARE = ("key", "chip", "memory_gb", "accelerators", "served_remotely", "nickname")
NICKNAME_MAX = 40
IP_LIKE = re.compile(r"(\d{1,3}\.){3}\d{1,3}|^ip[-_]\d|^[0-9a-f:]*:[0-9a-f:]+$", re.I)


def nickname_problem(value) -> str | None:
    """Why a hardware.nickname can't be published, if it can't: it must be a short, free-text name the user
    chose, never an IP address or an `ip-...` cloud host name."""
    if not isinstance(value, str) or not value.strip():
        return "must be a non-empty string"
    if len(value) > NICKNAME_MAX:
        return f"must be at most {NICKNAME_MAX} characters"
    if any(ord(c) < 32 for c in value):
        return "must be a single line of plain text"
    if IP_LIKE.search(value.strip()):
        return "looks like an IP address or host name"
    return None


def machine_nickname() -> str | None:
    """The name the user chose for their machine (env CRUCIBLE_MACHINE_NAME). Never the OS hostname by
    default: unset means no nickname. A value publish would reject is an error here, at run time."""
    value = os.environ.get("CRUCIBLE_MACHINE_NAME", "").strip()
    if not value:
        return None
    problem = nickname_problem(value)
    if problem:
        raise SystemExit(f"CRUCIBLE_MACHINE_NAME={value!r}: {problem}")
    return value
FORMAT_SOURCES = ("runtime", "filename", "unknown")


def record_format() -> int:
    """The run record format to write: 3 (default) or 4. The live legacy page skips records past format 3,
    so 4 stays off until the dashboard cuts over; set CRUCIBLE_RECORD_FORMAT=4 to opt in."""
    value = os.environ.get("CRUCIBLE_RECORD_FORMAT", "").strip()
    if value in ("", "3"):
        return 3
    if value == "4":
        return 4
    raise SystemExit(f"CRUCIBLE_RECORD_FORMAT={value!r}: record formats are 3 and 4")


def null_provenance_v4() -> dict:
    return {"crucible_version": None, "crucible_commit": None, "crucible_dirty": None,
            "source": None, "content_hash": None}


def format_and_source(model: str | None, inference: dict | None, recorded: str | None = None) -> tuple[str | None, str]:
    """(weights format, where it came from): `runtime` when the serving runtime said it (LM Studio's
    compatibility_type, Ollama serving GGUF only, a .gguf file the harness read), `filename` when only the
    model key or quant name implies it, `unknown` otherwise. A cloud run has no format: (None, "unknown")."""
    inference = inference or {}
    if where(model, inference) == "cloud":
        return None, "unknown"
    said = inference.get("format")
    if isinstance(said, str) and said.strip():
        return said.strip().lower(), "runtime"
    if str(inference.get("model_path") or "").lower().endswith(".gguf"):
        return "gguf", "runtime"
    implied = implied_variant(model, inference.get("quantization"))["format"] or (recorded.lower() if recorded else None)
    return (implied, "filename") if implied else (None, "unknown")


def record_v4(meta: dict, reg=None, inference: dict | None = None, nickname: str | None = None) -> dict:
    """A format-3 run record rewritten as format 4 (docs/bundle-format.md#format-4).

    `reg` is the registry (crucible.registry.Registry): with it the record carries the canonical
    `model.id`, the maker and the packager's id; without, `model.id` is null and the maker is only what
    the runtime told. `inference` is what the harness captured of the serving runtime (default: the
    record's local.environment.inference). `nickname` is the user's chosen machine name (default: env
    CRUCIBLE_MACHINE_NAME; none when unset). run_path and `local` stay in the local meta.json for the
    tools that read it; `published()` drops both.
    """
    env = (meta.get("local") or {}).get("environment") or {}
    inference = inference if inference is not None else env.get("inference") or {}
    model, endpoint, hardware = meta.get("model") or {}, meta.get("endpoint") or {}, meta.get("hardware")
    prov = meta.get("provenance") or {}
    raw = model.get("base")
    found = reg.model_for_base(raw) if reg is not None else None
    origin = {k: v for k, v in (model.get("origin") or {}).items() if k != "base_repo"}
    maker = reg.models[found[0]]["maker"] if found else origin.get("maker")
    is_local = endpoint.get("where") == "local"
    fmt, fmt_source = format_and_source(model.get("id"), inference, model.get("format"))
    packager = model.get("publisher")
    if reg is not None and packager:
        packager = reg.packager_id(packager)
    # The machine that served the weights, by class: no host name, label or machine id
    serving = None
    if hardware is not None:
        nick = nickname if nickname is not None else machine_nickname()
        serving = {"key": hardware.get("key"), "chip": hardware.get("cpu"), "memory_gb": hardware.get("system_memory_gb"),
                   "accelerators": hardware.get("accelerators") or [],
                   "served_remotely": inference.get("same_machine") is False,
                   **({"nickname": nick} if nick else {})}
    out = {k: v for k, v in meta.items() if k not in ("model", "endpoint", "hardware", "provenance", "local")}
    out.update({
        "format_version": 4,
        "model": {
            "id": found[0] if found else None,
            "raw_base": raw,
            "maker": maker,
            "packager": packager,
            "artifact": model.get("artifact"),
            "format": fmt,
            "format_source": fmt_source if is_local else None,
            "quant": model.get("quant"),
            "reasoning": model.get("reasoning"),
            "context_loaded": model.get("context_loaded"),
            **({"origin": origin} if origin else {}),
        },
        "endpoint": {k: v for k, v in endpoint.items() if k not in ("app", "device")},
        "hardware": serving,
        "provenance": {k: v for k, v in prov.items() if k in null_provenance_v4()},
    })
    order = ["record", "format_version", "run_uuid", "run_path", "legacy_run_id", "started_at", "ended_at", "elapsed_s",
             "task", "harness", "model", "endpoint", "hardware", "outcome", "metrics",
             "output_ref", "provenance"]
    result = {k: out[k] for k in order if k in out}
    result.update({k: v for k, v in out.items() if k not in order})
    if "local" in meta:
        result["local"] = meta["local"]
    return result


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------

def read(run_dir: Path) -> dict:
    meta = read_json(run_dir / "meta.json")
    return meta if is_record(meta) else {}


def invalid(run_dir: Path, meta: dict | None = None) -> dict | None:
    """Why the run doesn't count: marked at run time, or by a later status record."""
    meta = meta if meta is not None else read(run_dir)
    marked = (meta.get("outcome") or {}).get("invalid")
    for entry in statuses(run_dir):
        if entry.get("invalid") or entry.get("withdrawn"):
            marked = entry.get("invalid") or entry.get("withdrawn")
        elif entry.get("valid"):
            marked = None
    return marked


def output_text(run_dir: Path) -> str:
    from crucible import checks
    return checks.final_answer(run_dir)


# --------------------------------------------------------------------------
# Score records
# --------------------------------------------------------------------------

def score_path(run_dir: Path, rubric_version, method: str) -> Path:
    return run_dir / SCORES_DIR / f"r{rubric_version}.{method}.json"


def scores(run_dir: Path) -> list[dict]:
    return [r for p in sorted((run_dir / SCORES_DIR).glob("r*.json")) if (r := read_json(p))]


def score_for(run_dir: Path, rubric_version, method: str | None = None) -> dict | None:
    """The score record at this rubric version (checks or hidden tests; a method narrows it)."""
    found = [r for r in scores(run_dir) if r.get("rubric_version") == rubric_version
             and (method is None or r.get("method") == method)]
    return found[-1] if found else None


def score_from_checks(check_record: dict, run_uuid: str | None, grader: dict | None = None,
                      crucible_version: str | None = None, rubric: list[dict] | None = None) -> dict:
    """A score record from what checks.save_check_score computes (or a pre-3.0.0 check_results.json).

    The score is the one computed, never recomputed here; `raw` says what was counted.
    """
    criteria = check_record.get("criteria")
    tests = (grader or {}).get("tests") or []
    overall = (check_record.get("scores") or {}).get("_overall")
    method = "hidden_tests" if (check_record.get("scorer") or {}).get("type") == "tests" else "checks"
    passed_tests = sum(bool(t.get("passed")) for t in tests)
    if method == "hidden_tests" and tests and overall == round(passed_tests / len(tests) * SCALE, 2):
        raw = {"passed": passed_tests, "total": len(tests), "unit": "tests"}
    elif criteria:
        raw = {"passed": round(sum(c.get("score") or 0 for c in criteria), 4),
               "total": round(sum(c.get("max_score") or 0 for c in criteria), 4), "unit": "points"}
    else:
        raw = {"passed": None, "total": None, "unit": "points"}
    by_check = {item.get("check"): item.get("criterion") for item in rubric or [] if item.get("check")}
    items = []
    for check in check_record.get("checks") or []:
        criterion = by_check.get(check.get("id"))
        items.append({"id": check.get("id"), "type": check.get("type"), "group": criterion,
                      "label": check.get("rule"), "passed": check.get("passed"), "detail": check.get("detail"),
                      **({"share": check["share"]} if "share" in check else {}),
                      **({"items": check["items"]} if "items" in check else {})})
    for t in tests:
        items.append({"id": f"{t.get('group')} > {t.get('name')}", "type": "hidden_test", "group": t.get("group"),
                      "label": t.get("name"), "passed": t.get("passed"),
                      "detail": (t.get("error") or "").splitlines()[0][:200] if t.get("error") else None})
    return {
        "record": "score", "format_version": FORMAT_VERSION,
        "run_uuid": run_uuid,
        "rubric_version": check_record.get("rubric_version"),
        "rubric_hash": check_record.get("rubric_hash"),
        "method": method,
        "scored_at": check_record.get("scored_at"),
        "crucible_version": crucible_version,
        "raw": raw,
        "score": overall,
        "scale": SCALE,
        "capped_at": check_record.get("capped_at"),
        "passed": check_record.get("passed"),
        "items": items,
        "groups": None if criteria is None else [
            {"id": c.get("criterion"), "passed": c.get("score"), "total": c.get("max_score"), "detail": c.get("detail")}
            for c in criteria],
        # The exact text that was scored, for auditing (stays local; the published output is the same text)
        "checked_text": check_record.get("checked_text"),
    }


def criteria(score: dict | None) -> list[dict] | None:
    """A score record's groups as the per-criterion rows the dashboard shows."""
    if not score or score.get("groups") is None:
        return None
    return [{"criterion": g["id"], "max_score": g["total"], "score": g["passed"], "detail": g.get("detail")}
            for g in score["groups"]]


def write_score(run_dir: Path, record: dict) -> Path:
    path = score_path(run_dir, record["rubric_version"], record["method"])
    write_json(path, record)
    return path


# --------------------------------------------------------------------------
# Status records
# --------------------------------------------------------------------------

def statuses(run_dir: Path) -> list[dict]:
    return read_json(run_dir / STATUS_FILE) or []


def add_status(run_dir: Path, run_uuid: str, by: str = "maintainer", **change) -> dict:
    """Append a status record: invalid={"reason": ...}, withdrawn={"reason": ...} or valid=True."""
    entry = {"record": "status", "format_version": FORMAT_VERSION, "run_uuid": run_uuid,
             "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **change, "by": by}
    write_json(run_dir / STATUS_FILE, [*statuses(run_dir), entry])
    return entry


def published(meta: dict) -> dict:
    """The run record as published: everything but what stays on this machine (`local`, and in format 4
    the run's local path)."""
    left = ("local", "run_path") if meta.get("format_version") == 4 else ("local",)
    return {k: v for k, v in meta.items() if k not in left}


def status_main() -> None:
    """`crucible status RUN`: show a run's status, or append a status record marking it invalid or withdrawn."""
    import argparse
    from crucible.scorer import find_run_dir
    parser = argparse.ArgumentParser(prog="crucible status", description=status_main.__doc__)
    parser.add_argument("run", help="Run path (model/task/timestamp), its timestamp, or a path")
    change = parser.add_mutually_exclusive_group()
    change.add_argument("--invalid", metavar="REASON", help="The run's setup was broken (e.g. a stale server)")
    change.add_argument("--withdrawn", metavar="REASON", help="Take a published run out of the results")
    change.add_argument("--valid", action="store_true", help="Undo an earlier invalid or withdrawn mark")
    parser.add_argument("--by", default="maintainer")
    args = parser.parse_args()
    run_dir = find_run_dir(args.run)
    meta = read(run_dir)
    if not meta:
        raise SystemExit(f"{run_dir} has no run record (runs from before 3.0.0 need `crucible migrate`)")
    if args.invalid or args.withdrawn or args.valid:
        change = ({"invalid": {"reason": args.invalid}} if args.invalid else
                  {"withdrawn": {"reason": args.withdrawn}} if args.withdrawn else {"valid": True})
        add_status(run_dir, meta["run_uuid"], args.by, **change)
    marked = invalid(run_dir, meta)
    print(f"{meta['run_path']}: {'invalid: ' + marked.get('reason', '') if marked else 'valid'}")
