"""The one spelling of a caller's identity.

A wallet address is hex, and hex letters have two cases, so one wallet has many
spellings: all lower case, all upper case, the EIP-55 checksum form, every mix,
with an upper- or lower-case ``x`` in the prefix. EIP-55 mixed case is a
checksum, not a second identity, and Sign-In with Ethereum proves control of the
key behind the address in any of them. A decision keyed on who is calling (a
conversation's owner, a sponsorship budget, a verdict the security core reaches
about a caller) would see one wallet as several callers if each spelling
reached it as sent.

So wherever the platform names a caller it uses one spelling: ``0x`` followed by
the forty hex digits in lower case, the spelling the sponsorship meter and the
wallet rate limiter already key on. That covers a session the gateway creates
or reads back, the wallet it links to an Apple user, an identity the operator
states, the identity a tool and a signature are metered against, and the
context the platform hands the security seam. Anything that is not a hex
address (``apple:<sub>``, a label, ``""``, a value that is not a string) is
returned exactly as given: a user id may distinguish ``A`` from ``a``, and
folding those together would merge two callers into one.

This is the only place the rule is written.
"""

from __future__ import annotations

import re
from typing import Any

_HEX_ADDRESS = re.compile(r"0[xX][0-9a-fA-F]{40}")


def is_wallet_address(value: Any) -> bool:
    """True when *value* is a 20-byte hex address in any spelling (surrounding
    whitespace aside)."""
    return isinstance(value, str) and _HEX_ADDRESS.fullmatch(value.strip()) is not None


def canonical_identity(value: Any) -> Any:
    """*value* in the one spelling the platform names a caller by.

    A hex address, in any case, with either ``0x`` or ``0X`` and with
    surrounding whitespace, becomes ``0x`` plus its digits in lower case.
    Anything else is returned unchanged.
    """
    if not is_wallet_address(value):
        return value
    return "0x" + value.strip()[2:].lower()
