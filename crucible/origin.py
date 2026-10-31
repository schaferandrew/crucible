"""Who made a model, as its own source says: the run record's `model.origin`.

`model.publisher` is who packaged the weights (mlx-community, lmstudio-community) and is part of the
variant key. `model.origin` is the lab that trained them, the repo they came from and their size, read
from the source at run time and never looked up in a hand-kept list:

  gguf          the GGUF file's header (general.base_model.0.*, general.organization,
                general.parameter_count, general.size_label), when the file is on this machine
  mlx-card      an MLX model folder's README front matter (`base_model`), when the folder is on this machine
  ollama        Ollama's /api/show model_info (the same general.* keys) and details.parameter_size
  openrouter    the model ID's author prefix (`~` dropped) and, when Crucible already fetched the
                model's entry from /api/v1/models, its `hugging_face_id`
  lmstudio-key  LM Studio's model key prefix (qwen/qwen3.5-9b -> qwen)

Sources are asked in that order and the first one that answers wins, field by field; `source` names
every source that contributed, in that order, joined with "+" ("none" when nothing answered). A
packager namespace is never a maker. Everything is best effort: an unreadable file or a missing field
leaves a null, never fails the run. See docs/data-model.md.
"""
from __future__ import annotations

import re
import struct
from pathlib import Path

# Namespaces that repackage other labs' weights (quantized GGUF or MLX conversions). They're the
# run's `publisher`, never its maker. The one list of packagers: runrecord.implied_variant uses it too,
# so adding a name here also fills `publisher` for model keys under it.
PACKAGERS = ("mlx-community", "lmstudio-community", "unsloth", "bartowski")

FIELDS = ("maker", "base_repo", "params", "active_params")
SOURCES = ("gguf", "mlx-card", "ollama", "openrouter", "lmstudio-key")

HF_URL = re.compile(r"^https?://(?:www\.)?huggingface\.co/([^/\s]+/[^/\s?#]+)")
SIZE_LABEL = re.compile(r"^(\d+(?:\.\d+)?)([KMBT])(?:-A(\d+(?:\.\d+)?)([KMBT]))?$", re.IGNORECASE)
SCALE = {"K": 10**3, "M": 10**6, "B": 10**9, "T": 10**12}


def empty() -> dict:
    return {"maker": None, "base_repo": None, "params": None, "active_params": None, "source": "none"}


def maker_id(name: str | None) -> str | None:
    """A namespace or organization as a maker ID (Qwen -> qwen, ~openai -> openai); None for a packager."""
    if not isinstance(name, str):
        return None
    slug = re.sub(r"[^a-z0-9.-]+", "-", name.strip().lstrip("~").lower()).strip("-")
    return slug if slug and slug not in PACKAGERS else None


def repo_id(value: str | None) -> str | None:
    """org/name from a Hugging Face URL or ID; other URLs as given."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    match = HF_URL.match(value)
    if match:
        return match.group(1)
    return value if re.fullmatch(r"[\w.-]+/[\w.-]+", value) or "://" in value else None


def _org(repo: str | None) -> str | None:
    return repo.split("/")[0] if repo and "://" not in repo and "/" in repo else None


def parse_size(label) -> tuple[int | None, int | None]:
    """(params, active params) from a size label as GGUF and Ollama write it: 9B, 35B-A3B, 8.0B, 1.5B."""
    match = SIZE_LABEL.match(str(label or "").strip())
    if not match:
        return None, None
    total = round(float(match.group(1)) * SCALE[match.group(2).upper()])
    active = round(float(match.group(3)) * SCALE[match.group(4).upper()]) if match.group(3) else None
    return total, active


# --------------------------------------------------------------------------
# GGUF header
# --------------------------------------------------------------------------

GGUF_MAGIC = b"GGUF"
# GGUF value types: id -> struct format (8 is a string, 9 an array)
GGUF_SCALARS = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}
GGUF_STRING, GGUF_ARRAY = 8, 9


class _Reader:
    def __init__(self, f):
        self.f = f

    def take(self, fmt: str):
        size = struct.calcsize(fmt)
        data = self.f.read(size)
        if len(data) != size:
            raise EOFError
        return struct.unpack(fmt, data)[0]

    def string(self, keep: bool = True):
        n = self.take("<Q")
        if not keep:
            self.f.seek(n, 1)
            return None
        data = self.f.read(n)
        if len(data) != n:
            raise EOFError
        return data.decode("utf-8", "replace")

    def value(self, kind: int, keep: bool):
        if kind == GGUF_STRING:
            return self.string(keep)
        if kind == GGUF_ARRAY:
            item, count = self.take("<I"), self.take("<Q")
            if item in GGUF_SCALARS:   # skip a scalar array in one seek
                self.f.seek(struct.calcsize(GGUF_SCALARS[item]) * count, 1)
            else:
                for _ in range(count):
                    self.value(item, keep=False)
            return None
        if kind in GGUF_SCALARS:
            return self.take(GGUF_SCALARS[kind])
        raise ValueError(f"unknown GGUF value type {kind}")


def gguf_general(path: Path) -> dict:
    """The `general.*` key-values of a GGUF file's header (read-only; arrays skipped). {} when unreadable."""
    found = {}
    try:
        with open(path, "rb") as f:
            r = _Reader(f)
            if f.read(4) != GGUF_MAGIC:
                return {}
            version = r.take("<I")
            count_fmt = "<I" if version == 1 else "<Q"
            r.take(count_fmt)                      # tensor count
            for _ in range(r.take(count_fmt)):     # key-value count
                key = r.string()
                keep = key.startswith("general.")
                value = r.value(r.take("<I"), keep)
                if keep and value is not None:
                    found[key] = value
    except (OSError, EOFError, ValueError, struct.error, MemoryError):
        pass
    return found


def from_general(kv: dict) -> dict:
    """Origin fields from GGUF-style general.* keys (a GGUF header, or Ollama's model_info)."""
    base_repo = repo_id(kv.get("general.base_model.0.repo_url"))
    maker = (maker_id(_org(base_repo)) or maker_id(kv.get("general.base_model.0.organization"))
             or maker_id(kv.get("general.organization")))
    params, active = parse_size(kv.get("general.size_label"))
    count = kv.get("general.parameter_count")
    if isinstance(count, int) and not isinstance(count, bool) and count > 0:
        params = count
    return {"maker": maker, "base_repo": base_repo, "params": params, "active_params": active}


# --------------------------------------------------------------------------
# MLX model card
# --------------------------------------------------------------------------

def card_base_model(folder: Path) -> str | None:
    """`base_model` from a model folder's README.md front matter (a string or the first of a list)."""
    import yaml
    try:
        text = (folder / "README.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", text, re.DOTALL)
    if not match:
        return None
    try:
        front = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return None
    base = front.get("base_model") if isinstance(front, dict) else None
    if isinstance(base, list):
        base = base[0] if base else None
    return base if isinstance(base, str) else None


def from_card(folder: Path) -> dict:
    base_repo = repo_id(card_base_model(folder))
    return {"maker": maker_id(_org(base_repo)), "base_repo": base_repo, "params": None, "active_params": None}


def from_file(path: str | Path | None) -> tuple[str | None, dict]:
    """(source, fields) from the model's file or folder on this machine; (None, {}) when there's none."""
    if not path:
        return None, {}
    p = Path(path)
    if p.is_dir():
        ggufs = sorted(p.glob("*.gguf"))
        if ggufs:
            p = ggufs[0]
        elif (p / "README.md").is_file():
            return "mlx-card", from_card(p)
        else:
            return None, {}
    if p.is_file() and p.suffix.lower() == ".gguf":
        kv = gguf_general(p)
        return ("gguf", from_general(kv)) if kv else (None, {})
    return None, {}


# --------------------------------------------------------------------------
# Server and model-key sources
# --------------------------------------------------------------------------

def from_ollama(model_info: dict | None, parameter_size: str | None = None) -> dict:
    fields = from_general(model_info or {})
    if fields["params"] is None:
        fields["params"] = parse_size(parameter_size)[0]
    return fields


def from_openrouter(model_id: str, entry: dict | None = None) -> dict:
    """model_id without the openrouter/ prefix: qwen/qwen3.5-9b, ~openai/gpt-luna-latest."""
    author = model_id.split("/", 1)[0] if "/" in model_id else None
    hf = repo_id((entry or {}).get("hugging_face_id"))
    return {"maker": maker_id(author), "base_repo": hf, "params": None, "active_params": None}


def from_lmstudio_key(model_id: str) -> dict:
    author = model_id.split("/", 1)[0] if "/" in model_id else None
    return {"maker": maker_id(author), "base_repo": None, "params": None, "active_params": None}


def merge(answers: list[tuple[str, dict]]) -> dict:
    """Sources in trust order; the first that answers a field wins it."""
    result, used = empty(), []
    for source, fields in answers:
        took = False
        for field in FIELDS:
            if result[field] is None and fields.get(field) is not None:
                result[field] = fields[field]
                took = True
        if took and source not in used:
            used.append(source)
    result["source"] = "+".join(used) if used else "none"
    return result


def capture(model: str | None, inference: dict | None, openrouter_entry: dict | None = None) -> dict:
    """`model.origin` for a run of `model` (provider/model), from what environment.inference captured."""
    inference = inference or {}
    provider, _, model_id = (model or "").partition("/")
    answers = []
    source, fields = from_file(inference.get("model_path"))
    if source:
        answers.append((source, fields))
    if provider == "ollama":
        answers.append(("ollama", from_ollama(inference.get("model_info"), inference.get("parameter_size"))))
    if provider == "openrouter" and model_id:
        answers.append(("openrouter", from_openrouter(model_id, openrouter_entry)))
    if provider == "lmstudio" and model_id:
        answers.append(("lmstudio-key", from_lmstudio_key(model_id)))
    return merge(answers)
