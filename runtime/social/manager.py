"""Social media manager — unified interface for all social platforms.

Routes post requests to the appropriate platform client and provides
a single point of configuration for social media integration.
"""

from __future__ import annotations

import logging
from typing import Any

from runtime.social.twitter import TwitterClient
from runtime.social.discord import DiscordClient

logger = logging.getLogger(__name__)

#: The platform names `SocialManager.post` routes. Anything else reaches no
#: client at all, so it is refused by name rather than answered with an empty
#: result — an empty result is what let a post to "linkedin" be recorded as
#: published (combine() of zero parts is SUCCESS: nothing went wrong, because
#: nothing was tried).
ROUTED_PLATFORMS: frozenset[str] = frozenset({"twitter", "discord", "all"})


class SocialManager:
    """Unified social media management for The Matrix agents.

    Provides a single ``post()`` method that routes to Twitter,
    Discord, or both. All operations are fault-tolerant.
    """

    def __init__(self, config: dict | None = None):
        """Initialise with optional config.

        Parameters
        ----------
        config : dict, optional
            Platform configuration with ``social`` section.
        """
        self.config = config or {}
        self.twitter = TwitterClient(config)
        self.discord = DiscordClient(config)

    @property
    def available(self) -> bool:
        """Whether any social platform is configured."""
        return self.twitter.available or self.discord.available

    @property
    def status(self) -> dict:
        """Status of all social integrations."""
        return {
            "twitter": {
                "configured": self.twitter.available,
            },
            "discord": {
                "configured": self.discord.available,
            },
        }

    async def post(
        self,
        content: str,
        platform: str = "all",
        metadata: dict | None = None,
    ) -> dict:
        """Post content to one or more social platforms.

        Parameters
        ----------
        content : str
            The content to post.
        platform : str
            Target: ``twitter``, ``discord``, or ``all``.
        metadata : dict, optional
            Platform-specific options (e.g. ``channel`` for Discord).

        Returns
        -------
        dict
            Results from each platform. A platform no client routes gets one
            entry of its own, an explicit refusal, so the answer is never an
            empty dict that reads as "nothing went wrong".
        """
        metadata = metadata or {}
        results: dict[str, Any] = {}

        if platform not in ROUTED_PLATFORMS:
            logger.warning("social post refused: no client routes platform %r", platform)
            return {
                str(platform): {
                    "status": "unsupported",
                    "error": (
                        f"no social client routes platform {platform!r}; "
                        f"routed: {', '.join(sorted(ROUTED_PLATFORMS))}"
                    ),
                },
            }

        if platform in ("twitter", "all"):
            results["twitter"] = await self.twitter.post_tweet(
                text=content,
                reply_to=metadata.get("reply_to"),
            )

        if platform in ("discord", "all"):
            results["discord"] = await self.discord.post_message(
                content=content,
                channel=metadata.get("channel", "default"),
                username=metadata.get("agent", "Trinity"),
            )

        return results
