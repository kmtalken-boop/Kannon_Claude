"""Ed25519 request signing for the Polymarket US API.

Keys are generated at polymarket.us/developer.  The portal gives you:
  key_id     — UUID identifying the key
  secret_key — Base64-encoded 32-byte Ed25519 private key (shown once; save it)

Signature message: {timestamp_ms}{METHOD}{path}
Headers sent on every authenticated request:
  X-PM-Access-Key   — key_id
  X-PM-Timestamp    — milliseconds since epoch (must be NTP-synced)
  X-PM-Signature    — base64(Ed25519.sign(message))
  Content-Type      — application/json
"""
from __future__ import annotations
import base64
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class PolymarketAuth:
    def __init__(self, key_id: str, secret_key: str):
        """
        Args:
            key_id: UUID from the developer portal.
            secret_key: Base64-encoded 32-byte Ed25519 private key.
        """
        self._key_id = key_id
        raw = base64.b64decode(secret_key)
        # Some encodings include the public key appended (64 bytes total).
        self._private_key = Ed25519PrivateKey.from_private_bytes(raw[:32])

    def sign_request(self, method: str, path: str) -> dict[str, str]:
        timestamp_ms = str(int(time.time() * 1000))
        message = f"{timestamp_ms}{method.upper()}{path}".encode()
        signature = self._private_key.sign(message)
        return {
            "X-PM-Access-Key": self._key_id,
            "X-PM-Timestamp": timestamp_ms,
            "X-PM-Signature": base64.b64encode(signature).decode(),
            "Content-Type": "application/json",
        }

    def ws_headers(self, path: str) -> dict[str, str]:
        """Auth headers for WebSocket upgrade requests."""
        return self.sign_request("GET", path)
