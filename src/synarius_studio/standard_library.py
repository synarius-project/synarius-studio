"""Synarius Standard Library (FMF v0.1): Grundrechenarten.

The on-disk library ships inside ``synarius-core``; Studio re-exports the same
paths so GUI and tooling can resolve icons and element metadata without a second
copy.
"""

from __future__ import annotations

from synarius_core.standard_library import STANDARD_LIBRARY_VERSION, standard_library_root

__all__ = ["STANDARD_LIBRARY_VERSION", "standard_library_root"]
