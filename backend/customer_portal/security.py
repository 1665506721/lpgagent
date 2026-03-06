import base64
import hashlib
import os

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _derive_fernet_key(seed: str) -> bytes:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _resolve_fernet_key() -> bytes:
    key = (os.getenv("PORTAL_PROVIDER_SECRET") or "").strip()
    if key:
        key_bytes = key.encode("utf-8")
        try:
            Fernet(key_bytes)
        except Exception as exc:
            raise ImproperlyConfigured("PORTAL_PROVIDER_SECRET is invalid for Fernet") from exc
        return key_bytes

    if settings.DEBUG:
        return _derive_fernet_key(settings.SECRET_KEY or "dev-secret-key")

    raise ImproperlyConfigured("PORTAL_PROVIDER_SECRET is required when DEBUG=False")


def get_fernet() -> Fernet:
    return Fernet(_resolve_fernet_key())


def encrypt_api_key(plain: str) -> str:
    value = (plain or "").strip()
    if not value:
        raise ValueError("api key is empty")
    return get_fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_api_key(cipher: str) -> str:
    value = (cipher or "").strip()
    if not value:
        raise ValueError("cipher is empty")
    return get_fernet().decrypt(value.encode("utf-8")).decode("utf-8")


def mask_api_key(plain: str) -> str:
    value = (plain or "").strip()
    if not value:
        return ""
    if len(value) <= 8:
        return f"{value[:2]}****{value[-2:]}" if len(value) >= 4 else "****"
    return f"{value[:4]}****{value[-4:]}"
