"""
Core logic: periodic synchronization of the configured DNS records with the
current public IP address (Dynamic DNS for Domain Chief, part of ETF-MultiDDNS).
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Optional

from . import config as config_module
from .domainchief_client import DomainChiefClient, DomainChiefError, DomainChiefRateLimitError
from .ip_provider import get_public_ipv4, get_public_ipv6

logger = logging.getLogger("etfmultiddns.ddns")


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
    def _client(self) -> DomainChiefClient:
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

        try:
            client = self._client()
        except DomainChiefError as exc:
            logger.error("Sync aborted: %s", exc)
            self.last_run_error = str(exc)
            for record in self.config["records"]:
                record["last_status"] = "error"
                record["last_error"] = str(exc)
            self._save()
            return summary

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

            try:
                result = self._sync_record(client, record, current_ip)
                summary[result] = summary.get(result, 0) + 1
                any_change = True
            except DomainChiefRateLimitError as exc:
                logger.warning("Rate limit hit for %s, will retry on the next run.", self._record_label(record))
                record["last_status"] = "error"
                record["last_error"] = str(exc)
                summary["errors"] += 1
                any_change = True
            except DomainChiefError as exc:
                logger.error("Error on %s: %s", self._record_label(record), exc)
                record["last_status"] = "error"
                record["last_error"] = str(exc)
                summary["errors"] += 1
                any_change = True

        self.last_run_at = _status_timestamp()
        self.last_run_error = None
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

    def _sync_record(self, client: DomainChiefClient, record: dict, current_ip: str) -> str:
        label = self._record_label(record)
        existing = None
        if record.get("dns_record_id"):
            # First try to find the known record directly (faster than scanning the list).
            try:
                for candidate in client.list_dns_records(record["domain"]):
                    if candidate.id == record["dns_record_id"]:
                        existing = candidate
                        break
            except DomainChiefError:
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
        # Don't compare only the IP, otherwise TTL/comment values changed via the
        # Web UI (edit function) would only be sent to Domain Chief on the next IP
        # change, instead of on the next sync.
        if existing.content == current_ip and existing.ttl == local_ttl and (existing.comment or "") == local_comment:
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
            comment=record.get("comment"),
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
    def update_record_and_resync(self, record_id: str, *, name: str, record_type: str, ttl: int, comment: str) -> dict:
        """Called from the Web UI (edit record). If this changes the record's
        identity (subdomain or type), the previous remote record at Domain
        Chief (if any) is deleted, so no orphaned record is left behind - the
        next sync then creates it fresh under the new identity. A missing/
        invalid API token does not prevent the local save of the change, but
        is logged."""
        record = config_module.get_record(self.config, record_id)
        if record is None:
            raise KeyError(f"Unknown record: {record_id}")
        identity_changed = record.get("name", "") != name or record["type"] != record_type
        if identity_changed and record.get("dns_record_id"):
            try:
                client = self._client()
                client.delete_dns_record(record["domain"], record["dns_record_id"])
                logger.info("%s: old record removed on Domain Chief (subdomain/type changed via edit)", self._record_label(record))
            except DomainChiefError as exc:
                logger.warning("Could not remove old record on Domain Chief after edit: %s", exc)
        updated = config_module.update_record(
            self.config, record_id, name=name, record_type=record_type, ttl=ttl, comment=comment
        )
        if updated is None:
            raise KeyError(f"Unknown record: {record_id}")
        self.trigger_now()
        return updated

    # ------------------------------------------------------------------
    def delete_record_remote_and_local(self, record_id: str) -> None:
        """Deletes a record both at Domain Chief and from the local configuration."""
        record = config_module.get_record(self.config, record_id)
        if not record:
            raise KeyError(f"Unknown record: {record_id}")
        if record.get("dns_record_id"):
            try:
                client = self._client()
                client.delete_dns_record(record["domain"], record["dns_record_id"])
                logger.info("%s: record deleted on Domain Chief", self._record_label(record))
            except DomainChiefError as exc:
                logger.error("Could not delete record on Domain Chief: %s", exc)
                raise
        config_module.remove_record(self.config, record_id)
        # Trigger an immediate sync, analogous to creating/editing - e.g. so that
        # needs_ipv4/needs_ipv6 (depends on the remaining records) and the
        # dashboard status update without waiting for the check interval.
        self.trigger_now()
