"""Twitter/X integration for The Matrix agents.

Posts agent-generated content to Twitter/X using OAuth 1.0a.
Requires requests-oauthlib (added to requirements.txt).

All methods are fault-tolerant — they never crash the platform
even if credentials are missing or API calls fail.

"Never crash the platform" covers two things that catching an exception does
not. The constructor used to read ``config["social"]["twitter"]`` through bare
``.get`` chaining, so ``"social": null`` raised an AttributeError out of
``__init__`` — before any of the try blocks the promise rests on. And the API
calls are synchronous ``requests`` calls made from inside ``async def``: an
unresponsive api.twitter.com did not fail the tweet, it froze every coroutine
in the process for as long as the socket stayed open, and there is no
exception to catch in a wait. Both are closed below: the config read is
defensive, and every request is bounded by a timeout and dispatched to a
worker thread so the event loop keeps running.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

# Connect and read budget for every Twitter call. The number matters less than
# its existence: `requests` with no timeout waits forever by default, and
# forever is the one duration a platform cannot absorb.
_REQUEST_TIMEOUT_SECONDS = (5, 15)

logger = logging.getLogger(__name__)


class TwitterClient:
    """Manages Twitter/X API interactions for agent posting.

    Uses OAuth 1.0a via requests-oauthlib. Falls back gracefully
    when credentials are not configured.
    """

    API_BASE = "https://api.twitter.com/2"

    def __init__(self, config: dict | None = None):
        """Initialise with optional config.

        Reads credentials from config or environment:
            TWITTER_API_KEY
            TWITTER_API_SECRET
            TWITTER_ACCESS_TOKEN
            TWITTER_ACCESS_SECRET
        """
        config = config if isinstance(config, dict) else {}
        social = config.get("social")
        social = social if isinstance(social, dict) else {}
        social_cfg = social.get("twitter")
        social_cfg = social_cfg if isinstance(social_cfg, dict) else {}

        self.api_key = social_cfg.get("api_key") or os.environ.get("TWITTER_API_KEY", "")
        self.api_secret = social_cfg.get("api_secret") or os.environ.get("TWITTER_API_SECRET", "")
        self.access_token = social_cfg.get("access_token") or os.environ.get("TWITTER_ACCESS_TOKEN", "")
        self.access_secret = social_cfg.get("access_secret") or os.environ.get("TWITTER_ACCESS_SECRET", "")

        self.available = bool(
            self.api_key and self.api_secret
            and self.access_token and self.access_secret
            and not self.api_key.startswith("YOUR_")
        )

        self._session = None

    @staticmethod
    async def _request(method, *args, **kwargs):
        """Run one blocking `requests` call off the event loop, with a timeout.

        `requests` has no async mode and no default timeout. Called directly
        from a coroutine it holds the loop for the whole round trip, so a
        provider that stops answering stops the platform — the failure mode the
        module docstring says cannot happen. A worker thread keeps the loop
        free; the timeout keeps the thread from being held forever.
        """
        kwargs.setdefault("timeout", _REQUEST_TIMEOUT_SECONDS)
        return await asyncio.to_thread(method, *args, **kwargs)

    def _get_session(self):
        """Create an OAuth1 session lazily."""
        if self._session is not None:
            return self._session

        if not self.available:
            return None

        try:
            from requests_oauthlib import OAuth1Session
            self._session = OAuth1Session(
                self.api_key,
                client_secret=self.api_secret,
                resource_owner_key=self.access_token,
                resource_owner_secret=self.access_secret,
            )
            return self._session
        except ImportError:
            logger.warning("requests-oauthlib not installed; Twitter integration disabled")
            self.available = False
            return None
        except Exception as exc:
            logger.error("Failed to create Twitter OAuth session: %s", exc)
            return None

    async def post_tweet(self, text: str, reply_to: str | None = None) -> dict:
        """Post a tweet.

        Parameters
        ----------
        text : str
            Tweet text (max 280 characters).
        reply_to : str, optional
            Tweet ID to reply to.

        Returns
        -------
        dict
            Result with tweet ID and URL on success.
        """
        if not self.available:
            return {"status": "not_configured", "message": "Twitter credentials not set."}

        session = self._get_session()
        if not session:
            return {"status": "error", "message": "Failed to create OAuth session."}

        try:
            payload: dict[str, Any] = {"text": text[:280]}
            if reply_to:
                payload["reply"] = {"in_reply_to_tweet_id": reply_to}

            resp = await self._request(
                session.post, f"{self.API_BASE}/tweets", json=payload)

            if resp.status_code in (200, 201):
                data = resp.json().get("data", {})
                tweet_id = data.get("id", "")
                return {
                    "status": "ok",
                    "tweet_id": tweet_id,
                    "url": f"https://twitter.com/i/status/{tweet_id}",
                    "text": text[:280],
                }
            else:
                error = resp.json().get("detail", resp.text)
                logger.error("Twitter post failed (%d): %s", resp.status_code, error)
                return {"status": "error", "message": str(error)}

        except Exception as exc:
            logger.error("Twitter post exception: %s", exc)
            return {"status": "error", "message": str(exc)}

    async def delete_tweet(self, tweet_id: str) -> dict:
        """Delete a tweet by ID."""
        if not self.available:
            return {"status": "not_configured"}

        session = self._get_session()
        if not session:
            return {"status": "error", "message": "No OAuth session."}

        try:
            resp = await self._request(
                session.delete, f"{self.API_BASE}/tweets/{tweet_id}")
            if resp.status_code == 200:
                return {"status": "ok", "deleted": tweet_id}
            return {"status": "error", "message": resp.text}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    async def get_me(self) -> dict:
        """Get the authenticated user's profile."""
        if not self.available:
            return {"status": "not_configured"}

        session = self._get_session()
        if not session:
            return {"status": "error"}

        try:
            resp = await self._request(session.get, f"{self.API_BASE}/users/me")
            if resp.status_code == 200:
                return {"status": "ok", "user": resp.json().get("data", {})}
            return {"status": "error", "message": resp.text}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
