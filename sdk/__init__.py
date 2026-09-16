"""
The Matrix Developer SDK — Python client for the Matrix platform.

Usage:
    from sdk import MatrixClient

    client = MatrixClient("http://localhost:18790")
    response = client.chat("Hello, Trinity!")
    print(response.text)
"""

from sdk.client import MatrixClient

__all__ = ["MatrixClient"]
# One source of truth (see runtime/__init__.py); never restate the number.
from runtime import __version__  # noqa: E402,F401
