from __future__ import annotations

from PySide6.QtWidgets import QLabel, QMainWindow, QVBoxLayout, QWidget


class MainWindow(QMainWindow):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Synarius Studio")

        central = QWidget(self)
        layout = QVBoxLayout(central)

        self.status_label = QLabel("Ready.", central)
        layout.addWidget(self.status_label)

        self.setCentralWidget(central)

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

