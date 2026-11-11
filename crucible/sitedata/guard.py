"""The privacy guard: no IP address, and no host name derived from one, may appear in site-data output."""
from __future__ import annotations

from pathlib import Path

from crucible import hostnames


def scan_text(text: str) -> list:
    """The detector is crucible/hostnames.py: the same one publish and the registry use."""
    return sorted({f"IP address or IP-derived host name {t!r}" for t in hostnames.find_ips(text)})


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
