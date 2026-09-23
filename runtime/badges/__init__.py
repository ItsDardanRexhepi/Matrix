"""Glasswing Security Badge -- verified smart contract audit badges.

Projects that pass a Glasswing security audit can display a badge on
their site. The badge is a record in the gateway's database; no EAS
attestation is written for it. Badges expire after one year; the
manager can renew one, but no route calls that yet.
"""

from runtime.badges.badge_manager import BadgeManager

__all__ = ["BadgeManager"]
