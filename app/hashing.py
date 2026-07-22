"""Request-signature hashing used for loop detection.

A prompt is normalised (whitespace-collapsed, lower-cased) then hashed. Two
functionally identical calls therefore produce the same ``request_hash``, which
the loop detector counts within a short window.
"""
from __future__ import annotations

import hashlib
import json
import re

_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    return _WS.sub(" ", text.strip().lower())


def request_hash(prompt: object) -> str:
    """Hash a prompt into a short hex signature.

    Accepts a string or any JSON-serialisable structure (e.g. a messages list).
    """
    if isinstance(prompt, str):
        payload = normalize(prompt)
    else:
        payload = normalize(json.dumps(prompt, sort_keys=True, default=str))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
