"""Diagram scene with simulation-mode flag and variable binding signals."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGraphicsScene


class SynariusDiagramScene(QGraphicsScene):
    """Context-menu results from variable blocks in simulation mode (stimulate / measure)."""

    variable_sim_binding_toggle = Signal(object, str, bool)
    open_dataviewer_requested = Signal(object)
    open_kenngroesse_requested = Signal(object)  # ElementaryInstance (std.Kennwert/Kennlinie/Kennfeld)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._simulation_mode = False
        # After a functional item double-click, skip one view ``scene_left_release`` so CCP does not get a duplicate ``select``.
        self._suppress_next_left_release_selection_sync = False

    def suppress_next_left_release_selection_sync(self) -> None:
        """Call when a double-click was handled (e.g. open DataViewer); the next left release will not sync selection to the controller."""
        self._suppress_next_left_release_selection_sync = True

    def take_suppress_next_left_release_selection_sync(self) -> bool:
        """If set, clear and return True (consume one skip)."""
        if not self._suppress_next_left_release_selection_sync:
            return False
        self._suppress_next_left_release_selection_sync = False
        return True

    def set_simulation_mode(self, on: bool) -> None:
        self._simulation_mode = bool(on)
