"""
Ermittelt die aktuelle oeffentliche IPv4/IPv6-Adresse ueber mehrere
austauschbare externe Dienste (mit Fallback, falls einer nicht erreichbar ist).
"""

from __future__ import annotations

import ipaddress
import logging
from typing import Optional

import requests

logger = logging.getLogger("etfmultiddns.ip")

DEFAULT_IPV4_PROVIDERS = [
    "https://api.ipify.org",
    "https://ipv4.icanhazip.com",
    "https://checkip.amazonaws.com",
]

DEFAULT_IPV6_PROVIDERS = [
    "https://api6.ipify.org",
    "https://ipv6.icanhazip.com",
]


def _fetch_ip(url: str, timeout: float = 8.0) -> Optional[str]:
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        candidate = response.text.strip()
        return candidate or None
    except requests.RequestException as exc:
        logger.debug("IP lookup at %s failed: %s", url, exc)
        return None


def get_public_ipv4(providers: Optional[list[str]] = None) -> Optional[str]:
    for url in providers or DEFAULT_IPV4_PROVIDERS:
        candidate = _fetch_ip(url)
        if not candidate:
            continue
        try:
            ip = ipaddress.IPv4Address(candidate)
            return str(ip)
        except ipaddress.AddressValueError:
            logger.debug("Received invalid IPv4 from %s: %r", url, candidate)
    return None


def get_public_ipv6(providers: Optional[list[str]] = None) -> Optional[str]:
    for url in providers or DEFAULT_IPV6_PROVIDERS:
        candidate = _fetch_ip(url)
        if not candidate:
            continue
        try:
            ip = ipaddress.IPv6Address(candidate)
            return str(ip)
        except ipaddress.AddressValueError:
            logger.debug("Received invalid IPv6 from %s: %r", url, candidate)
    return None


def get_public_ip(record_type: str, providers: Optional[list[str]] = None) -> Optional[str]:
    if record_type == "A":
        return get_public_ipv4(providers)
    if record_type == "AAAA":
        return get_public_ipv6(providers)
    raise ValueError(f"Unknown record_type for IP lookup: {record_type}")
