import sys
from pathlib import Path


# Make `src/` importable when running tests via `python -m unittest`.
sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))


import unittest


class SmokeTest(unittest.TestCase):
    def test_imports(self) -> None:
        import synarius_studio

        self.assertIsNotNone(synarius_studio)

    def test_pyside6_qtcore_importable(self) -> None:
        """Guards against missing/wrong-environment PySide6 (see README developer setup)."""
        from PySide6.QtCore import Qt, QTimer

        self.assertIsNotNone(Qt)
        self.assertIsNotNone(QTimer)

    def test_standard_library_from_core(self) -> None:
        from synarius_studio.standard_library import standard_library_root

        try:
            root = standard_library_root()
        except RuntimeError as exc:
            self.skipTest(
                "Bundled std FMF library not in this synarius-core install: " + str(exc)
            )
        self.assertTrue((root / "libraryDescription.xml").is_file())
        self.assertTrue((root / "components" / "Add" / "elementDescription.xml").is_file())

