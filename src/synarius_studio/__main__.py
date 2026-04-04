from __future__ import annotations

import sys
from pathlib import Path


def _load_run():
    """Import ``run`` from :mod:`synarius_studio.app` for frozen, editable and dev layouts."""
    # PyInstaller: entry script is not inside the ``synarius_studio`` package → no relative imports.
    if getattr(sys, "frozen", False):
        from synarius_studio.app import run

        return run

    # Running ``python .../synarius_studio/__main__.py`` sets ``__package__`` to None; relative imports fail.
    if __package__:
        from .app import run
        return run

    studio_src = Path(__file__).resolve().parents[1]
    repo_root = studio_src.parents[1]
    core_src = repo_root / "synarius-core" / "src"
    apps_src = repo_root / "synarius-apps" / "src"
    if str(studio_src) not in sys.path:
        sys.path.insert(0, str(studio_src))
    if core_src.is_dir() and str(core_src) not in sys.path:
        sys.path.insert(0, str(core_src))
    if apps_src.is_dir() and str(apps_src.resolve()) not in sys.path:
        sys.path.insert(0, str(apps_src.resolve()))
    from synarius_studio.app import run

    return run


def main() -> None:
    run = _load_run()
    raise SystemExit(run())


if __name__ == "__main__":
    main()
