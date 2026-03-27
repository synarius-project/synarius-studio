"""QGraphics items for data-flow diagram (variables, operators, edges)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsRectItem,
    QGraphicsSceneHoverEvent,
    QGraphicsSceneMouseEvent,
    QGraphicsSimpleTextItem,
    QStyleOptionGraphicsItem,
    QWidget,
)

from synarius_core.model import BasicOperator, BasicOperatorType, Variable

if TYPE_CHECKING:
    pass

# Global UI scale: 100 % nominal view uses 70 % of the former linear size (reverses mistaken 100/70 bump).
UI_SCALE = 70.0 / 100.0

# Base grid unit for block sizing; connector stroke stays readable at this scale.
MODULE = 15.0 * UI_SCALE
VARIABLE_HEIGHT = 2.0 * MODULE
# Width not fixed by spec; keeps ~ prior proportion to height (118:38 ≈ 6:2).
VARIABLE_WIDTH = 6.0 * MODULE
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


def _snap_pos_half_module(pos: QPointF) -> QPointF:
    step = MODULE * 0.5
    return QPointF(round(pos.x() / step) * step, round(pos.y() / step) * step)


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

    def __init__(self, parent: QGraphicsObject | None = None) -> None:
        super().__init__(parent)
        self.setZValue(1.0)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

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

    def __init__(self, variable: Variable, parent: QGraphicsRectItem | None = None) -> None:
        super().__init__(0, 0, VARIABLE_WIDTH, VARIABLE_HEIGHT, parent)
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
        self._label.setFont(_font_for_variable_name(variable.name, VARIABLE_WIDTH, VARIABLE_HEIGHT))
        br = self._label.boundingRect()
        self._label.setPos(
            (VARIABLE_WIDTH - br.width()) / 2,
            (VARIABLE_HEIGHT - br.height()) / 2,
        )

        _apply_light_diagonal_shadow(self)

        cy = VARIABLE_HEIGHT / 2.0
        self._pin_in = _InputPinItem(self)
        self._pin_in.setPos(0.0, cy)
        self._pin_out = _OutputPinItem(self)
        self._pin_out.setPos(VARIABLE_WIDTH, cy)

    def variable(self) -> Variable:
        return self._variable

    def connection_point(self, pin_name: str) -> QPointF:
        if pin_name == "out":
            return self._pin_out.mapToScene(self._pin_out.outer_attachment_local())
        if pin_name in ("in",):
            return self._pin_in.mapToScene(self._pin_in.outer_attachment_local())
        r = self.rect()
        return self.mapToScene(r.center())


class OperatorBlockItem(_MovableSnapRectMixin, QGraphicsRectItem):
    """Square operator block with centered vector glyph (+, −, ×, ÷)."""

    def __init__(self, operator: BasicOperator, parent: QGraphicsRectItem | None = None) -> None:
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

        # Pins on half-module grid (OPERATOR_SIZE = 3·MODULE): y = M, 2M, 1.5M for straight stubs.
        self._pin_in1 = _InputPinItem(self)
        self._pin_in1.setPos(0.0, MODULE)
        self._pin_in2 = _InputPinItem(self)
        self._pin_in2.setPos(0.0, 2.0 * MODULE)
        self._pin_out = _OutputPinItem(self)
        self._pin_out.setPos(OPERATOR_SIZE, 1.5 * MODULE)

        _apply_light_diagonal_shadow(self)

    def operator(self) -> BasicOperator:
        return self._operator

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
        self._att_src: QGraphicsItem | None = None
        self._att_dst: QGraphicsItem | None = None
        self._att_src_pin: str = ""
        self._att_dst_pin: str = ""

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

    def set_endpoints(self, p1: QPointF, p2: QPointF) -> None:
        self.prepareGeometryChange()
        self._p1 = p1
        self._p2 = p2
        self._stroke_path = _build_rounded_orthogonal_path(p1, p2)
        self.update()

    def boundingRect(self) -> QRectF:
        margin = max(8.0, CONNECTOR_LINE_WIDTH * 2.0)
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
        painter.setPen(self._pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self._stroke_path)
