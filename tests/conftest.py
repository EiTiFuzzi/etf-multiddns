"""Shared test setup: point the app at a throw-away config folder BEFORE any
app module is imported (app.config reads CONFIG_PATH once, at import time)."""

import os
import re
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="etf-multiddns-tests-")
os.environ["CONFIG_PATH"] = str(Path(_TMP) / "config.json")
for _name in ("WEBUI_USERNAME", "WEBUI_PASSWORD", "DOMAINCHIEF_API_TOKEN", "CLOUDFLARE_API_TOKEN", "TZ"):
    os.environ.pop(_name, None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from app import config as config_module  # noqa: E402
from app.ddns import DDNSService  # noqa: E402
from app.https_server import HttpsServerManager  # noqa: E402
from app.web.app import create_app  # noqa: E402

PASSWORD = "correct horse battery"


def token_from(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html) or re.search(r'name="csrf-token" content="([^"]+)"', html)
    assert match, "no CSRF token found in page"
    return match.group(1)


@pytest.fixture()
def service():
    # Fresh config per test; the sync loop is deliberately NOT started.
    for leftover in Path(config_module.CONFIG_PATH).parent.glob("config.json*"):
        leftover.unlink()
    return DDNSService()


@pytest.fixture()
def app(service):
    flask_app = create_app(service, HttpsServerManager())
    flask_app.testing = False  # real error handling: a crash must show up as HTTP 500
    return flask_app


@pytest.fixture()
def anon(app):
    return app.test_client()


@pytest.fixture()
def admin(app, service):
    """A test client that has completed the setup wizard (and is logged in)."""
    client = app.test_client()
    page = client.get("/setup")
    resp = client.post(
        "/setup",
        data={"username": "admin", "password": PASSWORD, "password2": PASSWORD, "csrf_token": token_from(page.get_data(as_text=True))},
    )
    assert resp.status_code == 302
    return client
