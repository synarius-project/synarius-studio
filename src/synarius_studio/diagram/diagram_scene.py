"""Diagram scene with simulation-mode flag and stimulation configuration signal."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGraphicsScene


class SynariusDiagramScene(QGraphicsScene):
    """Signals when the user configures stimulation on a variable (from the variable item context menu)."""

    configure_variable_stimulation = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._simulation_mode = False

    def set_simulation_mode(self, on: bool) -> None:
        self._simulation_mode = bool(on)
