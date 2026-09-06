"""
Small API client for the Cloudflare DNS REST API (https://api.cloudflare.com).

Documentation: https://developers.cloudflare.com/api/operations/dns-records-for-a-zone-list-dns-records
Uses a scoped API Token (Bearer auth) - Cloudflare's recommended authentication
method (Zone:DNS:Edit + Zone:Zone:Read permissions on the relevant zone(s)).

Mirrors the public interface of DomainChiefClient (list/find/create/update/delete
DNS records, keyed by domain + relative subdomain name) so app/ddns.py can treat
both providers interchangeably. Cloudflare itself has no concept of a "relative"
record name or a "domain" scoped client - both are bridged here:
  - Records are looked up/created within a "zone" (Cloudflare's term for what
    Domain Chief calls a "domain"); the zone ID is resolved from the domain
    name on first use and cached for the lifetime of this client instance.
  - Cloudflare's DNS record "name" is always the FULL hostname (e.g.
    "home.example.com", or "example.com" for the root) - converted to/from the
    relative name (name without the domain suffix) at the edges here, so the
    rest of the app never has to special-case which provider a record uses.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests

logger = logging.getLogger("etfmultiddns.cloudflare")

API_BASE_URL = "https://api.cloudflare.com/client/v4"

# DNS record types this client (and the Web UI's record form) may create/update.
# Cloudflare's API itself supports more (MX, TXT, SRV, ...) - the app only ever
# manages A/AAAA (dynamic DNS), so only those are exercised, but list_dns_records
# happily returns whatever a zone actually has.
SUPPORTED_RECORD_TYPES = ("A", "AAAA", "CNAME", "MX", "TXT", "NS", "SRV", "CAA")


class CloudflareError(RuntimeError):
    """Raised for any error from the Cloudflare API."""

    def __init__(self, message: str, status_code: Optional[int] = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class CloudflareRateLimitError(CloudflareError):
    """429 Too Many Requests - retry_after holds the recommended wait time in seconds."""

    def __init__(self, message: str, retry_after: Optional[float], payload: Any = None):
        super().__init__(message, status_code=429, payload=payload)
        self.retry_after = retry_after


@dataclass
class DNSRecord:
    id: str
    type: str
    name: str  # relative name (without the domain suffix); "" = root domain
    content: str
    ttl: int
    prio: int = 0
    comment: Optional[str] = None
    proxied: bool = False
    sync_error: Optional[str] = None
    sync_error_at: Optional[str] = None
    metadata: Optional[dict] = None

    @classmethod
    def from_api(cls, data: dict, domain: str) -> "DNSRecord":
        full_name = (data.get("name") or "").strip().rstrip(".")
        domain_norm = domain.strip().lower().rstrip(".")
        relative = full_name
        if full_name == domain_norm:
            relative = ""
        elif full_name.endswith("." + domain_norm):
            relative = full_name[: -(len(domain_norm) + 1)]
        return cls(
            id=data["id"],
            type=data["type"],
            name=relative,
            content=data.get("content", ""),
            # Cloudflare uses ttl=1 to mean "Automatic" - surfaced as-is; the
            # sync logic in ddns.py only compares it against the locally
            # configured value, so this doesn't need special-casing here.
            ttl=data.get("ttl", 1) or 1,
            prio=data.get("priority", 0) or 0,
            comment=data.get("comment"),
            proxied=bool(data.get("proxied", False)),
            metadata=data.get("meta") or {},
        )


class CloudflareClient:
    """Thin wrapper around the DNS endpoints of the Cloudflare API that we need."""

    def __init__(
        self,
        api_token: str,
        base_url: str = API_BASE_URL,
        timeout: float = 20.0,
        max_retries: int = 3,
    ):
        if not api_token:
            raise ValueError("api_token must not be empty")
        self.api_token = api_token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._zone_id_cache: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Low-level request handling
    # ------------------------------------------------------------------
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, params: dict | None = None, json_body: dict | None = None) -> Any:
        url = f"{self.base_url}{path}"
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self._session.request(
                    method, url, headers=self._headers(), params=params, json=json_body, timeout=self.timeout,
                )
            except requests.RequestException as exc:
                if attempt <= self.max_retries:
                    wait = min(2 ** attempt, 30)
                    logger.warning("Network error on %s %s (%s), retrying in %ss", method, url, exc, wait)
                    time.sleep(wait)
                    continue
                raise CloudflareError(f"Network error on {method} {url}: {exc}") from exc

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                retry_after_s = float(retry_after) if retry_after else None
                if attempt <= self.max_retries:
                    wait = retry_after_s if retry_after_s else min(2 ** attempt, 60)
                    logger.warning("Rate limit hit, waiting %ss before retrying", wait)
                    time.sleep(wait)
                    continue
                raise CloudflareRateLimitError(
                    "Rate limit reached (429)", retry_after=retry_after_s, payload=self._safe_json(response)
                )

            if response.status_code >= 500 and attempt <= self.max_retries:
                wait = min(2 ** attempt, 30)
                logger.warning("Server error %s on %s %s, retrying in %ss", response.status_code, method, url, wait)
                time.sleep(wait)
                continue

            payload = self._safe_json(response)
            if not response.ok or (isinstance(payload, dict) and payload.get("success") is False):
                message = self._extract_message(payload) or f"HTTP {response.status_code}: {str(payload)[:500]}"
                raise CloudflareError(message, status_code=response.status_code, payload=payload)

            if response.status_code == 204 or not response.content:
                return None
            return payload

    @staticmethod
    def _safe_json(response: requests.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return {"raw": response.text}

    @staticmethod
    def _extract_message(payload: Any) -> Optional[str]:
        if isinstance(payload, dict):
            errors = payload.get("errors")
            if errors:
                parts = []
                for err in errors:
                    if isinstance(err, dict) and err.get("message"):
                        parts.append(str(err["message"]))
                    else:
                        parts.append(str(err))
                if parts:
                    return "; ".join(parts)
        elif isinstance(payload, str) and payload.strip():
            return payload.strip()
        return None

    # ------------------------------------------------------------------
    # Zones (Cloudflare's equivalent of a "domain")
    # ------------------------------------------------------------------
    def list_zones(self) -> list[dict]:
        zones: list[dict] = []
        page = 1
        while True:
            data = self._request("GET", "/zones", params={"page": page, "per_page": 50})
            zones.extend(data.get("result", []) or [])
            info = (data.get("result_info") or {})
            total_pages = info.get("total_pages", page)
            if page >= total_pages:
                break
            page += 1
        return zones

    def find_zone_id(self, domain: str) -> str:
        domain_norm = domain.strip().lower().rstrip(".")
        if domain_norm in self._zone_id_cache:
            return self._zone_id_cache[domain_norm]
        data = self._request("GET", "/zones", params={"name": domain_norm, "per_page": 1})
        results = data.get("result") or []
        if not results:
            raise CloudflareError(f"No Cloudflare zone found for domain '{domain_norm}'.")
        zone_id = results[0]["id"]
        self._zone_id_cache[domain_norm] = zone_id
        return zone_id

    # ------------------------------------------------------------------
    # DNS records
    # ------------------------------------------------------------------
    def list_dns_records(self, domain: str, page: int = 1, per_page: int = 100) -> list[DNSRecord]:
        zone_id = self.find_zone_id(domain)
        records: list[DNSRecord] = []
        current_page = page
        while True:
            data = self._request(
                "GET", f"/zones/{zone_id}/dns_records", params={"page": current_page, "per_page": per_page}
            )
            for item in data.get("result", []) or []:
                records.append(DNSRecord.from_api(item, domain))
            info = data.get("result_info") or {}
            total_pages = info.get("total_pages", current_page)
            if current_page >= total_pages:
                break
            current_page += 1
        return records

    def find_dns_record(self, domain: str, name: str, record_type: str) -> Optional[DNSRecord]:
        """Finds a record by name (without domain) + type. name='' means the root domain."""
        normalized_name = (name or "").strip().rstrip(".")
        for record in self.list_dns_records(domain):
            if record.type == record_type and (record.name or "") == normalized_name:
                return record
        return None

    @staticmethod
    def _full_name(domain: str, name: str) -> str:
        name = (name or "").strip().rstrip(".")
        domain = domain.strip().lower().rstrip(".")
        return f"{name}.{domain}" if name else domain

    def create_dns_record(
        self,
        domain: str,
        record_type: str,
        content: str,
        ttl: int = 300,
        name: str = "",
        prio: Optional[int] = None,
        comment: Optional[str] = None,
        metadata: Optional[dict] = None,
        proxied: Optional[bool] = None,
    ) -> DNSRecord:
        zone_id = self.find_zone_id(domain)
        body: dict[str, Any] = {
            "type": record_type,
            "name": self._full_name(domain, name),
            "content": content,
            "ttl": ttl,
        }
        if prio is not None:
            body["priority"] = prio
        if comment is not None:
            body["comment"] = comment
        if proxied is not None:
            body["proxied"] = proxied
        data = self._request("POST", f"/zones/{zone_id}/dns_records", json_body=body)
        return DNSRecord.from_api(data["result"], domain)

    def update_dns_record(
        self,
        domain: str,
        record_id: str,
        record_type: str,
        content: str,
        ttl: int = 300,
        name: str = "",
        prio: Optional[int] = None,
        comment: Optional[str] = None,
        metadata: Optional[dict] = None,
        proxied: Optional[bool] = None,
    ) -> DNSRecord:
        zone_id = self.find_zone_id(domain)
        body: dict[str, Any] = {
            "type": record_type,
            "name": self._full_name(domain, name),
            "content": content,
            "ttl": ttl,
        }
        if prio is not None:
            body["priority"] = prio
        if comment is not None:
            body["comment"] = comment
        if proxied is not None:
            body["proxied"] = proxied
        data = self._request("PUT", f"/zones/{zone_id}/dns_records/{record_id}", json_body=body)
        return DNSRecord.from_api(data["result"], domain)

    def delete_dns_record(self, domain: str, record_id: str) -> None:
        zone_id = self.find_zone_id(domain)
        self._request("DELETE", f"/zones/{zone_id}/dns_records/{record_id}")

    # ------------------------------------------------------------------
    # Zones (only for the Web UI, to display available domains)
    # ------------------------------------------------------------------
    def list_domains(self) -> list[dict]:
        return [{"domain": z.get("name")} for z in self.list_zones() if z.get("name")]

    def verify_credentials(self) -> bool:
        """Lightweight check whether the token works (verify endpoint, works
        for scoped API tokens without needing any specific zone permission)."""
        self._request("GET", "/user/tokens/verify")
        return True
