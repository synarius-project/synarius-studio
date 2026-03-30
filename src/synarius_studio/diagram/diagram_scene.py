"""Diagram scene with simulation-mode flag and variable binding signals."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGraphicsScene


class SynariusDiagramScene(QGraphicsScene):
    """Context-menu results from variable blocks in simulation mode (stimulate / measure)."""

    variable_sim_binding_toggle = Signal(object, str, bool)
    open_dataviewer_requested = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._simulation_mode = False

    def set_simulation_mode(self, on: bool) -> None:
        self._simulation_mode = bool(on)
