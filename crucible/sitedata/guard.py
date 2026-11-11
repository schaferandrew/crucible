"""The privacy guard: no IP address, and no host name derived from one, may appear in site-data output."""
from __future__ import annotations

import re
from pathlib import Path

H = r"[0-9a-fA-F]{1,4}"
PATTERNS = {
    "IPv4 address": re.compile(r"(?<![\w.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\w.]*\d)"),
    "IPv6 address": re.compile(rf"(?<![\w:])(?:(?:{H}:){{7}}{H}|(?:{H}:){{1,7}}:(?:{H})?(?::{H}){{0,6}}|::(?:{H}:){{0,6}}{H})(?![\w:])"),
    "IP-derived host name": re.compile(r"\bip-\d{1,3}-\d{1,3}-\d{1,3}-\d{1,3}\b", re.IGNORECASE),
}


def scan_text(text: str) -> list:
    return sorted({f"{kind} {m.group(0)!r}" for kind, rx in PATTERNS.items() for m in rx.finditer(text)})


def scan(folder) -> list:
    """(relative path, finding) for every IP address or IP-derived host name in any file under `folder`."""
    folder = Path(folder)
    found = []
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        for finding in scan_text(path.read_text(encoding="utf-8", errors="replace")):
            found.append((path.relative_to(folder).as_posix(), finding))
    return found


class PrivacyError(RuntimeError):
    pass


def enforce(folder) -> None:
    found = scan(folder)
    if found:
        lines = "\n".join(f"  {path}: {what}" for path, what in found[:20])
        raise PrivacyError(f"site data contains IP addresses or IP-derived host names ({len(found)} hits), refusing to finish:\n{lines}"
                           f"\nFix the source (a registry label, or a record), then rebuild.")
