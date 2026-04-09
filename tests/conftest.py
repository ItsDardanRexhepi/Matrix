"""Shared fixtures for 0pnMatrx test suite."""

import pytest


@pytest.fixture
def mock_config(tmp_path):
    """Return a minimal valid config dict with temp directories."""
    return {
        "platform": "0pnMatrx",
        "memory_dir": str(tmp_path / "memory"),
        "workspace": str(tmp_path),
        "timezone": "UTC",
        "max_steps": 5,
        "model": {
            "provider": "ollama",
            "providers": {},
        },
        "agents": {
            "neo": {"enabled": True},
            "trinity": {"enabled": True},
            "morpheus": {"enabled": True},
        },
        "gateway": {
            "host": "0.0.0.0",
            "port": 18790,
            "api_key": "test-api-key-12345",
            "rate_limit_rpm": 60,
            "rate_limit_burst": 10,
        },
        "blockchain": {
            "rpc_url": "http://localhost:8545",
            "chain_id": 84532,
        },
        "security": {
            "block_on_critical": True,
            "block_on_high": False,
        },
    }


@pytest.fixture
def temp_workspace(tmp_path):
    """Provide a temporary workspace directory with standard subdirs."""
    for subdir in ["memory", "hivemind/queues", "hivemind/sessions", "hivemind/events"]:
        (tmp_path / subdir).mkdir(parents=True, exist_ok=True)
    return tmp_path
