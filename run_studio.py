#!/usr/bin/env python3
"""
Start Synarius Studio from this checkout (sets ``src/`` on ``sys.path``).

Usage::

    python run_studio.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from synarius_studio.__main__ import main

if __name__ == "__main__":
    main()
