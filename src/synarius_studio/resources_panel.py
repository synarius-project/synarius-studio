"""Resources tab: FMF libraries as collapsible sections with canvas-style element previews."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QDrag, QPainter, QPen
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from synarius_core.controller import SynariusController
from synarius_core.library import ParsedElement, ParsedLibrary

from .diagram.placement_interactive import LIBRARY_ELEMENT_DRAG_MIME
from .theme import (
    LIBRARY_HEADER_BACKGROUND,
    LIBRARY_HEADER_BUTTON_HOVER,
    LIBRARY_HEADER_SEPARATOR,
    LIBRARY_HEADER_TEXT,
    RESOURCES_PANEL_BACKGROUND,
    qss_widget_id_background,
)

# Canvas drawing constants (kept in sync with dataflow_items.py).
_BLOCK_FILL = QColor(255, 255, 255)
_BLOCK_OUTLINE_COLOR = QColor(45, 45, 45)
_BLOCK_OUTLINE_WIDTH = 2.7  # matches BLOCK_OUTLINE_WIDTH in dataflow_items.py

# Tile geometry — matches canvas proportions at 100 % zoom.
# OPERATOR_SIZE on canvas = 3 * MODULE = 3 * 10.5 = 31.5 px.
# SVG_SYMBOL_SIZE on canvas = 27.0 px (glyph rendered inside the block).
RESOURCES_TILE_SIZE = 38      # outer widget size: OPERATOR_SIZE + 2 * _TILE_MARGIN = 31.5 + 6.5 ≈ 38
_TILE_MARGIN = 3              # gap from widget edge to block rect
_GLYPH_SIZE = 27.0            # canonical glyph size matching SVG_SYMBOL_SIZE on canvas

# Grid layout constants.
RESOURCES_ICON_H_SPACING = 6
RESOURCES_ICON_V_SPACING = 6
RESOURCES_GRID_MARGIN = 6

# Minimum and default panel width (exported so main_window.py can use it as initial splitter size).
RESOURCES_PANEL_MIN_WIDTH = (
    3 * RESOURCES_TILE_SIZE + 2 * RESOURCES_ICON_H_SPACING + 2 * RESOURCES_GRID_MARGIN + 24
)
# Legacy aliases used by variables_tab_panel.py and other callers.
RESOURCES_PANEL_FIXED_WIDTH = RESOURCES_PANEL_MIN_WIDTH
RESOURCES_PANEL_SIDE_MARGIN = 10


def _read_icon16_relative_path(element_dir: Path) -> str | None:
    """Return relative SVG path from ``elementDescription.xml`` ``<Graphics icon16="..."/>``."""
    xml_path = element_dir / "elementDescription.xml"
    if not xml_path.is_file():
        return None
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError:
        return None
    root = tree.getroot()
    if root.tag != "ElementDescription":
        return None
    for child in root:
        if child.tag != "Graphics":
            continue
        icon = child.attrib.get("icon16") or child.attrib.get("icon") or child.attrib.get("diagram_icon")
        if icon:
            return icon
    return None


def _load_svg_renderer(element: ParsedElement) -> QSvgRenderer | None:
    """Return a ``QSvgRenderer`` for *element*'s icon SVG, or ``None`` if unavailable."""
    rel = _read_icon16_relative_path(element.element_dir)
    if not rel:
        return None
    svg_path = (element.element_dir / rel).resolve()
    if not svg_path.is_file() or svg_path.suffix.lower() != ".svg":
        return None
    renderer = QSvgRenderer(str(svg_path))
    return renderer if renderer.isValid() else None


class LibraryBlockTile(QWidget):
    """
    Canvas-style element preview tile: white block body with dark border, element SVG inside.

    Visually matches the element as drawn on the diagram canvas (same fill, same outline weight,
    same glyph), but without pin stubs.  Supports drag-to-canvas via ``LIBRARY_ELEMENT_DRAG_MIME``.
    """

    def __init__(
        self,
        type_key: str,
        tooltip: str,
        renderer: QSvgRenderer | None,
        tile_size: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._type_key = type_key
        self._renderer = renderer
        self._drag_start: QPoint | None = None
        self.setFixedSize(tile_size, tile_size)
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._paint_block(painter)
        self._paint_content(painter)
        painter.end()

    def _paint_block(self, painter: QPainter) -> None:
        m = float(_TILE_MARGIN)
        block = QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m)
        painter.fillRect(block, _BLOCK_FILL)
        pen = QPen(_BLOCK_OUTLINE_COLOR, _BLOCK_OUTLINE_WIDTH)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(block)

    def _paint_content(self, painter: QPainter) -> None:
        if self._renderer is not None:
            self._paint_svg(painter)
        else:
            self._paint_fallback(painter)

    def _paint_svg(self, painter: QPainter) -> None:
        # Centre the canonical glyph inside the tile — matches SVG_SYMBOL_SIZE on canvas.
        pad_x = (self.width() - _GLYPH_SIZE) / 2.0
        pad_y = (self.height() - _GLYPH_SIZE) / 2.0
        glyph = QRectF(pad_x, pad_y, _GLYPH_SIZE, _GLYPH_SIZE)
        if glyph.width() > 0 and glyph.height() > 0:
            self._renderer.render(painter, glyph)  # type: ignore[union-attr]

    def _paint_fallback(self, painter: QPainter) -> None:
        pad = _TILE_MARGIN + _BLOCK_OUTLINE_WIDTH / 2 + 2
        r = QRectF(pad, pad, self.width() - 2 * pad, self.height() - 2 * pad)
        pen = QPen(QColor(180, 180, 180), 1.5)
        painter.setPen(pen)
        painter.drawLine(r.topLeft(), r.bottomRight())
        painter.drawLine(r.topRight(), r.bottomLeft())

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._drag_start is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        if (event.position().toPoint() - self._drag_start).manhattanLength() < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return
        self._start_drag()
        self._drag_start = None

    def _start_drag(self) -> None:
        drag = QDrag(self)
        md = QMimeData()
        md.setData(LIBRARY_ELEMENT_DRAG_MIME, self._type_key.encode("utf-8"))
        drag.setMimeData(md)
        drag.exec(Qt.DropAction.CopyAction)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        self._drag_start = None
        super().mouseReleaseEvent(event)


class _AdaptiveBlockGrid(QWidget):
    """
    Grid of ``LibraryBlockTile`` widgets that reflows columns on resize.

    On each ``resizeEvent`` the column count is recomputed from the available width so that
    tiles fill the panel without horizontal overflow or a fixed column count.
    """

    def __init__(
        self,
        tiles: list[LibraryBlockTile],
        tile_size: int,
        h_spacing: int,
        v_spacing: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tiles = tiles
        self._tile_size = tile_size
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self._current_cols = 0
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self._grid = QGridLayout(self)
        self._grid.setHorizontalSpacing(h_spacing)
        self._grid.setVerticalSpacing(v_spacing)
        self._grid.setContentsMargins(
            RESOURCES_GRID_MARGIN, RESOURCES_GRID_MARGIN,
            RESOURCES_GRID_MARGIN, RESOURCES_GRID_MARGIN,
        )
        self._rebuild(3)

    def minimumSizeHint(self) -> QSize:
        # Allow the widget to shrink to a single column so that resizeEvent
        # fires with the true available width even when the panel is narrowed.
        min_w = self._tile_size + 2 * RESOURCES_GRID_MARGIN
        return QSize(min_w, super().minimumSizeHint().height())

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        avail = self.width() - 2 * RESOURCES_GRID_MARGIN
        cols = max(1, (avail + self._h_spacing) // (self._tile_size + self._h_spacing))
        if cols != self._current_cols:
            self._rebuild(cols)

    def _rebuild(self, cols: int) -> None:
        self._current_cols = cols
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        for i, tile in enumerate(self._tiles):
            row, col = divmod(i, cols)
            self._grid.addWidget(tile, row, col, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.updateGeometry()


class CollapsibleSection(QWidget):
    """Simple expand/collapse block with a header row and content widget."""

    _OPEN_GLYPH = "\u25bc"    # ▼
    _CLOSED_GLYPH = "\u25b6"  # ▶

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._content = QWidget(self)
        self._content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)
        _content_id = f"syn_lib_section_body_{id(self):x}"
        self._content.setObjectName(_content_id)
        self._content.setStyleSheet(qss_widget_id_background(_content_id, RESOURCES_PANEL_BACKGROUND))

        btn_style = (
            f"QToolButton {{ background-color: {LIBRARY_HEADER_BACKGROUND}; color: {LIBRARY_HEADER_TEXT}; "
            f"border: none; font-size: 10px; min-width: 18px; max-width: 22px; "
            f"min-height: 18px; max-height: 20px; padding: 0px; }}"
            f"QToolButton:hover {{ background-color: {LIBRARY_HEADER_BUTTON_HOVER}; }}"
        )
        self._toggle = QToolButton(self)
        self._toggle.setCheckable(True)
        self._toggle.setChecked(True)
        self._toggle.setAutoRaise(True)
        self._toggle.setText(self._OPEN_GLYPH)
        self._toggle.setToolTip("Einklappen / Ausklappen")
        self._toggle.setStyleSheet(btn_style)
        self._toggle.toggled.connect(self._on_toggled)

        title_lbl = QLabel(title, self)
        title_lbl.setStyleSheet(
            f"font-weight: 600; font-size: 12px; color: {LIBRARY_HEADER_TEXT}; background: transparent;"
        )
        title_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        header = QWidget(self)
        header.setStyleSheet(f"background-color: {LIBRARY_HEADER_BACKGROUND};")
        header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        header.setMaximumHeight(34)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 3)
        header_layout.setSpacing(6)
        header_layout.addWidget(self._toggle, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header_layout.addWidget(title_lbl, 1)

        line = QFrame(self)
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Plain)
        line.setFixedHeight(1)
        line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        line.setStyleSheet(f"background-color: {LIBRARY_HEADER_SEPARATOR}; border: none; max-height: 1px;")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(header)
        outer.addWidget(line)
        outer.addWidget(self._content)

    def _on_toggled(self, expanded: bool) -> None:
        self._content.setVisible(expanded)
        self._toggle.setText(self._OPEN_GLYPH if expanded else self._CLOSED_GLYPH)

    def content_layout(self) -> QVBoxLayout:
        return self._content_layout


def _library_section_title(lib: ParsedLibrary) -> str:
    v = lib.version.strip()
    if lib.name == "std":
        return f"Standard (std, v{v})" if v else "Standard (std)"
    return f"{lib.name} ({v})" if v else lib.name


def _libraries_display_order(libraries: list[ParsedLibrary]) -> list[ParsedLibrary]:
    """Same order as ``LibraryCatalog.libraries`` (mount order), but ``std`` always first."""
    libs = list(libraries)
    std = [lib for lib in libs if lib.name.lower() == "std"]
    rest = [lib for lib in libs if lib.name.lower() != "std"]
    return std + rest


def _build_element_tiles(library: ParsedLibrary) -> list[LibraryBlockTile]:
    tiles: list[LibraryBlockTile] = []
    for elem in library.elements:
        type_key = f"{library.name}.{elem.element_id}"
        renderer = _load_svg_renderer(elem)
        tooltip = f"{elem.display_name} ({elem.element_id})\nDrag to diagram to place."
        tiles.append(LibraryBlockTile(type_key, tooltip, renderer, RESOURCES_TILE_SIZE))
    return tiles


def build_resources_panel(controller: SynariusController, parent: QWidget | None = None) -> QWidget:
    """Scrollable panel: one collapsible section per loaded FMF library (``std`` first, then catalog order).

    Element tiles follow ``libraryDescription.xml`` element order. Width is user-resizable.
    """
    outer = QWidget(parent)
    outer.setMinimumWidth(RESOURCES_PANEL_MIN_WIDTH)
    outer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    outer.setObjectName("syn_resources_outer")
    outer.setStyleSheet(qss_widget_id_background("syn_resources_outer", RESOURCES_PANEL_BACKGROUND))
    outer_layout = QVBoxLayout(outer)
    outer_layout.setContentsMargins(0, 0, 0, 0)
    outer_layout.setSpacing(0)

    scroll = QScrollArea(outer)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setStyleSheet(
        f"QScrollArea {{ background-color: {RESOURCES_PANEL_BACKGROUND}; border: none; }}"
        f"QScrollArea > QWidget > QWidget {{ background-color: {RESOURCES_PANEL_BACKGROUND}; }}"
    )

    inner = QWidget()
    inner.setObjectName("syn_resources_inner")
    inner.setStyleSheet(qss_widget_id_background("syn_resources_inner", RESOURCES_PANEL_BACKGROUND))
    inner.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
    inner_layout = QVBoxLayout(inner)
    inner_layout.setContentsMargins(0, 0, 0, 0)
    inner_layout.setSpacing(0)

    catalog = controller.library_catalog
    if catalog.load_errors:
        err_text = "Some libraries failed to load:\n" + "\n".join(catalog.load_errors[:5])
        if len(catalog.load_errors) > 5:
            err_text += "\n…"
        err_lbl = QLabel(err_text, inner)
        err_lbl.setWordWrap(True)
        err_lbl.setStyleSheet(
            f"color: #a22; font-size: 11px; padding: 8px 10px;"
            f" background-color: {RESOURCES_PANEL_BACKGROUND};"
        )
        inner_layout.addWidget(err_lbl)

    libraries = _libraries_display_order(catalog.libraries)
    if not libraries:
        empty = QLabel("No FMF libraries found.", inner)
        empty.setStyleSheet(
            f"color: #555; padding: 8px 10px; background-color: {RESOURCES_PANEL_BACKGROUND};"
        )
        inner_layout.addWidget(empty)
    else:
        for lib in libraries:
            tiles = _build_element_tiles(lib)
            grid = _AdaptiveBlockGrid(
                tiles,
                RESOURCES_TILE_SIZE,
                RESOURCES_ICON_H_SPACING,
                RESOURCES_ICON_V_SPACING,
                inner,
            )
            section = CollapsibleSection(_library_section_title(lib), inner)
            section.content_layout().addWidget(grid)
            inner_layout.addWidget(section)

    pr = getattr(controller, "plugin_registry", None)
    if pr is not None and (pr.loaded_plugins or pr.load_errors or pr.capability_warnings):
        chunks: list[str] = []
        if pr.loaded_plugins:
            chunks.append("Plugins: " + ", ".join(lp.manifest.name for lp in pr.loaded_plugins))
        if pr.load_errors:
            chunks.append("Plugin load errors:\n" + "\n".join(pr.load_errors[:5]))
        if pr.capability_warnings:
            chunks.append("\n".join(pr.capability_warnings[:5]))
        plug_lbl = QLabel("\n\n".join(chunks), inner)
        plug_lbl.setWordWrap(True)
        plug_lbl.setStyleSheet(
            f"color: #333; font-size: 10px; padding: 8px 10px;"
            f" background-color: {RESOURCES_PANEL_BACKGROUND};"
        )
        inner_layout.addWidget(plug_lbl)

    inner_layout.addStretch(1)
    scroll.setWidget(inner)
    outer_layout.addWidget(scroll, 1)
    return outer
