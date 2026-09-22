"""Constant-time equality for a secret a caller presented — without the 500.

``hmac.compare_digest`` is the right primitive and the wrong interface for a
value that arrived over the wire: it raises ``TypeError`` when either side is a
``str`` holding a non-ASCII character, and when the two sides are not both
``str`` or both bytes-like. Every credential this platform compares in
constant time is written by a caller — the operator key in an ``Authorization``
header or an ``api_key`` query, a QR code's ``verification_hash``, a loyalty
proof's fields — so the bare call turned a bad input into a 500 at the auth
wall (measured: ``Authorization: Bearer éé`` answered 500 on every key-gated
route, and on ``/health`` from the rate limiter), and would have done the same
on the first route to reach ``verify_scan``.

``digests_equal`` answers False for anything that is not a pair of strings or a
pair of bytes-likes, and compares strings as their UTF-8 bytes — still
constant-time in the content, and a configured key with a non-ASCII character
in it now works instead of 500ing on its own operator. Like ``compare_digest``,
it does not hide the LENGTH of the expected value; nothing here did.
"""

from __future__ import annotations

import hmac

_BYTES_LIKE = (bytes, bytearray, memoryview)


def digests_equal(presented: object, expected: object) -> bool:
    """``presented == expected`` in constant time, or False — never a raise."""
    if isinstance(presented, str) and isinstance(expected, str):
        return hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))
    if isinstance(presented, _BYTES_LIKE) and isinstance(expected, _BYTES_LIKE):
        return hmac.compare_digest(bytes(presented), bytes(expected))
    return False


__all__ = ["digests_equal"]
