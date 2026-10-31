"""Glasswing Security Badge -- smart contract audit badges.

A badge is issued only on the platform's own Glasswing audit of the submitted
source (the caller cannot supply the verdict). It is a record in the gateway's
database, stored with a hash of that audit report, and expires after one year.
Badges are not written on-chain: the record keeps an ``eas_uid`` column that
nothing fills. ``BadgeManager.renew_badge`` re-audits the source, and no
gateway route calls it yet.
"""

from runtime.badges.badge_manager import BadgeManager

__all__ = ["BadgeManager"]
