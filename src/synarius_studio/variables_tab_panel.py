"""Left tab: variable names and instance counts from the in-memory SQLAlchemy index."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QMimeData, Qt
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from synarius_core.controller import MinimalController

from .diagram.placement_interactive import VARIABLE_NAME_DRAG_MIME
from .resources_panel import RESOURCES_PANEL_FIXED_WIDTH, RESOURCES_PANEL_SIDE_MARGIN
from .theme import (
    LIBRARY_HEADER_BACKGROUND,
    LIBRARY_HEADER_SEPARATOR,
    LIBRARY_HEADER_TEXT,
    RESOURCES_PANEL_ALTERNATE_ROW,
    RESOURCES_PANEL_BACKGROUND,
    SELECTION_HIGHLIGHT,
    SELECTION_HIGHLIGHT_TEXT,
)


class _VariablesDragTable(QTableWidget):
    """Row drag supplies ``VARIABLE_NAME_DRAG_MIME`` for drops on the diagram view."""

    def startDrag(self, supportedActions: Any) -> None:
        row = self.currentRow()
        if row < 0:
            return
        it = self.item(row, 0)
        if it is None:
            return
        name = it.text().strip()
        if not name:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(VARIABLE_NAME_DRAG_MIME, name.encode("utf-8"))
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction, Qt.DropAction.CopyAction)


class VariablesTabPanel(QWidget):
    """Variable / Instances table with the same strip header style as library sections."""

    def __init__(self, controller: MinimalController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self.setFixedWidth(RESOURCES_PANEL_FIXED_WIDTH)
        self.setStyleSheet(f"background-color: {RESOURCES_PANEL_BACKGROUND};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget(self)
        header.setStyleSheet(f"background-color: {LIBRARY_HEADER_BACKGROUND};")
        header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        header.setMaximumHeight(34)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(RESOURCES_PANEL_SIDE_MARGIN, 0, RESOURCES_PANEL_SIDE_MARGIN, 3)
        header_layout.setSpacing(6)

        title_style = (
            f"font-weight: 600; font-size: 12px; color: {LIBRARY_HEADER_TEXT}; background: transparent;"
        )
        var_title = QLabel("Variable", self)
        var_title.setStyleSheet(title_style)
        var_title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        inst_title = QLabel("Instances", self)
        inst_title.setStyleSheet(title_style)
        inst_title.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header_layout.addWidget(var_title, 1)
        header_layout.addWidget(inst_title, 0)

        sep = QFrame(self)
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Plain)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {LIBRARY_HEADER_SEPARATOR}; border: none; max-height: 1px;")

        self._table = _VariablesDragTable(0, 2, self)
        self._table.setDragEnabled(True)
        self._table.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self._table.setDefaultDropAction(Qt.DropAction.IgnoreAction)
        self._table.horizontalHeader().setVisible(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setDefaultSectionSize(20)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setStyleSheet(
            f"QTableWidget {{ background-color: {RESOURCES_PANEL_BACKGROUND}; "
            f"alternate-background-color: {RESOURCES_PANEL_ALTERNATE_ROW}; border: none; font-size: 12px; }}"
            "QTableWidget::item { color: #000000; padding: 0px 4px; }"
            f"QTableWidget::item:selected {{ background-color: {SELECTION_HIGHLIGHT}; color: {SELECTION_HIGHLIGHT_TEXT}; }}"
        )
        layout.addWidget(header)
        layout.addWidget(sep)
        layout.addWidget(self._table, 1)

    def refresh(self) -> None:
        rows = self._controller.model.variable_registry.rows_ordered_by_name()
        self._table.setRowCount(len(rows))
        for i, (name, count) in enumerate(rows):
            name_item = QTableWidgetItem(name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            count_item = QTableWidgetItem(str(count))
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            count_item.setFlags(count_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(i, 0, name_item)
            self._table.setItem(i, 1, count_item)


def build_variables_tab_panel(controller: MinimalController, parent: QWidget | None = None) -> VariablesTabPanel:
    return VariablesTabPanel(controller, parent)
