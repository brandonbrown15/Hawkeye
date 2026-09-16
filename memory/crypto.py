"""Optional at-rest protection for Hawkeye memory records.

Uses a SHA-256 keystream (CTR-style) + HMAC integrity. This is intentional
stdlib-only crypto for a private Jetson SSD — see docs/security.md for the
upgrade path to Fernet/age when `cryptography` is installed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Any


MAGIC = b"HK1\0"


def memory_key() -> bytes | None:
    raw = os.environ.get("HAWKEYE_MEMORY_KEY", "").strip()
    if not raw:
        return None
    # Accept raw passphrase or hex; always stretch into 32 bytes.
    try:
        if all(c in "0123456789abcdefABCDEF" for c in raw) and len(raw) >= 32:
            material = bytes.fromhex(raw[:64])
        else:
            material = raw.encode("utf-8")
    except ValueError:
        material = raw.encode("utf-8")
    return hashlib.sha256(b"hawkeye-memory-v1:" + material).digest()


def encrypt_bytes(plaintext: bytes, key: bytes | None = None) -> bytes:
    key = key if key is not None else memory_key()
    if key is None:
        return plaintext
    nonce = os.urandom(16)
    stream = _keystream(key, nonce, len(plaintext))
    cipher = bytes(a ^ b for a, b in zip(plaintext, stream))
    tag = hmac.new(key, MAGIC + nonce + cipher, hashlib.sha256).digest()
    return MAGIC + nonce + tag + cipher


def decrypt_bytes(blob: bytes, key: bytes | None = None) -> bytes:
    key = key if key is not None else memory_key()
    if key is None or not blob.startswith(MAGIC):
        return blob
    if len(blob) < 4 + 16 + 32:
        raise ValueError("truncated memory blob")
    nonce = blob[4:20]
    tag = blob[20:52]
    cipher = blob[52:]
    expect = hmac.new(key, MAGIC + nonce + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expect):
        raise ValueError("memory HMAC mismatch — wrong HAWKEYE_MEMORY_KEY?")
    stream = _keystream(key, nonce, len(cipher))
    return bytes(a ^ b for a, b in zip(cipher, stream))


def encode_record(obj: dict[str, Any], key: bytes | None = None) -> str:
    import json

    raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    key = key if key is not None else memory_key()
    if key is None:
        return raw.decode("utf-8")
    return "enc:" + base64.urlsafe_b64encode(encrypt_bytes(raw, key)).decode("ascii")


def decode_record(line: str, key: bytes | None = None) -> dict[str, Any]:
    import json

    line = line.strip()
    if not line:
        raise ValueError("empty memory line")
    key = key if key is not None else memory_key()
    if line.startswith("enc:"):
        blob = base64.urlsafe_b64decode(line[4:].encode("ascii"))
        raw = decrypt_bytes(blob, key)
        data = json.loads(raw.decode("utf-8"))
    else:
        data = json.loads(line)
    if not isinstance(data, dict):
        raise ValueError("memory record must be an object")
    return data


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])
