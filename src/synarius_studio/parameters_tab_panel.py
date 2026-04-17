"""Left tab: parameter datasets displayed as an expandable tree with toolbar actions."""

from __future__ import annotations

import fnmatch
import shlex
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

from PySide6.QtCore import QByteArray, QMimeData, QRectF, Qt, QSize
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QDrag,
    QFont,
    QGuiApplication,
    QIcon,
    QImage,
    QPainter,
    QPixmap,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from synarius_core.controller import CommandError, SynariusController
from synarius_core.model.data_model import ComplexInstance
from synarius_core.parameters.repository import ParameterRecord

from .diagram.placement_interactive import LIBRARY_ELEMENT_NAMED_DRAG_MIME

from .resources_panel import RESOURCES_PANEL_FIXED_WIDTH
from .svg_icons import icon_from_tinted_svg_file, tint_breeze_symbolic_svg_markup
from .theme import (
    ACTIVE_DATASET_BACKGROUND,
    ACTIVE_DATASET_FOREGROUND,
    LIBRARY_HEADER_BACKGROUND,
    LIBRARY_HEADER_SEPARATOR,
    LIBRARY_HEADER_TEXT,
    RESOURCES_PANEL_ALTERNATE_ROW,
    RESOURCES_PANEL_BACKGROUND,
    SELECTION_HIGHLIGHT,
    SELECTION_HIGHLIGHT_TEXT,
    STUDIO_TOOLBAR_FOREGROUND,
    TOOLTIP_QSS,
    studio_toolbar_stylesheet,
    with_tooltip_qss,
)

# ---------------------------------------------------------------------------
# Icon helpers
# ---------------------------------------------------------------------------

_ICONS_DIR = Path(__file__).resolve().parent / "icons"

# Simple inline SVG for the Andreas-cross (delete) toolbar button.
_DELETE_SVG = (
    '<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg">'
    '<line x1="2" y1="2" x2="14" y2="14" stroke="#232629" stroke-width="2.2" stroke-linecap="round"/>'
    '<line x1="14" y1="2" x2="2" y2="14" stroke="#232629" stroke-width="2.2" stroke-linecap="round"/>'
    "</svg>"
)

# Inline SVG for "activate dataset" (checkmark / apply).
_APPLY_SVG = (
    '<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg">'
    '<polyline points="2,9 6,13 14,3" fill="none" stroke="#232629"'
    ' stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>'
    "</svg>"
)


def _icon_from_svg_markup(markup: str, *, side: int = 16, fg: QColor | None = None) -> QIcon:
    """Render an inline SVG string (optionally tinted) to a ``QIcon``."""
    text = tint_breeze_symbolic_svg_markup(markup, fg) if fg is not None else markup
    renderer = QSvgRenderer(QByteArray(text.encode("utf-8")))
    if not renderer.isValid():
        return QIcon()
    app = QGuiApplication.instance()
    dpr = 1.0
    if app is not None:
        screen = app.primaryScreen()
        if screen is not None:
            dpr = max(1.0, float(screen.devicePixelRatio()))
    px = max(1, int(round(side * dpr)))
    img = QImage(px, px, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter, QRectF(0.0, 0.0, float(px), float(px)))
    painter.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return QIcon(pm)


def _icon_from_svg_path(path: Path, *, side: int = 16) -> QIcon:
    """Render an SVG file without tinting (for coloured category icons)."""
    if not path.is_file():
        return QIcon()
    renderer = QSvgRenderer(str(path))
    if not renderer.isValid():
        return QIcon()
    app = QGuiApplication.instance()
    dpr = 1.0
    if app is not None:
        screen = app.primaryScreen()
        if screen is not None:
            dpr = max(1.0, float(screen.devicePixelRatio()))
    px = max(1, int(round(side * dpr)))
    img = QImage(px, px, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter, QRectF(0.0, 0.0, float(px), float(px)))
    painter.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return QIcon(pm)


def _parawiz_icons_dir() -> Path | None:
    """Return the synarius_parawiz icons directory, or ``None`` if not installed."""
    try:
        import synarius_parawiz as _pkg  # pyright: ignore[reportMissingImports]

        d = Path(_pkg.__file__).resolve().parent / "icons"
        return d if d.is_dir() else None
    except ImportError:
        return None


_CATEGORY_ICON_CACHE: dict[str, QIcon] = {}

_CATEGORY_FILES: dict[str, str] = {
    "VALUE": "value.svg",
    "CURVE": "curve.svg",
    "MAP": "map.svg",
    "MATRIX": "matrix.svg",
    "ARRAY": "array.svg",
    "NODE_ARRAY": "array.svg",
    "ASCII": "value.svg",
}


def _parameter_name_matches_filter(name: str, pattern: str) -> bool:
    """Substring match; if the pattern contains ``*`` or ``?``, use shell-style glob (case-insensitive)."""
    p = pattern.strip()
    if not p:
        return True
    nl = name.lower()
    pl = p.lower()
    if "*" in pl or "?" in pl:
        return fnmatch.fnmatch(nl, pl)
    return pl in nl


def _category_icon(category: str) -> QIcon:
    """Load the ParaWiz-style category icon for *category* (16 × 16 px, no tint)."""
    cat_u = str(category).upper()
    if cat_u in _CATEGORY_ICON_CACHE:
        return _CATEGORY_ICON_CACHE[cat_u]
    icon = QIcon()
    fn = _CATEGORY_FILES.get(cat_u, "value.svg")
    icons_dir = _parawiz_icons_dir()
    if icons_dir is not None:
        p = icons_dir / fn
        if p.is_file():
            icon = _icon_from_svg_path(p, side=16)
    if icon.isNull():
        # Fall back: use Kennlinie / Kennfeld / Kennwert icons from standard library.
        try:
            from synarius_core.standard_library import standard_library_root

            _comp_map = {"VALUE": "Kennwert", "CURVE": "Kennlinie", "MAP": "Kennfeld"}
            comp = _comp_map.get(cat_u)
            if comp:
                p = (
                    standard_library_root()
                    / "components"
                    / comp
                    / "resources"
                    / "icons"
                    / f"{fn.split('.')[0]}_16.svg"
                )
                if p.is_file():
                    icon = _icon_from_svg_path(p, side=16)
        except Exception:
            pass
    _CATEGORY_ICON_CACHE[cat_u] = icon
    return icon


# ---------------------------------------------------------------------------
# Tree-widget item roles
# ---------------------------------------------------------------------------
_ROLE_DS_NAME = Qt.ItemDataRole.UserRole          # dataset name (str)
_ROLE_PARAM_NAME = Qt.ItemDataRole.UserRole + 1  # parameter name (str)
_ROLE_PARAM_ID = Qt.ItemDataRole.UserRole + 2    # parameter UUID (str)
_ROLE_KIND = Qt.ItemDataRole.UserRole + 3        # "dataset" | "param" | "search" | "_ph_"
_ROLE_PARAM_CATEGORY = Qt.ItemDataRole.UserRole + 4  # parameter category (str)

# Canvas-draggable categories and their std type_keys.
_DRAG_CATEGORY_TYPE_KEY: dict[str, str] = {
    "VALUE": "std.Kennwert",
    "CURVE": "std.Kennlinie",
    "MAP":   "std.Kennfeld",
}


class _ParamDragTree(QTreeWidget):
    """QTreeWidget that initiates a ``LIBRARY_ELEMENT_NAMED_DRAG_MIME`` drag for VALUE/CURVE/MAP items."""

    def startDrag(self, supported_actions: Qt.DropAction) -> None:  # type: ignore[override]
        item = self.currentItem()
        if item is None or item.data(0, _ROLE_KIND) != "param":
            return
        category = str(item.data(0, _ROLE_PARAM_CATEGORY) or "")
        type_key = _DRAG_CATEGORY_TYPE_KEY.get(category.upper())
        if type_key is None:
            return  # MATRIX / ARRAY / ASCII — not canvas-draggable
        param_name = str(item.data(0, _ROLE_PARAM_NAME) or "")
        if not param_name:
            return
        mime = QMimeData()
        mime.setData(
            LIBRARY_ELEMENT_NAMED_DRAG_MIME,
            f"{type_key}\0{param_name}".encode("utf-8"),
        )
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)

# ---------------------------------------------------------------------------
# Tree stylesheet
# ---------------------------------------------------------------------------
_TREE_QSS = with_tooltip_qss(
    f"QTreeWidget {{ background-color: {RESOURCES_PANEL_BACKGROUND}; "
    f"alternate-background-color: {RESOURCES_PANEL_ALTERNATE_ROW}; "
    "border: none; font-size: 12px; outline: 0; }}"
    "QTreeWidget::item { color: #000000; padding: 1px 4px; }"
    f"QTreeWidget::item:selected {{ background-color: {SELECTION_HIGHLIGHT};"
    f" color: {SELECTION_HIGHLIGHT_TEXT}; }}"
)


# ---------------------------------------------------------------------------
# Shared parameter viewer (used by ParametersTabPanel and canvas double-click)
# ---------------------------------------------------------------------------


def open_parameter_viewer_for_record(
    record: ParameterRecord,
    parent: QWidget | None = None,
    *,
    on_write_back: Callable[[Any, dict[int, Any]], None] | None = None,
) -> None:
    """Open the synariustools CalibrationMap viewer/editor for *record*.

    Falls back to a plain-text dialog when synariustools is not installed.
    This function is the single implementation shared by the parameter panel
    tree (double-click on a parameter row) and the canvas (double-click on a
    Kennwert / Kennlinie / Kennfeld block).

    Parameters
    ----------
    on_write_back:
        When provided, the dialog opens in **edit mode**.  Called on commit
        with ``(values: np.ndarray, axes: dict[int, np.ndarray])``.
        ``None`` → read-only view.
    """
    try:
        from synariustools.tools.calmapwidget import (  # type: ignore[import-untyped]
            CalibrationMapData,
            build_scalar_calibration_readonly_widget,
            create_calibration_map_viewer,
            exec_scalar_calibration_edit_dialog,
            supports_calibration_plot,
            supports_calibration_scalar_edit,
        )
    except ImportError:
        dlg = QDialog(parent, Qt.WindowType.Window)
        dlg.setWindowTitle(f"{record.name}  [{record.category}]")
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        lay = QVBoxLayout(dlg)
        te = QPlainTextEdit(dlg)
        te.setReadOnly(True)
        te.setPlainText(
            record.text_value if record.is_text
            else f"Shape: {record.values.shape}\n\n{record.values!r}"
        )
        te.setStyleSheet("font-family: monospace; font-size: 12px;")
        lay.addWidget(te)
        dlg.resize(420, 280)
        dlg.show()
        return

    import numpy as np
    data = CalibrationMapData.from_parameter_record(record)

    if on_write_back is not None and supports_calibration_scalar_edit(record):
        # Modal scalar editor; returns new value or None on cancel.
        new_val = exec_scalar_calibration_edit_dialog(parent, data)
        if new_val is not None:
            on_write_back(np.asarray(new_val, dtype=np.float64), {})
        return

    dlg = QDialog(parent, Qt.WindowType.Window)
    dlg.setWindowTitle(f"{record.name}  [{record.category}]")
    dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)

    if supports_calibration_scalar_edit(record):
        # Read-only scalar view (on_write_back is None).
        w = build_scalar_calibration_readonly_widget(dlg, data)
        lay.addWidget(w)
        dlg.resize(320, 180)
    elif supports_calibration_plot(record):
        # Kennlinie / Kennfeld: editable when on_write_back is provided.
        _wb = on_write_back

        def _on_applied(widget: Any) -> None:
            if _wb is not None:
                values, axes = widget.applied_values_and_axes()
                _wb(values, axes)

        shell = create_calibration_map_viewer(
            data,
            parent=dlg,
            embedded=True,
            on_applied_to_model=_on_applied if on_write_back is not None else None,
        )
        if hasattr(shell, "attach_dialog_close_guard"):
            shell.attach_dialog_close_guard(dlg)
        lay.addWidget(shell, 1)
        sh = shell.sizeHint()
        dlg.resize(sh.width(), sh.height())
    else:
        te = QPlainTextEdit(dlg)
        te.setReadOnly(True)
        te.setPlainText(record.text_value)
        te.setStyleSheet("font-family: monospace; font-size: 12px;")
        lay.addWidget(te)
        dlg.resize(420, 280)

    dlg.show()
    dlg.raise_()
    dlg.activateWindow()


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------
class ParametersTabPanel(QWidget):
    """Parameter-datasets tree with toolbar (load / activate / delete) for the left panel."""

    def __init__(
        self,
        controller: SynariusController,
        execute_fn: Callable[[str], str | None],
        parent: QWidget | None = None,
        *,
        on_param_written: Callable[[UUID], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._execute = execute_fn
        self._on_param_written = on_param_written
        self.setMinimumWidth(RESOURCES_PANEL_FIXED_WIDTH)
        self.setObjectName("syn_parameters_tab_panel")
        self.setStyleSheet(
            f"QWidget#syn_parameters_tab_panel {{ background-color: {RESOURCES_PANEL_BACKGROUND}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Toolbar ──────────────────────────────────────────────────────────
        tb = QToolBar(self)
        tb.setMovable(False)
        tb.setIconSize(QSize(16, 16))
        tb.setStyleSheet(studio_toolbar_stylesheet(background_color=LIBRARY_HEADER_BACKGROUND))
        tb.setFixedHeight(34)

        fg = QColor(STUDIO_TOOLBAR_FOREGROUND)

        # Load action
        self._act_load = QAction("Load parameter file…", self)
        load_icon_path = _ICONS_DIR / "document-open-folder-symbolic.svg"
        if load_icon_path.is_file():
            self._act_load.setIcon(icon_from_tinted_svg_file(load_icon_path, fg, logical_side=16))
        self._act_load.setToolTip("Load parameter file (DCM / CDFX) into a new dataset")
        self._act_load.triggered.connect(self._on_load_clicked)

        # Activate action
        self._act_activate = QAction("Set as active dataset", self)
        self._act_activate.setIcon(_icon_from_svg_markup(_APPLY_SVG, side=16, fg=fg))
        self._act_activate.setToolTip("Make the selected dataset the active dataset")
        self._act_activate.triggered.connect(self._on_activate_clicked)

        # Delete action (Andreas cross)
        self._act_delete = QAction("Delete selected dataset", self)
        self._act_delete.setIcon(_icon_from_svg_markup(_DELETE_SVG, side=16, fg=fg))
        self._act_delete.setToolTip("Delete the selected parameter dataset")
        self._act_delete.triggered.connect(self._on_delete_clicked)

        tb.addAction(self._act_load)
        tb.addAction(self._act_activate)
        tb.addAction(self._act_delete)

        # ── Tree ─────────────────────────────────────────────────────────────
        self._tree = _ParamDragTree(self)
        self._tree.setColumnCount(1)
        self._tree.setHeaderHidden(True)
        self._tree.header().hide()
        self._tree.setRootIsDecorated(True)
        self._tree.setIndentation(14)
        self._tree.setAlternatingRowColors(True)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._tree.setDragEnabled(True)
        self._tree.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self._tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._tree.setUniformRowHeights(False)
        self._tree.setStyleSheet(_TREE_QSS)
        self._tree.header().setStretchLastSection(False)
        self._tree.header().setMinimumSectionSize(1)
        self._tree.itemExpanded.connect(self._on_item_expanded)
        self._tree.itemCollapsed.connect(self._on_item_collapsed)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._tree.verticalScrollBar().rangeChanged.connect(self._update_search_margins)

        self._search_edits: list[QLineEdit] = []
        self._search_containers: list[QWidget] = []

        layout.addWidget(tb, 0)
        layout.addWidget(self._tree, 1)

    # ── Resize helper ─────────────────────────────────────────────────────
    def resizeEvent(self, event: Any) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._adjust_column_widths()

    def _adjust_column_widths(self) -> None:
        self._tree.setColumnWidth(0, self._tree.viewport().width())

    def _update_search_margins(self, *_: object) -> None:
        """Shift search fields right to clear the vertical scrollbar when it is active."""
        sb = self._tree.verticalScrollBar()
        # Use maximum() > 0 — more reliable than isVisible() inside rangeChanged.
        # sizeHint().width() gives the correct scrollbar width even before it is painted.
        margin = sb.sizeHint().width() if sb.maximum() > 0 else 0
        for container in self._search_containers:
            lay = container.layout()
            if lay is not None:
                lay.setContentsMargins(0, 0, margin, 0)

    # ── Refresh ───────────────────────────────────────────────────────────
    def refresh(self) -> None:
        """Repopulate the tree from the current model state."""
        # Remember which datasets were expanded.
        expanded: set[str] = set()
        for i in range(self._tree.topLevelItemCount()):
            it = self._tree.topLevelItem(i)
            if it is not None and it.isExpanded():
                ds_name = it.data(0, _ROLE_DS_NAME)
                if ds_name:
                    expanded.add(str(ds_name))

        sel_ds: str | None = self._selected_dataset_name()

        # Phase 1: rebuild skeleton with signals blocked (no setItemWidget here).
        self._search_edits.clear()
        self._search_containers.clear()
        self._tree.blockSignals(True)
        self._tree.clear()

        datasets = self._fetch_datasets()
        active_name = self._active_dataset_name()
        for ds in datasets:
            ds_item = self._make_dataset_item(ds, active_name)
            self._tree.addTopLevelItem(ds_item)

        self._tree.blockSignals(False)
        self._adjust_column_widths()

        # Phase 2: fill children and restore expansion.
        # Iterate the already-fetched list directly — no second model lookup needed.
        for i, ds in enumerate(datasets):
            ds_item = self._tree.topLevelItem(i)
            if ds_item is None:
                continue
            self._populate_dataset_children(ds, ds_item)
            if ds.name in expanded:
                ds_item.setExpanded(True)

        if sel_ds is not None:
            self._select_dataset_item(sel_ds)

    # ── Dataset item factory ──────────────────────────────────────────────
    def _make_dataset_item(self, ds: ComplexInstance, active_name: str | None) -> QTreeWidgetItem:
        it = QTreeWidgetItem()
        name = ds.name
        is_active = (name == active_name)

        it.setData(0, _ROLE_DS_NAME, name)
        it.setData(0, _ROLE_KIND, "dataset")
        it.setText(0, name)
        it.setToolTip(0, name)

        if is_active:
            bold = QFont()
            bold.setBold(True)
            it.setFont(0, bold)
            it.setBackground(0, QBrush(QColor(ACTIVE_DATASET_BACKGROUND)))
            it.setForeground(0, QColor(ACTIVE_DATASET_FOREGROUND))

        return it

    # ── Children: search + parameters ────────────────────────────────────
    def _populate_dataset_children(self, ds: ComplexInstance, ds_item: QTreeWidgetItem) -> None:
        ds_item.takeChildren()

        if ds.id is None:
            ds_item.addChild(QTreeWidgetItem(["(no id)"]))
            return

        param_ids: list = []
        summaries: dict = {}
        try:
            rt = self._controller.model.parameter_runtime()
            repo = rt.repo
            param_ids = repo.list_parameter_ids_for_data_set(ds.id)
            summaries = repo.get_parameter_table_summaries_for_ids(param_ids)
        except Exception as exc:
            ds_item.addChild(QTreeWidgetItem([f"Error: {exc}"]))
            return

        # ── Search row at index 0 ────────────────────────────────────────────
        search_item = QTreeWidgetItem()
        search_item.setData(0, _ROLE_KIND, "search")
        search_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        search_item.setSizeHint(0, QSize(0, 24))
        ds_item.addChild(search_item)
        # Wrap the QLineEdit in a container so the layout margin (not QSS margin)
        # provides the gap for the scrollbar — trailing actions stay inside the edit.
        container = QWidget()
        container.setStyleSheet(f"background-color: {RESOURCES_PANEL_BACKGROUND};")
        c_layout = QHBoxLayout(container)
        c_layout.setContentsMargins(0, 0, 0, 0)
        c_layout.setSpacing(0)
        search_edit = QLineEdit()
        search_edit.setPlaceholderText("Filter… (* ? Wildcards)")
        search_edit.setToolTip("Filter… (* ? Wildcards)")
        search_edit.setStyleSheet(with_tooltip_qss(
            "QLineEdit { border: 1px solid #000000; padding: 2px 4px; "
            "font-size: 11px; background: #ffffff; color: #000000; }"
        ))
        clear_action = QAction(search_edit)
        clear_action.setIcon(_icon_from_svg_markup(_DELETE_SVG, side=10))
        clear_action.setToolTip("Filter löschen")
        clear_action.setVisible(False)
        search_edit.addAction(clear_action, QLineEdit.ActionPosition.TrailingPosition)
        clear_action.triggered.connect(lambda: search_edit.setText("*"))
        search_edit.textChanged.connect(lambda text: clear_action.setVisible(text != "*"))
        search_edit.textChanged.connect(
            lambda text, item=ds_item: self._filter_parameters(text, item)
        )
        search_edit.setText("*")
        c_layout.addWidget(search_edit)
        self._search_edits.append(search_edit)
        self._search_containers.append(container)
        self._tree.setItemWidget(search_item, 0, container)
        self._update_search_margins()

        if not param_ids:
            ds_item.addChild(QTreeWidgetItem(["(empty dataset)"]))
            return

        for pid in param_ids:
            summary = summaries.get(pid)
            if summary is None:
                continue
            p_item = QTreeWidgetItem()
            p_item.setData(0, _ROLE_KIND, "param")
            p_item.setData(0, _ROLE_DS_NAME, ds.name)
            p_item.setData(0, _ROLE_PARAM_NAME, summary.name)
            p_item.setData(0, _ROLE_PARAM_ID, str(pid))
            p_item.setData(0, _ROLE_PARAM_CATEGORY, summary.category)
            p_item.setText(0, summary.name)
            p_item.setToolTip(0, summary.name)
            p_item.setIcon(0, _category_icon(summary.category))
            p_item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.DontShowIndicator)
            ds_item.addChild(p_item)

    def _filter_parameters(self, text: str, ds_item: QTreeWidgetItem) -> None:
        """Show only parameter rows whose name matches *text* (supports * and ? wildcards)."""
        for i in range(1, ds_item.childCount()):  # skip search row at index 0
            child = ds_item.child(i)
            if child is None:
                continue
            child.setHidden(not _parameter_name_matches_filter(child.text(0), text))

    # ── Tree signal handlers ──────────────────────────────────────────────
    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        self._adjust_column_widths()

    def _on_item_collapsed(self, item: QTreeWidgetItem) -> None:
        # Reset the search field so stale filters don't survive collapse.
        search_item = item.child(0)
        if search_item is not None:
            widget = self._tree.itemWidget(search_item, 0)
            # itemWidget is now a container QWidget; find the QLineEdit inside.
            edit = widget.findChild(QLineEdit) if isinstance(widget, QWidget) else None
            if isinstance(edit, QLineEdit):
                edit.setText("*")

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        kind = item.data(0, _ROLE_KIND)
        if kind == "search":
            return
        if kind != "param":
            return
        param_id_str = item.data(0, _ROLE_PARAM_ID)
        if not param_id_str:
            return
        try:
            pid = UUID(param_id_str)
            rt = self._controller.model.parameter_runtime()
            record = rt.repo.get_record(pid)
        except Exception as exc:
            QMessageBox.warning(self, "Parameter", f"Could not load parameter data:\n{exc}")
            return
        self._open_parameter_editor(pid, record)

    def _open_parameter_editor(self, pid: UUID, record: ParameterRecord) -> None:
        rt = self._controller.model.parameter_runtime()
        _notify = self._on_param_written

        def _write_back(values: Any, axes: dict[int, Any]) -> None:
            import numpy as np
            rt.repo.set_value(pid, np.asarray(values, dtype=np.float64))
            for axis_idx, ax_vals in axes.items():
                rt.repo.set_axis_values(pid, axis_idx, np.asarray(ax_vals, dtype=np.float64))
            if _notify is not None:
                _notify(pid)

        open_parameter_viewer_for_record(record, self, on_write_back=_write_back)

    # ── Toolbar action handlers ───────────────────────────────────────────
    def _on_load_clicked(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Load parameter file",
            "",
            "Parameter files (*.dcm *.cdfx);;DCM files (*.dcm);;All files (*)",
        )
        if not path_str:
            return
        path = Path(path_str)
        cli_path = path_str.replace("\\", "/")
        name = path.stem
        fmt = path.suffix.lstrip(".").lower() or "unknown"
        saved_cwd = self._controller.current
        try:
            self._execute("cd @main/parameters/data_sets")
            ds_name = (
                self._execute(
                    f"new DataSet {shlex.quote(name)}"
                    f" source_path={shlex.quote(cli_path)}"
                    f" source_format={fmt}"
                )
                or name
            ).strip()
            if fmt == "dcm":
                self._execute(f"import -dcm={shlex.quote(cli_path)} {shlex.quote(ds_name)}")
        except CommandError as exc:
            QMessageBox.warning(self, "Load failed", str(exc))
        except Exception as exc:
            QMessageBox.warning(self, "Load failed", str(exc))
        finally:
            self._controller.current = saved_cwd
        self.refresh()

    def _on_activate_clicked(self) -> None:
        ds_name = self._selected_dataset_name()
        if not ds_name:
            QMessageBox.information(self, "Activate dataset", "Select a dataset first.")
            return
        saved_cwd = self._controller.current
        try:
            self._execute("cd @main/parameters")
            self._execute(f"set active_dataset_name {shlex.quote(ds_name)}")
        except CommandError as exc:
            QMessageBox.warning(self, "Activate failed", str(exc))
        except Exception as exc:
            QMessageBox.warning(self, "Activate failed", str(exc))
        finally:
            self._controller.current = saved_cwd
        self.refresh()

    def _on_delete_clicked(self) -> None:
        ds_name = self._selected_dataset_name()
        if not ds_name:
            QMessageBox.information(self, "Delete dataset", "Select a dataset first.")
            return
        ret = QMessageBox.question(
            self,
            "Delete dataset",
            f"Delete parameter dataset '{ds_name}' and all its parameters?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        try:
            self._execute(
                f"del @main/parameters/data_sets/{shlex.quote(ds_name)}"
            )
        except CommandError as exc:
            QMessageBox.warning(self, "Delete failed", str(exc))
        except Exception as exc:
            QMessageBox.warning(self, "Delete failed", str(exc))
        self.refresh()

    # ── Helpers ───────────────────────────────────────────────────────────
    def _selected_dataset_name(self) -> str | None:
        item = self._tree.currentItem()
        if item is None:
            return None
        kind = item.data(0, _ROLE_KIND)
        if kind == "dataset":
            return item.data(0, _ROLE_DS_NAME)
        # For param / search items return the parent dataset name.
        parent = item.parent()
        if parent is not None:
            return parent.data(0, _ROLE_DS_NAME)
        return None

    def _select_dataset_item(self, ds_name: str) -> None:
        for i in range(self._tree.topLevelItemCount()):
            it = self._tree.topLevelItem(i)
            if it is not None and it.data(0, _ROLE_DS_NAME) == ds_name:
                self._tree.setCurrentItem(it)
                return

    def _fetch_datasets(self) -> list[ComplexInstance]:
        try:
            rt = self._controller.model.parameter_runtime()
            root = rt.data_sets_root()
            return [c for c in root.children if isinstance(c, ComplexInstance)]
        except Exception:
            return []

    def _active_dataset_name(self) -> str | None:
        try:
            rt = self._controller.model.parameter_runtime()
            ad = rt.active_dataset()
            return ad.name if ad is not None else None
        except Exception:
            return None

    def _find_dataset_by_name(self, name: str | None) -> ComplexInstance | None:
        if not name:
            return None
        for ds in self._fetch_datasets():
            if ds.name == name:
                return ds
        return None


def build_parameters_tab_panel(
    controller: SynariusController,
    execute_fn: Callable[[str], str | None],
    parent: QWidget | None = None,
    *,
    on_param_written: Callable[[UUID], None] | None = None,
) -> ParametersTabPanel:
    return ParametersTabPanel(controller, execute_fn, parent, on_param_written=on_param_written)
