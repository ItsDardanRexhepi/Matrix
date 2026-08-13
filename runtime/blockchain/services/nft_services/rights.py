"""
RightsManagement — manage intellectual property rights for NFTs.

Supports four rights types:
  - display: right to publicly display the artwork
  - commercial: right to use in commercial products
  - derivative: right to create derivative works
  - physical: right to produce physical reproductions

Rights can be transferred independently and are tracked per-token.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# Valid rights types
RIGHTS_TYPES: set[str] = {"display", "commercial", "derivative", "physical"}

# Default rights granted on mint
_DEFAULT_RIGHTS: dict[str, bool] = {
    "display": True,
    "commercial": False,
    "derivative": False,
    "physical": False,
}


class RightsManagement:
    """Manage IP rights for NFTs on the 0pnMatrx platform.

    Parameters
    ----------
    config : dict
        Platform config.  Reads:
        - ``nft.rights.default_rights`` — override default rights granted
        - ``nft.rights.transfer_requires_creator_approval`` (default False)
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        rights_cfg = config.get("nft", {}).get("rights", {})

        self._default_rights: dict[str, bool] = {
            **_DEFAULT_RIGHTS,
            **rights_cfg.get("default_rights", {}),
        }
        self._require_approval: bool = rights_cfg.get(
            "transfer_requires_creator_approval", False
        )

        # Storage: {collection:token_id: rights_record}
        self._rights: dict[str, dict[str, Any]] = {}
        # Transfer history
        self._transfer_history: dict[str, list[dict[str, Any]]] = {}

    async def set_rights(
        self,
        collection: str,
        token_id: int,
        rights: dict[str, Any],
        caller_identity: str = "",
        caller_source: str = "",
    ) -> dict[str, Any]:
        """Set or update IP rights for a token.

        Parameters
        ----------
        collection : str
            Collection contract address.
        token_id : int
            Token ID.
        rights : dict
            Rights configuration. Keys from RIGHTS_TYPES, values are
            dicts with ``granted`` (bool), ``holder`` (str),
            ``expires_at`` (int, optional), ``terms`` (str, optional).
        caller_identity : str, optional
            The AUTHENTICATED wallet address of whoever is setting these
            rights, threaded from the dispatcher (DOMAIN 17-D). Optional and
            defaulting to "" so existing callers — including this package's own
            `NFTService.mint`, which writes the default rights grant — keep
            working unchanged. "" is recorded as "" and means UNKNOWN.

        Returns
        -------
        dict
            Confirmed rights record.
        """
        # ── DOMAIN 17-D — THE RECORD NOW SAYS WHO ─────────────────────────
        #
        # This method granted `commercial` / `derivative` / `physical` rights
        # on any token to any holder, and stored the result with NO record of
        # who asked for it. The identity was not missing from the system — the
        # gateway had the caller's linked wallet and dropped it one frame above
        # the dispatcher — so the platform's own store could not answer "who
        # granted this?" about a grant it made itself.
        #
        # `set_by` is written at BOTH levels deliberately: on the record (who
        # touched this token's rights last) and on each individual right (who
        # granted THAT right), because a later call that changes one right type
        # must not silently reassign authorship of the others.
        #
        # THIS IS NOT AN AUTHORITY CHECK, AND IS NOT WRITTEN AS ONE. Nothing
        # here refuses. This platform holds no ownership record to check
        # against — `NFTFactory._collections` has zero writers — so a check
        # would have to invent its own truth. What lands here is the ATTRIBUTION
        # an ownership check would need once ownership is readable, plus a
        # record that answers "who" today.
        #
        # A CALL WITH NO IDENTITY IS STILL SERVED. Refusing every unauthenticated
        # caller would break `NFTService.mint`'s default-rights write and every
        # non-gateway entry point, and would trade a gap in the record for an
        # outage. It degrades to `set_by: ""` — the honest answer, "we do not
        # know" — never to a fabricated or self-asserted address.
        _set_by = caller_identity or ""
        # 17-J: WHO, and separately HOW WE KNOW. `set_by: ""` alone could not
        # distinguish "no human initiated this" from "we dropped the identity"
        # — and those are exactly the two facts 17-D exists to separate. A
        # sentinel was rejected: it makes ONE string carry both the identity and
        # the reason for its absence, which is the collapse this fixes.
        _set_by_source = caller_source or ("authenticated" if _set_by else "unauthenticated")
        key = f"{collection}:{token_id}"

        # Validate rights types
        for right_type in rights:
            if right_type not in RIGHTS_TYPES:
                raise ValueError(
                    f"Unknown right type '{right_type}'. "
                    f"Valid types: {', '.join(sorted(RIGHTS_TYPES))}"
                )

        # Build rights record
        record = self._rights.get(key, {
            "collection": collection,
            "token_id": token_id,
            "rights": {},
            "created_at": int(time.time()),
            "updated_at": int(time.time()),
            "created_by": _set_by,
            "created_by_source": _set_by_source,
        })

        now = int(time.time())
        for right_type, right_config in rights.items():
            if isinstance(right_config, bool):
                right_config = {"granted": right_config}

            record["rights"][right_type] = {
                "granted": right_config.get("granted", False),
                "holder": right_config.get("holder", ""),
                "expires_at": right_config.get("expires_at"),
                "terms": right_config.get("terms", ""),
                "updated_at": now,
                # 17-D: who granted THIS right, per right type.
                "set_by": _set_by,
            }

        record["updated_at"] = now
        record["set_by"] = _set_by
        self._rights[key] = record

        logger.info(
            "Rights set: %s #%d by %s — %s",
            collection[:10], token_id, _set_by or "<unknown caller>",
            {k: v.get("granted") for k, v in record["rights"].items()},
        )

        return {
            "status": "rights_set",
            "collection": collection,
            "token_id": token_id,
            "rights": record["rights"],
            "updated_at": now,
            "set_by": _set_by,
        }

    async def check_rights(
        self,
        collection: str,
        token_id: int,
        right_type: str,
    ) -> dict[str, Any]:
        """Check whether a specific right is granted for a token.

        Parameters
        ----------
        collection : str
            Collection contract address.
        token_id : int
            Token ID.
        right_type : str
            The right to check (e.g., ``"commercial"``).

        Returns
        -------
        dict
            Keys: ``granted``, ``holder``, ``expires_at``, ``expired``,
            ``right_type``.
        """
        if right_type not in RIGHTS_TYPES:
            raise ValueError(
                f"Unknown right type '{right_type}'. "
                f"Valid: {', '.join(sorted(RIGHTS_TYPES))}"
            )

        key = f"{collection}:{token_id}"
        record = self._rights.get(key)

        if record is None:
            # Return defaults
            granted = self._default_rights.get(right_type, False)
            return {
                "collection": collection,
                "token_id": token_id,
                "right_type": right_type,
                "granted": granted,
                "holder": "",
                "expires_at": None,
                "expired": False,
                "source": "default",
            }

        right = record["rights"].get(right_type)
        if right is None:
            granted = self._default_rights.get(right_type, False)
            return {
                "collection": collection,
                "token_id": token_id,
                "right_type": right_type,
                "granted": granted,
                "holder": "",
                "expires_at": None,
                "expired": False,
                "source": "default",
            }

        now = int(time.time())
        expired = False
        if right.get("expires_at") and right["expires_at"] < now:
            expired = True

        return {
            "collection": collection,
            "token_id": token_id,
            "right_type": right_type,
            "granted": right["granted"] and not expired,
            "holder": right.get("holder", ""),
            "expires_at": right.get("expires_at"),
            "expired": expired,
            "terms": right.get("terms", ""),
            # 17-D. A right that can be read must be readable back to whoever
            # granted it. Written by `set_rights` and surfaced here, so the
            # attribution is queryable and not just log-and-forget. "" means
            # the granting call carried no authenticated identity — an honest
            # "unknown", distinguishable from a real address.
            "set_by": right.get("set_by", ""),
            "source": "explicit",
        }

    async def transfer_rights(
        self,
        collection: str,
        token_id: int,
        new_holder: str,
        rights: list[str],
    ) -> dict[str, Any]:
        """Transfer specific rights to a new holder.

        Parameters
        ----------
        collection : str
            Collection contract address.
        token_id : int
            Token ID.
        new_holder : str
            Wallet address of the new rights holder.
        rights : list[str]
            List of right types to transfer.

        Returns
        -------
        dict
            Transfer confirmation with updated rights.
        """
        if not new_holder or not new_holder.startswith("0x"):
            raise ValueError("Valid new_holder address required")

        key = f"{collection}:{token_id}"
        record = self._rights.get(key)

        if record is None:
            raise KeyError(
                f"No rights record for {collection} #{token_id}. "
                f"Set rights first with set_rights()."
            )

        now = int(time.time())
        transferred: list[str] = []
        not_granted: list[str] = []

        for right_type in rights:
            if right_type not in RIGHTS_TYPES:
                raise ValueError(f"Unknown right type: {right_type}")

            right = record["rights"].get(right_type)
            if right is None or not right.get("granted"):
                not_granted.append(right_type)
                continue

            old_holder = right.get("holder", "")
            right["holder"] = new_holder
            right["updated_at"] = now
            transferred.append(right_type)

            # Record transfer
            history = self._transfer_history.setdefault(key, [])
            history.append({
                "right_type": right_type,
                "from": old_holder,
                "to": new_holder,
                "timestamp": now,
                "transfer_id": f"rt_{uuid.uuid4().hex[:12]}",
            })

        record["updated_at"] = now

        logger.info(
            "Rights transferred: %s #%d — %s -> %s (transferred=%s, skipped=%s)",
            collection[:10], token_id, "previous", new_holder,
            transferred, not_granted,
        )

        return {
            "status": "transferred",
            "collection": collection,
            "token_id": token_id,
            "new_holder": new_holder,
            "transferred": transferred,
            "not_granted": not_granted,
            "timestamp": now,
        }

    async def get_all_rights(
        self, collection: str, token_id: int
    ) -> dict[str, Any]:
        """Get all rights for a token."""
        key = f"{collection}:{token_id}"
        record = self._rights.get(key)

        if record is None:
            return {
                "collection": collection,
                "token_id": token_id,
                "rights": {
                    rt: {"granted": granted, "holder": "", "source": "default"}
                    for rt, granted in self._default_rights.items()
                },
                "source": "default",
            }

        return {
            "collection": collection,
            "token_id": token_id,
            "rights": record["rights"],
            "created_at": record.get("created_at"),
            "updated_at": record.get("updated_at"),
            "source": "explicit",
        }

    async def get_transfer_history(
        self, collection: str, token_id: int
    ) -> list[dict[str, Any]]:
        """Get the rights transfer history for a token."""
        key = f"{collection}:{token_id}"
        return list(self._transfer_history.get(key, []))
