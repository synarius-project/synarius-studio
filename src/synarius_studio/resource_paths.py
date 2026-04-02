from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    """Base for bundled runtime assets."""
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(str(meipass)).resolve()
    return Path(__file__).resolve().parent


def studio_icon_path(name: str = "synarius64.png") -> Path:
    return bundle_root() / "icons" / name


def prepend_dev_synarius_apps_src() -> bool:
    """Dev-only: add sibling monorepo ``synarius-apps/src`` when present."""
    if is_frozen():
        return False
    here = Path(__file__).resolve().parent
    for base in (here, *here.parents):
        cand = base / "synarius-apps" / "src"
        if not cand.is_dir():
            continue
        s = str(cand.resolve())
        if s not in sys.path:
            sys.path.insert(0, s)
        return True
    return False
