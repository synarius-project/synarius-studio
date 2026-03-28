"""Zoomable graphics view for the data-flow diagram."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Signal, Qt
from PySide6.QtGui import (
    QColor,
    QCursor,
    QEnterEvent,
    QGuiApplication,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QWheelEvent,
)
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

# Light yellow canvas (frame + scene); single source of truth for diagram area color.
CANVAS_BACKGROUND_COLOR = "#fffef2"

# Shared with console so diagram and terminal use identical scrollbar chrome (Qt style sheet).
SCROLLBAR_STYLE_QSS = """
QScrollBar:vertical {
    background: #3c3c3c;
    width: 11px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: #888888;
    min-height: 20px;
    border-radius: 5px;
    margin: 2px;
}
QScrollBar::handle:vertical:hover {
    background: #a0a0a0;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    border: none;
    background: none;
    height: 0px;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}
QScrollBar:horizontal {
    background: #3c3c3c;
    height: 11px;
    margin: 0px;
}
QScrollBar::handle:horizontal {
    background: #888888;
    min-width: 20px;
    border-radius: 5px;
    margin: 2px;
}
QScrollBar::handle:horizontal:hover {
    background: #a0a0a0;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    border: none;
    background: none;
    width: 0px;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
}
"""


class DataflowGraphicsView(QGraphicsView):
    """
    Renders a ``QGraphicsScene`` with:
    - **Wheel**: zoom (anchor under mouse).
    - **Ctrl + wheel**: vertical scroll.
    - **Shift + wheel**: horizontal scroll.
    - **Left-drag on empty background**: rubber-band rectangle to select multiple items (replace selection).
    - **Ctrl + left-drag on empty background**: pan the canvas (Qt’s Ctrl+rubber-band “add to selection” is not used).
    - **Ctrl** (over empty canvas): open-hand cursor hint; while panning, closed hand.
    """

    zoom_percent_changed = Signal(float)

    def __init__(self, scene: QGraphicsScene | None = None, parent=None) -> None:
        super().__init__(scene, parent)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setRubberBandSelectionMode(Qt.ItemSelectionMode.IntersectsItemShape)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setBackgroundBrush(QColor(CANVAS_BACKGROUND_COLOR))
        self.setStyleSheet(SCROLLBAR_STYLE_QSS)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._open_hand = QCursor(Qt.CursorShape.OpenHandCursor)
        self._closed_hand = QCursor(Qt.CursorShape.ClosedHandCursor)
        self._arrow_cursor = QCursor(Qt.CursorShape.ArrowCursor)
        self._pan_active = False
        self._pan_viewport_pos = None
        self._pan_h_scroll = 0
        self._pan_v_scroll = 0
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.viewport().setCursor(self._arrow_cursor)

    def _item_under(self, pos) -> bool:
        return self.itemAt(pos) is not None

    def _cursor_hint_empty_canvas(self, viewport_pos: QPoint) -> None:
        """Open hand if Ctrl is held over empty canvas; otherwise arrow (items set their own cursor)."""
        if self._pan_active:
            return
        if self._item_under(viewport_pos):
            return
        if QGuiApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier:
            self.viewport().setCursor(self._open_hand)
        else:
            self.viewport().setCursor(self._arrow_cursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        if (
            event.button() == Qt.MouseButton.LeftButton
            and not self._item_under(pos)
            and (event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        ):
            self._pan_active = True
            self._pan_viewport_pos = pos
            self._pan_h_scroll = self.horizontalScrollBar().value()
            self._pan_v_scroll = self.verticalScrollBar().value()
            self.viewport().setCursor(self._closed_hand)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._pan_active and self._pan_viewport_pos is not None:
            pos = event.position().toPoint()
            delta = pos - self._pan_viewport_pos
            self.horizontalScrollBar().setValue(self._pan_h_scroll - delta.x())
            self.verticalScrollBar().setValue(self._pan_v_scroll - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)
        if not self.rubberBandRect().isNull():
            return
        pos = event.position().toPoint()
        self._cursor_hint_empty_canvas(pos)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._pan_active:
            self._pan_active = False
            self._pan_viewport_pos = None
            pos = event.position().toPoint()
            self._cursor_hint_empty_canvas(pos)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        super().keyPressEvent(event)
        vp = self.viewport()
        self._cursor_hint_empty_canvas(vp.mapFromGlobal(QCursor.pos()))

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        super().keyReleaseEvent(event)
        vp = self.viewport()
        self._cursor_hint_empty_canvas(vp.mapFromGlobal(QCursor.pos()))

    def enterEvent(self, event: QEnterEvent) -> None:
        super().enterEvent(event)
        if not self._pan_active:
            vp = self.viewport()
            self._cursor_hint_empty_canvas(vp.mapFromGlobal(QCursor.pos()))

    def leaveEvent(self, event: QEvent) -> None:
        if not self._pan_active:
            self.viewport().setCursor(self._arrow_cursor)
        super().leaveEvent(event)

    def zoom_percent(self) -> float:
        """Uniform scale of the view transform as a percentage (100 = 100%)."""
        m11 = self.transform().m11()
        return round(m11 * 100.0, 2)

    def set_zoom_percent(self, percent: float) -> None:
        """Reset transform and apply uniform scale ``percent / 100``."""
        p = max(5.0, min(500.0, percent))
        self.resetTransform()
        s = p / 100.0
        self.scale(s, s)
        self.zoom_percent_changed.emit(self.zoom_percent())

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        mods = event.modifiers()

        if mods & Qt.KeyboardModifier.ControlModifier:
            vsb = self.verticalScrollBar()
            vsb.setValue(vsb.value() - delta)
            event.accept()
            return
        if mods & Qt.KeyboardModifier.ShiftModifier:
            hsb = self.horizontalScrollBar()
            hsb.setValue(hsb.value() - delta)
            event.accept()
            return

        # Zoom (no Ctrl/Shift)
        factor = 1.15 ** (delta / 240.0)
        if factor != 1.0:
            self.scale(factor, factor)
            self.zoom_percent_changed.emit(self.zoom_percent())
        event.accept()
