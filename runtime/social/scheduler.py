"""Post scheduler for automated social media publishing.

Manages a queue of scheduled posts that are published at their
designated times. Runs as a background task alongside the gateway.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ScheduledPost:
    """A social media post scheduled for future publishing."""
    post_id: str
    platform: str            # "twitter", "discord", or "all"
    content: str
    scheduled_at: float      # Unix timestamp
    agent: str = "trinity"   # Which agent's voice
    metadata: dict = field(default_factory=dict)
    status: str = "pending"  # pending, published, failed, cancelled
    published_at: float | None = None
    result: dict = field(default_factory=dict)


class PostScheduler:
    """Manages scheduled social media posts.

    Posts are stored in memory and optionally persisted to SQLite.
    A background loop checks for posts that are due and publishes them.
    """

    def __init__(self, social_manager=None, db=None):
        """Initialise the scheduler.

        Parameters
        ----------
        social_manager : SocialManager, optional
            The social media manager for publishing posts.
        db : Database, optional
            SQLite database for persistence.
        """
        self.manager = social_manager
        self.db = db
        self.posts: dict[str, ScheduledPost] = {}
        self._running = False
        self._task: asyncio.Task | None = None

    async def initialize(self) -> None:
        """Create the scheduled_posts table if it does not exist."""
        if self.db:
            await self.db.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduled_posts (
                    post_id         TEXT PRIMARY KEY,
                    platform        TEXT NOT NULL,
                    content         TEXT NOT NULL,
                    scheduled_at    REAL NOT NULL,
                    agent           TEXT NOT NULL DEFAULT 'trinity',
                    metadata        TEXT,
                    status          TEXT NOT NULL DEFAULT 'pending',
                    published_at    REAL,
                    result          TEXT,
                    created_at      REAL NOT NULL
                )
                """,
                commit=True,
            )

    async def schedule(
        self,
        platform: str,
        content: str,
        scheduled_at: float,
        agent: str = "trinity",
        metadata: dict | None = None,
    ) -> ScheduledPost:
        """Schedule a post for future publishing.

        Parameters
        ----------
        platform : str
            Target platform: ``twitter``, ``discord``, or ``all``.
        content : str
            Post content.
        scheduled_at : float
            Unix timestamp when to publish.
        agent : str
            Which agent's voice to use.
        metadata : dict, optional
            Additional metadata (e.g. channel, reply_to).

        Returns
        -------
        ScheduledPost
            The created scheduled post.
        """
        post = ScheduledPost(
            post_id=f"post_{uuid.uuid4().hex[:12]}",
            platform=platform,
            content=content,
            scheduled_at=scheduled_at,
            agent=agent,
            metadata=metadata or {},
        )
        self.posts[post.post_id] = post

        if self.db:
            await self.db.execute(
                """
                INSERT INTO scheduled_posts
                    (post_id, platform, content, scheduled_at, agent, metadata, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    post.post_id, post.platform, post.content,
                    post.scheduled_at, post.agent,
                    json.dumps(post.metadata), "pending", time.time(),
                ),
                commit=True,
            )

        logger.info("Scheduled post %s for %s at %s", post.post_id, platform, scheduled_at)
        return post

    async def cancel(self, post_id: str) -> bool:
        """Cancel a scheduled post."""
        post = self.posts.get(post_id)
        if not post or post.status != "pending":
            return False
        post.status = "cancelled"
        if self.db:
            await self.db.execute(
                "UPDATE scheduled_posts SET status = 'cancelled' WHERE post_id = ?",
                (post_id,),
                commit=True,
            )
        return True

    async def list_pending(self) -> list[ScheduledPost]:
        """List all pending scheduled posts."""
        return [p for p in self.posts.values() if p.status == "pending"]

    async def start(self) -> None:
        """Start the background publishing loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._publish_loop())
        logger.info("Post scheduler started")

    async def stop(self) -> None:
        """Stop the background publishing loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _publish_loop(self) -> None:
        """Background loop that publishes due posts."""
        while self._running:
            try:
                now = time.time()
                due_posts = [
                    p for p in self.posts.values()
                    if p.status == "pending" and p.scheduled_at <= now
                ]

                for post in due_posts:
                    await self._publish(post)

                await asyncio.sleep(30)  # Check every 30 seconds
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Scheduler loop error: %s", exc)
                await asyncio.sleep(60)

    async def _publish(self, post: ScheduledPost) -> None:
        """Publish a single post."""
        if not self.manager:
            post.status = "failed"
            post.result = {"error": "No social manager configured"}
            return

        try:
            result = await self.manager.post(
                content=post.content,
                platform=post.platform,
                metadata=post.metadata,
            )
            post.status = "published"
            post.published_at = time.time()
            post.result = result
            logger.info("Published post %s to %s", post.post_id, post.platform)
        except Exception as exc:
            post.status = "failed"
            post.result = {"error": str(exc)}
            logger.error("Failed to publish post %s: %s", post.post_id, exc)

        if self.db:
            await self.db.execute(
                """
                UPDATE scheduled_posts
                SET status = ?, published_at = ?, result = ?
                WHERE post_id = ?
                """,
                (post.status, post.published_at, json.dumps(post.result), post.post_id),
                commit=True,
            )
