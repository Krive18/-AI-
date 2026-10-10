import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class ProviderSecretCipher:
    """AES-GCM envelope for provider credentials; plaintext never leaves this boundary."""

    def __init__(self, encoded_key: str) -> None:
        try:
            key = base64.urlsafe_b64decode(encoded_key.encode())
        except ValueError as error:
            raise ValueError(
                "provider encryption key must be URL-safe base64"
            ) from error
        if len(key) != 32:
            raise ValueError("provider encryption key must decode to 32 bytes")
        self._cipher = AESGCM(key)

    def encrypt(self, value: str) -> bytes:
        nonce = os.urandom(12)
        return nonce + self._cipher.encrypt(nonce, value.encode(), None)

    def decrypt(self, value: bytes) -> str:
        if len(value) < 13:
            raise ValueError("encrypted provider secret is malformed")
        return self._cipher.decrypt(value[:12], value[12:], None).decode()


def masked_key(value: str) -> str:
    return "*" * max(0, len(value) - 4) + value[-4:]
