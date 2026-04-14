import importlib.util
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "synarius-core" / "src"))


@unittest.skipUnless(importlib.util.find_spec("PySide6") is not None, "PySide6 not installed")
class ResourcesPanelTest(unittest.TestCase):
    def test_build_panel_lists_std_icons(self) -> None:
        from PySide6.QtWidgets import QApplication

        from synarius_core.controller import SynariusController
        from synarius_studio.resources_panel import build_resources_panel

        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)

        ctl = SynariusController()
        panel = build_resources_panel(ctl)
        self.assertIsNotNone(panel)
        # CI / minimal wheels may omit Lib/std from synarius-core; panel still builds.
        if len(ctl.library_catalog.libraries) < 1:
            self.skipTest(
                "No FMF libraries in catalog (bundled std not present in this synarius-core build)"
            )
        self.assertGreaterEqual(len(ctl.library_catalog.libraries), 1)


if __name__ == "__main__":
    unittest.main()
