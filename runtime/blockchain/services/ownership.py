"""Shared ownership assertion for value-bearing service operations (NEW-77).

WHY THIS EXISTS AS A SHARED PRIMITIVE RATHER THAN A FOURTH AD-HOC CHECK

Three domains of this census have now needed the same check and none had it:

  domain 4  x402 `authorize_payment` — took no caller identity; anyone could
            authorise anyone's payment. Disabled (NEW-53) rather than fixed,
            because there was no identity to check against.
  domain 6  fundraising `verify_milestone` — took no caller identity, so the
            beneficiary could approve their own milestone and trigger release.
  domain 7  insurance `file_claim` — takes no caller identity; anyone who
            learns a policy id can claim against a stranger's policy.

NEW-54 already recorded that ownership verification in this codebase is
per-service, ad-hoc, and absent from the seam. Writing a fourth bespoke
`if caller != record["holder"]` would confirm that finding rather than
address it — and the failure mode is not that any one implementation is
wrong, it is that the NEXT one gets forgotten, silently, because there is
nothing to forget to call.

WHAT THIS IS AND IS NOT

It is a small, explicit assertion helper: given a caller and a record, refuse
unless they match. It deliberately does NOT authenticate the caller — this
layer cannot; identity must be established at the seam and passed in. What it
does is make the *absence* of a caller a refusal rather than a silent skip,
which is the specific way all three instances failed: the parameter simply
wasn't there, so no check could fail.

A call that names no caller is therefore refused, not waved through. That is the
fail-closed direction, and it is why `caller` has no default.
"""

from __future__ import annotations

from typing import Any


class OwnershipError(PermissionError):
    """Raised when a caller does not own the record they are acting on."""


def assert_owner(
    caller: str | None,
    record: dict[str, Any],
    *,
    owner_field: str = "holder",
    what: str = "record",
) -> str:
    """Refuse unless ``caller`` matches ``record[owner_field]``.

    Parameters
    ----------
    caller:
        Identity established upstream. ``None`` or empty is a REFUSAL, not a
        bypass — the missing-parameter case is exactly how this check was
        absent in all three domains that needed it.
    record:
        The thing being acted on (policy, campaign, payment…).
    owner_field:
        Which field holds the owner. Defaults to ``holder``; callers pass
        ``creator``/``borrower``/``contributor`` as appropriate.
    what:
        Noun used in the error message.

    Returns
    -------
    The verified caller, so call sites can use the return value and a reviewer
    can see the check was not merely executed for its side effect.

    Raises
    ------
    OwnershipError
    """
    if not caller:
        raise OwnershipError(
            f"Caller identity is required to act on this {what}. "
            "Anonymous access is refused."
        )

    owner = record.get(owner_field)
    if not owner:
        # A record with no recorded owner cannot be owned by anyone. Fail
        # closed rather than treating "no owner" as "any owner" — the
        # unenumerated case of a boundary fails closed.
        raise OwnershipError(
            f"This {what} has no recorded {owner_field}; ownership cannot be "
            "established and the operation is refused."
        )

    if caller != owner:
        raise OwnershipError(
            f"Caller does not own this {what}."
        )

    return caller
