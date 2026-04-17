"""Tests for the DataViewer open_widget pipeline.

Covers:
  - Model-attribute semantics of DataViewer.open_widget
  - _open_live_dataviewer_dialog creates a QDialog with DataViewerShell inside
  - _flush_dataviewer_open_widget_from_model dispatches and clears the flag

The bug: double-clicking the Oszi canvas block (e.g. example_maps_curves.syn) did not
open the DataViewer because either the DataViewerWidget constructor crashed on a
PySide6 Enum coercion or the flush pipeline silently swallowed the exception.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[2]  # h:/Programmierung/Synarius
# Dev monorepo: prefer local src over any installed package.
for _p in (
    Path(__file__).resolve().parents[1] / "src",         # synarius-studio/src
    _REPO_ROOT / "synarius-core" / "src",                 # synarius-core/src
    _REPO_ROOT / "synarius-apps" / "src",                 # synarius-apps/src
):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)

from PySide6.QtWidgets import QApplication, QDialog, QMainWindow  # noqa: E402

from synarius_core.model import DataViewer  # noqa: E402


# ---------------------------------------------------------------------------
# Minimal MainWindow stub
#
# We borrow _open_live_dataviewer_dialog and _flush_dataviewer_open_widget_from_model
# from the real MainWindow but run them on a lightweight QMainWindow subclass
# that implements only the helper methods those two functions call.  This
# avoids spinning up the full Studio UI while still exercising the real code.
# ---------------------------------------------------------------------------

def _empty_series(name: str) -> tuple[np.ndarray, np.ndarray]:
    return np.array([0.0]), np.array([0.0])


class _MinimalMainWindow(QMainWindow):
    """Minimal QMainWindow providing only the attributes needed by the DataViewer open pipeline."""

    def __init__(self) -> None:
        super().__init__()
        self._live_dataviewers: dict[int, QDialog] = {}

    # Methods called from _open_live_dataviewer_dialog --------------------

    def _bound_variables_for_dataviewer_id(self, vid: int) -> list:
        return []

    def _resolve_live_series(self, name: str) -> tuple[np.ndarray, np.ndarray]:
        return _empty_series(name)

    def _resolve_live_unit(self, name: str) -> str:
        return ""

    def _attach_canvas_runtime_actions_to_dynamic_dataviewer(self, shell: object) -> None:
        pass

    def _ensure_live_series_seed(self, name: str) -> None:
        pass

    def _register_recording_entry(self, path: object) -> None:
        pass


def _install_borrowed_methods() -> None:
    """Attach real MainWindow methods to _MinimalMainWindow once, lazily."""
    if hasattr(_MinimalMainWindow, "_open_live_dataviewer_dialog"):
        return
    from synarius_studio.main_window import MainWindow

    _MinimalMainWindow._open_live_dataviewer_dialog = (  # type: ignore[attr-defined]
        MainWindow._open_live_dataviewer_dialog
    )
    _MinimalMainWindow._flush_dataviewer_open_widget_from_model = (  # type: ignore[attr-defined]
        MainWindow._flush_dataviewer_open_widget_from_model
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class DataViewerModelAttributeTest(unittest.TestCase):
    """Model-layer: DataViewer.open_widget attribute semantics (no Qt required)."""

    def test_open_widget_starts_false(self) -> None:
        dv = DataViewer(viewer_id=1)
        self.assertIn("open_widget", dv.attribute_dict)
        self.assertFalse(bool(dv.get("open_widget")))

    def test_open_widget_set_and_clear(self) -> None:
        dv = DataViewer(viewer_id=2)
        dv.set("open_widget", True)
        self.assertTrue(bool(dv.get("open_widget")))
        dv.set("open_widget", False)
        self.assertFalse(bool(dv.get("open_widget")))

    def test_dataviewer_id_readable(self) -> None:
        dv = DataViewer(viewer_id=42)
        self.assertEqual(int(dv.get("dataviewer_id")), 42)


class DataViewerOpenDialogTest(unittest.TestCase):
    """_open_live_dataviewer_dialog must create a QDialog with DataViewerShell inside."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])
        _install_borrowed_methods()

    def setUp(self) -> None:
        self._win = _MinimalMainWindow()

    def tearDown(self) -> None:
        # Close any dialogs opened during the test.
        for dlg in list(self._win._live_dataviewers.values()):
            try:
                dlg.close()
            except Exception:
                pass
        self._win.close()

    def test_dialog_created_and_registered(self) -> None:
        """Calling _open_live_dataviewer_dialog must register a QDialog in _live_dataviewers."""
        from synarius_dataviewer.widgets.data_viewer import DataViewerShell

        dv = DataViewer(viewer_id=5)
        self._win._open_live_dataviewer_dialog(dv)  # type: ignore[attr-defined]

        self.assertIn(5, self._win._live_dataviewers)
        dlg = self._win._live_dataviewers[5]
        self.assertIsInstance(dlg, QDialog)
        # The shell must be wired in as well.
        self.assertIsInstance(getattr(dlg, "_dv_shell", None), DataViewerShell)

    def test_second_call_reuses_existing_dialog(self) -> None:
        """Calling the method twice for the same viewer_id must not create a second dialog."""
        dv = DataViewer(viewer_id=6)
        self._win._open_live_dataviewer_dialog(dv)  # type: ignore[attr-defined]
        dlg_first = self._win._live_dataviewers.get(6)

        self._win._open_live_dataviewer_dialog(dv)  # type: ignore[attr-defined]
        dlg_second = self._win._live_dataviewers.get(6)

        self.assertIs(dlg_first, dlg_second)

    def test_bad_dataviewer_id_does_not_raise(self) -> None:
        """A DataViewer whose dataviewer_id cannot be coerced to int must be silently skipped."""
        dv = DataViewer(viewer_id=9)
        # Corrupt the id in the attribute dict to provoke the int() failure path.
        dv.set("dataviewer_id", "not-an-int")
        # Must not raise; the method returns early without touching _live_dataviewers.
        self._win._open_live_dataviewer_dialog(dv)  # type: ignore[attr-defined]
        self.assertNotIn(9, self._win._live_dataviewers)


class DataViewerFlushPipelineTest(unittest.TestCase):
    """_flush_dataviewer_open_widget_from_model must dispatch and clear the flag."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])
        _install_borrowed_methods()

    def setUp(self) -> None:
        self._win = _MinimalMainWindow()

    def tearDown(self) -> None:
        self._win.close()

    def test_flush_calls_open_dialog_when_flag_true(self) -> None:
        """flush must call _open_live_dataviewer_dialog exactly once when open_widget=True."""
        dv = DataViewer(viewer_id=11)
        dv.set("open_widget", True)

        self._win._controller = MagicMock()  # type: ignore[attr-defined]
        self._win._controller.model.iter_objects.return_value = [dv]

        with patch.object(
            self._win,
            "_open_live_dataviewer_dialog",
        ) as mock_open:
            self._win._flush_dataviewer_open_widget_from_model()  # type: ignore[attr-defined]

        mock_open.assert_called_once_with(dv)

    def test_flush_clears_flag_after_dispatch(self) -> None:
        """open_widget must be False after a successful flush."""
        dv = DataViewer(viewer_id=12)
        dv.set("open_widget", True)

        self._win._controller = MagicMock()  # type: ignore[attr-defined]
        self._win._controller.model.iter_objects.return_value = [dv]

        with patch.object(self._win, "_open_live_dataviewer_dialog"):
            self._win._flush_dataviewer_open_widget_from_model()  # type: ignore[attr-defined]

        self.assertFalse(bool(dv.get("open_widget")))

    def test_flush_skips_when_flag_false(self) -> None:
        """flush must not call _open_live_dataviewer_dialog when open_widget is False."""
        dv = DataViewer(viewer_id=13)
        # open_widget stays False (default)

        self._win._controller = MagicMock()  # type: ignore[attr-defined]
        self._win._controller.model.iter_objects.return_value = [dv]

        with patch.object(
            self._win,
            "_open_live_dataviewer_dialog",
        ) as mock_open:
            self._win._flush_dataviewer_open_widget_from_model()  # type: ignore[attr-defined]

        mock_open.assert_not_called()

    def test_flush_skips_non_dataviewer_objects(self) -> None:
        """flush must ignore non-DataViewer objects returned by iter_objects."""
        from synarius_core.model import Variable

        dv = DataViewer(viewer_id=14)
        dv.set("open_widget", True)
        var = Variable(name="x", type_key="t", value=0.0)

        self._win._controller = MagicMock()  # type: ignore[attr-defined]
        self._win._controller.model.iter_objects.return_value = [var, dv]

        with patch.object(
            self._win,
            "_open_live_dataviewer_dialog",
        ) as mock_open:
            self._win._flush_dataviewer_open_widget_from_model()  # type: ignore[attr-defined]

        mock_open.assert_called_once_with(dv)


if __name__ == "__main__":
    unittest.main()
