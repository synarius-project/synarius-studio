"""Tests for diagram scene population."""

from __future__ import annotations

import sys
from pathlib import Path

import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication, QGraphicsScene  # noqa: E402

from synarius_core.controller import SynariusController  # noqa: E402
from synarius_core.model import Connector  # noqa: E402
from synarius_studio.diagram.dataflow_layout import (  # noqa: E402
    default_sample_syn_path,
    populate_scene_from_model,
)


def _direct_connector_bends(connector: Connector, bends: list[float]) -> bool:
    connector.set("orthogonal_bends", list(bends))
    return True


class DataflowLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_populate_from_bundled_syn(self) -> None:
        path = default_sample_syn_path()
        self.assertTrue(path.is_file(), msg=f"missing {path}")
        ctl = SynariusController()
        ctl.execute(f'load "{path}"')
        scene = QGraphicsScene()
        populate_scene_from_model(
            scene,
            ctl.model,
            on_connector_orthogonal_bends=_direct_connector_bends,
        )
        # 7 variables + 3 operators + 9 connectors = 19 top-level items (children: labels, SVG glyphs).
        roots = [i for i in scene.items() if i.parentItem() is None]
        self.assertEqual(len(roots), 19)


if __name__ == "__main__":
    unittest.main()
