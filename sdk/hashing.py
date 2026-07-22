"""Request-signature hashing (standalone copy for the SDK).

Kept byte-for-byte compatible with ``app.hashing`` so a hash computed client-side
matches one the server would compute from the same prompt. A parity test guards
against drift. Duplicated here so the ``sdk/`` package only depends on ``httpx``
and can be vendored into any application on its own.
"""
from __future__ import annotations

import hashlib
import json
import re

_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    return _WS.sub(" ", text.strip().lower())


def request_hash(prompt: object) -> str:
    if isinstance(prompt, str):
        payload = normalize(prompt)
    else:
        payload = normalize(json.dumps(prompt, sort_keys=True, default=str))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
