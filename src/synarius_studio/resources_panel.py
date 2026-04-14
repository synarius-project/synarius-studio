"""Resources tab: FMF libraries as collapsible sections with element icons."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QRectF, QMimeData
from PySide6.QtGui import QDrag, QPainter, QPixmap
from PySide6.QtWidgets import QApplication
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
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
)

# Fixed strip: 4 icons, equal left/right inset inside the panel widget.
RESOURCES_ICON_SIZE = 32
RESOURCES_ICON_COLUMNS = 4
RESOURCES_ICON_H_SPACING = 8
RESOURCES_ICON_V_SPACING = 8
RESOURCES_GRID_MARGIN_H = 4
RESOURCES_GRID_MARGIN_V = 4
RESOURCES_PANEL_SIDE_MARGIN = 10

RESOURCES_PANEL_FIXED_WIDTH = (
    2 * RESOURCES_GRID_MARGIN_H
    + RESOURCES_ICON_COLUMNS * RESOURCES_ICON_SIZE
    + (RESOURCES_ICON_COLUMNS - 1) * RESOURCES_ICON_H_SPACING
    + 2 * RESOURCES_PANEL_SIDE_MARGIN
)


def _read_icon16_relative_path(element_dir: Path) -> str | None:
    """Return relative path from ``elementDescription.xml`` ``<Graphics icon16="..."/>`` if present."""
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
        icon = child.attrib.get("icon16") or child.attrib.get("icon")
        if icon:
            return icon
    return None


class DraggableLibraryElementIcon(QLabel):
    """Tile from the Resources grid: drag ``type_key`` (``Lib.ElementId``) to the diagram canvas."""

    def __init__(self, type_key: str, tooltip: str, pixmap: QPixmap, display_size: int, parent: QWidget | None = None):
        super().__init__(parent)
        self._type_key = type_key
        self._drag_start: QPoint | None = None
        self.setPixmap(pixmap)
        self.setFixedSize(display_size, display_size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setToolTip(tooltip)
        self.setStyleSheet(
            "background-color: #ffffff; border: 1px solid #d8d4c4; border-radius: 3px; padding: 0px; margin: 0px;"
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_start is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        if (event.position().toPoint() - self._drag_start).manhattanLength() < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return
        drag = QDrag(self)
        md = QMimeData()
        md.setData(LIBRARY_ELEMENT_DRAG_MIME, self._type_key.encode("utf-8"))
        drag.setMimeData(md)
        drag.setPixmap(self.pixmap())
        drag.setHotSpot(self._drag_start)
        drag.exec(Qt.DropAction.CopyAction)
        self._drag_start = None

    def mouseReleaseEvent(self, event):
        self._drag_start = None
        super().mouseReleaseEvent(event)


def _load_element_icon(element: ParsedElement, display_size: int, *, svg_zoom: float = 1.18) -> QPixmap:
    """Rasterize SVG into a square pixmap; ``svg_zoom`` > 1 scales past the cell (clipped) so glyphs fill the tile."""
    rel = _read_icon16_relative_path(element.element_dir)
    if rel:
        svg_path = (element.element_dir / rel).resolve()
        if svg_path.is_file() and svg_path.suffix.lower() == ".svg":
            renderer = QSvgRenderer(str(svg_path))
            pm = QPixmap(display_size, display_size)
            pm.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pm)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            side = float(display_size) * svg_zoom
            ox = (float(display_size) - side) * 0.5
            renderer.render(painter, QRectF(ox, ox, side, side))
            painter.end()
            return pm
    pm = QPixmap(display_size, display_size)
    pm.fill(Qt.GlobalColor.lightGray)
    return pm


class CollapsibleSection(QWidget):
    """Simple expand/collapse block with a header row and content widget."""

    _OPEN_GLYPH = "\u25bc"  # ▼ triangle, tip down
    _CLOSED_GLYPH = "\u25b6"  # ▶ triangle, tip right

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._content = QWidget(self)
        self._content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)
        self._content.setStyleSheet(f"background-color: {RESOURCES_PANEL_BACKGROUND};")

        btn_style = (
            f"QToolButton {{ background-color: {LIBRARY_HEADER_BACKGROUND}; color: {LIBRARY_HEADER_TEXT}; "
            f"border: none; font-size: 10px; min-width: 18px; max-width: 22px; min-height: 18px; max-height: 20px; "
            f"padding: 0px; }}"
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


def _build_library_icons_grid(
    library: ParsedLibrary,
    *,
    icon_size: int = RESOURCES_ICON_SIZE,
    columns: int = RESOURCES_ICON_COLUMNS,
    h_spacing: int = RESOURCES_ICON_H_SPACING,
    v_spacing: int = RESOURCES_ICON_V_SPACING,
    margin_h: int = RESOURCES_GRID_MARGIN_H,
    margin_v: int = RESOURCES_GRID_MARGIN_V,
) -> QWidget:
    grid_host = QWidget()
    grid = QGridLayout(grid_host)
    grid.setHorizontalSpacing(h_spacing)
    grid.setVerticalSpacing(v_spacing)
    grid.setContentsMargins(margin_h, margin_v, margin_h, margin_v)
    elements = sorted(library.elements, key=lambda e: e.element_id.lower())
    for i, elem in enumerate(elements):
        pm = _load_element_icon(elem, display_size=icon_size)
        type_key = f"{library.name}.{elem.element_id}"
        lbl = DraggableLibraryElementIcon(
            type_key,
            f"{elem.display_name} ({elem.element_id})\nDrag to diagram to place.",
            pm,
            icon_size,
        )
        row, col = divmod(i, columns)
        grid.addWidget(lbl, row, col, Qt.AlignmentFlag.AlignCenter)
    return grid_host


def build_resources_panel(controller: SynariusController, parent: QWidget | None = None) -> QWidget:
    """Scrollable panel (canvas-toned): one collapsible section per loaded FMF library."""
    outer = QWidget(parent)
    outer.setFixedWidth(RESOURCES_PANEL_FIXED_WIDTH)
    outer.setStyleSheet(f"background-color: {RESOURCES_PANEL_BACKGROUND};")
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
    inner.setStyleSheet(f"background-color: {RESOURCES_PANEL_BACKGROUND};")
    inner.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
    inner_layout = QVBoxLayout(inner)
    inner_layout.setContentsMargins(0, 0, 0, 0)
    inner_layout.setSpacing(0)

    catalog = controller.library_catalog
    if catalog.load_errors:
        err_lbl = QLabel(
            "Some libraries failed to load:\n" + "\n".join(catalog.load_errors[:5])
            + ("\n…" if len(catalog.load_errors) > 5 else ""),
            inner,
        )
        err_lbl.setWordWrap(True)
        err_lbl.setStyleSheet(
            f"color: #a22; font-size: 11px; padding: 8px 10px; background-color: {RESOURCES_PANEL_BACKGROUND};"
        )
        inner_layout.addWidget(err_lbl)

    libraries = sorted(catalog.libraries, key=lambda lib: lib.name.lower())
    if not libraries:
        empty = QLabel("No FMF libraries found.", inner)
        empty.setStyleSheet(
            f"color: #555; padding: 8px 10px; background-color: {RESOURCES_PANEL_BACKGROUND};"
        )
        inner_layout.addWidget(empty)
    else:
        for lib in libraries:
            section = CollapsibleSection(_library_section_title(lib), inner)
            grid = _build_library_icons_grid(lib)
            grid_row = QWidget()
            grid_row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            row_l = QHBoxLayout(grid_row)
            row_l.setContentsMargins(0, 0, 0, 0)
            row_l.setSpacing(0)
            row_l.addStretch(1)
            row_l.addWidget(grid, 0, Qt.AlignmentFlag.AlignTop)
            row_l.addStretch(1)
            section.content_layout().addWidget(grid_row)
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
            f"color: #333; font-size: 10px; padding: 8px 10px; background-color: {RESOURCES_PANEL_BACKGROUND};"
        )
        inner_layout.addWidget(plug_lbl)

    inner_layout.addStretch(1)
    scroll.setWidget(inner)
    outer_layout.addWidget(scroll, 1)
    return outer
