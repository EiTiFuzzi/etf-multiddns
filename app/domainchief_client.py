"""
Small API client for the Domain Chief REST API (https://domain.chief.app).

Documentation: https://docs.chief.tools/domainchief/developers/build-with-domain-chief
API reference: https://docs.chief.tools/api/domainchief

Supports Personal Access Tokens (ctp_...) and Team Access Tokens (ctt_...).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests

logger = logging.getLogger("etfmultiddns.client")

API_BASE_URL = "https://domain.chief.app/api/v1"

# DNS record types supported by Domain Chief (see OpenAPI schema).
SUPPORTED_RECORD_TYPES = (
    "A",
    "AAAA",
    "CNAME",
    "MX",
    "TXT",
    "ALIAS",
    "CAA",
    "SRV",
    "TLSA",
    "NS",
)


class DomainChiefError(RuntimeError):
    """Raised for any error from the Domain Chief API."""

    def __init__(self, message: str, status_code: Optional[int] = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class DomainChiefRateLimitError(DomainChiefError):
    """429 Too Many Requests - retry_after holds the recommended wait time in seconds."""

    def __init__(self, message: str, retry_after: Optional[float], payload: Any = None):
        super().__init__(message, status_code=429, payload=payload)
        self.retry_after = retry_after


@dataclass
class DNSRecord:
    id: str
    type: str
    name: str
    content: str
    ttl: int
    prio: int = 0
    comment: Optional[str] = None
    sync_error: Optional[str] = None
    sync_error_at: Optional[str] = None
    metadata: Optional[dict] = None

    @classmethod
    def from_api(cls, data: dict) -> "DNSRecord":
        return cls(
            id=data["id"],
            type=data["type"],
            name=data.get("name", "") or "",
            content=data["content"],
            ttl=data["ttl"],
            prio=data.get("prio", 0) or 0,
            comment=data.get("comment"),
            sync_error=data.get("sync_error"),
            sync_error_at=data.get("sync_error_at"),
            metadata=data.get("metadata") or {},
        )


class DomainChiefClient:
    """Thin wrapper around the DNS endpoints of the Domain Chief API that we need."""

    def __init__(
        self,
        api_token: str,
        team_id: Optional[str] = None,
        base_url: str = API_BASE_URL,
        timeout: float = 20.0,
        max_retries: int = 3,
    ):
        if not api_token:
            raise ValueError("api_token must not be empty")
        self.api_token = api_token
        self.team_id = team_id or None
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # Low-level request handling
    # ------------------------------------------------------------------
    def _headers(self, with_json_body: bool = False) -> dict:
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json",
            # Without a custom User-Agent, the requests library uses the default
            # "python-requests/x.y", which gets blocked by the bot protection in
            # front of domain.chief.app (symptom: plain text "Bad Request" instead
            # of a JSON error from the actual API - confirmed by testing on
            # 2026-09-01). A curl-like User-Agent is demonstrably let through,
            # hence it's hardcoded here.
            "User-Agent": "curl/8.4.0",
        }
        if with_json_body:
            headers["Content-Type"] = "application/json"
        if self.team_id:
            headers["X-Chief-Team"] = self.team_id
        return headers

    def _request(self, method: str, path: str, params: dict | None = None, json_body: dict | None = None) -> Any:
        url = f"{self.base_url}{path}"
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self._session.request(
                    method,
                    url,
                    headers=self._headers(with_json_body=json_body is not None),
                    params=params,
                    json=json_body,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                if attempt <= self.max_retries:
                    wait = min(2 ** attempt, 30)
                    logger.warning("Network error on %s %s (%s), retrying in %ss", method, url, exc, wait)
                    time.sleep(wait)
                    continue
                raise DomainChiefError(f"Network error on {method} {url}: {exc}") from exc

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                retry_after_s = float(retry_after) if retry_after else None
                if attempt <= self.max_retries:
                    wait = retry_after_s if retry_after_s else min(2 ** attempt, 60)
                    logger.warning("Rate limit hit, waiting %ss before retrying", wait)
                    time.sleep(wait)
                    continue
                raise DomainChiefRateLimitError(
                    "Rate limit reached (429)", retry_after=retry_after_s, payload=self._safe_json(response)
                )

            if response.status_code >= 500 and attempt <= self.max_retries:
                wait = min(2 ** attempt, 30)
                logger.warning("Server error %s on %s %s, retrying in %ss", response.status_code, method, url, wait)
                time.sleep(wait)
                continue

            if not response.ok:
                payload = self._safe_json(response)
                message = self._extract_message(payload)
                if not message:
                    # No known error format (message/errors) found - include the raw
                    # response body anyway instead of just logging "HTTP 400", so the
                    # actual reason (e.g. a Domain Chief validation error) is still
                    # visible in the logs.
                    body_preview = str(payload)[:500]
                    message = f"HTTP {response.status_code}: {body_preview}"
                raise DomainChiefError(message, status_code=response.status_code, payload=payload)

            if response.status_code == 204 or not response.content:
                return None
            return self._safe_json(response)

    @staticmethod
    def _safe_json(response: requests.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return {"raw": response.text}

    @staticmethod
    def _extract_message(payload: Any) -> Optional[str]:
        if isinstance(payload, dict):
            if payload.get("message") and payload.get("errors"):
                return f"{payload['message']} ({payload['errors']})"
            if payload.get("message"):
                return payload["message"]
            if payload.get("errors"):
                return f"Validation error: {payload['errors']}"
        elif isinstance(payload, str) and payload.strip():
            # E.g. 409 responses from Domain Chief return plain text instead of JSON.
            return payload.strip()
        return None

    # ------------------------------------------------------------------
    # DNS records
    # ------------------------------------------------------------------
    def list_dns_records(self, domain: str, page: int = 1, per_page: int = 100) -> list[DNSRecord]:
        """Fetch all DNS records of a domain (paginated, we automatically follow all pages)."""
        records: list[DNSRecord] = []
        current_page = page
        while True:
            data = self._request(
                "GET",
                f"/domains/{domain}/dns/records",
                params={"page": current_page, "per_page": per_page},
            )
            for item in data.get("data", []):
                records.append(DNSRecord.from_api(item))
            meta = data.get("meta", {})
            if not meta or meta.get("current_page", current_page) >= meta.get("last_page", current_page):
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
    ) -> DNSRecord:
        body: dict[str, Any] = {"type": record_type, "content": content, "ttl": ttl}
        if name:
            body["name"] = name
        if prio is not None:
            body["prio"] = prio
        if comment is not None:
            body["comment"] = comment
        if metadata is not None:
            body["metadata"] = metadata
        data = self._request("POST", f"/domains/{domain}/dns/records", json_body=body)
        return DNSRecord.from_api(data["data"])

    def update_dns_record(
        self,
        domain: str,
        record_id: str,
        record_type: str,
        content: str,
        ttl: int = 300,
        prio: Optional[int] = None,
        comment: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> DNSRecord:
        # PUT requires type/content/ttl as mandatory fields (full replace, not a PATCH).
        body: dict[str, Any] = {"type": record_type, "content": content, "ttl": ttl}
        if prio is not None:
            body["prio"] = prio
        if comment is not None:
            body["comment"] = comment
        if metadata is not None:
            body["metadata"] = metadata
        data = self._request(
            "PUT", f"/domains/{domain}/dns/records/{record_id}", json_body=body
        )
        return DNSRecord.from_api(data["data"])

    def delete_dns_record(self, domain: str, record_id: str) -> None:
        self._request("DELETE", f"/domains/{domain}/dns/records/{record_id}")

    # ------------------------------------------------------------------
    # Domains (only for the Web UI, to display existing domains)
    # ------------------------------------------------------------------
    def list_domains(self) -> list[dict]:
        domains: list[dict] = []
        page = 1
        while True:
            data = self._request("GET", "/domains", params={"page": page, "per_page": 100})
            domains.extend(data.get("data", []))
            meta = data.get("meta", {})
            if not meta or meta.get("current_page", page) >= meta.get("last_page", page):
                break
            page += 1
        return domains

    def verify_credentials(self) -> bool:
        """Lightweight check whether token + team work (lists 1 domain)."""
        self._request("GET", "/domains", params={"page": 1, "per_page": 1})
        return True
