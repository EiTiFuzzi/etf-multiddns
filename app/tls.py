"""
TLS certificate management for the optional HTTPS listener (see
app/https_server.py).

Two certificate sources are supported, selectable in Settings:
- "self_signed" (default once HTTPS is enabled): a self-signed certificate
  generated on demand and stored on the same persistent volume as
  config.json (config.CERT_DIR), so it survives container restarts. Browsers
  will show a security warning for it since it isn't issued by a trusted CA
  - that's expected and unavoidable for a self-signed certificate.
- "custom": a certificate + private key imported by the user (e.g. a
  Let's Encrypt certificate, or one issued by an internal/company CA).

Nothing here talks to the network or a CA - "self-signed" really just means
generated locally with the cryptography library.
"""

from __future__ import annotations

import datetime
import ipaddress
import logging
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from . import config as config_module

logger = logging.getLogger("etfmultiddns.tls")

SELF_SIGNED_CERT = config_module.CERT_DIR / "selfsigned.crt"
SELF_SIGNED_KEY = config_module.CERT_DIR / "selfsigned.key"
CUSTOM_CERT = config_module.CERT_DIR / "custom.crt"
CUSTOM_KEY = config_module.CERT_DIR / "custom.key"

# Self-signed certificates aren't trusted by any browser regardless of their
# validity period (they always trigger a warning), so a long lifetime is
# chosen purely for user convenience - it avoids needing to regenerate/
# re-accept the warning every year.
SELF_SIGNED_VALIDITY_DAYS = 3650


def _fallback_sans() -> list[x509.GeneralName]:
    return [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
        x509.IPAddress(ipaddress.ip_address("::1")),
    ]


def _hostname_general_name(hostname: str) -> x509.GeneralName | None:
    hostname = (hostname or "").strip()
    if not hostname:
        return None
    try:
        return x509.IPAddress(ipaddress.ip_address(hostname))
    except ValueError:
        return x509.DNSName(hostname)


def generate_self_signed(hostname: str, cert_path: Path = SELF_SIGNED_CERT, key_path: Path = SELF_SIGNED_KEY) -> None:
    """(Re)generates the self-signed certificate/key pair, with the given
    hostname (or IP) as the certificate's subject and included in the
    Subject Alternative Names - alongside localhost/127.0.0.1/::1, which are
    always included so the dashboard stays reachable that way too."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    common_name = (hostname or "").strip() or "etf-multiddns"
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])

    sans: list[x509.GeneralName] = []
    seen: set[str] = set()
    custom_san = _hostname_general_name(hostname)
    if custom_san is not None:
        sans.append(custom_san)
        seen.add(str(custom_san.value))
    for name in _fallback_sans():
        if str(name.value) not in seen:
            sans.append(name)
            seen.add(str(name.value))

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(hours=1))
        .not_valid_after(now + datetime.timedelta(days=SELF_SIGNED_VALIDITY_DAYS))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    cert_path.parent.mkdir(parents=True, exist_ok=True)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    try:
        key_path.chmod(0o600)
    except OSError:  # pragma: no cover - defensive, e.g. unsupported on some volumes
        pass
    logger.info("Generated a new self-signed certificate (CN=%s).", common_name)


def _load_cert(path: Path) -> x509.Certificate | None:
    try:
        return x509.load_pem_x509_certificate(path.read_bytes())
    except Exception:  # pragma: no cover - defensive (missing/corrupt file)
        return None


def _cert_is_currently_valid(cert: x509.Certificate) -> bool:
    not_after = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after.replace(tzinfo=datetime.timezone.utc)
    return not_after > datetime.datetime.now(datetime.timezone.utc)


def _cert_matches_hostname(cert: x509.Certificate, hostname: str) -> bool:
    hostname = (hostname or "").strip()
    if not hostname:
        # No specific hostname requested - any previously generated
        # self-signed certificate (generic or not) remains fine as-is.
        return True
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return False
    names = set(san.get_values_for_type(x509.DNSName)) | {str(ip) for ip in san.get_values_for_type(x509.IPAddress)}
    return hostname in names


def ensure_self_signed(hostname: str) -> tuple[Path, Path]:
    """Makes sure a valid self-signed certificate for the given hostname
    exists, (re)generating it if it's missing, expired, or was generated for
    a different hostname. Cheap to call on every request that needs it -
    parsing/verifying an existing certificate is fast."""
    cert = _load_cert(SELF_SIGNED_CERT) if SELF_SIGNED_CERT.exists() and SELF_SIGNED_KEY.exists() else None
    if cert is None or not _cert_is_currently_valid(cert) or not _cert_matches_hostname(cert, hostname):
        generate_self_signed(hostname)
    return SELF_SIGNED_CERT, SELF_SIGNED_KEY


def save_custom_cert(cert_pem: bytes, key_pem: bytes) -> None:
    """Validates and stores an imported certificate + private key. Raises
    ValueError (with a short machine-readable reason, translated in the Web
    UI) if the certificate/key are not valid PEM data or don't belong
    together. The private key must be unencrypted PEM (no passphrase)."""
    try:
        cert = x509.load_pem_x509_certificate(cert_pem)
    except Exception as exc:
        raise ValueError("invalid_cert") from exc
    try:
        key = serialization.load_pem_private_key(key_pem, password=None)
    except Exception as exc:
        raise ValueError("invalid_key") from exc

    cert_pub = cert.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    key_pub = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    if cert_pub != key_pub:
        raise ValueError("key_mismatch")

    CUSTOM_CERT.parent.mkdir(parents=True, exist_ok=True)
    CUSTOM_CERT.write_bytes(cert_pem)
    CUSTOM_KEY.write_bytes(key_pem)
    try:
        CUSTOM_KEY.chmod(0o600)
    except OSError:  # pragma: no cover - defensive
        pass
    logger.info("Imported a custom certificate.")


def remove_custom_cert() -> None:
    for path in (CUSTOM_CERT, CUSTOM_KEY):
        try:
            path.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - defensive
            pass
    logger.info("Removed the custom certificate.")


def resolve_active_cert(cfg: dict) -> tuple[Path | None, Path | None, str | None]:
    """Returns (cert_path, key_path, error) for the currently configured
    certificate source. error is a short machine-readable reason (translated
    in the Web UI) when no usable certificate is available."""
    if cfg.get("https_cert_source") == "custom":
        if CUSTOM_CERT.exists() and CUSTOM_KEY.exists():
            return CUSTOM_CERT, CUSTOM_KEY, None
        return None, None, "no_custom_cert"
    cert_path, key_path = ensure_self_signed(cfg.get("https_cert_hostname", ""))
    return cert_path, key_path, None


def cert_summary(path: Path) -> dict | None:
    """Human-readable info about a stored certificate, for display in
    Settings (subject, SANs, expiry, fingerprint). None if it doesn't exist
    or can't be parsed."""
    if not path.exists():
        return None
    cert = _load_cert(path)
    if cert is None:
        return None

    def _common_name(name: x509.Name) -> str:
        attrs = name.get_attributes_for_oid(NameOID.COMMON_NAME)
        return attrs[0].value if attrs else ""

    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        sans = list(san.get_values_for_type(x509.DNSName)) + [str(ip) for ip in san.get_values_for_type(x509.IPAddress)]
    except x509.ExtensionNotFound:
        sans = []

    not_after = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after.replace(tzinfo=datetime.timezone.utc)
    fingerprint = cert.fingerprint(hashes.SHA256()).hex()
    return {
        "common_name": _common_name(cert.subject),
        "issuer": _common_name(cert.issuer),
        "sans": sans,
        "valid_until": not_after.strftime("%Y-%m-%d"),
        "expired": not _cert_is_currently_valid(cert),
        "is_self_signed": cert.subject == cert.issuer,
        "fingerprint_sha256": ":".join(fingerprint[i : i + 2] for i in range(0, len(fingerprint), 2)),
    }
