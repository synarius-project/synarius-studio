"""Left tab: model elements – Variables and parameter lookup instances with counts."""

from __future__ import annotations

from collections import defaultdict
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

from synarius_core.controller import SynariusController
from synarius_core.dataflow_sim._std_type_keys import STD_PARAM_LOOKUP
from synarius_core.model import ElementaryInstance

from .diagram.placement_interactive import LIBRARY_ELEMENT_NAMED_DRAG_MIME, VARIABLE_NAME_DRAG_MIME
from .parameters_tab_panel import _category_icon
from .resources_panel import RESOURCES_PANEL_FIXED_WIDTH, RESOURCES_PANEL_SIDE_MARGIN
from .theme import (
    LIBRARY_HEADER_BACKGROUND,
    LIBRARY_HEADER_SEPARATOR,
    LIBRARY_HEADER_TEXT,
    RESOURCES_PANEL_ALTERNATE_ROW,
    RESOURCES_PANEL_BACKGROUND,
    SELECTION_HIGHLIGHT,
    SELECTION_HIGHLIGHT_TEXT,
    qss_widget_id_background,
)

_TYPE_KEY_CATEGORY: dict[str, str] = {
    "std.Kennwert": "VALUE",
    "std.Kennlinie": "CURVE",
    "std.Kennfeld": "MAP",
}

_TYPE_KEY_ORDER: dict[str, int] = {
    "std.Kennwert": 0,
    "std.Kennlinie": 1,
    "std.Kennfeld": 2,
}

# Item-data roles stored on column-0 items.
_ROW_KIND_ROLE = Qt.ItemDataRole.UserRole        # "variable" | "param_lookup"
_ROW_DATA_ROLE = Qt.ItemDataRole.UserRole + 1    # variable name  |  type_key


class _ElementsDragTable(QTableWidget):
    """Rows carry kind/data roles; drag MIME type is chosen per row type."""

    def startDrag(self, supportedActions: Any) -> None:
        row = self.currentRow()
        if row < 0:
            return
        it = self.item(row, 0)
        if it is None:
            return
        kind = it.data(_ROW_KIND_ROLE)
        payload = it.data(_ROW_DATA_ROLE)
        if not payload:
            return
        drag = QDrag(self)
        mime = QMimeData()
        if kind == "param_lookup":
            type_key, inst_name = payload  # stored as (type_key, inst_name)
            mime.setData(LIBRARY_ELEMENT_NAMED_DRAG_MIME, f"{type_key}\0{inst_name}".encode("utf-8"))
        else:
            mime.setData(VARIABLE_NAME_DRAG_MIME, payload.encode("utf-8"))
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction, Qt.DropAction.CopyAction)


class VariablesTabPanel(QWidget):
    """Elements table: Variables and parameter lookup instances with instance counts."""

    def __init__(self, controller: SynariusController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self.setMinimumWidth(RESOURCES_PANEL_FIXED_WIDTH)
        self.setObjectName("syn_variables_tab_panel")
        self.setStyleSheet(qss_widget_id_background("syn_variables_tab_panel", RESOURCES_PANEL_BACKGROUND))

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
        el_title = QLabel("Element", self)
        el_title.setStyleSheet(title_style)
        el_title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        inst_title = QLabel("Instances", self)
        inst_title.setStyleSheet(title_style)
        inst_title.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header_layout.addWidget(el_title, 1)
        header_layout.addWidget(inst_title, 0)

        sep = QFrame(self)
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Plain)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {LIBRARY_HEADER_SEPARATOR}; border: none; max-height: 1px;")

        self._table = _ElementsDragTable(0, 2, self)
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
        model = self._controller.model

        # --- Variables (from the in-memory SQLAlchemy index) ---
        var_rows = model.variable_registry.rows_ordered_by_name()

        # --- Parameter lookup instances (Kennwert / Kennlinie / Kennfeld) ---
        param_counts: dict[tuple[str, str], int] = defaultdict(int)
        for obj in model.iter_objects():
            if isinstance(obj, ElementaryInstance) and obj.type_key in STD_PARAM_LOOKUP:
                if not model.is_in_trash_subtree(obj):
                    param_counts[(obj.name, obj.type_key)] += 1

        param_rows = sorted(
            param_counts.items(),
            key=lambda x: (_TYPE_KEY_ORDER.get(x[0][1], 99), x[0][0]),
        )

        total = len(var_rows) + len(param_rows)
        self._table.setRowCount(total)
        row_idx = 0

        # Variable rows (icons deferred to a future iteration)
        for name, count, _mapped in var_rows:
            name_item = QTableWidgetItem(name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name_item.setData(_ROW_KIND_ROLE, "variable")
            name_item.setData(_ROW_DATA_ROLE, name)
            count_item = QTableWidgetItem(str(count))
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            count_item.setFlags(count_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row_idx, 0, name_item)
            self._table.setItem(row_idx, 1, count_item)
            row_idx += 1

        # Parameter instance rows (with category icon from Parameters tab)
        for (inst_name, type_key), count in param_rows:
            category = _TYPE_KEY_CATEGORY.get(type_key, "VALUE")
            name_item = QTableWidgetItem(inst_name)
            name_item.setIcon(_category_icon(category))
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name_item.setData(_ROW_KIND_ROLE, "param_lookup")
            name_item.setData(_ROW_DATA_ROLE, (type_key, inst_name))
            count_item = QTableWidgetItem(str(count))
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            count_item.setFlags(count_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row_idx, 0, name_item)
            self._table.setItem(row_idx, 1, count_item)
            row_idx += 1


def build_variables_tab_panel(controller: SynariusController, parent: QWidget | None = None) -> VariablesTabPanel:
    return VariablesTabPanel(controller, parent)
