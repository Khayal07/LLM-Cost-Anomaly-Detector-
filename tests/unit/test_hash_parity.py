"""The SDK's hashing must stay byte-for-byte identical to the server's."""
from __future__ import annotations

from app.hashing import request_hash as server_hash
from sdk.hashing import request_hash as sdk_hash


def test_hash_parity_string():
    for prompt in ["Hello WORLD", "  spaced\tout  ", "loop signature", "a"]:
        assert sdk_hash(prompt) == server_hash(prompt)


def test_hash_parity_structured():
    messages = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]
    assert sdk_hash(messages) == server_hash(messages)
