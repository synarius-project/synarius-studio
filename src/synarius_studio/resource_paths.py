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


def _studio_icons_dir() -> Path:
    """Package ``icons`` directory (splash, toolbar SVGs).

    Editable/dev: :func:`bundle_root` is the ``synarius_studio`` package dir → ``…/synarius_studio/icons``.

    PyInstaller one-file: assets are under ``_MEIPASS/synarius_studio/icons`` (see ``synarius_studio.spec``),
    not ``_MEIPASS/icons``.
    """
    root = bundle_root()
    if is_frozen():
        return root / "synarius_studio" / "icons"
    return root / "icons"


def studio_icon_path(name: str = "synarius64.png") -> Path:
    return _studio_icons_dir() / name


def studio_splash_path(name: str = "splash.png") -> Path:
    return _studio_icons_dir() / name


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
