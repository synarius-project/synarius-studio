from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QLabel,
    QMainWindow,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)
from pathlib import Path
from ._version import __version__


class MainWindow(QMainWindow):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Synarius Studio {__version__}")
        self.resize(1200, 750)

        central = QWidget(self)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(8)

        self._create_actions()
        self._create_menu()
        self._create_toolbar()
        self._build_main_layout(root_layout)

        self.setStatusBar(self.statusBar())
        self.statusBar().showMessage("Ready.")
        self.setCentralWidget(central)

    def _create_actions(self) -> None:
        icons_dir = Path(__file__).resolve().parent / "icons"

        self.open_action = QAction("Open", self)
        self.save_action = QAction("Save", self)
        self.exit_action = QAction("Exit Synarius", self)
        self.toggle_right_panel_action = QAction("", self)
        self.toggle_bottom_panel_action = QAction("", self)

        self.toggle_right_panel_action.setCheckable(True)
        self.toggle_bottom_panel_action.setCheckable(True)
        self.toggle_right_panel_action.setChecked(True)
        self.toggle_bottom_panel_action.setChecked(True)
        self.toggle_right_panel_action.setIcon(QIcon(str(icons_dir / "toggle_right_panel.svg")))
        self.toggle_bottom_panel_action.setIcon(QIcon(str(icons_dir / "toggle_bottom_panel.svg")))
        self.toggle_right_panel_action.setToolTip("Toggle right panel")
        self.toggle_bottom_panel_action.setToolTip("Toggle bottom panel")

        self.open_action.triggered.connect(self._open_project)
        self.save_action.triggered.connect(self._save_project)
        self.exit_action.triggered.connect(self.close)
        self.toggle_right_panel_action.toggled.connect(self._toggle_right_panel)
        self.toggle_bottom_panel_action.toggled.connect(self._toggle_bottom_panel)

    def _create_menu(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        file_menu.addAction(self.open_action)
        file_menu.addAction(self.save_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

    def _create_toolbar(self) -> None:
        toolbar = QToolBar("Main Toolbar", self)
        toolbar.setMovable(False)
        toolbar.addAction(self.open_action)
        toolbar.addAction(self.save_action)

        spacer = QWidget(self)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        toolbar.addAction(self.toggle_right_panel_action)
        toolbar.addAction(self.toggle_bottom_panel_action)

        self.addToolBar(toolbar)

    def _build_main_layout(self, root_layout: QVBoxLayout) -> None:
        left_tabs = QTabWidget(self)
        left_tabs.setTabPosition(QTabWidget.TabPosition.East)
        left_tabs.addTab(self._panel_label("Resources"), "Resources")
        left_tabs.setMinimumWidth(140)

        canvas = QFrame(self)
        canvas.setFrameShape(QFrame.Shape.StyledPanel)
        canvas.setStyleSheet("background-color: #b8b5a9;")
        canvas.setMinimumWidth(260)

        self.right_tabs = QTabWidget(self)
        self.right_tabs.setTabPosition(QTabWidget.TabPosition.West)
        self.right_tabs.addTab(self._panel_label("Experiment"), "Experiment")
        self.right_tabs.setMinimumWidth(140)

        self.bottom_tabs = QTabWidget(self)
        self.bottom_tabs.addTab(self._panel_label("Console / Logging"), "Console")
        self.bottom_tabs.setMinimumHeight(100)

        self.center_split = QSplitter(self)
        self.center_split.setOrientation(Qt.Orientation.Vertical)
        self.center_split.addWidget(canvas)
        self.center_split.addWidget(self.bottom_tabs)
        self.center_split.setStretchFactor(0, 1)
        self.center_split.setStretchFactor(1, 0)
        self.center_split.setSizes([560, 180])

        self.horizontal_split = QSplitter(self)
        self.horizontal_split.setOrientation(Qt.Orientation.Horizontal)
        self.horizontal_split.addWidget(left_tabs)
        self.horizontal_split.addWidget(self.center_split)
        self.horizontal_split.addWidget(self.right_tabs)
        self.horizontal_split.setStretchFactor(0, 0)
        self.horizontal_split.setStretchFactor(1, 1)
        self.horizontal_split.setStretchFactor(2, 0)
        self.horizontal_split.setSizes([220, 760, 220])

        root_layout.addWidget(self.horizontal_split, 1)

    def _panel_label(self, text: str) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel(text, widget))
        layout.addStretch(1)
        return widget

    def _open_project(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Open Synarius Project",
            "",
            "Synarius Project (*.syn *.json *.yaml);;All Files (*)",
        )
        if file_name:
            self.statusBar().showMessage(f"Opened: {file_name}")
        else:
            self.statusBar().showMessage("Open canceled")

    def _save_project(self) -> None:
        file_name, _ = QFileDialog.getSaveFileName(
            self,
            "Save Synarius Project",
            "",
            "Synarius Project (*.syn *.json *.yaml);;All Files (*)",
        )
        if file_name:
            self.statusBar().showMessage(f"Saved: {file_name}")
        else:
            self.statusBar().showMessage("Save canceled")

    def _toggle_right_panel(self, visible: bool) -> None:
        self.right_tabs.setVisible(visible)
        if visible:
            self.horizontal_split.setSizes([220, 760, 220])
        else:
            self.horizontal_split.setSizes([220, 980, 0])

    def _toggle_bottom_panel(self, visible: bool) -> None:
        self.bottom_tabs.setVisible(visible)
        if visible:
            self.center_split.setSizes([560, 180])
        else:
            self.center_split.setSizes([740, 0])

