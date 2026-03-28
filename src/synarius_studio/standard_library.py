"""Standard library paths for the Studio GUI (data lives in ``synarius-core``).

FMF (library packaging) is its own specification; its version is unrelated to
Synarius Studio releases. This module re-exports ``synarius_core.standard_library``
so the GUI can resolve icons and element metadata without a second on-disk copy.
"""

from __future__ import annotations

from synarius_core.standard_library import STANDARD_LIBRARY_VERSION, standard_library_root

__all__ = ["STANDARD_LIBRARY_VERSION", "standard_library_root"]
