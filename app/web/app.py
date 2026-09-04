"""
Small Flask Web UI for the etf-multiddns container.

Shows the current sync status, allows creating/deleting managed records as
well as changing the settings (API token, team ID, interval, Web UI
credentials). Access is protected by login (initial setup on first start,
then session login), and the interface can be switched between German and
English.
"""

from __future__ import annotations

import logging
import os
import secrets as secrets_module
from datetime import timedelta

from flask import Flask, g, jsonify, make_response, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .. import config as config_module
from .. import tls as tls_module
from .. import totp as totp_module
from ..ddns import DDNSService
from ..domainchief_client import DomainChiefClient, DomainChiefError
from ..https_server import HttpsServerManager, https_port
from .i18n import DEFAULT_LANG, LANGUAGES, LANGUAGE_LABELS, translator

logger = logging.getLogger("etfmultiddns.web")

LANG_COOKIE = "lang"
LANG_COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # 1 year

# Endpoints that must be reachable even without login (or before initial setup).
# login_2fa is reachable pre-login too - it guards itself via the
# "awaiting_2fa" session flag set by login() (see below).
PUBLIC_ENDPOINTS = {"login", "login_2fa", "setup", "set_language", "static"}


def _env_webui_credentials() -> tuple[str, str] | None:
    username = os.environ.get("WEBUI_USERNAME", "")
    password = os.environ.get("WEBUI_PASSWORD", "")
    if username and password:
        return username, password
    return None


def _webui_configured(cfg: dict) -> bool:
    if _env_webui_credentials() is not None:
        return True
    return bool(cfg.get("webui_username")) and bool(cfg.get("webui_password_hash"))


def _check_webui_credentials(cfg: dict, username: str, password: str) -> bool:
    env_creds = _env_webui_credentials()
    if env_creds is not None:
        env_user, env_pass = env_creds
        return secrets_module.compare_digest(username, env_user) and secrets_module.compare_digest(password, env_pass)
    stored_user = cfg.get("webui_username", "")
    stored_hash = cfg.get("webui_password_hash", "")
    if not stored_user or not stored_hash:
        return False
    return secrets_module.compare_digest(username, stored_user) and check_password_hash(stored_hash, password)


def create_app(service: DDNSService, https_manager: HttpsServerManager) -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = service.config.get("secret_key") or secrets_module.token_hex(32)
    app.permanent_session_lifetime = timedelta(days=30)

    # ------------------------------------------------------------------
    # Language: stored via cookie, determined before every request.
    # ------------------------------------------------------------------
    @app.before_request
    def _prepare_language() -> None:
        lang = request.cookies.get(LANG_COOKIE)
        if lang not in LANGUAGES:
            lang = DEFAULT_LANG
        g.lang = lang
        g.t = translator(lang)

    @app.context_processor
    def inject_i18n():
        return {"t": g.t, "current_lang": g.lang, "languages": LANGUAGES, "language_labels": LANGUAGE_LABELS}

    @app.context_processor
    def inject_version():
        # Set in the Docker image at build time via --build-arg APP_VERSION=<git-tag>
        # (see Dockerfile + .github/workflows/release.yml). Locally without a build
        # arg, or outside the container, it stays at the placeholder "dev".
        return {"app_version": os.environ.get("APP_VERSION", "dev")}

    # Renders a "current status" timestamp (last_run_at, record.last_sync_at - stored
    # in a canonical, timezone-independent form by DDNSService, see ddns._status_timestamp())
    # as display text, using the CURRENTLY active timezone/format - computed fresh on every
    # render rather than baked in at write time, so a Settings change is reflected
    # immediately for every already-stored timestamp. A Jinja global (not a context
    # processor value) so it can be called per-record inside the {% for %} loop in
    # index.html; /api/status below uses the same function directly in Python.
    app.jinja_env.globals["format_ts"] = config_module.format_timestamp

    @app.get("/lang/<code>")
    def set_language(code: str):
        target = request.args.get("next") or url_for("index")
        response = make_response(redirect(target))
        if code in LANGUAGES:
            response.set_cookie(LANG_COOKIE, code, max_age=LANG_COOKIE_MAX_AGE, samesite="Lax")
        return response

    # ------------------------------------------------------------------
    # Login / initial setup
    # ------------------------------------------------------------------
    @app.before_request
    def require_login():
        if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint is None:
            return None
        cfg = service.config
        if not _webui_configured(cfg):
            return redirect(url_for("setup"))
        if not session.get("logged_in"):
            if session.get("awaiting_2fa"):
                return redirect(url_for("login_2fa"))
            return redirect(url_for("login"))
        return None

    @app.route("/setup", methods=["GET", "POST"])
    def setup():
        cfg = service.config
        if _webui_configured(cfg):
            return redirect(url_for("login"))
        error = None
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            password2 = request.form.get("password2", "")
            if not username or not password:
                error = g.t("setup.error_empty")
            elif password != password2:
                error = g.t("setup.error_mismatch")
            elif len(password) < 8:
                error = g.t("setup.error_short")
            else:
                cfg["webui_username"] = username
                cfg["webui_password_hash"] = generate_password_hash(password)
                config_module.save_config(cfg)
                service.reload_config()
                session.clear()
                session["logged_in"] = True
                session.permanent = True
                return redirect(url_for("index"))
        return render_template("setup.html", error=error)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        cfg = service.config
        if not _webui_configured(cfg):
            return redirect(url_for("setup"))
        error = None
        if request.method == "POST":
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            if _check_webui_credentials(cfg, username, password):
                session.clear()
                if cfg.get("totp_enabled"):
                    # Username/password alone aren't enough - hold off on
                    # "logged_in" until a valid code is also provided (see
                    # login_2fa() below). Non-permanent: this pending state is
                    # meant to be short-lived, not to survive for weeks.
                    session["awaiting_2fa"] = True
                    session.permanent = False
                    return redirect(url_for("login_2fa"))
                session["logged_in"] = True
                session.permanent = True
                return redirect(url_for("index"))
            error = g.t("login.error")
        return render_template("login.html", error=error)

    @app.route("/login/2fa", methods=["GET", "POST"])
    def login_2fa():
        if not session.get("awaiting_2fa"):
            return redirect(url_for("login"))
        cfg = service.config
        error = None
        if request.method == "POST":
            code = request.form.get("code", "")
            if _verify_totp_or_recovery(service, code):
                session.pop("awaiting_2fa", None)
                session["logged_in"] = True
                session.permanent = True
                return redirect(url_for("index"))
            error = g.t("login2fa.error")
        return render_template("login_2fa.html", error=error)

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------
    @app.get("/")
    def index():
        service.reload_config()
        cfg = service.config
        records = cfg.get("records", [])
        # For the JS that periodically refreshes the dashboard content from
        # /api/status (see index.html) - this way status labels also follow the
        # UI language, without /api/status itself having to return translated text.
        status_labels = {key: g.t("status." + key) for key in ("unchanged", "created", "updated", "error", "pending")}
        return render_template(
            "index.html",
            records=records,
            last_ipv4=service.last_ipv4,
            last_ipv6=service.last_ipv6,
            last_run_at=service.last_run_at,
            last_run_error=service.last_run_error,
            check_interval=cfg.get("check_interval", 300),
            has_token=bool(cfg.get("api_token")),
            status_labels=status_labels,
        )

    @app.post("/sync-now")
    def sync_now():
        service.trigger_now()
        return redirect(url_for("index"))

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------
    @app.get("/settings")
    def settings():
        service.reload_config()
        cfg = service.config
        return _render_settings(cfg)

    @app.post("/settings")
    def save_settings():
        cfg = service.config
        token = request.form.get("api_token", "").strip()
        team_id = request.form.get("team_id", "").strip()
        interval = request.form.get("check_interval", "300").strip()
        timezone_name = request.form.get("timezone", "").strip()
        datetime_format = request.form.get("datetime_format", "").strip()

        if token and not _env_token():
            cfg["api_token"] = token
        if not _env_token():
            cfg["team_id"] = team_id
        try:
            cfg["check_interval"] = max(60, int(interval))
        except ValueError:
            pass
        if not _env_timezone() and (timezone_name == "" or timezone_name in config_module.AVAILABLE_TIMEZONES):
            cfg["timezone"] = timezone_name
        if datetime_format in config_module.DATETIME_FORMATS:
            cfg["datetime_format"] = datetime_format
        config_module.save_config(cfg)
        service.reload_config()
        return redirect(url_for("settings"))

    @app.post("/settings/test")
    def test_connection():
        cfg = service.config
        token = cfg.get("api_token", "")
        if not token:
            return jsonify({"ok": False, "message": g.t("settings.test_no_token")})
        try:
            client = DomainChiefClient(api_token=token, team_id=cfg.get("team_id") or None)
            client.verify_credentials()
            return jsonify({"ok": True, "message": g.t("settings.test_success")})
        except DomainChiefError as exc:
            return jsonify({"ok": False, "message": str(exc)})

    @app.post("/settings/webui")
    def save_webui_credentials():
        cfg = service.config
        error = None
        saved = False
        if _env_webui_credentials() is None:
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            password2 = request.form.get("password2", "")
            if password or password2:
                if password != password2:
                    error = g.t("settings.webui_error_mismatch")
                elif len(password) < 8:
                    error = g.t("settings.webui_error_short")
            if not error:
                if username:
                    cfg["webui_username"] = username
                if password and not error:
                    cfg["webui_password_hash"] = generate_password_hash(password)
                config_module.save_config(cfg)
                service.reload_config()
                saved = True
        return _render_settings(cfg, webui_error=error, webui_saved=saved)

    # ------------------------------------------------------------------
    # HTTPS
    # ------------------------------------------------------------------
    @app.post("/settings/https")
    def save_https_settings():
        cfg = service.config
        cfg["https_enabled"] = request.form.get("https_enabled") == "on"
        source = request.form.get("https_cert_source", "self_signed")
        if source in ("self_signed", "custom"):
            cfg["https_cert_source"] = source
        cfg["https_cert_hostname"] = request.form.get("https_cert_hostname", "").strip()
        config_module.save_config(cfg)
        service.reload_config()
        error = https_manager.apply(service.config)
        return _render_settings(cfg, https_error=error, https_saved=error is None)

    @app.post("/settings/https/upload")
    def upload_https_cert():
        cfg = service.config
        cert_file = request.files.get("cert_file")
        key_file = request.files.get("key_file")
        error = None
        if not cert_file or not key_file or not cert_file.filename or not key_file.filename:
            error = "missing_files"
        else:
            try:
                tls_module.save_custom_cert(cert_file.read(), key_file.read())
            except ValueError as exc:
                error = str(exc)
            else:
                cfg["https_cert_source"] = "custom"
                config_module.save_config(cfg)
                service.reload_config()
        if not error:
            error = https_manager.apply(service.config)
        return _render_settings(cfg, https_error=error, https_saved=error is None)

    @app.post("/settings/https/regenerate")
    def regenerate_https_cert():
        cfg = service.config
        tls_module.generate_self_signed(cfg.get("https_cert_hostname", ""))
        error = https_manager.apply(service.config, force=True)
        return _render_settings(cfg, https_error=error, https_saved=error is None)

    @app.post("/settings/https/remove-custom")
    def remove_https_custom_cert():
        cfg = service.config
        tls_module.remove_custom_cert()
        if cfg.get("https_cert_source") == "custom":
            cfg["https_cert_source"] = "self_signed"
            config_module.save_config(cfg)
            service.reload_config()
        error = https_manager.apply(service.config)
        return _render_settings(cfg, https_error=error, https_saved=error is None)

    # ------------------------------------------------------------------
    # Two-factor authentication (TOTP)
    # ------------------------------------------------------------------
    @app.get("/settings/2fa/setup")
    def setup_2fa_form():
        cfg = service.config
        if cfg.get("totp_enabled"):
            return redirect(url_for("settings"))
        # Reuse a secret already pending from an earlier, unfinished attempt
        # (e.g. the page was reloaded) instead of generating a new one every
        # time - otherwise a previously scanned QR code would stop matching.
        secret = session.get("totp_setup_secret")
        if not secret:
            secret = totp_module.generate_secret()
            session["totp_setup_secret"] = secret
        uri = totp_module.provisioning_uri(secret, cfg.get("webui_username", ""))
        return render_template("settings_2fa_setup.html", secret=secret, qr_svg=totp_module.qr_code_svg(uri), error=None)

    @app.post("/settings/2fa/setup")
    def confirm_2fa_setup():
        cfg = service.config
        secret = session.get("totp_setup_secret")
        if not secret:
            return redirect(url_for("setup_2fa_form"))
        code = request.form.get("code", "")
        if not totp_module.verify_code(secret, code):
            uri = totp_module.provisioning_uri(secret, cfg.get("webui_username", ""))
            return render_template(
                "settings_2fa_setup.html",
                secret=secret,
                qr_svg=totp_module.qr_code_svg(uri),
                error=g.t("settings.totp_error_invalid_code"),
            )
        recovery_codes = totp_module.generate_recovery_codes()
        cfg["totp_enabled"] = True
        cfg["totp_secret"] = secret
        cfg["totp_recovery_codes"] = totp_module.hash_recovery_codes(recovery_codes)
        config_module.save_config(cfg)
        service.reload_config()
        session.pop("totp_setup_secret", None)
        return render_template("settings_2fa_recovery.html", recovery_codes=recovery_codes)

    @app.post("/settings/2fa/disable")
    def disable_2fa():
        cfg = service.config
        if not cfg.get("totp_enabled"):
            return redirect(url_for("settings"))
        code = request.form.get("code", "")
        if _verify_totp_or_recovery(service, code):
            cfg = service.config
            cfg["totp_enabled"] = False
            cfg["totp_secret"] = ""
            cfg["totp_recovery_codes"] = []
            config_module.save_config(cfg)
            service.reload_config()
            return _render_settings(cfg, totp_saved=True)
        return _render_settings(cfg, totp_error=g.t("settings.totp_error_invalid_code"))

    @app.post("/settings/2fa/recovery/regenerate")
    def regenerate_recovery_codes():
        cfg = service.config
        if not cfg.get("totp_enabled"):
            return redirect(url_for("settings"))
        recovery_codes = totp_module.generate_recovery_codes()
        cfg["totp_recovery_codes"] = totp_module.hash_recovery_codes(recovery_codes)
        config_module.save_config(cfg)
        service.reload_config()
        return render_template("settings_2fa_recovery.html", recovery_codes=recovery_codes)

    # ------------------------------------------------------------------
    # Records
    # ------------------------------------------------------------------
    @app.get("/records/new")
    def new_record_form():
        service.reload_config()
        domains = []
        error = None
        cfg = service.config
        if cfg.get("api_token"):
            try:
                client = DomainChiefClient(api_token=cfg["api_token"], team_id=cfg.get("team_id") or None)
                domains = sorted(d.get("domain") for d in client.list_domains() if d.get("domain"))
            except DomainChiefError as exc:
                error = str(exc)
        return render_template("record_form.html", record=None, domains=domains, error=error)

    @app.post("/records/new")
    def create_record():
        cfg = service.config
        domain = request.form.get("domain", "").strip().lower()
        name = request.form.get("name", "").strip().lower()
        record_type = request.form.get("type", "A").strip().upper()
        ttl = request.form.get("ttl", "300").strip()
        comment = request.form.get("comment", "").strip()

        if not domain or record_type not in ("A", "AAAA"):
            return redirect(url_for("new_record_form"))
        try:
            ttl_value = max(60, int(ttl))
        except ValueError:
            ttl_value = 300

        config_module.add_record(cfg, domain=domain, name=name, record_type=record_type, ttl=ttl_value, comment=comment)
        service.reload_config()
        service.trigger_now()
        return redirect(url_for("index"))

    @app.get("/records/<record_id>/edit")
    def edit_record_form(record_id: str):
        service.reload_config()
        record = config_module.get_record(service.config, record_id)
        if record is None:
            return redirect(url_for("index"))
        return render_template("record_form.html", record=record, domains=[], error=None)

    @app.post("/records/<record_id>/edit")
    def edit_record(record_id: str):
        cfg = service.config
        record = config_module.get_record(cfg, record_id)
        if record is None:
            return redirect(url_for("index"))
        # The subdomain is deliberately not editable when editing (only when
        # creating) - that's why the form field is "disabled" and doesn't submit
        # any value at all. Additionally secured here server-side: a "name" that
        # might still be submitted anyway is ignored, the record's existing value
        # always applies.
        name = record.get("name", "")
        record_type = request.form.get("type", record["type"]).strip().upper()
        ttl = request.form.get("ttl", "300").strip()
        comment = request.form.get("comment", "").strip()

        if record_type not in ("A", "AAAA"):
            return redirect(url_for("edit_record_form", record_id=record_id))
        try:
            ttl_value = max(60, int(ttl))
        except ValueError:
            ttl_value = 300

        try:
            service.update_record_and_resync(record_id, name=name, record_type=record_type, ttl=ttl_value, comment=comment)
        except KeyError:
            pass
        return redirect(url_for("index"))

    @app.post("/records/<record_id>/delete")
    def delete_record(record_id: str):
        try:
            service.delete_record_remote_and_local(record_id)
        except (KeyError, DomainChiefError) as exc:
            logger.error("Could not delete record %s: %s", record_id, exc)
        return redirect(url_for("index"))

    @app.post("/records/<record_id>/toggle")
    def toggle_record(record_id: str):
        cfg = service.config
        record = config_module.get_record(cfg, record_id)
        if record:
            record["enabled"] = not record.get("enabled", True)
            config_module.save_config(cfg)
        return redirect(url_for("index"))

    @app.get("/logs")
    def logs():
        return render_template("logs.html", lines=service.log_buffer.tail(300))

    @app.get("/api/status")
    def api_status():
        service.reload_config()
        # last_run_at/record["last_sync_at"] are stored in a canonical, timezone-
        # independent form (see ddns._status_timestamp()) - format_ts() renders them
        # using the currently active timezone/format for display here, same as the
        # Jinja template does for the initial page load. Build new dicts for the
        # records rather than mutating service.config["records"] in place: those are
        # the SAME objects a later save_config() call persists to disk, so writing a
        # display-formatted string into them would corrupt the stored canonical value.
        records = [
            {**record, "last_sync_at": config_module.format_timestamp(record.get("last_sync_at"))}
            for record in service.config.get("records", [])
        ]
        return jsonify(
            {
                "last_ipv4": service.last_ipv4,
                "last_ipv6": service.last_ipv6,
                "last_run_at": config_module.format_timestamp(service.last_run_at),
                "last_run_error": service.last_run_error,
                "records": records,
            }
        )

    return app


def _env_token() -> str:
    return os.environ.get("DOMAINCHIEF_API_TOKEN", "")


def _env_timezone() -> str:
    # Deliberately NOT a live os.environ.get("TZ") read: config_module.apply_timezone()
    # also writes to os.environ["TZ"] to make a Web UI-selected timezone take effect
    # immediately, which would make a live read here see that self-set value and
    # wrongly (and permanently, until a restart) treat the timezone as fixed by the
    # deployment. config_module.env_timezone() returns a frozen snapshot of TZ taken
    # at process start, before anything else touches it.
    return config_module.env_timezone()


def _settings_context(cfg: dict) -> dict:
    """Shared context for the settings page - needed by several routes
    (GET /settings as well as the various POST routes, which re-render the
    page with an error/success message)."""
    return {
        "api_token_set": bool(cfg.get("api_token")),
        "team_id": cfg.get("team_id", ""),
        "check_interval": cfg.get("check_interval", 300),
        "api_token_from_env": bool(_env_token()),
        "webui_username": cfg.get("webui_username", ""),
        "webui_from_env": bool(_env_webui_credentials()),
        "timezone": cfg.get("timezone", ""),
        "timezone_from_env": bool(_env_timezone()),
        "available_timezones": config_module.AVAILABLE_TIMEZONES,
        "datetime_format": cfg.get("datetime_format", config_module.DEFAULT_DATETIME_FORMAT),
        "datetime_format_examples": config_module.format_examples(),
        "https_enabled": bool(cfg.get("https_enabled")),
        "https_cert_source": cfg.get("https_cert_source", "self_signed"),
        "https_cert_hostname": cfg.get("https_cert_hostname", ""),
        "https_port": https_port(),
        "self_signed_cert_info": tls_module.cert_summary(tls_module.SELF_SIGNED_CERT),
        "custom_cert_info": tls_module.cert_summary(tls_module.CUSTOM_CERT),
        "has_custom_cert": tls_module.CUSTOM_CERT.exists(),
        "totp_enabled": bool(cfg.get("totp_enabled")),
        "totp_recovery_codes_remaining": len(cfg.get("totp_recovery_codes", [])),
    }


def _verify_totp_or_recovery(service: DDNSService, code: str) -> bool:
    """Checks a submitted code against either the account's TOTP secret or
    its recovery codes (see app/totp.py) - used both for the second login
    step and for confirming a "disable 2FA" request. Persists+reloads the
    config only when a recovery code was actually consumed."""
    cfg = service.config
    if totp_module.verify_code(cfg.get("totp_secret", ""), code):
        return True
    if totp_module.consume_recovery_code(cfg, code):
        config_module.save_config(cfg)
        service.reload_config()
        return True
    return False


# Machine-readable error reasons (from HttpsServerManager.apply() and
# tls.save_custom_cert()) mapped to translation keys, so the Settings page
# can show a translated message instead of a raw internal code.
_HTTPS_ERROR_KEYS = {
    "no_custom_cert": "settings.https_err_no_custom_cert",
    "port_in_use": "settings.https_err_port_in_use",
    "cert_error": "settings.https_err_cert_error",
    "not_ready": "settings.https_err_cert_error",
    "invalid_cert": "settings.https_err_invalid_cert",
    "invalid_key": "settings.https_err_invalid_key",
    "key_mismatch": "settings.https_err_key_mismatch",
    "missing_files": "settings.https_err_missing_files",
}


def _render_settings(
    cfg: dict,
    *,
    webui_error: str | None = None,
    webui_saved: bool = False,
    https_error: str | None = None,
    https_saved: bool = False,
    totp_error: str | None = None,
    totp_saved: bool = False,
):
    """Shared render call for the settings page, used by every route that
    can change a setting - resolves a raw HTTPS error reason (see
    _HTTPS_ERROR_KEYS) to a translated message. totp_error is passed in
    already translated (there's only one possible reason, unlike HTTPS)."""
    https_error_message = g.t(_HTTPS_ERROR_KEYS.get(https_error, https_error)) if https_error else None
    return render_template(
        "settings.html",
        **_settings_context(cfg),
        webui_error=webui_error,
        webui_saved=webui_saved,
        https_error=https_error_message,
        https_saved=https_saved,
        totp_error=totp_error,
        totp_saved=totp_saved,
    )
