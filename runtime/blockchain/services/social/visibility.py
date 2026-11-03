"""Whether an item may be shown to everyone: the platform's one reading.

Three surfaces decide whether something is public, and each of them calls this
function:

  * `SocialService._is_public_item`, which filters SocialService's own feed;
  * `SocialFeedEngine.ingest`, the door of the platform's public,
    unauthenticated feed (/social/feed), to which the service dispatcher
    publishes every settled state-modifying action, `send_message` (that is,
    `social.share_proof`) included;
  * `ServiceRoutes._maybe_ripple`, which announces an action to every
    /api/v1/events/stream subscriber.

The second and third used to read nothing at all: a proof share whose
visibility was "followers" was stored on the public feed with its proof_data
and rippled with its actor, while SocialService's own feed hid it. One function
means an item one surface hides is hidden by all three. It takes the strictest
reading, because a caller writes these values:

  * a ``visibility`` that is present, at the top of an item or inside its
    ``proof_data``, must be the word "public" in any letter case, with nothing
    around it; anything else — ``" public"``, an explicit null, "followers" —
    is not public, and a top-level "public" does not outrank a ``proof_data``
    that says otherwise;
  * an explicit ``private`` or ``is_private`` flag that is set (anything but
    absent, ``None`` or ``False``) is not public;
  * a ``proof_data`` that is present and is not a mapping cannot be read, and
    is not public;
  * an item that says none of this is public: a plain post carries no
    visibility, and that has always meant public.
"""

from __future__ import annotations

from typing import Any

_PRIVATE_FLAGS = ("private", "is_private")


def _says_public(value: Any) -> bool:
    return isinstance(value, str) and value.lower() == "public"


def _node_is_public(node: dict) -> bool:
    if "visibility" in node and not _says_public(node["visibility"]):
        return False
    return all(node.get(flag) in (None, False) for flag in _PRIVATE_FLAGS)


def is_public(*sources: Any) -> bool:
    """True only when none of *sources* says it is not for everyone.

    Each source that is a mapping is read at its top level and inside its
    ``proof_data``; a source that is not a mapping says nothing. See the module
    docstring for the rules and why there is one function for them.
    """
    for source in sources:
        if not isinstance(source, dict):
            continue
        if not _node_is_public(source):
            return False
        proof_data = source.get("proof_data")
        if proof_data is None:
            continue
        if not isinstance(proof_data, dict) or not _node_is_public(proof_data):
            return False
    return True
