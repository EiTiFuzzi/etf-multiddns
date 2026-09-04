"""
Container entry point: starts the DDNS sync loop in the background and
serves the Web UI at the same time.

This module is imported exactly once per gunicorn worker process (see the
Dockerfile CMD, "--workers 1"), so the module-level objects below (service,
app, https_manager) are singletons for the lifetime of the container. That
matters for HTTPS: https_manager runs its listener as a thread inside this
very process instead of a second process, precisely so it shares the same
DDNSService instance/in-memory state as the plain HTTP server gunicorn
serves - see app/https_server.py for the full reasoning.
"""

from __future__ import annotations

import logging
import os
import sys

from .ddns import DDNSService
from .https_server import HttpsServerManager
from .web.app import create_app

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    stream=sys.stdout,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

service = DDNSService()
service.start()

https_manager = HttpsServerManager()
app = create_app(service, https_manager)
https_manager.set_app(app)
https_manager.apply(service.config)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
