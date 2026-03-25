from __future__ import annotations

from typing import Sequence

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def run(argv: Sequence[str] | None = None) -> int:
    import sys

    app = QApplication(list(argv) if argv is not None else sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()

