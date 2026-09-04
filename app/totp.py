"""
Optional two-factor authentication (TOTP, RFC 6238) on top of the existing
username/password login.

When enabled (see Settings), a correct username+password no longer logs the
user in directly - it only grants a temporary "awaiting 2FA" session state
(see app/web/app.py: login()/login_2fa()) until a valid 6-digit code from an
authenticator app, or an unused recovery code, is also provided.

Recovery codes exist so a lost/reset authenticator doesn't permanently lock
the user out - they're shown once (right after enabling 2FA, or after
regenerating them) and stored only as hashes (werkzeug.security, the same
approach already used for the login password), consumed (removed) on use.
"""

from __future__ import annotations

import io
import secrets

import pyotp
import qrcode
import qrcode.image.svg
from werkzeug.security import check_password_hash, generate_password_hash

RECOVERY_CODE_COUNT = 8


def generate_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, username: str, issuer: str = "ETF-MultiDDNS") -> str:
    """otpauth:// URI encoded into the setup QR code - this is what makes an
    authenticator app show "ETF-MultiDDNS (username)" instead of a bare
    secret."""
    return pyotp.TOTP(secret).provisioning_uri(name=username or "admin", issuer_name=issuer)


def qr_code_svg(uri: str) -> str:
    """Renders the given otpauth:// URI as an inline SVG QR code. Uses
    qrcode's pure-Python SVG path backend deliberately (instead of the PNG
    backend) - that one needs no Pillow/pypng dependency, keeping the image
    consistent with this project's existing preference for inline SVGs."""
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=6, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")


def verify_code(secret: str, code: str) -> bool:
    """Checks a 6-digit TOTP code against the given secret, allowing one
    30-second step of clock drift in either direction."""
    code = (code or "").strip()
    if not secret or not code.isdigit() or len(code) != 6:
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    """Plaintext recovery codes, e.g. "AB12-CD34" - only ever returned here
    to be shown once to the user; the caller is responsible for hashing them
    (hash_recovery_codes) before storing."""
    codes = []
    for _ in range(count):
        raw = secrets.token_hex(4).upper()  # 8 hex chars
        codes.append(f"{raw[:4]}-{raw[4:]}")
    return codes


def hash_recovery_codes(codes: list[str]) -> list[str]:
    return [generate_password_hash(_normalize_recovery_code(c)) for c in codes]


def _normalize_recovery_code(code: str) -> str:
    return (code or "").replace("-", "").replace(" ", "").strip().upper()


def consume_recovery_code(cfg: dict, code: str) -> bool:
    """Checks the given code against the stored (hashed) recovery codes and,
    if it matches, removes it from cfg["totp_recovery_codes"] in place (a
    recovery code only works once). Returns whether it matched - the caller
    is responsible for persisting cfg (config.save_config) when it does."""
    normalized = _normalize_recovery_code(code)
    if not normalized:
        return False
    hashes = cfg.get("totp_recovery_codes", [])
    for i, stored_hash in enumerate(hashes):
        if check_password_hash(stored_hash, normalized):
            del hashes[i]
            return True
    return False
