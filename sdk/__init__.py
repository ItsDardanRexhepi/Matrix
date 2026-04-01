"""
0pnMatrx Developer SDK — Python client for the 0pnMatrx platform.

Usage:
    from sdk import MatrixClient

    client = MatrixClient("http://localhost:18790")
    response = client.chat("Hello, Trinity!")
    print(response.text)
"""

from sdk.client import MatrixClient

__all__ = ["MatrixClient"]
__version__ = "1.0.0"
