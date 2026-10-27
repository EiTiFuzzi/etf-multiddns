"""Regression tests for the findings of the 2026-10-27 security audit
(see CVE-AUDIT.md). Run with:  pip install pytest && pytest"""

import re
import stat

import pytest

from app import config as config_module
from app import totp as totp_module
from app.throttle import FailureThrottle

from conftest import PASSWORD, token_from

# --------------------------------------------------------------------------
# F1: CSRF
# --------------------------------------------------------------------------


def _post_rules(app):
    for rule in app.url_map.iter_rules():
        if "POST" in rule.methods and rule.endpoint != "static":
            path = re.sub(r"<[^>]+>", "x", rule.rule)
            yield rule.endpoint, path


def test_every_post_route_rejects_requests_without_token(app, admin):
    rules = list(_post_rules(app))
    assert len(rules) >= 15, "expected to find all POST routes"
    for endpoint, path in rules:
        resp = admin.post(path, data={"anything": "x"})
        assert resp.status_code == 400, f"{endpoint} ({path}) accepted a POST without CSRF token"


def test_wrong_token_is_rejected_and_header_token_is_accepted(admin):
    assert admin.post("/sync-now", data={"csrf_token": "forged"}).status_code == 400
    page = admin.get("/settings")
    token = token_from(page.get_data(as_text=True))
    # JSON endpoints use the header variant; no API token configured -> still a normal JSON answer, not 400
    resp = admin.post("/settings/test", headers={"X-CSRF-Token": token})
    assert resp.status_code == 200 and resp.get_json()["ok"] is False
    # forged header -> JSON 400
    resp = admin.post("/settings/test", headers={"X-CSRF-Token": "forged"})
    assert resp.status_code == 400 and resp.get_json()["ok"] is False


def test_cross_site_webui_takeover_is_blocked(admin, service):
    before = service.config["webui_username"]
    resp = admin.post(
        "/settings/webui",
        data={"username": "attacker", "password": "pwned12345", "password2": "pwned12345"},
        headers={"Origin": "https://evil.example", "Referer": "https://evil.example/x"},
    )
    assert resp.status_code == 400
    service.reload_config()
    assert service.config["webui_username"] == before


def test_all_rendered_post_forms_carry_a_token(admin, anon, service, monkeypatch):
    monkeypatch.setattr(service, "find_importable_records", lambda: ([], {}, None, None))
    pages = [(admin, p) for p in ("/", "/settings", "/records/new", "/records/import", "/logs")]
    pages += [(anon, "/login")]
    checked = 0
    for client, path in pages:
        html = client.get(path).get_data(as_text=True)
        for form in re.finditer(r"<form\b[^>]*\bmethod=\"post\"[^>]*>(.*?)</form>", html, re.S | re.I):
            assert 'name="csrf_token"' in form.group(1), f"form without CSRF token on {path}"
            checked += 1
    assert checked >= 8


def test_session_cookie_is_samesite_lax_and_httponly(anon):
    cookie = anon.get("/setup").headers.get("Set-Cookie", "")  # unconfigured instance: wizard page
    assert "SameSite=Lax" in cookie and "HttpOnly" in cookie


# --------------------------------------------------------------------------
# F2: open redirect
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "target",
    ["https://evil.example/phish", "//evil.example", "/\\evil.example", "\\\\evil.example", "/\t/evil.example", "javascript:alert(1)", "evil.example", "http:evil.example"],
)
def test_language_switch_does_not_redirect_off_site(anon, target):
    resp = anon.get("/lang/en", query_string={"next": target})
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"


def test_language_switch_keeps_local_paths(anon):
    resp = anon.get("/lang/en", query_string={"next": "/settings"})
    assert resp.headers["Location"] == "/settings"
    assert "lang=en" in resp.headers.get("Set-Cookie", "")


# --------------------------------------------------------------------------
# F3: brute force
# --------------------------------------------------------------------------


def _login(client, username, password):
    token = token_from(client.get("/login").get_data(as_text=True))
    return client.post("/login", data={"username": username, "password": password, "csrf_token": token})


def test_login_is_blocked_after_repeated_failures(anon, admin):
    codes = [_login(anon, "admin", f"wrong-{i}").status_code for i in range(8)]
    assert codes == [200] * 8
    blocked = _login(anon, "admin", "wrong-again")
    assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) > 0
    # even the CORRECT password is refused while blocked
    assert _login(anon, "admin", PASSWORD).status_code == 429


def test_successful_login_resets_the_counter(app, admin):
    client = app.test_client()
    for i in range(5):
        _login(client, "admin", f"wrong-{i}")
    assert _login(client, "admin", PASSWORD).status_code == 302
    client2 = app.test_client()
    for i in range(7):
        assert _login(client2, "admin", f"wrong-{i}").status_code == 200


def test_2fa_codes_are_rate_limited(app, service, admin):
    secret = totp_module.generate_secret()
    cfg = service.config
    cfg.update(totp_enabled=True, totp_secret=secret, totp_recovery_codes=[])
    config_module.save_config(cfg)
    service.reload_config()

    client = app.test_client()
    assert _login(client, "admin", PASSWORD).headers["Location"].endswith("/login/2fa")
    statuses = []
    for _ in range(7):
        token = token_from(client.get("/login/2fa").get_data(as_text=True))
        statuses.append(client.post("/login/2fa", data={"code": "000000", "csrf_token": token}).status_code)
    assert statuses[:5] == [200] * 5 and statuses[5:] == [429, 429]
    # a correct code is refused too while blocked
    token = token_from(client.get("/login/2fa").get_data(as_text=True))
    import pyotp

    resp = client.post("/login/2fa", data={"code": pyotp.TOTP(secret).now(), "csrf_token": token})
    assert resp.status_code == 429


def test_throttle_window_expiry_and_reset():
    t = FailureThrottle(3, 60)
    for i in range(3):
        t.record_failure("ip", now=100 + i)
    assert t.retry_after("ip", now=103) > 0
    assert t.retry_after("other", now=103) == 0
    assert t.retry_after("ip", now=100 + 61) == 0  # oldest failure aged out of the window
    t.record_failure("ip", now=200)
    t.reset("ip")
    assert t.retry_after("ip", now=200) == 0


def test_throttle_memory_is_bounded():
    t = FailureThrottle(3, 60, max_keys=50)
    for i in range(500):
        t.record_failure(f"ip-{i}", now=1000 + i * 0.001)
    assert len(t._failures) <= 50


# --------------------------------------------------------------------------
# F4: non-ASCII credentials
# --------------------------------------------------------------------------


def test_non_ascii_login_does_not_crash(anon, admin):
    assert _login(anon, "Jürgen", "pässwörd").status_code == 200


def test_non_ascii_username_can_be_used_to_log_in(app):
    client = app.test_client()
    token = token_from(client.get("/setup").get_data(as_text=True))
    client.post("/setup", data={"username": "Jürgen", "password": PASSWORD, "password2": PASSWORD, "csrf_token": token})
    other = app.test_client()
    assert _login(other, "Jürgen", PASSWORD).status_code == 302


# --------------------------------------------------------------------------
# F1b: credentials change needs the current password
# --------------------------------------------------------------------------


def _change(admin, **fields):
    token = token_from(admin.get("/settings").get_data(as_text=True))
    return admin.post("/settings/webui", data={"csrf_token": token, **fields})


def test_credentials_change_requires_current_password(admin, service):
    resp = _change(admin, username="attacker", password="pwned12345", password2="pwned12345")
    assert resp.status_code == 200
    service.reload_config()
    assert service.config["webui_username"] == "admin"

    resp = _change(admin, username="attacker", password="pwned12345", password2="pwned12345", current_password="wrong")
    service.reload_config()
    assert service.config["webui_username"] == "admin"

    _change(admin, username="newname", password="", password2="", current_password=PASSWORD)
    service.reload_config()
    assert service.config["webui_username"] == "newname"


# --------------------------------------------------------------------------
# F6: file permissions
# --------------------------------------------------------------------------


def _mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def test_saved_config_is_owner_only(service):
    service.reload_config()
    config_module.save_config(service.config)
    assert _mode(config_module.CONFIG_PATH) == 0o600


def test_legacy_world_readable_config_is_tightened_on_load(service):
    config_module.save_config(service.config)
    config_module.CONFIG_PATH.chmod(0o644)
    config_module.load_config()
    assert _mode(config_module.CONFIG_PATH) == 0o600


def test_private_key_files_are_owner_only(tmp_path):
    from app import tls

    cert, key = tmp_path / "c.pem", tmp_path / "k.pem"
    tls.generate_self_signed("example.test", cert_path=cert, key_path=key)
    assert _mode(key) == 0o600
