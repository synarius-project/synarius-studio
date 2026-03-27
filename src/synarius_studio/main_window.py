from __future__ import annotations

import re
from dataclasses import dataclass, field
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QIcon, QKeyEvent, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsScene,
    QLabel,
    QMainWindow,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)
from pathlib import Path
from ._version import __version__
from synarius_core.controller import CommandError, MinimalController

from .diagram import DataflowGraphicsView, populate_scene_from_model
from .diagram.dataflow_canvas import CANVAS_BACKGROUND_COLOR, SCROLLBAR_STYLE_QSS
from .diagram.dataflow_layout import SCENE_RECT, open_syn_dialog_start_dir

DEFAULT_OUTPUT_COLOR = "#ADD8E6"  # light blue
DEFAULT_PROMPT_COLOR = "#90EE90"  # light green
DEFAULT_INPUT_COLOR = "#FFFFFF"  # terminal-like user input
ERROR_COLOR = "#FF6666"


@dataclass
class _History:
    entries: list[str] = field(default_factory=list)
    index: int = 0

    def push(self, line: str) -> None:
        if line.strip() == "":
            return
        self.entries.append(line)
        self.index = len(self.entries)

    def prev(self) -> str | None:
        if not self.entries:
            return None
        self.index = max(0, self.index - 1)
        return self.entries[self.index]

    def next(self) -> str:
        if not self.entries:
            return ""
        self.index = min(len(self.entries), self.index + 1)
        if self.index >= len(self.entries):
            return ""
        return self.entries[self.index]


class _TerminalConsole(QTextEdit):
    def __init__(self, on_submit, on_prev, on_next, parent: QWidget | None = None):
        super().__init__(parent)
        self._on_submit = on_submit
        self._on_prev = on_prev
        self._on_next = on_next
        self._input_start = 0
        self.setAcceptRichText(False)

    def _insert_colored(self, text: str, color: str) -> None:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.setTextCursor(cursor)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor.mergeCharFormat(fmt)
        cursor.insertText(text)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def append_output(self, text: str, color: str) -> None:
        self._insert_colored(f"{text}\n", color)

    def show_prompt(self, prompt: str, color: str) -> None:
        self._insert_colored(prompt, color)
        self._input_start = self.textCursor().position()
        # Keep user-typed command text white, matching terminal UX.
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(DEFAULT_INPUT_COLOR))
        self.setCurrentCharFormat(fmt)

    def current_input(self) -> str:
        return self.toPlainText()[self._input_start :]

    def replace_current_input(self, text: str) -> None:
        cursor = self.textCursor()
        cursor.setPosition(self._input_start)
        cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        cursor.insertText(text)
        self.setTextCursor(cursor)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        cursor = self.textCursor()

        if key == Qt.Key.Key_Up:
            self._on_prev()
            return
        if key == Qt.Key.Key_Down:
            self._on_next()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            line = self.current_input()
            self._insert_colored("\n", DEFAULT_OUTPUT_COLOR)
            self._on_submit(line)
            return
        if key == Qt.Key.Key_Backspace and cursor.position() <= self._input_start:
            return
        if key == Qt.Key.Key_Left and cursor.position() <= self._input_start:
            return
        if key == Qt.Key.Key_Home:
            cursor.setPosition(self._input_start)
            self.setTextCursor(cursor)
            return
        if cursor.position() < self._input_start:
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.setTextCursor(cursor)

        super().keyPressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Synarius Studio {__version__}")
        self.resize(1200, 750)
        self._controller = MinimalController()
        self._history = _History()
        self._default_output_color = DEFAULT_OUTPUT_COLOR

        central = QWidget(self)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(8)

        self._diagram_scene = QGraphicsScene(self)
        self._diagram_scene.setSceneRect(SCENE_RECT)

        self._create_actions()
        self._create_menu()
        self._build_main_layout(root_layout)
        self._create_toolbar()

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

        toolbar.addSeparator()
        toolbar.addWidget(QLabel("Zoom:", self))
        self._zoom_combo = QComboBox(self)
        self._zoom_combo.setEditable(True)
        self._zoom_combo.setMinimumWidth(88)
        for z in ("60%", "80%", "100%", "120%", "140%"):
            self._zoom_combo.addItem(z)
        self._zoom_combo.setCurrentText("100%")
        zoom_le = self._zoom_combo.lineEdit()
        if zoom_le is not None:
            zoom_le.setPlaceholderText("100%")
            zoom_le.returnPressed.connect(self._on_zoom_combo_return)
        toolbar.addWidget(self._zoom_combo)
        self._zoom_combo.activated.connect(self._on_zoom_combo_activated)
        self._dataflow_view.zoom_percent_changed.connect(self._sync_zoom_combo_from_view)

        spacer = QWidget(self)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        toolbar.addAction(self.toggle_right_panel_action)
        toolbar.addAction(self.toggle_bottom_panel_action)

        self.addToolBar(toolbar)

    @staticmethod
    def _parse_zoom_percent_text(text: str) -> float | None:
        t = text.strip().upper().replace("%", "").strip()
        try:
            v = float(t.replace(",", "."))
        except ValueError:
            return None
        if 5.0 <= v <= 500.0:
            return v
        return None

    def _on_zoom_combo_activated(self, index: int) -> None:
        if index < 0:
            return
        pct = self._parse_zoom_percent_text(self._zoom_combo.itemText(index))
        if pct is not None:
            self._dataflow_view.set_zoom_percent(pct)

    def _on_zoom_combo_return(self) -> None:
        pct = self._parse_zoom_percent_text(self._zoom_combo.currentText())
        if pct is not None:
            self._dataflow_view.set_zoom_percent(pct)
        else:
            self._sync_zoom_combo_from_view(self._dataflow_view.zoom_percent())

    def _sync_zoom_combo_from_view(self, percent: float) -> None:
        self._zoom_combo.blockSignals(True)
        self._zoom_combo.setCurrentText(f"{int(round(percent))}%")
        self._zoom_combo.blockSignals(False)

    def _build_main_layout(self, root_layout: QVBoxLayout) -> None:
        left_tabs = QTabWidget(self)
        left_tabs.setTabPosition(QTabWidget.TabPosition.East)
        left_tabs.addTab(self._panel_label("Resources"), "Resources")
        left_tabs.setMinimumWidth(140)

        canvas = QFrame(self)
        canvas.setFrameShape(QFrame.Shape.StyledPanel)
        canvas.setStyleSheet(f"background-color: {CANVAS_BACKGROUND_COLOR};")
        canvas.setMinimumWidth(260)
        canvas_layout = QVBoxLayout(canvas)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        self._dataflow_view = DataflowGraphicsView(self._diagram_scene, canvas)
        canvas_layout.addWidget(self._dataflow_view)

        self.right_tabs = QTabWidget(self)
        self.right_tabs.setTabPosition(QTabWidget.TabPosition.West)
        self.right_tabs.addTab(self._panel_label("Experiment"), "Experiment")
        self.right_tabs.setMinimumWidth(140)

        self.bottom_tabs = QTabWidget(self)
        self.bottom_tabs.addTab(self._build_console_panel(), "Console")
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

    def _refresh_diagram(self) -> None:
        populate_scene_from_model(self._diagram_scene, self._controller.model)

    def _panel_label(self, text: str) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel(text, widget))
        layout.addStretch(1)
        return widget

    def _build_console_panel(self) -> QWidget:
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self.console = _TerminalConsole(self._on_console_enter, self._history_prev, self._history_next, widget)
        self.console.setStyleSheet(
            "QTextEdit { background-color: #2f2f2f; color: #e0e0e0; "
            "font-family: Consolas, 'Courier New', monospace; }\n"
            + SCROLLBAR_STYLE_QSS
        )
        layout.addWidget(self.console, 1)

        self._append_console_line("synarius-core minimal CLI", self._get_output_color())
        self._append_console_line("Type 'help' for commands, 'exit' to quit.", self._get_output_color())
        self._show_prompt()
        return widget

    def _get_output_color(self) -> str:
        try:
            value = self._controller.model.root.get("output_color")
            if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                return value
        except Exception:
            pass
        return self._default_output_color

    def _show_prompt(self) -> None:
        prompt = str(self._controller.current.get("prompt_path"))
        self.console.show_prompt(f"{prompt}> ", DEFAULT_PROMPT_COLOR)

    def _append_console_line(self, text: str, color: str) -> None:
        self.console.append_output(text, color)

    def _on_console_enter(self, line: str) -> None:
        stripped = line.strip()
        if stripped == "":
            self._show_prompt()
            return
        self._history.push(line)

        if stripped in {"exit", "quit"}:
            self.close()
            return
        if stripped == "help":
            self._append_console_line("Built-in commands:", self._get_output_color())
            self._append_console_line("  help                    Show this help", self._get_output_color())
            self._append_console_line("  exit | quit             Exit CLI", self._get_output_color())
            self._append_console_line("  load <file.syn>         Load command-stack script", self._get_output_color())
            self._append_console_line("", self._get_output_color())
            self._append_console_line("Protocol commands:", self._get_output_color())
            self._append_console_line(
                "  ls, lsattr [-l], cd <path>, new ..., select ..., set ..., get ..., del ...",
                self._get_output_color(),
            )
            self._show_prompt()
            return

        try:
            result = self._controller.execute(stripped)
        except CommandError as exc:
            self._append_console_line(f"error: {exc}", ERROR_COLOR)
            self._show_prompt()
            return
        except Exception as exc:
            self._append_console_line(f"error: {exc}", ERROR_COLOR)
            self._show_prompt()
            return

        if result is not None and result != "":
            self._append_console_line(result, self._get_output_color())
        if stripped.lower().startswith("load "):
            self._refresh_diagram()
        self._show_prompt()

    def _history_prev(self) -> None:
        prev_line = self._history.prev()
        if prev_line is not None:
            self.console.replace_current_input(prev_line)

    def _history_next(self) -> None:
        self.console.replace_current_input(self._history.next())

    def _open_project(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Open Synarius Project",
            str(open_syn_dialog_start_dir()),
            "Synarius Project (*.syn *.json *.yaml);;All Files (*)",
        )
        if file_name:
            self.statusBar().showMessage(f"Opened: {file_name}")
            prompt = str(self._controller.current.get("prompt_path"))
            self._append_console_line(f'{prompt}> load "{file_name}"', DEFAULT_PROMPT_COLOR)
            try:
                result = self._controller.execute(f'load "{file_name}"')
                if result:
                    self._append_console_line(result, self._get_output_color())
                self._refresh_diagram()
            except Exception as exc:
                self._append_console_line(f"error: {exc}", ERROR_COLOR)
            self._show_prompt()
        else:
            self.statusBar().showMessage("Open canceled")

    def _save_project(self) -> None:
        file_name, _ = QFileDialog.getSaveFileName(
            self,
            "Save Synarius Project",
            str(open_syn_dialog_start_dir()),
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

