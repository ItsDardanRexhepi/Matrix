"""
0pnMatrx Developer SDK — Python client for the 0pnMatrx platform.

Usage:
    from sdk import OpenMatrixClient

    client = OpenMatrixClient("http://localhost:18790")
    response = client.chat("Hello, Trinity!")
    print(response.text)
"""

from sdk.client import OpenMatrixClient

__all__ = ["OpenMatrixClient"]
__version__ = "1.0.0"
