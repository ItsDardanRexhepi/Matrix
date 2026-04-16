#!/usr/bin/env python3
"""
Thin shim kept for backwards compatibility.

Delegates to ``setup.telegram`` so existing docs / scripts that call
``python setup_telegram.py`` keep working. For new installs, prefer:

    python setup_communications.py telegram
    python setup_communications.py              # interactive menu
"""

from __future__ import annotations

import sys

from setup.telegram import main

if __name__ == "__main__":
    sys.exit(main())
