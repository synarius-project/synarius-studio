"""Qt bridge for thread-safe log lines to the GUI."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class LogEmitter(QObject):
    message = Signal(str)
