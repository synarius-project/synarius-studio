"""QGraphics items for data-flow diagram (variables, operators, edges)."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import NamedTuple
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

from synarius_core.model import (
    BasicOperator,
    BasicOperatorType,
    Connector,
    DataViewer,
    ElementaryInstance,
    Pin,
    Variable,
)
from synarius_core.model.diagram_geometry import variable_diagram_block_width_scene
from synarius_core.model.connector_routing import (
    auto_orthogonal_bends,
    bends_absolute_to_relative,
    bends_relative_to_absolute,
    orthogonal_drag_segments,
    polyline_for_endpoints,
)

try:
    from synarius_core.model.connector_routing import simplify_axis_aligned_polyline
except ImportError:
    # Packaged builds may pin an older synarius-core without this helper; keep in sync with core implementation.
    _SIMPLIFY_EPS_POLY = 1e-2

    def _axis_redundant_middle(
        prev: tuple[float, float],
        mid: tuple[float, float],
        nxt: tuple[float, float],
        eps: float = _SIMPLIFY_EPS_POLY,
    ) -> bool:
        x0, y0 = prev
        x1, y1 = mid
        x2, y2 = nxt
        if abs(y0 - y1) < eps and abs(y1 - y2) < eps:
            lo, hi = (x0, x2) if x0 <= x2 else (x2, x0)
            return lo - eps <= x1 <= hi + eps
        if abs(x0 - x1) < eps and abs(x1 - x2) < eps:
            lo, hi = (y0, y2) if y0 <= y2 else (y2, y0)
            return lo - eps <= y1 <= hi + eps
        return False

    def simplify_axis_aligned_polyline(
        pts: list[tuple[float, float]], eps: float = _SIMPLIFY_EPS_POLY
    ) -> list[tuple[float, float]]:
        if len(pts) < 3:
            return list(pts)
        out: list[tuple[float, float]] = [pts[0]]
        for i in range(1, len(pts) - 1):
            if _axis_redundant_middle(out[-1], pts[i], pts[i + 1], eps):
                continue
            out.append(pts[i])
        out.append(pts[-1])
        return out

from ..theme import (
    DIAGRAM_SELECTION_HALO_CORNER_RADIUS_PX,
    DIAGRAM_SELECTION_OVERHANG_PX,
    selection_highlight_qcolor,
)

try:
    from synarius_core.model import (  # type: ignore[attr-defined]
        elementary_diagram_subtitle_for_geometry as _core_elementary_diagram_subtitle_for_geometry,
    )
except Exception:  # noqa: BLE001

    def _core_elementary_diagram_subtitle_for_geometry(inst: object) -> str:
        if not isinstance(inst, ElementaryInstance):
            return ""
        try:
            v = inst.get("diagram.subtitle")
            if isinstance(v, str) and v.strip():
                return v.strip()[:28]
        except Exception:
            pass
        try:
            mid = inst.get("fmu.model_identifier")
            if isinstance(mid, str) and mid.strip():
                return mid.strip()[:28]
        except Exception:
            pass
        return ""

elementary_diagram_subtitle_for_geometry = _core_elementary_diagram_subtitle_for_geometry

try:
    from synarius_core.model.diagram_geometry import (  # type: ignore[attr-defined]
        ELEMENTARY_LIB_HEADER_GRAPHIC_HEIGHT_SCENE,
        elementary_lib_header_height_scene,
    )
except Exception:  # noqa: BLE001

    def _approx_text_metrics(name: str, pixel_size: float) -> tuple[float, float]:
        if not name:
            return (float(pixel_size), pixel_size * 1.18)
        adv = 0.58 * pixel_size
        w = 0.0
        for ch in name:
            if ch.isascii() and ch.isdigit():
                w += adv * 0.62
            elif ch.isascii() and ch in "ijl1|.!,:;'":
                w += adv * 0.32
            elif ch.isascii() and ch in "mwMW%@":
                w += adv * 1.12
            elif ch.isascii() and ch.isupper():
                w += adv * 0.85
            else:
                w += adv * 1.05
        h = pixel_size * 1.18
        return (max(w, adv * 0.5), h)

    ELEMENTARY_LIB_HEADER_GRAPHIC_HEIGHT_SCENE = 0.0

    def elementary_lib_header_height_scene(title: str, subtitle: str, graphic_h: float = 0.0) -> float:
        # Keep fallback numerically aligned with current core defaults.
        _mod = 15.0 * (70.0 / 100.0)
        _variable_height = 2.0 * _mod
        _ELEMENTARY_LIB_HEADER_BAND_MIN = _mod * 1.38
        _ELEMENTARY_LIB_TITLE_SUB_GAP = _mod * 0.1
        _ELEMENTARY_LIB_GRAPHIC_GAP = _mod * 0.12
        _ELEMENTARY_LIB_HEADER_GROUP_VPAD = _mod * 0.24
        _tw, title_h = _approx_text_metrics(title, max(4.0, _variable_height * 0.45))
        text_stack = title_h
        sub = subtitle.strip()
        if sub:
            _sw, sub_h = _approx_text_metrics(sub[:28], max(7.0, _mod * 0.78))
            text_stack += _ELEMENTARY_LIB_TITLE_SUB_GAP + sub_h
        gap_tg = _ELEMENTARY_LIB_GRAPHIC_GAP if graphic_h > 0.0 else 0.0
        stack_h = text_stack + gap_tg + float(graphic_h)
        nudge = 0.1 * title_h
        min_for_title_centered = max(0.0, 2.0 * stack_h - title_h - 2.0 * nudge) + 2.0
        return max(
            _ELEMENTARY_LIB_HEADER_BAND_MIN,
            stack_h + _ELEMENTARY_LIB_HEADER_GROUP_VPAD,
            min_for_title_centered,
        )

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
# Uniform body fill for variable / operator / FMU / DataViewer blocks on the canvas.
DIAGRAM_BLOCK_FILL = QColor(255, 255, 255)
_REF_PIN_MOD = 19.0  # legacy reference for pin proportions vs MODULE
# Longer horizontal stubs (variables/operators).
PIN_LINE_LENGTH = MODULE * (15.0 / _REF_PIN_MOD)
# Arrowhead triangles: +100% vs baseline (depth × height of tip).
_PIN_TRI_SCALE = 2.0
PIN_TRI_DEPTH = MODULE * (6.0 / _REF_PIN_MOD) * _PIN_TRI_SCALE
PIN_TRI_HALF_HEIGHT = MODULE * (4.5 / _REF_PIN_MOD) * _PIN_TRI_SCALE
# Wire attachment distance from block edge: snapped to half-module so pins sit on the diagram grid.
_HALF_MODULE = MODULE * 0.5
_PIN_STUB_RAW = PIN_LINE_LENGTH + PIN_TRI_DEPTH
PIN_STUB_OUTER_REACH = max(
    PIN_TRI_DEPTH + 1e-9,
    round(_PIN_STUB_RAW / _HALF_MODULE) * _HALF_MODULE,
)
# Extra stub segment in simulation mode for large stimulate/measure markers.
PIN_SIM_EXTENSION = MODULE * 1.2
SIM_PIN_GREEN = QColor(0, 128, 48)
SIM_PIN_GREEN_DARK = QColor(0, 82, 32)

OPERATOR_GLYPH_STROKE = QColor(22, 22, 28)
_FILL_BLUE = QColor(36, 104, 220)

# Global selection / “marked” highlight (from ``theme.selection_highlight_qcolor``).
MARK_HIGHLIGHT_COLOR = selection_highlight_qcolor()
# Connector hit target: line + same overhang as blocks + small comfort margin.
_MARK_CONNECTOR_HIT_SLACK = 8.0
# Hit-test radius around a draggable leg (scene px); broad segment quads.
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


def _orthogonal_stroke_polyline(tpl: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Merge collinear vertices; snap interior bends only — endpoints stay on pin coordinates."""
    sim = simplify_axis_aligned_polyline(list(tpl))
    if not sim:
        return sim
    n = len(sim)
    out: list[tuple[float, float]] = []
    for i, (x, y) in enumerate(sim):
        if i == 0 or i == n - 1:
            px, py = float(x), float(y)
        else:
            px = _snap_scalar_half_module(x)
            py = _snap_scalar_half_module(y)
        if out and abs(px - out[-1][0]) < 1e-6 and abs(py - out[-1][1]) < 1e-6:
            continue
        out.append((px, py))
    return out


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
    In simulation mode, optional green down-arrow (stimulate) on an extended outer segment.
    """

    def __init__(self, pin_name: str, parent: QGraphicsObject | None = None) -> None:
        super().__init__(parent)
        self._pin_name = pin_name
        self.setZValue(1.0)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setAcceptHoverEvents(True)
        self._show_stim_arrow = False

    def logical_pin_name(self) -> str:
        return self._pin_name

    def is_output_pin(self) -> bool:
        return False

    def configure_sim_input(self, canvas_sim_on: bool, stimulated: bool) -> None:
        show = bool(canvas_sim_on and stimulated)
        if show == self._show_stim_arrow:
            return
        self.prepareGeometryChange()
        self._show_stim_arrow = show
        self.update()

    def boundingRect(self) -> QRectF:
        w = PIN_STUB_OUTER_REACH
        base_h = PIN_TRI_HALF_HEIGHT * 2.0 + 4.0
        down = MODULE * 1.05 if self._show_stim_arrow else 0.0
        return QRectF(-w, -base_h / 2.0, w, base_h + down)

    def outer_attachment_local(self) -> QPointF:
        # Always use the base pin length so connectors do not move when stimulation markers appear.
        return QPointF(-PIN_STUB_OUTER_REACH, 0.0)

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
            QPointF(-PIN_STUB_OUTER_REACH, 0.0),
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
        if self._show_stim_arrow:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            # Arrow is centered just outside the pin's triangle tip.
            # Spitze endet direkt am Pin (y = 0); Schaft + Dreieck zeigen nach unten.
            cx = -PIN_STUB_OUTER_REACH + MODULE * 0.12
            tip_y = 0.0
            base_y = MODULE * 0.55
            half_w = MODULE * 0.4
            # Shaft (line) von der Pin-Basis bis zur Dreiecks-Basis.
            shaft_pen = QPen(SIM_PIN_GREEN, max(3.0, CONNECTOR_LINE_WIDTH * 1.8))
            shaft_pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.setPen(shaft_pen)
            painter.drawLine(QPointF(cx, -2 * base_y), QPointF(cx, - base_y))
            # Triangle tip.
            tri = QPolygonF(
                [
                    QPointF(cx, tip_y),
                    QPointF(cx - half_w, - base_y),
                    QPointF(cx + half_w, - base_y),
                ]
            )
            painter.setBrush(SIM_PIN_GREEN)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPolygon(tri)
            painter.restore()


class _OutputPinItem(QGraphicsObject):
    """
    Output stub to the right of the block edge: outlined white triangle (tip right), then horizontal line.
    In simulation mode, optional green up-arrow + viewer id labels on an extended outer segment (measure).
    """

    def __init__(self, parent: QGraphicsObject | None = None, *, logical_name: str = "out") -> None:
        super().__init__(parent)
        self._logical_name = str(logical_name)
        self.setZValue(1.0)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setAcceptHoverEvents(True)
        self._measure_ids: list[int] = []

    def logical_pin_name(self) -> str:
        return self._logical_name

    def is_output_pin(self) -> bool:
        return True

    def configure_sim_output(self, canvas_sim_on: bool, measure_ids: list[int]) -> None:
        ids = [int(x) for x in measure_ids] if measure_ids else []
        # Same rule as stimulation on the input pin: markers only in simulation canvas mode.
        show = ids if canvas_sim_on else []
        if show == self._measure_ids:
            return
        self.prepareGeometryChange()
        self._measure_ids = show
        self.update()

    def boundingRect(self) -> QRectF:
        label_h = 0.0
        up = 0.0
        if self._measure_ids:
            up = MODULE * 1.0
            label_h = max(MODULE * 1.15, 12.0)
        w = PIN_STUB_OUTER_REACH + 2.0
        base_h = PIN_TRI_HALF_HEIGHT * 2.0 + 4.0
        h = base_h + label_h + up
        return QRectF(-1.0, -h / 2.0 - up, w, h)

    def outer_attachment_local(self) -> QPointF:
        # Always use the base pin length so connectors do not move when measurement markers appear.
        return QPointF(PIN_STUB_OUTER_REACH, 0.0)

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
        painter.drawLine(QPointF(e, 0.0), QPointF(PIN_STUB_OUTER_REACH, 0.0))
        if self._measure_ids:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            # Arrow is centered just outside the pin's triangle tip.
            # Spitze endet direkt am Pin (y = 0); Schaft + Dreieck zeigen nach oben.
            cx = PIN_STUB_OUTER_REACH - MODULE * 0.12
            tip_y = 0.0
            base_y = -MODULE * 0.55
            half_w = MODULE * 0.4
            # Shaft (line) von der Pin-Basis bis zur Dreiecks-Basis.
            shaft_pen = QPen(SIM_PIN_GREEN, max(3.0, CONNECTOR_LINE_WIDTH * 1.8))
            shaft_pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.setPen(shaft_pen)
            painter.drawLine(QPointF(cx, 0.0), QPointF(cx, base_y))
            tri_g = QPolygonF(
                [
                    QPointF(cx, tip_y + 2 * base_y),
                    QPointF(cx - half_w, base_y),
                    QPointF(cx + half_w, base_y),
                ]
            )
            painter.setBrush(SIM_PIN_GREEN)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPolygon(tri_g)
            lab = ",".join(str(i) for i in self._measure_ids)
            f = QFont()
            f.setWeight(QFont.Weight.Bold)
            f.setPixelSize(max(11, int(MODULE * 1.05)))
            painter.setFont(f)
            painter.setPen(QPen(SIM_PIN_GREEN))
            fm = QFontMetricsF(f)
            tw = fm.horizontalAdvance(lab)
            ty = tip_y - fm.height() - MODULE 
            painter.drawText(QPointF(cx - tw / 2, ty + fm.ascent()), lab)
            painter.restore()


def _variable_is_stimulated(variable: Variable) -> bool:
    try:
        return str(variable.get("stim_kind")).strip().lower() not in ("", "none")
    except (KeyError, TypeError, ValueError):
        return False


def _variable_measure_ids(variable: Variable) -> list[int]:
    try:
        raw = variable.get("dataviewer_measure_ids")
    except (KeyError, TypeError, ValueError):
        return []
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[int] = []
    for x in raw:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


class VariableBlockItem(_MovableSnapRectMixin, QGraphicsRectItem):
    """Rounded variable block (screenshot-style: wide rectangle, label)."""

    def __init__(
        self,
        variable: Variable,
        parent: QGraphicsRectItem | None = None,
    ) -> None:
        block_w = variable_diagram_block_width_scene(variable.name)
        super().__init__(0, 0, block_w, VARIABLE_HEIGHT, parent)
        self._variable = variable
        self.setBrush(DIAGRAM_BLOCK_FILL)
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
            v = self.variable()
            was_stim = _variable_is_stimulated(v)
            was_meas = bool(_variable_measure_ids(v))
            menu = QMenu()
            a_stim = menu.addAction("Stimulate")
            a_stim.setCheckable(True)
            a_stim.setChecked(was_stim)
            a_meas = menu.addAction("Measure")
            a_meas.setCheckable(True)
            a_meas.setChecked(was_meas)
            chosen = menu.exec(event.screenPos())
            if chosen is a_stim:
                sc.variable_sim_binding_toggle.emit(v, "stimulate", a_stim.isChecked())
            elif chosen is a_meas:
                sc.variable_sim_binding_toggle.emit(v, "measure", a_meas.isChecked())
            event.accept()
            return
        super().contextMenuEvent(event)

    def refresh_sim_pin_overlay(self, canvas_sim_on: bool) -> None:
        v = self._variable
        self._pin_in.configure_sim_input(canvas_sim_on, _variable_is_stimulated(v))
        self._pin_out.configure_sim_output(canvas_sim_on, _variable_measure_ids(v))

    def live_value_overlay_enabled(self) -> bool:
        return self._live_value_overlay

    def set_live_value_overlay(self, on: bool) -> None:
        on = bool(on)
        if self._live_value_overlay == on:
            self.refresh_sim_pin_overlay(on)
            return
        self.prepareGeometryChange()
        self._live_value_overlay = on
        self._value_label.setVisible(on)
        if not on:
            self._value_label.setText("")
        self.refresh_sim_pin_overlay(on)

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
            pad = DIAGRAM_SELECTION_OVERHANG_PX
            hr = r.adjusted(-pad, -pad, pad, pad)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(MARK_HIGHLIGHT_COLOR)
            rr = DIAGRAM_SELECTION_HALO_CORNER_RADIUS_PX
            painter.drawRoundedRect(hr, rr, rr)
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
    ) -> None:
        super().__init__(0, 0, OPERATOR_SIZE, OPERATOR_SIZE, parent)
        self._operator = operator
        self.setBrush(DIAGRAM_BLOCK_FILL)
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
            pad = DIAGRAM_SELECTION_OVERHANG_PX
            hr = r.adjusted(-pad, -pad, pad, pad)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(MARK_HIGHLIGHT_COLOR)
            rr = DIAGRAM_SELECTION_HALO_CORNER_RADIUS_PX
            painter.drawRoundedRect(hr, rr, rr)
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


# Vertical pitch for FMU / multi-pin lib pin rows; keep in sync with synarius_core ``diagram_geometry._ELEMENTARY_LIB_PIN_ROW``.
ELEMENTARY_LIB_PIN_ROW = MODULE * 1.52
# Multi-pin elementary library blocks (FMU, future types): header layout — sync with ``diagram_geometry`` _ELEMENTARY_LIB_* .
ELEMENTARY_LIB_HEADER_TITLE_SUB_GAP = MODULE * 0.1
ELEMENTARY_LIB_HEADER_GRAPHIC_GAP = MODULE * 0.12
ELEMENTARY_LIB_HEADER_GROUP_VPAD = MODULE * 0.24


class _ElementaryLibHeaderGraphicSlot(QGraphicsRectItem):
    """Reserved area for an optional header icon below the title (any multi-pin elementary lib block)."""

    def __init__(self, size: float, parent: QGraphicsItem | None = None) -> None:
        super().__init__(0.0, 0.0, size, size, parent)
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setBrush(Qt.BrushStyle.NoBrush)
        self.setZValue(1.5)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)


def _distributed_ys(n: int, y0: float, y1: float) -> list[float]:
    if n <= 0:
        return []
    if n == 1:
        return [(y0 + y1) * 0.5]
    return [y0 + (y1 - y0) * i / (n - 1) for i in range(n)]


class _FmuBlockGeometry(NamedTuple):
    title: str
    sub: str
    font: QFont
    fm: QFontMetricsF
    sub_font: QFont | None
    block_w: float
    block_h: float
    header_h: float
    pin_area_h: float
    stack_h: float
    text_stack_h: float
    nudge: float
    lx: float
    ly: float
    gh: float


_FMU_PIN_LABEL_EDGE_INSET = MODULE * 0.32
_FMU_PIN_LABEL_CENTER_GAP = MODULE * 1.2
_FMU_PIN_LABEL_MIN_SIDE_WIDTH = MODULE * 1.5
_FMU_PIN_LABEL_COLOR = QColor(76, 64, 46)


class FmuBlockItem(_MovableSnapRectMixin, QGraphicsRectItem):
    """Multi-pin elementary library block (e.g. FMU): dynamic I/O from the model ``pin`` map."""

    def __init__(
        self,
        elementary: ElementaryInstance,
        parent: QGraphicsRectItem | None = None,
    ) -> None:
        ins, outs, n_in, n_out, pin_rows = self.__init_sorted_pins(elementary)
        geo = self.__init_block_geometry(elementary, pin_rows, ins, outs)
        super().__init__(0, 0, geo.block_w, geo.block_h, parent)
        self._el = elementary
        self._pins: dict[str, _InputPinItem | _OutputPinItem] = {}
        self._pin_labels: dict[str, QGraphicsSimpleTextItem] = {}
        self._header_graphic: _ElementaryLibHeaderGraphicSlot | None = None
        self.__init_frame_appearance()
        self.__init_header_labels(geo)
        self.__init_pin_widgets(ins, outs, n_in, n_out, geo)

    @staticmethod
    def __init_sorted_pins(
        elementary: ElementaryInstance,
    ) -> tuple[list[Pin], list[Pin], int, int, int]:
        ins = sorted(elementary.in_pins, key=lambda p: p.name)
        outs = sorted(elementary.out_pins, key=lambda p: p.name)
        n_in, n_out = len(ins), len(outs)
        pin_rows = max(n_in, n_out, 1)
        return ins, outs, n_in, n_out, pin_rows

    @staticmethod
    def __init_block_geometry(
        elementary: ElementaryInstance,
        pin_rows: int,
        ins: list[Pin],
        outs: list[Pin],
    ) -> _FmuBlockGeometry:
        title = elementary.name
        sub = elementary_diagram_subtitle_for_geometry(elementary)

        font = _font_for_variable_name(title, 999, VARIABLE_HEIGHT)
        fm = QFontMetricsF(font)
        tw = fm.horizontalAdvance(title)
        sub_font: QFont | None = None
        if sub:
            sub_font = QFont()
            sub_font.setPixelSize(max(7, int(MODULE * 0.78)))
            tw = max(tw, QFontMetricsF(sub_font).horizontalAdvance(sub))
        pin_font = FmuBlockItem.__pin_label_font()
        pin_fm = QFontMetricsF(pin_font)
        max_in_w = max((pin_fm.horizontalAdvance(p.name) for p in ins), default=0.0)
        max_out_w = max((pin_fm.horizontalAdvance(p.name) for p in outs), default=0.0)
        pin_text_w = (
            2.0 * _FMU_PIN_LABEL_EDGE_INSET
            + _FMU_PIN_LABEL_CENTER_GAP
            + max_in_w
            + max_out_w
        )
        inner_w = max(4.8 * MODULE, tw + MODULE * 1.4, pin_text_w)
        min_bw = inner_w + MODULE * 2.4
        step = MODULE * 0.5
        block_w = max(min_bw, math.ceil(min_bw / step) * step)

        gh = float(ELEMENTARY_LIB_HEADER_GRAPHIC_HEIGHT_SCENE)
        probe_title = QGraphicsSimpleTextItem(title)
        probe_title.setFont(font)
        title_br0 = probe_title.boundingRect()
        text_stack_h = title_br0.height()
        if sub and sub_font is not None:
            probe_sub = QGraphicsSimpleTextItem(sub)
            probe_sub.setFont(sub_font)
            text_stack_h += ELEMENTARY_LIB_HEADER_TITLE_SUB_GAP + probe_sub.boundingRect().height()
        stack_h = text_stack_h + ((ELEMENTARY_LIB_HEADER_GRAPHIC_GAP + gh) if gh > 0.0 else 0.0)
        nudge = 0.45 * fm.descent()
        header_h = max(
            elementary_lib_header_height_scene(title, sub, gh),
            2.0 * stack_h - title_br0.height() - 2.0 * nudge + 2.0,
        )

        pin_area_h = max(ELEMENTARY_LIB_PIN_ROW, pin_rows * ELEMENTARY_LIB_PIN_ROW)
        block_h_raw = header_h + pin_area_h + MODULE * 0.55
        block_h = max(block_h_raw, math.ceil(block_h_raw / step) * step)

        y_group = max(0.0, (block_h - stack_h) / 2)
        ly = max(0.0, y_group - nudge)
        lx = (block_w - fm.horizontalAdvance(title)) / 2

        return _FmuBlockGeometry(
            title=title,
            sub=sub,
            font=font,
            fm=fm,
            sub_font=sub_font,
            block_w=block_w,
            block_h=block_h,
            header_h=header_h,
            pin_area_h=pin_area_h,
            stack_h=stack_h,
            text_stack_h=text_stack_h,
            nudge=nudge,
            lx=lx,
            ly=ly,
            gh=gh,
        )

    def __init_frame_appearance(self) -> None:
        self.setBrush(DIAGRAM_BLOCK_FILL)
        self.setPen(_block_outline_pen(QColor(88, 70, 42)))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)

    def __init_header_labels(self, geo: _FmuBlockGeometry) -> None:
        # Vertical center of title stack in the full block rect (cf. VariableBlockItem).
        self._label = QGraphicsSimpleTextItem(geo.title, self)
        self._label.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._label.setBrush(QColor(38, 32, 22))
        self._label.setZValue(3.0)
        self._label.setFont(geo.font)
        self._label.setPos(geo.lx, geo.ly)

        self._sub_label: QGraphicsSimpleTextItem | None = None
        if geo.sub and geo.sub_font is not None:
            self._sub_label = QGraphicsSimpleTextItem(geo.sub, self)
            self._sub_label.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self._sub_label.setBrush(QColor(90, 80, 65))
            self._sub_label.setFont(geo.sub_font)
            self._sub_label.setZValue(3.0)
            sw = QFontMetricsF(geo.sub_font).horizontalAdvance(geo.sub)
            title_br = self._label.boundingRect()
            self._sub_label.setPos(
                (geo.block_w - sw) / 2,
                geo.ly + title_br.height() + ELEMENTARY_LIB_HEADER_TITLE_SUB_GAP,
            )

        if geo.gh > 0.0:
            self._header_graphic = _ElementaryLibHeaderGraphicSlot(geo.gh, self)
            self._header_graphic.setZValue(3.0)
            gx = (geo.block_w - geo.gh) / 2
            gy = geo.ly + geo.text_stack_h + ELEMENTARY_LIB_HEADER_GRAPHIC_GAP
            self._header_graphic.setPos(gx, gy)

    @staticmethod
    def __pin_label_font() -> QFont:
        f = QFont()
        f.setWeight(QFont.Weight.Medium)
        # Between the old tiny labels and the oversized bump; still readable on canvas.
        f.setPixelSize(max(10, int(MODULE * 1.15)))
        return f

    @staticmethod
    def __elide_label(text: str, fm: QFontMetricsF, max_width: float) -> str:
        t = text.strip()
        if t == "" or max_width <= 2.0:
            return ""
        if fm.horizontalAdvance(t) <= max_width:
            return t
        dots = "..."
        dots_w = fm.horizontalAdvance(dots)
        if dots_w >= max_width:
            return dots
        while t and fm.horizontalAdvance(t + dots) > max_width:
            t = t[:-1]
        return (t + dots) if t else dots

    def __init_pin_widgets(
        self,
        ins: list[Pin],
        outs: list[Pin],
        n_in: int,
        n_out: int,
        geo: _FmuBlockGeometry,
    ) -> None:
        y0 = geo.header_h + ELEMENTARY_LIB_PIN_ROW * 0.35
        y1 = geo.header_h + geo.pin_area_h - ELEMENTARY_LIB_PIN_ROW * 0.35
        ys_in = [_snap_scalar_half_module(y) for y in _distributed_ys(n_in, y0, y1)]
        ys_out = [_snap_scalar_half_module(y) for y in _distributed_ys(n_out, y0, y1)]
        pin_font = self.__pin_label_font()
        pin_fm = QFontMetricsF(pin_font)
        side_w = max(
            _FMU_PIN_LABEL_MIN_SIDE_WIDTH,
            (geo.block_w - 2.0 * _FMU_PIN_LABEL_EDGE_INSET - _FMU_PIN_LABEL_CENTER_GAP) / 2.0,
        )
        left_x = _FMU_PIN_LABEL_EDGE_INSET
        right_anchor_x = geo.block_w - _FMU_PIN_LABEL_EDGE_INSET

        for p, py in zip(ins, ys_in):
            pin_it = _InputPinItem(p.name, self)
            pin_it.setPos(0.0, py)
            self._pins[p.name] = pin_it
            txt = self.__elide_label(p.name, pin_fm, side_w)
            lbl = QGraphicsSimpleTextItem(txt, self)
            lbl.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            lbl.setBrush(_FMU_PIN_LABEL_COLOR)
            lbl.setFont(pin_font)
            lbl.setZValue(2.8)
            lh = lbl.boundingRect().height()
            lbl.setPos(left_x, py - lh / 2.0)
            self._pin_labels[p.name] = lbl
        for p, py in zip(outs, ys_out):
            pin_it = _OutputPinItem(self, logical_name=p.name)
            pin_it.setPos(geo.block_w, py)
            self._pins[p.name] = pin_it
            txt = self.__elide_label(p.name, pin_fm, side_w)
            lbl = QGraphicsSimpleTextItem(txt, self)
            lbl.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            lbl.setBrush(_FMU_PIN_LABEL_COLOR)
            lbl.setFont(pin_font)
            lbl.setZValue(2.8)
            tw = pin_fm.horizontalAdvance(txt)
            lh = lbl.boundingRect().height()
            lbl.setPos(right_anchor_x - tw, py - lh / 2.0)
            self._pin_labels[p.name] = lbl

    def elementary(self) -> ElementaryInstance:
        return self._el

    def controller_select_token(self) -> str:
        return self._el.hash_name

    def set_diagram_editing_enabled(self, enabled: bool) -> None:
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, enabled)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, enabled)
        self.setAcceptHoverEvents(enabled)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton if enabled else Qt.MouseButton.NoButton)

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
            pad = DIAGRAM_SELECTION_OVERHANG_PX
            hr = r.adjusted(-pad, -pad, pad, pad)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(MARK_HIGHLIGHT_COLOR)
            rr = DIAGRAM_SELECTION_HALO_CORNER_RADIUS_PX
            painter.drawRoundedRect(hr, rr, rr)
        painter.restore()
        super().paint(painter, _style_option_without_item_selection(option), widget)

    def connection_point(self, pin_name: str) -> QPointF:
        pin = self._pins.get(pin_name)
        if pin is None:
            r = self.rect()
            return self.mapToScene(r.center())
        return pin.mapToScene(pin.outer_attachment_local())


class DataViewerBlockItem(_MovableSnapRectMixin, QGraphicsRectItem):
    """Data-viewer badge im Stil der übrigen Blöcke (weißer Block mit Scope-Bildschirm)."""

    DV_W = 4.75 * MODULE
    DV_H = 3.95 * MODULE

    def __init__(
        self,
        dataviewer: DataViewer,
        parent: QGraphicsRectItem | None = None,
    ) -> None:
        super().__init__(0, 0, self.DV_W, self.DV_H, parent)
        self._dataviewer = dataviewer
        self.setBrush(Qt.BrushStyle.NoBrush)
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self.setVisible(False)

        self._vid_str = str(int(dataviewer.get("dataviewer_id")))

    def dataviewer(self) -> DataViewer:
        return self._dataviewer

    def controller_select_token(self) -> str:
        return self._dataviewer.hash_name

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent) -> None:  # type: ignore[override]
        scene = self.scene()
        if scene is not None:
            try:
                # Typ wird zur Laufzeit geprüft; Import hier wäre zirkulär.
                from .diagram_scene import SynariusDiagramScene

                if isinstance(scene, SynariusDiagramScene):
                    scene.open_dataviewer_requested.emit(self._dataviewer)
                    scene.suppress_next_left_release_selection_sync()
                    event.accept()
                    return
            except Exception:
                pass
        super().mouseDoubleClickEvent(event)

    def set_sim_canvas_visible(self, sim_on: bool) -> None:
        sim_on = bool(sim_on)
        self.setVisible(sim_on)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, sim_on)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, sim_on)
        self.setAcceptHoverEvents(sim_on)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton if sim_on else Qt.MouseButton.NoButton)

    def set_diagram_editing_enabled(self, _enabled: bool) -> None:
        """Visibility/interaction are driven by ``set_sim_canvas_visible`` from the main window."""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = self.rect()
        # Äußerer Block: wie Variable/Operator – weißer Block mit dunklem, relativ dickem Rand.
        outer_inset = MODULE * 0.25
        outer = r.adjusted(outer_inset, outer_inset, -outer_inset, -outer_inset)
        if self.isSelected():
            pad = DIAGRAM_SELECTION_OVERHANG_PX
            hr = outer.adjusted(-pad, -pad, pad, pad)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(MARK_HIGHLIGHT_COLOR)
            rr = DIAGRAM_SELECTION_HALO_CORNER_RADIUS_PX
            painter.drawRoundedRect(hr, rr, rr)

        painter.setBrush(DIAGRAM_BLOCK_FILL)
        painter.setPen(_block_outline_pen(QColor(55, 55, 55)))
        radius = MODULE * 0.4
        painter.drawRoundedRect(outer, radius, radius)

        # Innerer „Bildschirm“: weißes Rechteck mit dünnerem Rand, etwas nach oben versetzt
        # (angelehnt an Scope-Darstellung, aber im Studio-Stil gehalten).
        screen_margin_h = MODULE * 0.55
        screen_margin_v_top = MODULE * 0.45
        screen_margin_v_bottom = MODULE * 0.8
        screen = outer.adjusted(
            screen_margin_h,
            screen_margin_v_top,
            -screen_margin_h,
            -screen_margin_v_bottom,
        )
        thin_pen = QPen(QColor(80, 80, 80), CONNECTOR_LINE_WIDTH)
        painter.setPen(thin_pen)
        painter.setBrush(DIAGRAM_BLOCK_FILL)
        painter.drawRoundedRect(screen, MODULE * 0.22, MODULE * 0.22)

        # DataViewer-Nummer mittig im Bildschirm.
        font = QFont()
        font.setWeight(QFont.Weight.DemiBold)
        font.setPixelSize(max(16, int(MODULE * 1.6)))
        painter.setFont(font)
        painter.setPen(QColor(40, 40, 40))
        painter.drawText(screen, int(Qt.AlignmentFlag.AlignCenter), self._vid_str)
        painter.restore()


def diagram_pin_from_graphics_item(
    item: QGraphicsItem | None,
) -> tuple[_InputPinItem | _OutputPinItem, VariableBlockItem | OperatorBlockItem | FmuBlockItem] | None:
    """If ``item`` is (or is under) a diagram pin, return ``(pin_item, block_item)``."""
    while item is not None:
        if isinstance(item, (_InputPinItem, _OutputPinItem)):
            parent = item.parentItem()
            if isinstance(parent, (VariableBlockItem, OperatorBlockItem, FmuBlockItem)):
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
            tpl = _orthogonal_stroke_polyline(tpl)
            pts = [QPointF(x, y) for x, y in tpl]
            self._stroke_path = _rounded_orthogonal_chain(pts, radius=14.0)
        elif c is not None and c._orthogonal_bends:
            tpl = c.polyline_xy((sx, sy), (tx, ty))
            tpl = _orthogonal_stroke_polyline(tpl)
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
            bend_i, axis, press_pt, start_val, _sx0, _sy0, _tx0, _ty0 = self._bend_drag
            release_dx = float(event.scenePos().x() - press_pt.x())
            release_dy = float(event.scenePos().y() - press_pt.y())
            moved = abs(release_dx) > 0.5 or abs(release_dy) > 0.5
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
                and final_bends is not None
                and moved
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
        stroker.setWidth(CONNECTOR_LINE_WIDTH + 2.0 * DIAGRAM_SELECTION_OVERHANG_PX + _MARK_CONNECTOR_HIT_SLACK)
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return stroker.createStroke(self._stroke_path)

    def boundingRect(self) -> QRectF:
        half_halo = 0.5 * (CONNECTOR_LINE_WIDTH + 2.0 * DIAGRAM_SELECTION_OVERHANG_PX)
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
            halo_w = CONNECTOR_LINE_WIDTH + 2.0 * DIAGRAM_SELECTION_OVERHANG_PX
            halo = QPen(MARK_HIGHLIGHT_COLOR, halo_w)
            halo.setCapStyle(Qt.PenCapStyle.RoundCap)
            halo.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.strokePath(self._stroke_path, halo)
        painter.setPen(self._pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self._stroke_path)
        painter.restore()
