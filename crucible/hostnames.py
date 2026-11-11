"""Keeping IP addresses and IP-derived host names out of run records.

A machine's OS host name is sometimes a DHCP name (`ip-192-168-1-162`) that spells its address. Records
are published, so every host name enters a record through `public_label`, and `crucible publish` refuses
a new run record in which `ip_strings` finds an address anywhere.
"""
from __future__ import annotations

import ipaddress
import re

# Four numbers joined by the same . - or _ (1.2.3.4, ip-1-2-3-4, ec2-1-2-3-4.compute.amazonaws.com), not inside a longer number
IPV4 = re.compile(r"(?<![\d.])\d{1,3}([-_.])\d{1,3}\1\d{1,3}\1\d{1,3}(?!\d)")
# A name that starts like an address (192-168-..., 10.0.1) or says it is `ip-<number>`
LEADING_NUMBERS = re.compile(r"^\d{1,3}[-_.]\d{1,3}[-_.]\d{1,3}")
IP_PREFIX = re.compile(r"^ip[-_]?\d", re.I)
IPV6_CANDIDATE = re.compile(r"[0-9A-Fa-f:.%\[\]]{2,}")


def _is_address(token: str) -> bool:
    try:
        ipaddress.ip_address(token.strip("[]").split("%")[0])
        return True
    except ValueError:
        return False


def contains_ip(text: str) -> bool:
    """True when `text` holds an IPv4 or IPv6 address, or a host name derived from one."""
    if not isinstance(text, str):
        return False
    for m in IPV4.finditer(text):
        octets = re.split(r"[-_.]", m.group())
        if all(int(o) <= 255 for o in octets):
            return True
    return any(_is_address(m.group().rstrip(".]")) or _is_address(m.group().rstrip(".")) for m in IPV6_CANDIDATE.finditer(text)
               if m.group().count(":") >= 2)


def public_label(name) -> str | None:
    """A host name or device label that's safe to record, or None for an IP address or IP-derived name.

        Ironwood -> Ironwood         Mac-168 -> Mac-168         MacBook-Pro-2.local -> MacBook-Pro-2.local
        192.168.1.162 -> None        ip-192-168-1-162 -> None   fe80::1 -> None
        192-168-1-162.local -> None  ec2-1-2-3-4.compute.amazonaws.com -> None  "" -> None
    """
    if not isinstance(name, str) or not name.strip():
        return None
    label = name.strip()
    if _is_address(label) or contains_ip(label) or LEADING_NUMBERS.match(label) or IP_PREFIX.match(label):
        return None
    return label


def ip_strings(value, path: str = "$") -> list[str]:
    """Every string value under `value` (a record) that holds an IP address or IP-derived name, as
    "path: value" lines."""
    found = []
    if isinstance(value, str):
        if contains_ip(value):
            found.append(f"{path}: {value[:80]!r}")
    elif isinstance(value, dict):
        for key, sub in value.items():
            found += ip_strings(sub, f"{path}.{key}")
    elif isinstance(value, list):
        for i, sub in enumerate(value):
            found += ip_strings(sub, f"{path}[{i}]")
    return found
