"""
Configuration management.

The configuration lives as a JSON file (default: /config/config.json,
mounted via a volume so it survives container restarts). Sensitive values
(API token) can instead also be set via an environment variable - that
takes precedence over the JSON file.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
import uuid
import zoneinfo
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("etfmultiddns.config")

CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", "/config/config.json"))

# Where TLS certificates/private keys (self-signed + an imported custom one)
# are stored - a subfolder next to config.json, so it lives on the same
# volume and survives container restarts without needing a separate mount.
CERT_DIR = CONFIG_PATH.parent / "certs"

try:
    AVAILABLE_TIMEZONES = sorted(zoneinfo.available_timezones())
except Exception:  # pragma: no cover - defensive, in case tzdata is missing
    AVAILABLE_TIMEZONES = []

# The TZ environment variable as set by the DEPLOYMENT (docker-compose/.env)
# when this process started - captured once, here, before anything else in
# this module ever touches os.environ["TZ"]. apply_timezone() below also
# writes to os.environ["TZ"] (that's how it makes datetime.now()/time.tzset()
# pick up a timezone chosen in the Web UI without a container restart). If
# code elsewhere read os.environ.get("TZ") directly to decide "was this fixed
# by the deployment", it would see that self-set value on every subsequent
# call and wrongly conclude the timezone is permanently fixed by the
# environment - which is exactly what happened before this fix: the first
# Web UI change silently "locked" the timezone forever (env override logic
# kept re-imposing it, and the Settings field disabled itself), and only a
# container restart (which resets the process environment) allowed one more
# change. Using this frozen snapshot instead of a live os.environ read keeps
# "did the deployment fix this" and "what's currently applied" separate.
_INITIAL_ENV_TZ = os.environ.get("TZ", "")


def env_timezone() -> str:
    """The timezone fixed by the deployment's TZ environment variable (if
    any), as it was at process start - empty if the timezone is freely
    configurable via the Web UI. See _INITIAL_ENV_TZ above for why this is a
    frozen snapshot rather than a live os.environ.get("TZ") read."""
    return _INITIAL_ENV_TZ

# Display formats for timestamps (dashboard, logs). Deliberately a fixed
# selection instead of freely enterable strftime patterns, so no
# invalid/nonsensical formats can be stored.
DATETIME_FORMATS: dict[str, str] = {
    "iso": "%Y-%m-%d %H:%M:%S",
    "iso_t": "%Y-%m-%dT%H:%M:%S",
    "eu_24h": "%d.%m.%Y %H:%M:%S",
    "eu_short": "%d.%m.%y %H:%M",
    "us_12h": "%m/%d/%Y %I:%M:%S %p",
}
DEFAULT_DATETIME_FORMAT = "iso"

DEFAULT_CONFIG: dict[str, Any] = {
    "api_token": "",
    "team_id": "",
    # Cloudflare API Token (Bearer auth, Zone:DNS:Edit + Zone:Zone:Read) - a
    # second, independent DNS provider records can choose from (see the
    # per-record "provider" field below). Both providers can be configured
    # and used at the same time.
    "cloudflare_api_token": "",
    "check_interval": 300,
    "ipv4_providers": [],
    "ipv6_providers": [],
    "records": [],
    # Web UI login: empty = not set up yet (setup wizard kicks in), can be
    # overridden via the WEBUI_USERNAME/WEBUI_PASSWORD env vars.
    "secret_key": "",
    "webui_username": "",
    "webui_password_hash": "",
    # Empty = system default (UTC in the container, unless set via the TZ env var).
    "timezone": "",
    "datetime_format": DEFAULT_DATETIME_FORMAT,
    # HTTPS: off by default (existing setups only expose the HTTP port).
    # "self_signed" (default once enabled) or "custom" (an imported certificate,
    # see app/tls.py). https_cert_hostname is an optional hostname/IP used as
    # the self-signed certificate's subject/SAN.
    "https_enabled": False,
    "https_cert_source": "self_signed",
    "https_cert_hostname": "",
    # Two-factor authentication (TOTP, RFC 6238) for the Web UI login - off by
    # default. totp_secret is only set once setup is confirmed with a valid
    # code (see app/totp.py). totp_recovery_codes holds hashed, single-use
    # backup codes (werkzeug password hashing, like webui_password_hash) -
    # each is removed from the list once consumed.
    "totp_enabled": False,
    "totp_secret": "",
    "totp_recovery_codes": [],
}

_lock = threading.Lock()

# Currently active display format, updated by load_config(). Kept here as a
# module variable (instead of reloading the config on every call) so
# format_now() can also be called from contexts without direct access to the
# config dict (e.g. the log buffer) - analogous to the TZ environment variable.
_current_datetime_format = DEFAULT_DATETIME_FORMAT


def apply_timezone(tz_name: str) -> None:
    """Sets the process timezone (TZ env var + tzset), so datetime.now(),
    time.localtime() and therefore also Python logging (%(asctime)s)
    immediately use the selected timezone - without a container restart."""
    tz_name = (tz_name or "").strip()
    if tz_name and tz_name in AVAILABLE_TIMEZONES:
        os.environ["TZ"] = tz_name
    else:
        os.environ.pop("TZ", None)
    if hasattr(time, "tzset"):
        try:
            time.tzset()
        except Exception:  # pragma: no cover - defensive
            logger.warning("Could not apply timezone %r.", tz_name)


def format_now() -> str:
    """Current time, formatted according to the selected timezone + display format.
    For text that's written once and meant to stay as-is (e.g. a log line) - see
    utc_now_iso()/format_timestamp() below for anything that should keep reflecting
    the CURRENT timezone/format setting even after it was first recorded."""
    pattern = DATETIME_FORMATS.get(_current_datetime_format, DATETIME_FORMATS[DEFAULT_DATETIME_FORMAT])
    return datetime.now().astimezone().strftime(pattern)


def utc_now_iso() -> str:
    """Current time as a timezone-independent, unambiguous ISO-8601 string (UTC).
    Use this - NOT format_now() - to store a timestamp that's shown as "current
    status" somewhere in the Web UI (last sync, last run): storing the already
    display-formatted text would freeze it in whatever timezone/format was active
    at the moment it was written, so a later change to either setting would only
    affect the NEXT such timestamp, not the ones already on screen - exactly the
    "the change doesn't take effect" complaint this pairing is meant to avoid.
    format_timestamp() converts a value stored this way back to display text,
    using the CURRENTLY active timezone/format, at render time."""
    return datetime.now(timezone.utc).isoformat()


def format_timestamp(value: str | None) -> str | None:
    """Renders a timestamp stored via utc_now_iso() as display text, using the
    currently active timezone + format (see load_config()) - always freshly
    computed at render time, so a Settings change is reflected immediately for
    every already-stored timestamp, not just ones recorded after the change.
    Passing None (never synced yet) returns None. A value that isn't a valid
    ISO-8601 string is returned unchanged - this only happens for timestamps
    written by an older version of this app (before this function existed),
    which stored already-formatted text directly; those keep showing as
    originally recorded until they're next overwritten, rather than crashing."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    pattern = DATETIME_FORMATS.get(_current_datetime_format, DATETIME_FORMATS[DEFAULT_DATETIME_FORMAT])
    return dt.astimezone().strftime(pattern)


def format_examples() -> dict[str, str]:
    """Example timestamp for each available display format (for the selector in
    the Web UI). Fixed example moment, independent of the current time/timezone,
    so the formats are clearly distinguishable (day != month)."""
    sample = datetime(2026, 3, 4, 17, 8, 9)
    return {key: sample.strftime(pattern) for key, pattern in DATETIME_FORMATS.items()}


def _merge_defaults(data: dict) -> dict:
    merged = dict(DEFAULT_CONFIG)
    merged.update(data or {})
    merged.setdefault("records", [])
    for record in merged["records"]:
        record.setdefault("id", uuid.uuid4().hex[:12])
        record.setdefault("ttl", 300)
        record.setdefault("enabled", True)
        record.setdefault("comment", "Managed by etf-multiddns")
        # "domainchief" is the default (not "cloudflare") so records created
        # before Cloudflare support existed keep working against Domain Chief
        # unchanged after an upgrade.
        record.setdefault("provider", "domainchief")
        # Cloudflare-only ("proxied" / orange-cloud) - ignored for Domain Chief records.
        record.setdefault("proxied", False)
        record.setdefault("last_ip", None)
        record.setdefault("last_sync_at", None)
        record.setdefault("last_status", "pending")
        record.setdefault("last_error", None)
        record.setdefault("dns_record_id", None)
    return merged


PROVIDERS = ("domainchief", "cloudflare")
DEFAULT_PROVIDER = "domainchief"


def load_config() -> dict:
    with _lock:
        if not CONFIG_PATH.exists():
            logger.info("No configuration found at %s, creating a new one.", CONFIG_PATH)
            config = _merge_defaults({})
            _write(config)
            return config
        try:
            with CONFIG_PATH.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Could not read configuration (%s), using defaults.", exc)
            data = {}
        config = _merge_defaults(data)

    # Environment variables take precedence for sensitive / deployment-specific values.
    env_token = os.environ.get("DOMAINCHIEF_API_TOKEN")
    if env_token:
        config["api_token"] = env_token
    env_team = os.environ.get("DOMAINCHIEF_TEAM_ID")
    if env_team:
        config["team_id"] = env_team
    env_cf_token = os.environ.get("CLOUDFLARE_API_TOKEN")
    if env_cf_token:
        config["cloudflare_api_token"] = env_cf_token
    env_interval = os.environ.get("CHECK_INTERVAL")
    if env_interval:
        try:
            config["check_interval"] = int(env_interval)
        except ValueError:
            pass
    if _INITIAL_ENV_TZ:
        config["timezone"] = _INITIAL_ENV_TZ

    # Session signing key: generate once and persist, otherwise all existing
    # logins would become invalid on every restart.
    if not config.get("secret_key"):
        config["secret_key"] = secrets.token_hex(32)
        save_config(config)

    # Apply timezone + display format immediately, on every load (startup, Web UI
    # change, sync loop) - so a change takes effect without a container restart.
    apply_timezone(config.get("timezone", ""))
    global _current_datetime_format
    fmt = config.get("datetime_format") or DEFAULT_DATETIME_FORMAT
    if fmt not in DATETIME_FORMATS:
        fmt = DEFAULT_DATETIME_FORMAT
    _current_datetime_format = fmt

    return config


def save_config(config: dict) -> None:
    with _lock:
        _write(config)


def _write(config: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = CONFIG_PATH.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2, ensure_ascii=False)
    tmp_path.replace(CONFIG_PATH)


def add_record(
    config: dict,
    domain: str,
    name: str,
    record_type: str,
    ttl: int = 300,
    comment: str = "",
    provider: str = DEFAULT_PROVIDER,
    proxied: bool = False,
) -> dict:
    record = {
        "id": uuid.uuid4().hex[:12],
        "domain": domain.strip().lower(),
        "name": (name or "").strip().lower(),
        "type": record_type.upper(),
        "ttl": int(ttl),
        "enabled": True,
        "comment": comment or "Managed by etf-multiddns",
        "provider": provider if provider in PROVIDERS else DEFAULT_PROVIDER,
        "proxied": bool(proxied),
        "last_ip": None,
        "last_sync_at": None,
        "last_status": "pending",
        "last_error": None,
        "dns_record_id": None,
    }
    config["records"].append(record)
    save_config(config)
    return record


def remove_record(config: dict, record_id: str) -> bool:
    before = len(config["records"])
    config["records"] = [r for r in config["records"] if r["id"] != record_id]
    changed = len(config["records"]) != before
    if changed:
        save_config(config)
    return changed


def get_record(config: dict, record_id: str) -> dict | None:
    for record in config["records"]:
        if record["id"] == record_id:
            return record
    return None


def update_record(
    config: dict,
    record_id: str,
    *,
    name: str,
    record_type: str,
    ttl: int,
    comment: str,
    provider: str | None = None,
    proxied: bool | None = None,
) -> dict | None:
    """Updates the subdomain/type/TTL/comment/provider of an existing record
    (the domain itself stays fixed - changing the domain means delete+
    recreate, not an edit). If the name, type or provider changes, the
    record's identity at the DNS provider changes too (lookup/matching is
    done via name+type within one provider) - the local sync status is then
    reset so the next sync creates it fresh under the new identity. Cleaning
    up the old remote record is the caller's responsibility (needs the API
    client for that, see DDNSService)."""
    record = get_record(config, record_id)
    if record is None:
        return None
    new_provider = provider if provider in PROVIDERS else record.get("provider", DEFAULT_PROVIDER)
    identity_changed = (
        record.get("name", "") != name
        or record["type"] != record_type
        or record.get("provider", DEFAULT_PROVIDER) != new_provider
    )
    record["name"] = name
    record["type"] = record_type
    record["ttl"] = int(ttl)
    record["comment"] = comment or "Managed by etf-multiddns"
    record["provider"] = new_provider
    if proxied is not None:
        record["proxied"] = bool(proxied)
    if identity_changed:
        record["dns_record_id"] = None
        record["last_ip"] = None
        record["last_sync_at"] = None
        record["last_status"] = "pending"
        record["last_error"] = None
    save_config(config)
    return record
