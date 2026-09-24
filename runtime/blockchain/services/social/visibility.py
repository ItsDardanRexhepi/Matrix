"""Whether an item may be shown to everyone: the platform's one reading.

Three surfaces decide whether something is public, and they used to decide it
with two different functions. `SocialService` filtered its own feed with
`_is_public_item`, and the dispatcher's feed ingest and the HTTP ripple used
`service_dispatcher.declares_non_public`, whose docstring called it
"SocialService's reading" although it was not. The two disagreed on inputs a
caller writes:

  * ``{"visibility": " public"}`` — the dispatcher stripped the spaces and
    published the share to the public feed; SocialService did not strip, and
    its own feed hid the same item.
  * ``{"visibility": None}`` inside ``proof_data`` — the dispatcher skipped
    the null and published; SocialService read it as the word "none" and hid
    the item.
  * a top-level ``"visibility": "public"`` beside a ``proof_data`` that says
    ``"followers"`` — SocialService read only the top level and showed it.

Each disagreement published, or showed, an item that another surface treated
as private. So both surfaces now call this function, and it takes the
strictest of the readings:

  * a ``visibility`` that is present, at the top of an item or inside its
    ``proof_data``, must be the word "public" in any letter case, with nothing
    around it; anything else, an explicit null included, is not public;
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
