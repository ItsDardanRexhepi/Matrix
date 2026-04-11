"""Social media integration and live activity feed for 0pnMatrx agents.

Provides Twitter/X and Discord posting, scheduling, and management,
plus a real-time ranked activity feed that surfaces platform actions
(contract deployments, swaps, NFT mints, DAO votes, …) to users.

All integrations are optional — the platform starts and runs normally
without any social media credentials configured.
"""

from runtime.social.manager import SocialManager
from runtime.social.scheduler import PostScheduler
from runtime.social.feed_engine import FeedEvent, FeedRankingEngine, SocialFeedEngine
from runtime.social.feed_formatter import FeedFormatter

__all__ = [
    "SocialManager",
    "PostScheduler",
    "FeedEvent",
    "FeedRankingEngine",
    "SocialFeedEngine",
    "FeedFormatter",
]
