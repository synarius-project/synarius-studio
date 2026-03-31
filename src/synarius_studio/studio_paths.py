"""Per-user directories for Synarius Studio (plugins, optional Lib overrides)."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def studio_user_data_dir() -> Path:
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            base = Path(local)
        else:
            base = Path.home() / "AppData" / "Local"
        return base / "Synarius"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Synarius"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "synarius"
    return Path.home() / ".local" / "share" / "synarius"


def studio_plugins_dir() -> Path:
    return studio_user_data_dir() / "Plugins"


def studio_lib_dir() -> Path:
    return studio_user_data_dir() / "Lib"


def studio_library_extra_roots() -> list[Path]:
    """FMF library roots (each with ``libraryDescription.xml``) under the user ``Lib`` folder."""
    root = studio_lib_dir()
    if not root.is_dir():
        return []
    return sorted(
        (p for p in root.iterdir() if p.is_dir() and (p / "libraryDescription.xml").is_file()),
        key=lambda p: p.name.lower(),
    )
