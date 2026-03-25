import sys
from pathlib import Path


# Make `src/` importable when running tests via `python -m unittest`.
sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))


import unittest


class SmokeTest(unittest.TestCase):
    def test_imports(self) -> None:
        import synarius_studio

        # Importing the package should work even if PySide6 isn't installed yet.
        self.assertIsNotNone(synarius_studio)

