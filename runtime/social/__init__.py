"""Social media integration for 0pnMatrx agents.

Provides Twitter/X and Discord posting, scheduling, and management.
All integrations are optional — the platform starts and runs normally
without any social media credentials configured.
"""

from runtime.social.manager import SocialManager
from runtime.social.scheduler import PostScheduler

__all__ = ["SocialManager", "PostScheduler"]
