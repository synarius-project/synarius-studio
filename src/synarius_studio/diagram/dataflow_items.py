"""QGraphics items for data-flow diagram (variables, operators, edges)."""

from __future__ import annotations

import math
from collections.abc import Callable
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsRectItem,
    QGraphicsSceneContextMenuEvent,
    QGraphicsSceneHoverEvent,
    QGraphicsSceneMouseEvent,
    QGraphicsSimpleTextItem,
    QMenu,
    QStyle,
    QStyleOptionGraphicsItem,
    QWidget,
)

from synarius_core.model import BasicOperator, BasicOperatorType, Connector, Variable
from synarius_core.model.diagram_geometry import variable_diagram_block_width_scene
from synarius_core.model.connector_routing import (
    auto_orthogonal_bends,
    bends_absolute_to_relative,
    bends_relative_to_absolute,
    orthogonal_drag_segments,
    polyline_for_endpoints,
)

from ..theme import selection_highlight_qcolor

# Global UI scale: 100 % nominal view uses 70 % of the former linear size (reverses mistaken 100/70 bump).
UI_SCALE = 70.0 / 100.0

# Base grid unit for block sizing; connector stroke stays readable at this scale.
MODULE = 15.0 * UI_SCALE
VARIABLE_HEIGHT = 2.0 * MODULE
# Live value text is drawn above the block (outside the box).
VALUE_LABEL_GAP = 3.0
# Width not fixed by spec; keeps ~ prior proportion to height (118:38 ≈ 6:2).
VARIABLE_WIDTH = 6.0 * MODULE  # default / minimum; instance width from ``variable_diagram_block_width_scene``
OPERATOR_SIZE = 3.0 * MODULE
_GLYPH_BASE = OPERATOR_SIZE * (40.0 / 56.0)
SVG_SYMBOL_SIZE = _GLYPH_BASE * 1.2

# Match connector edges (stroke weight). Block outlines are 2× this.
CONNECTOR_LINE_WIDTH = 1.35
BLOCK_OUTLINE_WIDTH = 2.0 * CONNECTOR_LINE_WIDTH
_REF_PIN_MOD = 19.0  # legacy reference for pin proportions vs MODULE
PIN_LINE_LENGTH = MODULE * (9.0 / _REF_PIN_MOD)
# Arrowhead triangles: +100% vs baseline (depth × height of tip).
_PIN_TRI_SCALE = 2.0
PIN_TRI_DEPTH = MODULE * (6.0 / _REF_PIN_MOD) * _PIN_TRI_SCALE
PIN_TRI_HALF_HEIGHT = MODULE * (4.5 / _REF_PIN_MOD) * _PIN_TRI_SCALE

OPERATOR_GLYPH_STROKE = QColor(22, 22, 28)
_FILL_BLUE = QColor(36, 104, 220)

# Global selection / “marked” highlight (from ``theme.selection_highlight_qcolor``).
MARK_HIGHLIGHT_COLOR = selection_highlight_qcolor()
# Outward extent from the element outline (scene px); same for blocks and connectors.
MARK_BLOCK_PADDING = 3.0
MARK_VARIABLE_HIGHLIGHT_RADIUS = max(3.5, MODULE * 0.22)
MARK_OPERATOR_HIGHLIGHT_RADIUS = max(2.5, MODULE * 0.12)
# Connector hit target: line + same padding as blocks + small comfort margin.
_MARK_CONNECTOR_HIT_SLACK = 8.0
# Hit-test radius around a draggable leg (scene px); PyLinX uses broad segment quads.
_CONNECTOR_BEND_DRAG_HIT = 12.0
_CONNECTOR_BEND_DRAG_HIT_SQ = _CONNECTOR_BEND_DRAG_HIT * _CONNECTOR_BEND_DRAG_HIT


def _bends_list_equal(a: list[float], b: list[float]) -> bool:
    if len(a) != len(b):
        return False
    return all(math.isclose(float(x), float(y), rel_tol=0.0, abs_tol=1e-4) for x, y in zip(a, b))


def _dist_sq_point_to_seg(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    vx = x2 - x1
    vy = y2 - y1
    wx = px - x1
    wy = py - y1
    c1 = vx * wx + vy * wy
    if c1 <= 0.0:
        return wx * wx + wy * wy
    c2 = vx * vx + vy * vy
    if c2 <= c1:
        dx = px - x2
        dy = py - y2
        return dx * dx + dy * dy
    t = c1 / c2
    lx = x1 + t * vx
    ly = y1 + t * vy
    dx = px - lx
    dy = py - ly
    return dx * dx + dy * dy


def _style_option_without_item_selection(option: QStyleOptionGraphicsItem) -> QStyleOptionGraphicsItem:
    """Avoid Qt’s default selection chrome; we draw ``MARK_HIGHLIGHT_COLOR`` ourselves."""
    opt = QStyleOptionGraphicsItem(option)
    opt.state &= ~QStyle.StateFlag.State_Selected
    opt.state &= ~QStyle.StateFlag.State_HasFocus
    return opt


def _snap_pos_half_module(pos: QPointF) -> QPointF:
    step = MODULE * 0.5
    return QPointF(round(pos.x() / step) * step, round(pos.y() / step) * step)


def _snap_scalar_half_module(v: float) -> float:
    step = MODULE * 0.5
    return round(v / step) * step


def _refresh_connectors_touching(block: QGraphicsItem) -> None:
    scene = block.scene()
    if scene is None:
        return
    for it in scene.items():
        notifier = getattr(it, "notify_block_moved", None)
        if callable(notifier):
            notifier(block)


class _MovableSnapRectMixin:
    """Snap top-left position to half-module grid; keep connectors in sync when moved."""

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: object) -> object:
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and isinstance(value, QPointF):
            value = _snap_pos_half_module(value)
        result = super().itemChange(change, value)
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            _refresh_connectors_touching(self)
        return result

    def hoverEnterEvent(self, event: QGraphicsSceneHoverEvent) -> None:
        self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent) -> None:
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            if self.isUnderMouse():
                self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
            else:
                self.unsetCursor()


def _block_outline_pen(color: QColor) -> QPen:
    pen = QPen(color, BLOCK_OUTLINE_WIDTH)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    return pen


def _thick_segment_path(p1: QPointF, p2: QPointF, thickness: float) -> QPainterPath:
    """Closed path: straight bar from ``p1`` to ``p2`` with full width ``thickness``."""
    dx = p2.x() - p1.x()
    dy = p2.y() - p1.y()
    L = math.hypot(dx, dy)
    if L < 1e-9:
        return QPainterPath()
    px = (-dy / L) * thickness * 0.5
    py = (dx / L) * thickness * 0.5
    path = QPainterPath()
    path.moveTo(p1.x() - px, p1.y() - py)
    path.lineTo(p1.x() + px, p1.y() + py)
    path.lineTo(p2.x() + px, p2.y() + py)
    path.lineTo(p2.x() - px, p2.y() - py)
    path.closeSubpath()
    return path


def _plus_cross_path(cx: float, cy: float, arm: float, bar_thickness: float) -> QPainterPath:
    t = bar_thickness * 0.5
    horizontal = QPainterPath()
    horizontal.addRect(QRectF(cx - arm, cy - t, 2.0 * arm, bar_thickness))
    vertical = QPainterPath()
    vertical.addRect(QRectF(cx - t, cy - arm, bar_thickness, 2.0 * arm))
    return horizontal.united(vertical)


def _fill_and_outline_glyph(painter: QPainter, path: QPainterPath, outline_w: float) -> None:
    painter.fillPath(path, _FILL_BLUE)
    pen = QPen(OPERATOR_GLYPH_STROKE, outline_w)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.strokePath(path, pen)


class _OperatorGlyphItem(QGraphicsRectItem):
    """
    Vector glyphs: filled ``QPainterPath`` shapes (blue) with a single black ``strokePath``.

    Plus and multiply use united paths so outlines do not stack like two overlaid pens.
    """

    def __init__(
        self,
        operation: BasicOperatorType,
        size: float,
        parent: QGraphicsItem | None = None,
    ) -> None:
        super().__init__(0.0, 0.0, size, size, parent)
        self._op = operation
        self.setBrush(Qt.BrushStyle.NoBrush)
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setZValue(2.0)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def boundingRect(self) -> QRectF:
        r = self.rect()
        m = max(r.width(), r.height()) * 0.15
        return r.adjusted(-m, -m, m, m)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        _paint_basic_operator_glyph(painter, self._op, self.rect())
        painter.restore()


def _paint_basic_operator_glyph(
    painter: QPainter,
    op: BasicOperatorType,
    rect: QRectF,
) -> None:
    w = rect.width()
    h = rect.height()
    cx = rect.center().x()
    cy = rect.center().y()
    arm = min(w, h) * 0.36
    inset = min(w, h) * 0.18
    bar = max(2.2, min(w, h) * 0.09)
    outline_w = max(1.2, bar * 0.38)

    if op == BasicOperatorType.PLUS:
        cross = _plus_cross_path(cx, cy, arm, bar)
        _fill_and_outline_glyph(painter, cross, outline_w)
    elif op == BasicOperatorType.MINUS:
        t = bar * 0.5
        bar_path = QPainterPath()
        bar_path.addRect(QRectF(cx - arm, cy - t, 2.0 * arm, bar))
        _fill_and_outline_glyph(painter, bar_path, outline_w)
    elif op == BasicOperatorType.MULTIPLY:
        k = 0.72
        x0, y0 = cx - arm * k, cy - arm * k
        x1, y1 = cx + arm * k, cy + arm * k
        d1 = _thick_segment_path(QPointF(x0, y0), QPointF(x1, y1), bar)
        d2 = _thick_segment_path(QPointF(x0, y1), QPointF(x1, y0), bar)
        x_shape = d1.united(d2)
        _fill_and_outline_glyph(painter, x_shape, outline_w)
    elif op == BasicOperatorType.DIVIDE:
        t = bar * 0.5
        bar_path = QPainterPath()
        bar_path.addRect(QRectF(rect.left() + inset, cy - t, rect.right() - rect.left() - 2.0 * inset, bar))
        dot_r = min(w, h) * 0.068
        gap = min(w, h) * 0.22
        dots = QPainterPath()
        for offy in (-gap, gap):
            dots.addEllipse(QRectF(cx - dot_r, cy + offy - dot_r, 2.0 * dot_r, 2.0 * dot_r))
        full = bar_path.united(dots)
        _fill_and_outline_glyph(painter, full, outline_w)
    else:
        cross = _plus_cross_path(cx, cy, arm, bar)
        _fill_and_outline_glyph(painter, cross, outline_w)


def _apply_light_diagonal_shadow(item: QGraphicsRectItem) -> None:
    """Soft shadow, slightly down-right (tighter offset than before, darker for readability)."""
    ox = max(1.0, MODULE * 0.07)
    oy = max(1.2, MODULE * 0.09)
    blur = max(4.0, MODULE * 0.62)
    fx = QGraphicsDropShadowEffect()
    fx.setBlurRadius(blur)
    fx.setColor(QColor(18, 18, 22, 95))
    fx.setOffset(ox, oy)
    item.setGraphicsEffect(fx)


def _font_for_variable_name(name: str, max_width: float, max_height: float) -> QFont:
    """Largest font (pixel size) that fits inside the label area with a small margin."""
    margin_h = max(1.0, max_height * 0.08)
    tol_w = max(1.0, max_height * 0.06)
    inner_h = max_height - 2.0 * margin_h
    inner_w = max_width - 2.0 * tol_w
    font = QFont()
    font.setWeight(QFont.Weight.Medium)
    lo, hi = 4, max(6, int(max_height * 3.0))
    best = 4
    while lo <= hi:
        mid = (lo + hi) // 2
        font.setPixelSize(mid)
        m = QFontMetricsF(font)
        br = m.boundingRect(name)
        if br.height() <= inner_h and br.width() <= inner_w:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    out = QFont()
    out.setWeight(QFont.Weight.Medium)
    out.setPixelSize(max(4, best))
    return out


class _InputPinItem(QGraphicsObject):
    """
    Input stub to the left of the block edge: horizontal line, then solid black triangle (tip on block edge).
    """

    def __init__(self, pin_name: str, parent: QGraphicsObject | None = None) -> None:
        super().__init__(parent)
        self._pin_name = pin_name
        self.setZValue(1.0)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setAcceptHoverEvents(True)

    def logical_pin_name(self) -> str:
        return self._pin_name

    def is_output_pin(self) -> bool:
        return False

    def boundingRect(self) -> QRectF:
        w = PIN_LINE_LENGTH + PIN_TRI_DEPTH
        h = PIN_TRI_HALF_HEIGHT * 2.0 + 4.0
        return QRectF(-w, -h / 2.0, w, h)

    def outer_attachment_local(self) -> QPointF:
        return QPointF(-(PIN_LINE_LENGTH + PIN_TRI_DEPTH), 0.0)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        pen = QPen(QColor(35, 35, 35), CONNECTOR_LINE_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)
        e = PIN_TRI_DEPTH
        painter.drawLine(
            QPointF(-(PIN_LINE_LENGTH + e), 0.0),
            QPointF(-e, 0.0),
        )
        painter.setBrush(QColor(35, 35, 35))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(0.0, 0.0),
                    QPointF(-e, -PIN_TRI_HALF_HEIGHT),
                    QPointF(-e, PIN_TRI_HALF_HEIGHT),
                ]
            )
        )


class _OutputPinItem(QGraphicsObject):
    """
    Output stub to the right of the block edge: outlined white triangle (tip right), then horizontal line.
    """

    def __init__(self, parent: QGraphicsObject | None = None) -> None:
        super().__init__(parent)
        self.setZValue(1.0)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setAcceptHoverEvents(True)

    def logical_pin_name(self) -> str:
        return "out"

    def is_output_pin(self) -> bool:
        return True

    def boundingRect(self) -> QRectF:
        w = PIN_LINE_LENGTH + PIN_TRI_DEPTH + 2.0
        h = PIN_TRI_HALF_HEIGHT * 2.0 + 4.0
        return QRectF(-1.0, -h / 2.0, w, h)

    def outer_attachment_local(self) -> QPointF:
        return QPointF(PIN_TRI_DEPTH + PIN_LINE_LENGTH, 0.0)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        pen = QPen(QColor(35, 35, 35), CONNECTOR_LINE_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        e = PIN_TRI_DEPTH
        tri = QPolygonF(
            [
                QPointF(0.0, -PIN_TRI_HALF_HEIGHT),
                QPointF(0.0, PIN_TRI_HALF_HEIGHT),
                QPointF(e, 0.0),
            ]
        )
        painter.setBrush(QColor(255, 255, 255))
        painter.setPen(pen)
        painter.drawPolygon(tri)
        painter.drawLine(QPointF(e, 0.0), QPointF(e + PIN_LINE_LENGTH, 0.0))


class VariableBlockItem(_MovableSnapRectMixin, QGraphicsRectItem):
    """Rounded variable block (screenshot-style: wide rectangle, label)."""

    def __init__(
        self,
        variable: Variable,
        parent: QGraphicsRectItem | None = None,
        *,
        drop_shadow: bool = True,
    ) -> None:
        block_w = variable_diagram_block_width_scene(variable.name)
        super().__init__(0, 0, block_w, VARIABLE_HEIGHT, parent)
        self._variable = variable
        self.setBrush(QColor(250, 250, 248))
        self.setPen(_block_outline_pen(QColor(55, 55, 55)))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)

        self._label = QGraphicsSimpleTextItem(variable.name, self)
        self._label.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._label.setBrush(QColor(30, 30, 30))
        self._label.setZValue(2.0)
        font = _font_for_variable_name(variable.name, block_w, VARIABLE_HEIGHT)
        self._label.setFont(font)
        fm = QFontMetricsF(font)
        name = variable.name
        br = self._label.boundingRect()
        # Horizontal: width from metrics (stable centering). Vertical: SimpleTextItem’s rect
        # sits low vs. caps; nudge up so the label reads centered in the block.
        text_w = fm.horizontalAdvance(name)
        x = (block_w - text_w) / 2
        y = (VARIABLE_HEIGHT - br.height()) / 2 - 0.45 * fm.descent()
        self._label.setPos(x, y)

        vfont = QFont()
        # Simulation overlay: slightly larger for readability over the canvas grid.
        vfont.setPixelSize(max(8, int(MODULE * 1.0)))
        self._value_label = QGraphicsSimpleTextItem("", self)
        self._value_label.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._value_label.setBrush(QColor(0, 110, 45))
        self._value_label.setFont(vfont)
        self._value_label.setZValue(3.0)
        self._live_value_overlay = False
        self._value_label.setVisible(False)

        if drop_shadow:
            _apply_light_diagonal_shadow(self)

        cy = VARIABLE_HEIGHT / 2.0
        self._pin_in = _InputPinItem("in", self)
        self._pin_in.setPos(0.0, cy)
        self._pin_out = _OutputPinItem(self)
        self._pin_out.setPos(block_w, cy)

    def controller_select_token(self) -> str:
        """Token for ``select`` in the Controller Command Protocol (unique ``hash_name``)."""
        return self._variable.hash_name

    def contextMenuEvent(self, event: QGraphicsSceneContextMenuEvent) -> None:
        sc = self.scene()
        from .diagram_scene import SynariusDiagramScene

        if isinstance(sc, SynariusDiagramScene) and sc._simulation_mode:
            menu = QMenu()
            act = menu.addAction("Stimulation…")
            chosen = menu.exec(event.screenPos())
            if chosen is act:
                sc.configure_variable_stimulation.emit(self.variable())
            event.accept()
            return
        super().contextMenuEvent(event)

    def live_value_overlay_enabled(self) -> bool:
        return self._live_value_overlay

    def set_live_value_overlay(self, on: bool) -> None:
        on = bool(on)
        if self._live_value_overlay == on:
            return
        self.prepareGeometryChange()
        self._live_value_overlay = on
        self._value_label.setVisible(on)
        if not on:
            self._value_label.setText("")

    def boundingRect(self) -> QRectF:
        r = QRectF(self.rect())
        if not self._live_value_overlay:
            return r
        vr = self._value_label.mapRectToParent(self._value_label.boundingRect())
        return r.united(vr)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self.isSelected():
            r = self.rect()
            pad = MARK_BLOCK_PADDING
            hr = r.adjusted(-pad, -pad, pad, pad)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(MARK_HIGHLIGHT_COLOR)
            painter.drawRoundedRect(hr, MARK_VARIABLE_HIGHLIGHT_RADIUS, MARK_VARIABLE_HIGHLIGHT_RADIUS)
        painter.restore()
        super().paint(painter, _style_option_without_item_selection(option), widget)

    def variable(self) -> Variable:
        return self._variable

    @staticmethod
    def format_value_for_display(value: object) -> str:
        if value is None:
            return "—"
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, float):
            if math.isnan(value):
                return "nan"
            av = abs(value)
            if av >= 1e5 or (0 < av < 1e-3):
                return f"{value:.3e}"
            s = f"{value:.5g}"
            return s
        if isinstance(value, int):
            return str(value)
        return str(value)

    def refresh_value_display(self) -> None:
        if not self._live_value_overlay:
            return
        self.prepareGeometryChange()
        text = self.format_value_for_display(self._variable.value)
        self._value_label.setText(text)
        block_w = self.rect().width()
        fm = QFontMetricsF(self._value_label.font())
        tw = fm.horizontalAdvance(text)
        vx = max(0.0, (block_w - tw) / 2)
        vy = -VALUE_LABEL_GAP - fm.height() + 0.25 * fm.ascent()
        self._value_label.setPos(vx, vy)

    def set_diagram_editing_enabled(self, enabled: bool) -> None:
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, enabled)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, enabled)
        self.setAcceptHoverEvents(enabled)
        # Simulation mode: keep right-click for *Stimulation…* context menu on the scene.
        if enabled:
            self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        else:
            self.setAcceptedMouseButtons(Qt.MouseButton.RightButton)

    def connection_point(self, pin_name: str) -> QPointF:
        if pin_name == "out":
            return self._pin_out.mapToScene(self._pin_out.outer_attachment_local())
        if pin_name in ("in",):
            return self._pin_in.mapToScene(self._pin_in.outer_attachment_local())
        r = self.rect()
        return self.mapToScene(r.center())


class OperatorBlockItem(_MovableSnapRectMixin, QGraphicsRectItem):
    """Square operator block with centered vector glyph (+, −, ×, ÷)."""

    def __init__(
        self,
        operator: BasicOperator,
        parent: QGraphicsRectItem | None = None,
        *,
        drop_shadow: bool = True,
    ) -> None:
        super().__init__(0, 0, OPERATOR_SIZE, OPERATOR_SIZE, parent)
        self._operator = operator
        self.setBrush(QColor(245, 243, 238))
        self.setPen(_block_outline_pen(QColor(45, 45, 45)))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)

        self._glyph = _OperatorGlyphItem(operator.operation, SVG_SYMBOL_SIZE, self)
        self._glyph.setPos(
            (OPERATOR_SIZE - SVG_SYMBOL_SIZE) / 2,
            (OPERATOR_SIZE - SVG_SYMBOL_SIZE) / 2,
        )

        # Pins: inputs ±0.5·M from former M / 2M so they sit nearer top/bottom; out stays at 1.5M (center).
        self._pin_in1 = _InputPinItem("in1", self)
        self._pin_in1.setPos(0.0, 0.5 * MODULE)
        self._pin_in2 = _InputPinItem("in2", self)
        self._pin_in2.setPos(0.0, 2.5 * MODULE)
        self._pin_out = _OutputPinItem(self)
        self._pin_out.setPos(OPERATOR_SIZE, 1.5 * MODULE)

        if drop_shadow:
            _apply_light_diagonal_shadow(self)

    def controller_select_token(self) -> str:
        return self._operator.hash_name

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self.isSelected():
            r = self.rect()
            pad = MARK_BLOCK_PADDING
            hr = r.adjusted(-pad, -pad, pad, pad)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(MARK_HIGHLIGHT_COLOR)
            painter.drawRoundedRect(hr, MARK_OPERATOR_HIGHLIGHT_RADIUS, MARK_OPERATOR_HIGHLIGHT_RADIUS)
        painter.restore()
        super().paint(painter, _style_option_without_item_selection(option), widget)

    def operator(self) -> BasicOperator:
        return self._operator

    def set_diagram_editing_enabled(self, enabled: bool) -> None:
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, enabled)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, enabled)
        self.setAcceptHoverEvents(enabled)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton if enabled else Qt.MouseButton.NoButton)

    def connection_point(self, pin_name: str) -> QPointF:
        if pin_name == "out":
            return self._pin_out.mapToScene(self._pin_out.outer_attachment_local())
        if pin_name == "in1":
            return self._pin_in1.mapToScene(self._pin_in1.outer_attachment_local())
        if pin_name == "in2":
            return self._pin_in2.mapToScene(self._pin_in2.outer_attachment_local())
        if pin_name in ("in",):
            return self._pin_in1.mapToScene(self._pin_in1.outer_attachment_local())
        r = self.rect()
        return self.mapToScene(r.center())


def diagram_pin_from_graphics_item(
    item: QGraphicsItem | None,
) -> tuple[_InputPinItem | _OutputPinItem, VariableBlockItem | OperatorBlockItem] | None:
    """If ``item`` is (or is under) a diagram pin, return ``(pin_item, block_item)``."""
    while item is not None:
        if isinstance(item, (_InputPinItem, _OutputPinItem)):
            parent = item.parentItem()
            if isinstance(parent, (VariableBlockItem, OperatorBlockItem)):
                return (item, parent)
            return None
        item = item.parentItem()
    return None


def _build_rounded_orthogonal_path(
    p1: QPointF,
    p2: QPointF,
    radius: float = 14.0,
) -> QPainterPath:
    """
    Orthogonal route with rounded bends only.

    Pins extend horizontally (out stub / in stub), so the wire must leave horizontally
    from the source and arrive horizontally at the target — H–V–H with two quad corners
    when both axes differ (avoids a sharp 90° at the pins).
    """
    path = QPainterPath()
    x1, y1 = p1.x(), p1.y()
    x2, y2 = p2.x(), p2.y()
    dx = x2 - x1
    dy = y2 - y1

    if abs(dx) < 1.0 and abs(dy) < 1.0:
        path.moveTo(p1)
        path.lineTo(p2)
        return path

    if abs(dy) < 1.0:
        path.moveTo(p1)
        path.lineTo(p2)
        return path

    if abs(dx) < 1.0:
        path.moveTo(p1)
        path.lineTo(p2)
        return path

    # Pins are horizontal; tiny Δy with long Δx used to force a short vertical mid-leg (H–V–H) and a visible kink.
    _COLLINEAR_DY_PX = 10.0
    if abs(dy) <= _COLLINEAR_DY_PX:
        path.moveTo(x1, y1)
        path.lineTo(x2, y2)
        return path

    sx = 1.0 if dx >= 0.0 else -1.0
    sy = 1.0 if dy >= 0.0 else -1.0

    x_min, x_max = (x1, x2) if x1 <= x2 else (x2, x1)
    span_x = x_max - x_min
    span_y = abs(dy)

    # Middle vertical leg needs dy > 2*r; horizontal span must fit two fillets.
    r_y_cap = max(0.5, span_y * 0.5 - 1.0)
    r = min(radius, span_x * 0.32, span_y * 0.32, r_y_cap)
    r = max(0.5, r)
    eps = 2.0
    while r > 0.55:
        lo_b = x_min + r + eps
        hi_b = x_max - r - eps
        if lo_b <= hi_b:
            break
        r = max(0.5, r * 0.82)

    x_mid = (x1 + x2) * 0.5
    lo_b = x_min + r + eps
    hi_b = x_max - r - eps
    if lo_b <= hi_b:
        x_mid = max(lo_b, min(x_mid, hi_b))

    path.moveTo(x1, y1)
    path.lineTo(x_mid - sx * r, y1)
    path.quadTo(QPointF(x_mid, y1), QPointF(x_mid, y1 + sy * r))
    path.lineTo(x_mid, y2 - sy * r)
    path.quadTo(QPointF(x_mid, y2), QPointF(x_mid + sx * r, y2))
    path.lineTo(x2, y2)

    return path


def _rounded_orthogonal_chain(points: list[QPointF], radius: float = 14.0) -> QPainterPath:
    """Axis-aligned polyline with small quadratic fillets at interior corners."""
    path = QPainterPath()
    n = len(points)
    if n == 0:
        return path
    if n == 1:
        path.moveTo(points[0])
        return path
    if n == 2:
        path.moveTo(points[0])
        path.lineTo(points[1])
        return path
    path.moveTo(points[0])
    for i in range(1, n - 1):
        p0, p1, p2 = points[i - 1], points[i], points[i + 1]
        dx1 = p1.x() - p0.x()
        dy1 = p1.y() - p0.y()
        dx2 = p2.x() - p1.x()
        dy2 = p2.y() - p1.y()
        len1 = math.hypot(dx1, dy1)
        len2 = math.hypot(dx2, dy2)
        if len1 < 1e-9 or len2 < 1e-9:
            path.lineTo(p1)
            continue
        ux1, uy1 = dx1 / len1, dy1 / len1
        ux2, uy2 = dx2 / len2, dy2 / len2
        r = min(radius, len1 * 0.32, len2 * 0.32)
        r = max(0.5, r)
        c1x = p1.x() - ux1 * r
        c1y = p1.y() - uy1 * r
        c2x = p1.x() + ux2 * r
        c2y = p1.y() + uy2 * r
        path.lineTo(QPointF(c1x, c1y))
        path.quadTo(p1, QPointF(c2x, c2y))
    path.lineTo(points[-1])
    return path


class ConnectorEdgeItem(QGraphicsObject):
    """Orthogonal connector (no line-end arrow; target input pin shows direction)."""

    def __init__(self, parent: QGraphicsObject | None = None) -> None:
        super().__init__(parent)
        self._p1 = QPointF()
        self._p2 = QPointF()
        self._stroke_path = QPainterPath()
        self._pen = QPen(QColor(35, 35, 35), CONNECTOR_LINE_WIDTH)
        self._pen.setStyle(Qt.PenStyle.SolidLine)
        self._pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self.setZValue(-10.0)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self._connector: Connector | None = None
        self._att_src: QGraphicsItem | None = None
        self._att_dst: QGraphicsItem | None = None
        self._att_src_pin: str = ""
        self._att_dst_pin: str = ""
        self._bends_apply_fn: Callable[[Connector, list[float]], bool] | None = None
        # Working copy during drag; committed via ``_apply_bends_list`` on mouse release only.
        self._bend_drag_local: list[float] | None = None
        # bend_index, axis ('x'|'y'), press scene pos, bend value at press, sx, sy, tx, ty
        self._bend_drag: tuple[int, str, QPointF, float, float, float, float, float] | None = None

    def set_domain_connector(self, connector: Connector) -> None:
        """Bind the scene edge to the core ``Connector`` (for ``select`` tokens)."""
        self._connector = connector

    def set_bends_apply_fn(self, fn: Callable[[Connector, list[float]], bool] | None) -> None:
        """Apply ``orthogonal_bends`` only through this callback (e.g. controller ``set`` + console log)."""
        self._bends_apply_fn = fn

    def _apply_bends_list(self, bends: list[float]) -> bool:
        c = self._connector
        if c is None or self._bends_apply_fn is None:
            return False
        return self._bends_apply_fn(c, list(bends))

    @property
    def domain_connector(self) -> Connector | None:
        return self._connector

    def controller_select_token(self) -> str | None:
        if self._connector is None:
            return None
        return self._connector.hash_name

    def set_route_editing_enabled(self, enabled: bool) -> None:
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, enabled)
        self.setAcceptHoverEvents(enabled)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton if enabled else Qt.MouseButton.NoButton)

    def attach_blocks(
        self,
        src_block: QGraphicsItem,
        dst_block: QGraphicsItem,
        source_pin: str,
        target_pin: str,
    ) -> None:
        self._att_src = src_block
        self._att_dst = dst_block
        self._att_src_pin = source_pin
        self._att_dst_pin = target_pin
        self._sync_attached_geometry()

    def _sync_attached_geometry(self) -> None:
        if self._att_src is None or self._att_dst is None:
            return
        src_fn = getattr(self._att_src, "connection_point", None)
        dst_fn = getattr(self._att_dst, "connection_point", None)
        if not callable(src_fn) or not callable(dst_fn):
            return
        self.set_endpoints(
            src_fn(self._att_src_pin),
            dst_fn(self._att_dst_pin),
        )

    def notify_block_moved(self, block: QGraphicsItem) -> None:
        if self._att_src is None:
            return
        if block is self._att_src or block is self._att_dst:
            self._sync_attached_geometry()

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: object) -> object:
        result = super().itemChange(change, value)
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged and not value:
            self.unsetCursor()
        return result

    def _poly_tuple(self) -> list[tuple[float, float]]:
        p1, p2 = self._p1, self._p2
        if self._connector is None:
            return [(p1.x(), p1.y()), (p2.x(), p2.y())]
        return self._connector.polyline_xy((p1.x(), p1.y()), (p2.x(), p2.y()))

    def _rebuild_stroke(self) -> None:
        self.prepareGeometryChange()
        p1, p2 = self._p1, self._p2
        c = self._connector
        sx, sy = p1.x(), p1.y()
        tx, ty = p2.x(), p2.y()
        if self._bend_drag_local is not None:
            tpl = polyline_for_endpoints(sx, sy, tx, ty, self._bend_drag_local)
            pts = [QPointF(x, y) for x, y in tpl]
            self._stroke_path = _rounded_orthogonal_chain(pts, radius=14.0)
        elif c is not None and c._orthogonal_bends:
            tpl = c.polyline_xy((sx, sy), (tx, ty))
            pts = [QPointF(x, y) for x, y in tpl]
            self._stroke_path = _rounded_orthogonal_chain(pts, radius=14.0)
        else:
            self._stroke_path = _build_rounded_orthogonal_path(p1, p2)
        self.update()

    def set_endpoints(self, p1: QPointF, p2: QPointF) -> None:
        self._p1 = p1
        self._p2 = p2
        self._rebuild_stroke()

    def _preview_bends(self) -> list[float]:
        """Absolute-diagram bend list for hit-testing / drag (stored bends are source-relative)."""
        if self._connector is None:
            return []
        sx, sy = self._p1.x(), self._p1.y()
        tx, ty = self._p2.x(), self._p2.y()
        if self._connector._orthogonal_bends:
            return bends_relative_to_absolute(sx, sy, list(self._connector._orthogonal_bends))
        return auto_orthogonal_bends(sx, sy, tx, ty)

    def _pick_bend_at(self, scene_pos: QPointF) -> tuple[int, str] | None:
        if self._connector is None:
            return None
        preview = self._preview_bends()
        if not preview:
            return None
        sx, sy = self._p1.x(), self._p1.y()
        tx, ty = self._p2.x(), self._p2.y()
        segs = orthogonal_drag_segments(sx, sy, tx, ty, preview)
        px, py = scene_pos.x(), scene_pos.y()
        best: tuple[int, str] | None = None
        best_d = _CONNECTOR_BEND_DRAG_HIT_SQ
        for x1, y1, x2, y2, bi, axis in segs:
            d = _dist_sq_point_to_seg(px, py, x1, y1, x2, y2)
            if d <= best_d:
                best_d = d
                best = (bi, axis)
        return best

    def _update_bend_hover_cursor(self, scene_pos: QPointF) -> None:
        if self._bend_drag is not None:
            return
        if not self.isSelected() or self._connector is None:
            self.unsetCursor()
            return
        pick = self._pick_bend_at(scene_pos)
        if pick is None:
            self.unsetCursor()
            return
        axis = pick[1]
        self.setCursor(
            QCursor(
                Qt.CursorShape.SizeHorCursor if axis == "x" else Qt.CursorShape.SizeVerCursor,
            )
        )

    def hoverMoveEvent(self, event: QGraphicsSceneHoverEvent) -> None:
        if self._bend_drag is None:
            self._update_bend_hover_cursor(event.scenePos())
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent) -> None:
        if self._bend_drag is None:
            self.unsetCursor()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._connector is not None
            and self._bend_drag is None
        ):
            pick = self._pick_bend_at(event.scenePos())
            if pick is not None:
                self.setSelected(True)
                bend_i, axis = pick
                sx, sy = self._p1.x(), self._p1.y()
                tx, ty = self._p2.x(), self._p2.y()
                if self._connector._orthogonal_bends:
                    working = bends_relative_to_absolute(sx, sy, list(self._connector._orthogonal_bends))
                else:
                    working = auto_orthogonal_bends(sx, sy, tx, ty)
                if not working or not (0 <= bend_i < len(working)):
                    event.accept()
                    return
                self._bend_drag_local = working
                self.grabMouse()
                bends = self._bend_drag_local
                if 0 <= bend_i < len(bends):
                    self._bend_drag = (
                        bend_i,
                        axis,
                        QPointF(event.scenePos()),
                        float(bends[bend_i]),
                        sx,
                        sy,
                        tx,
                        ty,
                    )
                else:
                    self.ungrabMouse()
                    self._bend_drag_local = None
                self._rebuild_stroke()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if self._bend_drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            st = self._bend_drag
            bend_i, axis, press_pt, start_val, sx, sy, tx, ty = st
            if self._connector is None:
                return
            if axis == "x":
                new_v = start_val + (event.scenePos().x() - press_pt.x())
            else:
                new_v = start_val + (event.scenePos().y() - press_pt.y())
            new_v = _snap_scalar_half_module(new_v)
            b = self._bend_drag_local
            if b is not None and 0 <= bend_i < len(b):
                b[bend_i] = new_v
                self._rebuild_stroke()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._bend_drag is not None:
            final_bends = list(self._bend_drag_local) if self._bend_drag_local is not None else None
            c = self._connector
            sx, sy = self._p1.x(), self._p1.y()
            self.ungrabMouse()
            self._bend_drag = None
            self._bend_drag_local = None
            rel_final = (
                bends_absolute_to_relative(sx, sy, final_bends)
                if final_bends is not None
                else None
            )
            if (
                rel_final is not None
                and c is not None
                and not _bends_list_equal(rel_final, list(c._orthogonal_bends))
            ):
                self._apply_bends_list(final_bends)
            self._rebuild_stroke()
            if self.isSelected():
                self._update_bend_hover_cursor(event.scenePos())
            else:
                self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(CONNECTOR_LINE_WIDTH + 2.0 * MARK_BLOCK_PADDING + _MARK_CONNECTOR_HIT_SLACK)
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return stroker.createStroke(self._stroke_path)

    def boundingRect(self) -> QRectF:
        half_halo = 0.5 * (CONNECTOR_LINE_WIDTH + 2.0 * MARK_BLOCK_PADDING)
        margin = max(6.0, half_halo + 1.0)
        br = self._stroke_path.boundingRect()
        br = br.united(QRectF(self._p1, self._p1))
        br = br.united(QRectF(self._p2, self._p2))
        return br.adjusted(-margin, -margin, margin, margin)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self.isSelected():
            # Halo width: black stroke + same outward pad as variable/operator rects.
            halo_w = CONNECTOR_LINE_WIDTH + 2.0 * MARK_BLOCK_PADDING
            halo = QPen(MARK_HIGHLIGHT_COLOR, halo_w)
            halo.setCapStyle(Qt.PenCapStyle.RoundCap)
            halo.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.strokePath(self._stroke_path, halo)
        painter.setPen(self._pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self._stroke_path)
        painter.restore()
