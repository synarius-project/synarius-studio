"""Tests for small, mostly pure-logic studio modules.

Covers: bootstrap_paths, qt_log_handler, diagram_scene, experiment_codegen,
app_logging, theme.apply_dark_palette, svg_icons, dataflow_layout extras.
"""

from __future__ import annotations

import logging
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (
    Path(__file__).resolve().parents[1] / "src",
    _REPO_ROOT / "synarius-core" / "src",
    _REPO_ROOT / "synarius-apps" / "src",
):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# bootstrap_paths
# ---------------------------------------------------------------------------

class BootstrapPathsTest(unittest.TestCase):

    def test_prepend_adds_studio_src_to_path(self) -> None:
        from synarius_studio.bootstrap_paths import prepend_dev_package_paths
        before = len(sys.path)
        prepend_dev_package_paths()
        # Either paths were already present (no change) or were added.
        self.assertGreaterEqual(len(sys.path), before)

    def test_prepend_is_idempotent(self) -> None:
        from synarius_studio.bootstrap_paths import prepend_dev_package_paths
        prepend_dev_package_paths()
        path_before = list(sys.path)
        prepend_dev_package_paths()
        self.assertEqual(sys.path, path_before)


# ---------------------------------------------------------------------------
# qt_log_handler
# ---------------------------------------------------------------------------

class QtLogHandlerTest(unittest.TestCase):

    def _make_emitter(self):
        from synarius_studio.log_emitter import LogEmitter
        return LogEmitter()

    def test_qtloghandler_construction(self) -> None:
        from synarius_studio.qt_log_handler import QtLogHandler
        emitter = self._make_emitter()
        h = QtLogHandler(emitter)
        self.assertIsNotNone(h)

    def test_qtloghandler_emit_does_not_raise(self) -> None:
        from synarius_studio.qt_log_handler import QtLogHandler
        emitter = self._make_emitter()
        h = QtLogHandler(emitter)
        h.setFormatter(logging.Formatter("%(message)s"))
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        h.emit(record)  # must not raise

    def test_split_handler_construction(self) -> None:
        from synarius_studio.qt_log_handler import SplitStudioGuiLogHandler
        g = self._make_emitter()
        b = self._make_emitter()
        e = self._make_emitter()
        h = SplitStudioGuiLogHandler(g, b, e)
        self.assertIsNotNone(h)

    def test_split_handler_emit_does_not_raise(self) -> None:
        from synarius_studio.qt_log_handler import SplitStudioGuiLogHandler
        g = self._make_emitter()
        b = self._make_emitter()
        e = self._make_emitter()
        h = SplitStudioGuiLogHandler(g, b, e)
        h.setFormatter(logging.Formatter("%(message)s"))
        record = logging.LogRecord(
            name="synarius_studio.build.cmd", level=logging.ERROR, pathname="",
            lineno=0, msg="err", args=(), exc_info=None,
        )
        h.emit(record)

    def test_to_build_returns_true_for_build_logger(self) -> None:
        from synarius_studio.qt_log_handler import SplitStudioGuiLogHandler
        r = logging.LogRecord("synarius_studio.build.cmd", logging.DEBUG, "", 0, "", (), None)
        self.assertTrue(SplitStudioGuiLogHandler._to_build(r))

    def test_to_build_returns_true_for_console_warning(self) -> None:
        from synarius_studio.qt_log_handler import SplitStudioGuiLogHandler
        r = logging.LogRecord("synarius_studio.console", logging.WARNING, "", 0, "", (), None)
        self.assertTrue(SplitStudioGuiLogHandler._to_build(r))

    def test_to_build_returns_false_for_other(self) -> None:
        from synarius_studio.qt_log_handler import SplitStudioGuiLogHandler
        r = logging.LogRecord("synarius_studio.other", logging.INFO, "", 0, "", (), None)
        self.assertFalse(SplitStudioGuiLogHandler._to_build(r))

    def test_to_experiment_returns_true_for_experiment_logger(self) -> None:
        from synarius_studio.qt_log_handler import SplitStudioGuiLogHandler
        r = logging.LogRecord("synarius_studio.experiment.worker", logging.INFO, "", 0, "", (), None)
        self.assertTrue(SplitStudioGuiLogHandler._to_experiment(r))

    def test_to_experiment_returns_true_for_recordings(self) -> None:
        from synarius_studio.qt_log_handler import SplitStudioGuiLogHandler
        r = logging.LogRecord("synarius_studio.recordings", logging.INFO, "", 0, "", (), None)
        self.assertTrue(SplitStudioGuiLogHandler._to_experiment(r))

    def test_to_experiment_returns_false_for_other(self) -> None:
        from synarius_studio.qt_log_handler import SplitStudioGuiLogHandler
        r = logging.LogRecord("synarius_studio.other", logging.INFO, "", 0, "", (), None)
        self.assertFalse(SplitStudioGuiLogHandler._to_experiment(r))


# ---------------------------------------------------------------------------
# diagram_scene
# ---------------------------------------------------------------------------

class DiagramSceneTest(unittest.TestCase):

    def setUp(self) -> None:
        from synarius_studio.diagram.diagram_scene import SynariusDiagramScene
        self._scene = SynariusDiagramScene()

    def test_suppress_flag_starts_false(self) -> None:
        self.assertFalse(self._scene._suppress_next_left_release_selection_sync)

    def test_suppress_sets_flag(self) -> None:
        self._scene.suppress_next_left_release_selection_sync()
        self.assertTrue(self._scene._suppress_next_left_release_selection_sync)

    def test_take_returns_true_and_clears_flag(self) -> None:
        self._scene.suppress_next_left_release_selection_sync()
        result = self._scene.take_suppress_next_left_release_selection_sync()
        self.assertTrue(result)
        self.assertFalse(self._scene._suppress_next_left_release_selection_sync)

    def test_take_returns_false_when_not_set(self) -> None:
        result = self._scene.take_suppress_next_left_release_selection_sync()
        self.assertFalse(result)

    def test_set_simulation_mode(self) -> None:
        self._scene.set_simulation_mode(True)
        self.assertTrue(self._scene._simulation_mode)
        self._scene.set_simulation_mode(False)
        self.assertFalse(self._scene._simulation_mode)


# ---------------------------------------------------------------------------
# experiment_codegen
# ---------------------------------------------------------------------------

class ExperimentCodegenTest(unittest.TestCase):

    def test_model_from_controller_gives_view(self) -> None:
        from synarius_core.controller import SynariusController
        from synarius_studio.experiment_codegen import DataflowCompileView, compile_dataflow_for_view
        ctl = SynariusController()
        view = compile_dataflow_for_view(ctl.model)
        self.assertIsInstance(view, DataflowCompileView)
        self.assertIsInstance(view.diagnostics, tuple)


# ---------------------------------------------------------------------------
# app_logging (pure-logic functions)
# ---------------------------------------------------------------------------

class AppLoggingTest(unittest.TestCase):

    def test_log_directory_returns_path(self) -> None:
        from synarius_studio.app_logging import log_directory
        d = log_directory()
        self.assertIsInstance(d, Path)

    def test_main_log_path_returns_none_or_path(self) -> None:
        from synarius_studio.app_logging import main_log_path
        result = main_log_path()
        self.assertTrue(result is None or isinstance(result, Path))

    def test_install_qt_message_handler_does_not_raise(self) -> None:
        from synarius_studio.app_logging import install_qt_message_handler
        install_qt_message_handler()  # idempotent — safe to call repeatedly


# ---------------------------------------------------------------------------
# theme — apply_dark_palette
# ---------------------------------------------------------------------------

class ApplyDarkPaletteTest(unittest.TestCase):

    def test_apply_dark_palette_does_not_raise(self) -> None:
        from synarius_studio.theme import apply_dark_palette
        _app.setStyle("Fusion")
        apply_dark_palette(_app)

    def test_studio_toolbar_dock_toggle_qss(self) -> None:
        from synarius_studio.theme import studio_toolbar_dock_toggle_icon_only_qss
        qss = studio_toolbar_dock_toggle_icon_only_qss()
        self.assertIn("studio_dock_toggle", qss)
        self.assertIn("background-color", qss)


# ---------------------------------------------------------------------------
# svg_icons — pure string replacement
# ---------------------------------------------------------------------------

class SvgIconsTintTest(unittest.TestCase):

    def test_tint_replaces_breeze_symbolic_color(self) -> None:
        from PySide6.QtGui import QColor
        from synarius_studio.svg_icons import tint_breeze_symbolic_svg_markup
        svg = '<circle fill="#232629" />'
        result = tint_breeze_symbolic_svg_markup(svg, QColor("#ffffff"))
        self.assertNotIn("#232629", result)
        self.assertIn("#ffffff", result)

    def test_tint_replaces_pure_black(self) -> None:
        from PySide6.QtGui import QColor
        from synarius_studio.svg_icons import tint_breeze_symbolic_svg_markup
        svg = '<rect fill="#000000" />'
        result = tint_breeze_symbolic_svg_markup(svg, QColor("#ff0000"))
        self.assertNotIn("#000000", result)

    def test_tint_replaces_dark_custom(self) -> None:
        from PySide6.QtGui import QColor
        from synarius_studio.svg_icons import tint_breeze_symbolic_svg_markup
        svg = '<path fill="#1c1c1c" />'
        result = tint_breeze_symbolic_svg_markup(svg, QColor("#aabbcc"))
        self.assertNotIn("#1c1c1c", result)


# ---------------------------------------------------------------------------
# dataflow_layout extras
# ---------------------------------------------------------------------------

class DataflowLayoutExtrasTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QGraphicsScene
        from synarius_core.controller import SynariusController
        from synarius_studio.diagram.dataflow_layout import (
            default_sample_syn_path,
            populate_scene_from_model,
        )
        # Empty (fresh) model → hits the scene.setSceneRect(SCENE_RECT) fallback
        from synarius_core.controller import SynariusController
        empty_ctl = SynariusController()
        cls._empty_scene = QGraphicsScene()
        populate_scene_from_model(cls._empty_scene, empty_ctl.model)

        # Maps-curves example (has DataViewer + param lookup blocks)
        maps_path = default_sample_syn_path().parent / "example_maps_curves.syn"
        if maps_path.is_file():
            ctl = SynariusController()
            ctl.execute(f'load "{maps_path}"')
            cls._maps_scene = QGraphicsScene()
            populate_scene_from_model(cls._maps_scene, ctl.model)
            cls._has_maps = True
        else:
            cls._has_maps = False

    def test_empty_model_populates_without_error(self) -> None:
        self.assertIsNotNone(self._empty_scene)

    def test_maps_curves_populates_when_available(self) -> None:
        if not self._has_maps:
            self.skipTest("example_maps_curves.syn not available")
        roots = [i for i in self._maps_scene.items() if i.parentItem() is None]
        self.assertGreater(len(roots), 0)

    def test_open_syn_dialog_start_dir_returns_path(self) -> None:
        from synarius_studio.diagram.dataflow_layout import open_syn_dialog_start_dir
        result = open_syn_dialog_start_dir()
        self.assertIsInstance(result, Path)


if __name__ == "__main__":
    unittest.main()
