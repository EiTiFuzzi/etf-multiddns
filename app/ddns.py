"""
Core logic: periodic synchronization of the configured DNS records with the
current public IP address (Dynamic DNS for Domain Chief, part of ETF-MultiDDNS).
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any, Optional

from . import config as config_module
from .cloudflare_client import CloudflareClient, CloudflareError, CloudflareRateLimitError
from .domainchief_client import DomainChiefClient, DomainChiefError, DomainChiefRateLimitError
from .ip_provider import get_public_ipv4, get_public_ipv6

logger = logging.getLogger("etfmultiddns.ddns")

# Both providers raise their own (structurally identical) exception classes -
# these tuples let the sync loop handle "any provider error"/"any provider
# rate limit" generically instead of duplicating every except-branch per
# provider.
ProviderError = (DomainChiefError, CloudflareError)
ProviderRateLimitError = (DomainChiefRateLimitError, CloudflareRateLimitError)


def _now_iso() -> str:
    """Current timestamp as already-formatted display text (user's selected
    timezone + format, Settings) - for a LOG LINE, which is one-shot text
    that's appended to the log and never re-rendered afterwards, so baking in
    the format at write time is fine (same as any other log timestamp). The
    name is historical - the format is no longer necessarily ISO 8601.
    NOT for last_run_at/record["last_sync_at"] - see _status_timestamp()."""
    return config_module.format_now()


def _status_timestamp() -> str:
    """Current timestamp for a "current status" field (last_run_at,
    record["last_sync_at"]) that stays on screen and keeps getting re-rendered
    - unlike a log line. Stored in a timezone-independent canonical form
    (config.utc_now_iso()) rather than already-formatted text, so a later
    Settings change to the timezone/display format is reflected immediately
    everywhere this value is shown, not only for timestamps recorded after
    the change (see config.format_timestamp(), used wherever these fields are
    rendered)."""
    return config_module.utc_now_iso()


class LogBuffer:
    """Ring buffer for the most recent log lines, so the Web UI can display them."""

    def __init__(self, maxlen: int = 500):
        self._buffer: deque[str] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def append(self, message: str) -> None:
        with self._lock:
            self._buffer.append(f"[{_now_iso()}] {message}")

    def tail(self, n: int = 200) -> list[str]:
        with self._lock:
            items = list(self._buffer)
        return items[-n:]


class BufferLogHandler(logging.Handler):
    def __init__(self, buffer: LogBuffer):
        super().__init__()
        self.buffer = buffer

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.buffer.append(self.format(record))
        except Exception:  # pragma: no cover - logging must never crash
            pass


class DDNSService:
    """Holds configuration + status in memory and runs the sync loop."""

    def __init__(self):
        self.config: dict = config_module.load_config()
        self.log_buffer = LogBuffer()
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._state_lock = threading.Lock()
        self.last_ipv4: Optional[str] = None
        self.last_ipv6: Optional[str] = None
        self.last_run_at: Optional[str] = None
        self.last_run_error: Optional[str] = None

        handler = BufferLogHandler(self.log_buffer)
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        logging.getLogger("etfmultiddns").addHandler(handler)

    # ------------------------------------------------------------------
    def _client(self, provider: str = "domainchief"):
        """Returns a provider client for the given record provider
        ("domainchief" or "cloudflare"). Both clients expose the same
        list/find/create/update/delete_dns_record interface, so the rest of
        this class (see _sync_record()) doesn't need to know which one it got."""
        if provider == "cloudflare":
            token = self.config.get("cloudflare_api_token", "")
            if not token:
                raise CloudflareError("No Cloudflare API token configured. Please set one up in Settings.")
            return CloudflareClient(api_token=token)
        token = self.config.get("api_token", "")
        if not token:
            raise DomainChiefError("No API token configured. Please set one up in Settings.")
        return DomainChiefClient(api_token=token, team_id=self.config.get("team_id") or None)

    def reload_config(self) -> None:
        with self._state_lock:
            self.config = config_module.load_config()

    def _save(self) -> None:
        config_module.save_config(self.config)

    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="ddns-sync-loop", daemon=True)
        self._thread.start()
        logger.info("DDNS sync loop started.")

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def trigger_now(self) -> None:
        """Called from the Web UI to trigger an immediate sync run."""
        self._wake_event.set()

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.sync_once()
            except Exception as exc:  # pragma: no cover - the loop must never crash
                logger.exception("Unexpected error in the sync loop: %s", exc)
                with self._state_lock:
                    self.last_run_error = str(exc)
            interval = max(60, int(self.config.get("check_interval", 300)))
            self._wake_event.wait(timeout=interval)
            self._wake_event.clear()

    # ------------------------------------------------------------------
    def sync_once(self) -> dict:
        """Performs a full synchronization of all active records."""
        summary = {"checked": 0, "updated": 0, "created": 0, "unchanged": 0, "errors": 0}
        self.reload_config()

        needs_ipv4 = any(r["type"] == "A" and r.get("enabled", True) for r in self.config["records"])
        needs_ipv6 = any(r["type"] == "AAAA" and r.get("enabled", True) for r in self.config["records"])

        ipv4 = get_public_ipv4(self.config.get("ipv4_providers") or None) if needs_ipv4 else None
        ipv6 = get_public_ipv6(self.config.get("ipv6_providers") or None) if needs_ipv6 else None

        with self._state_lock:
            if needs_ipv4:
                self.last_ipv4 = ipv4
            if needs_ipv6:
                self.last_ipv6 = ipv6

        if not self.config["records"]:
            logger.info("No records configured, nothing to do.")
            self.last_run_at = _status_timestamp()
            return summary

        # One client per provider, built lazily and reused for every record of
        # that provider in this run (instead of one client for the whole sync,
        # like before Cloudflare support) - so a missing/invalid token for one
        # provider only fails ITS records, not every record regardless of
        # which provider they actually use.
        clients: dict[str, Any] = {}
        client_errors: dict[str, str] = {}

        def _client_for(provider: str):
            if provider in clients:
                return clients[provider]
            if provider in client_errors:
                return None
            try:
                clients[provider] = self._client(provider)
                return clients[provider]
            except ProviderError as exc:
                client_errors[provider] = str(exc)
                return None

        any_change = False
        for record in self.config["records"]:
            if not record.get("enabled", True):
                continue
            summary["checked"] += 1
            current_ip = ipv4 if record["type"] == "A" else ipv6
            if not current_ip:
                msg = f"Could not determine public {'IPv4' if record['type'] == 'A' else 'IPv6'} address."
                logger.warning("%s -> %s", self._record_label(record), msg)
                record["last_status"] = "error"
                record["last_error"] = msg
                summary["errors"] += 1
                any_change = True
                continue

            provider = record.get("provider", "domainchief")
            client = _client_for(provider)
            if client is None:
                msg = client_errors[provider]
                logger.error("%s -> %s", self._record_label(record), msg)
                record["last_status"] = "error"
                record["last_error"] = msg
                summary["errors"] += 1
                any_change = True
                continue

            try:
                result = self._sync_record(client, record, current_ip)
                summary[result] = summary.get(result, 0) + 1
                any_change = True
            except ProviderRateLimitError as exc:
                logger.warning("Rate limit hit for %s, will retry on the next run.", self._record_label(record))
                record["last_status"] = "error"
                record["last_error"] = str(exc)
                summary["errors"] += 1
                any_change = True
            except ProviderError as exc:
                logger.error("Error on %s: %s", self._record_label(record), exc)
                record["last_status"] = "error"
                record["last_error"] = str(exc)
                summary["errors"] += 1
                any_change = True

        self.last_run_at = _status_timestamp()
        self.last_run_error = "; ".join(f"{p}: {m}" for p, m in client_errors.items()) or None
        if any_change:
            self._save()
        logger.info(
            "Sync finished: %s checked, %s created, %s updated, %s unchanged, %s errors",
            summary["checked"], summary["created"], summary["updated"], summary["unchanged"], summary["errors"],
        )
        return summary

    @staticmethod
    def _record_label(record: dict) -> str:
        host = f"{record['name']}.{record['domain']}" if record.get("name") else record["domain"]
        return f"{host} ({record['type']})"

    def _sync_record(self, client, record: dict, current_ip: str) -> str:
        label = self._record_label(record)
        proxied = bool(record.get("proxied", False))
        existing = None
        if record.get("dns_record_id"):
            # First try to find the known record directly (faster than scanning the list).
            try:
                for candidate in client.list_dns_records(record["domain"]):
                    if candidate.id == record["dns_record_id"]:
                        existing = candidate
                        break
            except ProviderError:
                existing = None
        if existing is None:
            existing = client.find_dns_record(record["domain"], record.get("name", ""), record["type"])

        if existing is None:
            created = client.create_dns_record(
                domain=record["domain"],
                record_type=record["type"],
                content=current_ip,
                ttl=record.get("ttl", 300),
                name=record.get("name", ""),
                comment=record.get("comment"),
                proxied=proxied,
            )
            record["dns_record_id"] = created.id
            record["last_ip"] = current_ip
            record["last_status"] = "created"
            record["last_error"] = None
            record["last_sync_at"] = _status_timestamp()
            logger.info("%s: record newly created -> %s", label, current_ip)
            return "created"

        record["dns_record_id"] = existing.id
        local_ttl = record.get("ttl", existing.ttl)
        local_comment = record.get("comment") or ""
        existing_proxied = bool(getattr(existing, "proxied", False))
        # Don't compare only the IP, otherwise TTL/comment/proxied values changed
        # via the Web UI (edit function) would only be sent to the provider on
        # the next IP change, instead of on the next sync.
        if (
            existing.content == current_ip
            and existing.ttl == local_ttl
            and (existing.comment or "") == local_comment
            and existing_proxied == proxied
        ):
            record["last_ip"] = current_ip
            record["last_status"] = "unchanged"
            record["last_error"] = None
            record["last_sync_at"] = _status_timestamp()
            logger.debug("%s: unchanged (%s)", label, current_ip)
            return "unchanged"

        client.update_dns_record(
            domain=record["domain"],
            record_id=existing.id,
            record_type=record["type"],
            content=current_ip,
            ttl=record.get("ttl", existing.ttl),
            name=record.get("name", ""),
            comment=record.get("comment"),
            proxied=proxied,
        )
        record["last_ip"] = current_ip
        record["last_status"] = "updated"
        record["last_error"] = None
        record["last_sync_at"] = _status_timestamp()
        logger.info(
            "%s: updated (IP %s -> %s, TTL %s, comment %r)",
            label, existing.content, current_ip, local_ttl, local_comment,
        )
        return "updated"

    # ------------------------------------------------------------------
    def update_record_and_resync(
        self,
        record_id: str,
        *,
        name: str,
        record_type: str,
        ttl: int,
        comment: str,
        provider: str | None = None,
        proxied: bool | None = None,
    ) -> dict:
        """Called from the Web UI (edit record). If this changes the record's
        identity (subdomain, type or provider), the previous remote record
        (if any) is deleted at its OLD provider, so no orphaned record is
        left behind - the next sync then creates it fresh under the new
        identity/provider. A missing/invalid API token does not prevent the
        local save of the change, but is logged."""
        record = config_module.get_record(self.config, record_id)
        if record is None:
            raise KeyError(f"Unknown record: {record_id}")
        old_provider = record.get("provider", "domainchief")
        new_provider = provider if provider in ("domainchief", "cloudflare") else old_provider
        identity_changed = (
            record.get("name", "") != name or record["type"] != record_type or old_provider != new_provider
        )
        if identity_changed and record.get("dns_record_id"):
            try:
                client = self._client(old_provider)
                client.delete_dns_record(record["domain"], record["dns_record_id"])
                logger.info("%s: old record removed at %s (subdomain/type/provider changed via edit)", self._record_label(record), old_provider)
            except ProviderError as exc:
                logger.warning("Could not remove old record at %s after edit: %s", old_provider, exc)
        updated = config_module.update_record(
            self.config,
            record_id,
            name=name,
            record_type=record_type,
            ttl=ttl,
            comment=comment,
            provider=new_provider,
            proxied=proxied,
        )
        if updated is None:
            raise KeyError(f"Unknown record: {record_id}")
        self.trigger_now()
        return updated

    # ------------------------------------------------------------------
    def delete_record_remote_and_local(self, record_id: str) -> None:
        """Deletes a record both at its DNS provider and from the local configuration."""
        record = config_module.get_record(self.config, record_id)
        if not record:
            raise KeyError(f"Unknown record: {record_id}")
        if record.get("dns_record_id"):
            try:
                client = self._client(record.get("provider", "domainchief"))
                client.delete_dns_record(record["domain"], record["dns_record_id"])
                logger.info("%s: record deleted at %s", self._record_label(record), record.get("provider", "domainchief"))
            except ProviderError as exc:
                logger.error("Could not delete record at %s: %s", record.get("provider", "domainchief"), exc)
                raise
        config_module.remove_record(self.config, record_id)
        # Trigger an immediate sync, analogous to creating/editing - e.g. so that
        # needs_ipv4/needs_ipv6 (depends on the remaining records) and the
        # dashboard status update without waiting for the check interval.
        self.trigger_now()

    # ------------------------------------------------------------------
    def set_record_enabled(self, record_id: str, enabled: bool) -> dict:
        """Called from the Web UI (On/Off button in the record list).

        Turning a record OFF doesn't just pause it locally - it also removes
        the DNS record at its provider (like delete_record_remote_and_local,
        but the entry itself stays in the local list/config instead of being
        removed). This avoids a stale/orphaned DNS record silently sticking
        around at the provider, still pointing at whatever IP address it was
        last updated to, for as long as the record stays disabled here - which
        could be a stale IP later reassigned to someone else once the
        connection this dynamic DNS depends on changes.

        If the remote deletion fails (network issue, revoked token, ...), the
        exception is re-raised and NO local state is changed at all (mirrors
        delete_record_remote_and_local) - the record stays enabled and
        actively managed rather than ending up disabled locally while still
        live (and un-managed) at the provider.

        Turning a record back ON only flips the local flag; the next sync
        (triggered immediately, not waiting for the check interval) then
        creates a fresh DNS record for it, exactly like a brand new record."""
        record = config_module.get_record(self.config, record_id)
        if not record:
            raise KeyError(f"Unknown record: {record_id}")

        if enabled:
            record["enabled"] = True
            self._save()
            self.trigger_now()
            return record

        provider = record.get("provider", "domainchief")
        if record.get("dns_record_id"):
            try:
                client = self._client(provider)
                client.delete_dns_record(record["domain"], record["dns_record_id"])
                logger.info("%s: record deleted at %s (disabled via dashboard)", self._record_label(record), provider)
            except ProviderError as exc:
                logger.error("Could not delete record at %s while disabling: %s", provider, exc)
                raise

        record["enabled"] = False
        record["dns_record_id"] = None
        record["last_ip"] = None
        record["last_status"] = "disabled"
        record["last_error"] = None
        record["last_sync_at"] = _status_timestamp()
        self._save()
        return record

    # ------------------------------------------------------------------
    def find_importable_records(self) -> tuple[list[dict], list[str], Optional[str], Optional[str]]:
        """Called from the Web UI ("Import existing records", linked from the
        provider sections in Settings). Scans every domain at every
        CONFIGURED provider for A/AAAA records that already point at the
        current public IPv4/IPv6 but aren't locally managed yet - so records
        that were created directly at the provider (or by an older setup
        this app never knew about) can be adopted without retyping every
        domain/subdomain by hand.

        Read-only: only lists data at the provider(s), never creates/changes/
        deletes anything there or in the local config - see import_records()
        for the write side. A provider without a configured token is skipped
        silently (nothing to scan); a provider/domain that fails while
        already configured is recorded in the returned scan_errors list, but
        does not stop the scan of the others.

        Returns (candidates, scan_errors, ipv4, ipv6). Each candidate is a
        plain dict (domain/name/type/content/ttl/comment/proxied/provider/
        dns_record_id) - the same shape import_records() expects."""
        self.reload_config()
        ipv4 = get_public_ipv4(self.config.get("ipv4_providers") or None)
        ipv6 = get_public_ipv6(self.config.get("ipv6_providers") or None)

        candidates: list[dict] = []
        scan_errors: list[str] = []

        # (provider, domain, name, type) of every record already managed
        # locally - a candidate matching one of these is already known and
        # must not be offered again.
        existing_keys = {
            (
                r.get("provider", "domainchief"),
                r["domain"].strip().lower(),
                (r.get("name") or "").strip().lower(),
                r["type"],
            )
            for r in self.config["records"]
        }

        for provider in ("domainchief", "cloudflare"):
            try:
                client = self._client(provider)
            except ProviderError:
                continue  # not configured - nothing to scan for this provider

            try:
                domains = [d.get("domain") for d in client.list_domains() if d.get("domain")]
            except ProviderError as exc:
                scan_errors.append(f"{provider}: {exc}")
                continue

            for domain in domains:
                try:
                    records = client.list_dns_records(domain)
                except ProviderError as exc:
                    scan_errors.append(f"{provider}/{domain}: {exc}")
                    continue

                for rec in records:
                    if rec.type not in ("A", "AAAA"):
                        continue
                    target_ip = ipv4 if rec.type == "A" else ipv6
                    if not target_ip or rec.content != target_ip:
                        continue
                    name = (rec.name or "").strip().lower()
                    key = (provider, domain.strip().lower(), name, rec.type)
                    if key in existing_keys:
                        continue
                    candidates.append(
                        {
                            "provider": provider,
                            "domain": domain,
                            "name": rec.name or "",
                            "type": rec.type,
                            "content": rec.content,
                            "ttl": rec.ttl,
                            "comment": rec.comment or "",
                            "proxied": bool(getattr(rec, "proxied", False)),
                            "dns_record_id": rec.id,
                        }
                    )

        return candidates, scan_errors, ipv4, ipv6

    def import_records(self, selected: list[dict]) -> int:
        """Adds each of the given candidate records (as returned by
        find_importable_records(), selected by the user in the Web UI) to
        local management, already marked as synced/adopted - see
        config.import_record(). Nothing is created or changed at the
        provider here: the whole point is that these records already exist
        there and already match, so the next regular sync only needs to
        confirm that (or pick up anything that changed since the scan).
        Returns how many records were actually imported (entries with an
        unknown/missing provider are skipped)."""
        count = 0
        for item in selected or []:
            provider = item.get("provider")
            if provider not in ("domainchief", "cloudflare"):
                continue
            domain = item.get("domain") or ""
            record_type = item.get("type") or ""
            if not domain or record_type not in ("A", "AAAA"):
                continue
            config_module.import_record(
                self.config,
                domain=domain,
                name=item.get("name", ""),
                record_type=record_type,
                ttl=item.get("ttl", 300),
                comment=item.get("comment", ""),
                provider=provider,
                proxied=item.get("proxied", False),
                dns_record_id=item.get("dns_record_id"),
                current_ip=item.get("content", ""),
            )
            count += 1
        if count:
            self.trigger_now()
        return count
