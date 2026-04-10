"""Glasswing Security Badge -- verified smart contract audit badges.

Projects that pass a Glasswing security audit can display a verifiable
badge on their site. Badges are backed by on-chain EAS attestations
and expire after one year (renewable).
"""

from runtime.badges.badge_manager import BadgeManager

__all__ = ["BadgeManager"]
