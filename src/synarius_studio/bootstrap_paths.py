"""Dev-time ``sys.path`` fixes when packages are not ``pip install``-ed.

Expects the usual monorepo layout::

    <repo>/
      synarius-studio/src/synarius_studio/...
      synarius-core/src/synarius_core/...
"""

from __future__ import annotations

import sys
from pathlib import Path


def prepend_dev_package_paths() -> None:
    """Put ``synarius-studio/src`` and ``synarius-core/src`` first on ``sys.path`` if they exist."""
    pkg_dir = Path(__file__).resolve().parent
    studio_src = pkg_dir.parent
    monorepo_root = studio_src.parent.parent
    core_src = monorepo_root / "synarius-core" / "src"
    for directory in (studio_src, core_src):
        if directory.is_dir():
            root = str(directory.resolve())
            if root not in sys.path:
                sys.path.insert(0, root)
