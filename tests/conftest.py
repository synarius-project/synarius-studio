import sys
from pathlib import Path

# Prefer local monorepo siblings over any installed wheels so that all tests
# pick up the current development versions of synarius-core and synarius-apps.
_repo_root = Path(__file__).resolve().parents[2]
for _src in (
    Path(__file__).resolve().parents[1] / "src",      # synarius-studio/src
    _repo_root / "synarius-core" / "src",              # synarius-core/src
    _repo_root / "synarius-apps" / "src",              # synarius-apps/src
):
    _s = str(_src)
    if _s not in sys.path:
        sys.path.insert(0, _s)
