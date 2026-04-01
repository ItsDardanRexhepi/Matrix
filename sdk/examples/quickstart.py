#!/usr/bin/env python3
"""
0pnMatrx SDK Quickstart — demonstrates basic usage of the MatrixClient.

Before running:
1. Start the 0pnMatrx gateway: python -m gateway.server
2. Run this script: python -m sdk.examples.quickstart
"""

import asyncio
import sys
sys.path.insert(0, ".")

from sdk import MatrixClient


async def main():
    client = MatrixClient("http://localhost:18790")
    print(f"Connected: {client}")

    # 1. Health check
    print("\n── Health Check ──")
    try:
        health = await client.ahealth()
        print(f"Status: {health.status}")
        print(f"Agents: {health.agents}")
        print(f"Provider: {health.model_provider}")
    except Exception as e:
        print(f"Gateway not running: {e}")
        print("Start it with: python -m gateway.server")
        return

    # 2. Chat with Trinity
    print("\n── Chat with Trinity ──")
    response = await client.achat("Hello Trinity! What can you help me with?")
    print(f"Trinity: {response.text[:200]}")

    # 3. Ask Neo to do something
    print("\n── Neo Execution ──")
    response = await client.achat("List the files in the current directory", agent="neo")
    print(f"Neo: {response.text[:200]}")
    if response.tool_calls:
        print(f"Tools used: {[tc.get('name') for tc in response.tool_calls]}")

    # 4. Platform status
    print("\n── Platform Status ──")
    status = await client.astatus()
    print(f"Version: {status.version}")
    print(f"Uptime: {status.uptime_seconds:.0f}s")
    print(f"Requests: {status.total_requests}")
    print(f"Sessions: {status.sessions}")

    # 5. Memory operations
    print("\n── Memory ──")
    await client.amemory_write("neo", "sdk_test", "quickstart completed")
    memory = await client.amemory_read("neo")
    print(f"Neo memory: {memory}")

    print("\nQuickstart complete!")


if __name__ == "__main__":
    asyncio.run(main())
