from __future__ import annotations

try:
    from .app import run
except ImportError:
    # Allow direct execution of this file (python path/to/__main__.py).
    import sys
    from pathlib import Path

    studio_src = Path(__file__).resolve().parents[1]
    repo_root = studio_src.parents[1]
    core_src = repo_root / "synarius-core" / "src"

    sys.path.append(str(studio_src))
    if core_src.exists():
        sys.path.append(str(core_src))
    from synarius_studio.app import run

def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()

