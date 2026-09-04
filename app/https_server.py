"""
Optional in-process HTTPS listener, running alongside gunicorn's plain HTTP
server.

Why not just run a second gunicorn process bound to the HTTPS port? Because
DDNSService keeps its live state (log buffer, last sync status/IPs) purely
in memory (see app/ddns.py) - a second OS process would import app.main
again and end up with its own independent DDNSService instance, i.e. a
second background sync loop hitting the Domain Chief API on its own
schedule, and a dashboard whose status differs depending on which port you
happen to open it on. Instead, HttpsServerManager runs a small threaded WSGI
server (werkzeug's, the same one Flask's dev server is built on) as a daemon
thread inside the very same gunicorn worker process that already holds the
"real" Flask app and DDNSService - so both ports serve the exact same
in-memory state.

Started once at container boot (see app/main.py) and re-applied from
Settings whenever an HTTPS-related option changes (enable/disable, cert
source, hostname, importing/removing a custom certificate) - no container
restart required, analogous to how a timezone change already takes effect
immediately elsewhere in this app.
"""

from __future__ import annotations

import logging
import os
import threading

from werkzeug.serving import make_server

from . import tls

logger = logging.getLogger("etfmultiddns.https")

DEFAULT_HTTPS_PORT = 8443


def https_port() -> int:
    try:
        return int(os.environ.get("PORT_HTTPS", str(DEFAULT_HTTPS_PORT)))
    except ValueError:  # pragma: no cover - defensive, invalid env var
        return DEFAULT_HTTPS_PORT


class HttpsServerManager:
    """Starts/stops/restarts the HTTPS listener to match the current config.
    All state changes go through apply(), which is safe to call repeatedly
    (e.g. after every settings save) - it only actually restarts the
    listener when something relevant changed."""

    def __init__(self) -> None:
        self._app = None
        self._server = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._active_key: tuple | None = None
        self.last_error: str | None = None

    def set_app(self, wsgi_app) -> None:
        self._app = wsgi_app

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._server is not None

    def apply(self, cfg: dict, *, force: bool = False) -> str | None:
        """(Re)starts or stops the HTTPS listener to match the given config.
        Returns a short machine-readable error reason on failure (translated
        in the Web UI), or None on success."""
        with self._lock:
            if not cfg.get("https_enabled"):
                self._stop_locked()
                self.last_error = None
                return None

            if self._app is None:  # pragma: no cover - defensive, set_app() not called yet
                self.last_error = "not_ready"
                return self.last_error

            try:
                cert_path, key_path, error = tls.resolve_active_cert(cfg)
            except Exception:  # pragma: no cover - defensive
                logger.exception("Could not prepare the HTTPS certificate.")
                self._stop_locked()
                self.last_error = "cert_error"
                return self.last_error

            if error:
                self._stop_locked()
                self.last_error = error
                return error

            port = https_port()
            cert_mtime = cert_path.stat().st_mtime if cert_path.exists() else None
            key = (str(cert_path), str(key_path), port, cert_mtime)
            if not force and self._server is not None and self._active_key == key:
                self.last_error = None
                return None

            self._stop_locked()
            try:
                self._start_locked(port, cert_path, key_path)
            except OSError as exc:
                logger.error("Could not start the HTTPS listener on port %s: %s", port, exc)
                self.last_error = "port_in_use"
                return self.last_error

            self._active_key = key
            self.last_error = None
            return None

    def _start_locked(self, port: int, cert_path, key_path) -> None:
        server = make_server(
            "0.0.0.0",
            port,
            self._app,
            threaded=True,
            ssl_context=(str(cert_path), str(key_path)),
        )
        thread = threading.Thread(target=server.serve_forever, name="https-listener", daemon=True)
        thread.start()
        self._server = server
        self._thread = thread
        logger.info("HTTPS listener started on port %s.", port)

    def _stop_locked(self) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:  # pragma: no cover - defensive
                logger.exception("Error while stopping the HTTPS listener.")
            logger.info("HTTPS listener stopped.")
        self._server = None
        self._thread = None
        self._active_key = None
