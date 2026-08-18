"""Fail-closed handling for encrypted database credentials.

The platform's ``ConnectionConfigCrypto`` format is intentionally kept
compatible: Base64(12-byte IV || AES-GCM ciphertext+16-byte tag).  Ciphertext
may be persisted in task files, but plaintext must only exist in memory while
constructing a database connection.
"""

from __future__ import annotations

import base64
import binascii
import logging
import os
from typing import Any

from .config import load_config

try:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:  # pragma: no cover - exercised as a deployment dependency check
    InvalidTag = Exception
    AESGCM = None


LOGGER = logging.getLogger("ontology-agent.credentials")
GCM_IV_BYTES = 12
GCM_TAG_BYTES = 16
MIN_ENCRYPTED_PAYLOAD_BYTES = GCM_IV_BYTES + GCM_TAG_BYTES
CRYPTO_SECRET_ENV_NAMES = (
    "ONTOLOGY_CRYPTO_SECRET",
    "ONTOLOGY_CRYPTO_SECRET_BASE64",
    "ontology.crypto.secret",
)
CRYPTO_SECRET_CONFIG_NAMES = (
    "ontology.crypto.secret",
    "ontology_crypto_secret",
    "ontologyCryptoSecret",
)


class CredentialCryptoError(RuntimeError):
    """Base class for safe, user-facing credential crypto failures."""

    code = "DATABASE_CREDENTIAL_DECRYPTION_FAILED"


class CredentialCryptoConfigurationError(CredentialCryptoError):
    """The agent cannot process encrypted credentials in this deployment."""

    code = "ONTOLOGY_CRYPTO_SECRET_NOT_CONFIGURED"


class CredentialDecryptionError(CredentialCryptoError):
    """An encrypted credential could not be authenticated and decrypted."""


def _configured_secret_values() -> list[Any]:
    values = [os.environ.get(name) for name in CRYPTO_SECRET_ENV_NAMES]
    try:
        config = load_config()
    except Exception:
        config = {}
    if isinstance(config, dict):
        values.extend(config.get(name) for name in CRYPTO_SECRET_CONFIG_NAMES)
    return [value for value in values if value is not None and str(value).strip()]


def load_crypto_key() -> bytes | None:
    """Return the valid AES-256 key without exposing its value."""
    for value in _configured_secret_values():
        try:
            key = base64.b64decode(str(value).strip(), validate=True)
        except (ValueError, binascii.Error):
            continue
        if len(key) == 32:
            return key
    return None


def crypto_status() -> dict[str, Any]:
    """Return non-secret startup status suitable for diagnostics/UI metadata."""
    configured_values = _configured_secret_values()
    key = load_crypto_key()
    return {
        "configured": bool(key),
        "hasConfiguredValue": bool(configured_values),
        "algorithm": "AES-256-GCM",
        "mode": "ready" if key else "degraded",
    }


def require_crypto_key() -> bytes:
    key = load_crypto_key()
    if key:
        return key
    LOGGER.error(
        "ONTOLOGY_CRYPTO_SECRET_NOT_CONFIGURED: encrypted database credentials are disabled"
    )
    raise CredentialCryptoConfigurationError(
        "ontology.crypto.secret is not configured or is invalid; encrypted database credentials are disabled"
    )


def startup_crypto_check() -> dict[str, Any]:
    """Check configuration at process startup without taking the service down.

    The service enters an explicit degraded mode so plaintext-only legacy tasks
    remain operable, while encrypted credentials fail closed at their boundary.
    """
    status = crypto_status()
    if not status["configured"]:
        LOGGER.error(
            "ONTOLOGY_CRYPTO_SECRET_NOT_CONFIGURED: service started in degraded credential mode"
        )
    return status


def _decode_encrypted_payload(value: object) -> bytes | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        payload = base64.b64decode(text, validate=True)
    except (ValueError, binascii.Error):
        return None
    # The Java producer has no textual prefix; this is the stable structural
    # discriminator available for backwards-compatible plaintext support.
    return payload if len(payload) >= MIN_ENCRYPTED_PAYLOAD_BYTES else None


def is_encrypted_credential(value: object, explicitly_encrypted: object = None) -> bool:
    if explicitly_encrypted is not None:
        if isinstance(explicitly_encrypted, str):
            return explicitly_encrypted.strip().lower() not in {"", "0", "false", "no", "n"}
        return bool(explicitly_encrypted)
    return _decode_encrypted_payload(value) is not None


def decrypt_connection_credential(
    value: object,
    explicitly_encrypted: object = None,
) -> str:
    """Decrypt an encrypted credential or return explicitly/plain legacy text.

    Once a value matches the platform encrypted format, every failure is
    terminal.  In particular, ciphertext is never returned as a password.
    """
    text = str(value or "")
    if not text or text in {"********", "***"}:
        return text
    encrypted = is_encrypted_credential(text, explicitly_encrypted)
    if not encrypted:
        return text

    payload = _decode_encrypted_payload(text)
    if payload is None:
        LOGGER.error("DATABASE_CREDENTIAL_DECRYPTION_FAILED reason=invalid_ciphertext_format")
        raise CredentialDecryptionError(
            "DATABASE_CREDENTIAL_DECRYPTION_FAILED: encrypted database credential has an invalid format"
        )
    try:
        key = require_crypto_key()
        if AESGCM is None:
            raise RuntimeError("cryptography dependency is unavailable")
        plain = AESGCM(key).decrypt(payload[:GCM_IV_BYTES], payload[GCM_IV_BYTES:], None)
        return plain.decode("utf-8")
    except CredentialCryptoConfigurationError:
        LOGGER.error("DATABASE_CREDENTIAL_DECRYPTION_FAILED reason=crypto_secret_missing")
        raise CredentialDecryptionError(
            "DATABASE_CREDENTIAL_DECRYPTION_FAILED: ontology.crypto.secret is not configured"
        ) from None
    except Exception as exc:
        # Do not include exception text: some crypto providers can expose
        # implementation details, and no credential material belongs in logs.
        LOGGER.error("DATABASE_CREDENTIAL_DECRYPTION_FAILED reason=authentication_or_decode_failure")
        raise CredentialDecryptionError(
            "DATABASE_CREDENTIAL_DECRYPTION_FAILED: encrypted database credential could not be decrypted"
        ) from None
