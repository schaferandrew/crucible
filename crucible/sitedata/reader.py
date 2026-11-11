"""Read a published bundle (format 3 and 4 records) into plain dicts, the way the page's `collect` did
(core 389-450), minus the nesting: records are found by their own `record` field, wherever they sit.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from crucible.sitedata.rules import d, num, s

SUPPORTED_FORMAT = 4


@dataclass
class Bundle:
    catalogs: dict = field(default_factory=dict)      # suite id -> catalog (highest format_revision wins)
    runs: dict = field(default_factory=dict)          # run_uuid -> run record (the first read wins)
    scores: dict = field(default_factory=dict)        # run_uuid -> [score record] in a stable order
    status: dict = field(default_factory=dict)        # run_uuid -> [status record] oldest first
    skipped: int = 0                                  # records newer than SUPPORTED_FORMAT, or unreadable
    latest: str = ""                                  # the latest timestamp any record carries
    hash: str = ""                                    # sha256 over every bundle file (path + bytes)


def _newer(node: dict) -> bool:
    v = node.get("format_version")
    return isinstance(v, int) and not isinstance(v, bool) and v > SUPPORTED_FORMAT


def suite_id(catalog: dict) -> str:
    suite = d(catalog.get("suite"))
    return str(suite.get("id") or suite.get("version") or "?")


def read_bundle(folder) -> Bundle:
    folder = Path(folder)
    out = Bundle()
    digest = hashlib.sha256()
    scores_seen = {}
    files = sorted(p for p in folder.rglob("*.json") if p.is_file())
    for path in files:
        raw = path.read_bytes()
        digest.update(path.relative_to(folder).as_posix().encode() + b"\0" + hashlib.sha256(raw).digest())
        try:
            node = json.loads(raw)
        except ValueError:
            out.skipped += 1
            continue
        for rec in (node if isinstance(node, list) else [node]):
            if isinstance(rec, dict):
                _add(out, rec, scores_seen)
    out.hash = digest.hexdigest()
    for uuid, key_map in scores_seen.items():
        out.scores[uuid] = sorted(key_map.values(), key=lambda r: (str(r.get("rubric_version")), str(r.get("method")),
                                                                    str(r.get("scored_at"))))
    for uuid in out.status:   # status records only ever append: the last one wins
        out.status[uuid].sort(key=lambda r: str(r.get("at") or ""))
    return out


def _add(out: Bundle, rec: dict, scores_seen: dict) -> None:
    kind = rec.get("record")
    if kind == "run":
        if _newer(rec):
            out.skipped += 1
        elif s(rec.get("run_uuid")) and rec["run_uuid"] not in out.runs:
            out.runs[rec["run_uuid"]] = rec
            out.latest = max(out.latest, str(rec.get("started_at") or "")[:19])
    elif kind == "score":
        if _newer(rec):
            out.skipped += 1
        elif s(rec.get("run_uuid")):
            # a repeated (run, rubric_version, method) keeps the last one read
            scores_seen.setdefault(rec["run_uuid"], {})[(rec.get("rubric_version"), rec.get("method"))] = rec
            out.latest = max(out.latest, str(rec.get("scored_at") or "")[:19])
    elif kind == "status":
        if s(rec.get("run_uuid")):
            out.status.setdefault(rec["run_uuid"], []).append(rec)
            out.latest = max(out.latest, str(rec.get("at") or "")[:19])
    elif isinstance(rec.get("suite"), dict) and isinstance(rec.get("tasks"), list):
        if _newer(rec):
            out.skipped += 1
            return
        sid = suite_id(rec)
        old = out.catalogs.get(sid)
        if old is None or num(rec.get("format_revision"), 0) > num(old.get("format_revision"), 0):
            out.catalogs[sid] = rec
