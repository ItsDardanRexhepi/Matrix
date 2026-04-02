#!/usr/bin/env python3
"""
SDK integration test — validates the OpenMatrixClient against a live gateway.

Usage:
    python -m sdk.test_sdk          # gateway must be running on :18790
"""

import sys
import os

# Ensure the repo root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sdk.client import OpenMatrixClient


def main():
    passed = 0
    failed = 0

    client = OpenMatrixClient("http://localhost:18790")
    print(f"SDK client: {client}\n")

    # ── Test 1: Health ─────────────────────────────────────────────
    print("1. Health check ...", end=" ")
    try:
        health = client.health()
        assert health.status == "ok", f"expected 'ok', got '{health.status}'"
        assert len(health.agents) > 0, "no agents"
        print(f"PASS  (agents={health.agents})")
        passed += 1
    except Exception as e:
        print(f"FAIL  ({e})")
        failed += 1

    # ── Test 2: Status ─────────────────────────────────────────────
    print("2. Platform status ...", end=" ")
    try:
        status = client.status()
        assert status.version, "no version"
        assert status.agents, "no agents"
        print(f"PASS  (v{status.version}, agents={status.agents})")
        passed += 1
    except Exception as e:
        print(f"FAIL  ({e})")
        failed += 1

    # ── Test 3: Chat with Trinity ──────────────────────────────────
    print("3. Chat with Trinity ...", end=" ")
    try:
        response = client.chat("Hello, Trinity!", agent="trinity")
        assert response.text, "empty response"
        assert response.agent == "trinity"
        print(f"PASS  (response={response.text[:80]}...)")
        passed += 1
    except Exception as e:
        print(f"FAIL  ({e})")
        failed += 1

    # ── Test 4: Session ID persistence ─────────────────────────────
    print("4. Session persistence ...", end=" ")
    try:
        sid = client.session_id
        assert sid, "no session_id"
        new_sid = client.new_session()
        assert new_sid != sid, "session_id did not change"
        print(f"PASS  (old={sid}, new={new_sid})")
        passed += 1
    except Exception as e:
        print(f"FAIL  ({e})")
        failed += 1

    # ── Summary ────────────────────────────────────────────────────
    total = passed + failed
    print(f"\n{'='*40}")
    print(f"Results: {passed}/{total} passed, {failed}/{total} failed")
    if failed > 0:
        print("SOME TESTS FAILED")
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()
