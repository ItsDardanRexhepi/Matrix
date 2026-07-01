"""P0-1 regression: the social feed engine must attach to the ServiceDispatcher
nested inside the ReAct ToolDispatcher — attaching to the ToolDispatcher itself
was a silent no-op (AttributeError swallowed by the startup try/except)."""

import pytest

from runtime.tools.dispatcher import ToolDispatcher
from gateway.server import attach_social_feed


class _FakeLoop:
    def __init__(self):
        self.dispatcher = ToolDispatcher({})


class _FakeEngine:
    pass


def test_feed_attaches_to_nested_service_dispatcher():
    loop = _FakeLoop()
    if loop.dispatcher.service_dispatcher is None:
        pytest.skip("ServiceDispatcher unavailable in this env")
    engine = _FakeEngine()
    sd = attach_social_feed(loop, engine)
    assert sd is loop.dispatcher.service_dispatcher
    assert sd._feed_engine is engine


def test_attach_returns_none_without_dispatcher():
    class _Bare:
        dispatcher = None

    assert attach_social_feed(_Bare(), _FakeEngine()) is None
