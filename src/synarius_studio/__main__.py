from __future__ import annotations


def main() -> None:
    if __package__:
        from .app import run
    else:
        import sys
        from pathlib import Path

        # Support direct file execution:
        # python path/to/synarius_studio/__main__.py
        sys.path.append(str(Path(__file__).resolve().parents[1]))
        from synarius_studio.app import run

    raise SystemExit(run())


if __name__ == "__main__":
    main()

