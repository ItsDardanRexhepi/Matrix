"""A post sent nowhere is not published.

attest-money F13/F15. `PostScheduler._publish` decides the row from
`combine(per_platform.values())`, and `combine` of ZERO parts is SUCCESS — by
design: its docstring says an operation that fanned out to nothing had nothing
go wrong, and a caller asking "did anything happen at all" must count the
parts. `SocialManager.post` routes only twitter / discord / all and answered
`{}` for any other name, and `schedule()` accepted any name. Measured before
the fix: `ScheduledPost(platform="linkedin")` through `_publish` ->
status "published", `published_at` set, `result` {}.

Latent in the scheduler (nothing in production constructs a PostScheduler) and
LIVE one hop over: the gateway's POST /social/post handed the same name to the
same `SocialManager.post` and answered 200 `{}` — a post that went nowhere,
reported as nothing having gone wrong.

Closed at every layer that can see it, because each is reachable on its own:
the manager refuses the name with an explicit per-platform refusal, the
scheduler refuses to schedule it and counts parts before believing `combine`,
and the route answers 400.

SIBLING AXIS, named and not changed: `runtime/a2a/coordinator.py` also
combines a possibly-empty list — a job whose agent made no tool calls is
SUCCESS and invoiced. There the reply text IS the deliverable a
"provide a structured response" service sells, so zero tool calls is not
"nothing happened"; whether a text-only job is billable is a product call.
"""

from __future__ import annotations

import time

import pytest

from runtime.social.manager import ROUTED_PLATFORMS, SocialManager
from runtime.social.scheduler import PostScheduler, ScheduledPost


def _due(platform: str) -> ScheduledPost:
    return ScheduledPost(post_id="p1", platform=platform, content="hello",
                         scheduled_at=time.time() - 1)


async def test_a_post_to_an_unrouted_platform_is_not_published():
    """DEFECT-PROVER, through the real manager."""
    sched = PostScheduler(social_manager=SocialManager({}))
    post = _due("linkedin")
    sched.posts[post.post_id] = post

    await sched._publish(post)

    assert post.status == "failed", post.status
    assert post.published_at is None, "a post sent nowhere has a publication time"


class _EmptyManager:
    """Any manager that answers a fan-out to nothing with `{}`."""

    async def post(self, **_kwargs) -> dict:
        return {}


async def test_an_empty_fan_out_is_not_a_delivery():
    """The scheduler counts the parts itself, so a manager that answers `{}` —
    this one or any other — cannot have a post recorded as published."""
    sched = PostScheduler(social_manager=_EmptyManager())
    post = _due("twitter")
    sched.posts[post.post_id] = post

    await sched._publish(post)

    assert post.status == "failed" and post.published_at is None, post
    assert post.result.get("error"), post.result


async def test_an_unrouted_platform_cannot_be_scheduled():
    sched = PostScheduler()
    with pytest.raises(ValueError, match="linkedin"):
        await sched.schedule("linkedin", "hello", time.time() + 60)
    assert sched.posts == {}


@pytest.mark.parametrize("platform", sorted(ROUTED_PLATFORMS))
async def test_a_routed_platform_can_still_be_scheduled(platform):
    """SCOPE PIN."""
    sched = PostScheduler()
    post = await sched.schedule(platform, "hello", time.time() + 60)
    assert sched.posts[post.post_id].status == "pending"


async def test_the_manager_refuses_an_unrouted_platform_by_name():
    """The manager's answer names the platform and carries an error, so
    `report_of` reads it as the refusal it is instead of reading nothing."""
    from runtime.protocols.outcome_truth import FAILURE, report_of

    result = await SocialManager({}).post(content="hello", platform="linkedin")

    assert list(result) == ["linkedin"], result
    assert report_of(result["linkedin"]) == FAILURE


class _Request:
    def __init__(self, body: dict) -> None:
        self._body = body

    async def json(self):
        return dict(self._body)


class _AvailableManager(SocialManager):
    @property
    def available(self) -> bool:  # a configured deployment
        return True


async def test_the_live_route_refuses_an_unrouted_platform():
    """DEFECT-PROVER for the live surface: it answered 200 `{}`."""
    import json

    from gateway.server import GatewayServer

    class _Self:
        social_manager = _AvailableManager({})

    resp = await GatewayServer.handle_social_post(
        _Self(), _Request({"content": "hello", "platform": "linkedin"}))

    assert resp.status == 400, (resp.status, resp.text)
    assert "platform" in json.loads(resp.text)["error"]
