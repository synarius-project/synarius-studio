"""Interactive orthogonal connector routing (click output pin → H/V bends → input pin)."""

from __future__ import annotations

import shlex
from uuid import UUID

from PySide6.QtCore import QObject, QPoint, QPointF, QRectF, Qt, QSizeF, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsScene,
    QStyleOptionGraphicsItem,
    QWidget,
)

from synarius_core.controller import MinimalController
from synarius_core.model import Connector

from .dataflow_items import (
    CONNECTOR_LINE_WIDTH,
    MARK_HIGHLIGHT_COLOR,
    FmuBlockItem,
    OperatorBlockItem,
    VariableBlockItem,
    _rounded_orthogonal_chain,
    _snap_scalar_half_module,
    diagram_pin_from_graphics_item,
)

def _endpoint_after_bends(sx: float, sy: float, bends: list[float]) -> tuple[float, float]:
    lx, ly = float(sx), float(sy)
    for i, b in enumerate(bends):
        if i % 2 == 0:
            lx = float(b)
        else:
            ly = float(b)
    return lx, ly


def _rubber_xy(sx: float, sy: float, bends: list[float], phase_h: bool, mx: float, my: float) -> tuple[float, float]:
    lx, ly = _endpoint_after_bends(sx, sy, bends)
    if phase_h:
        return float(mx), ly
    return lx, float(my)


def _append_orthogonal_to_target(
    bends: list[float],
    lx: float,
    ly: float,
    phase_horizontal: bool,
    tx: float,
    ty: float,
    *,
    eps: float = 1e-3,
) -> None:
    h = phase_horizontal
    guard = 0
    while (abs(lx - tx) > eps or abs(ly - ty) > eps) and guard < 40:
        guard += 1
        if h:
            if abs(lx - tx) <= eps:
                h = False
                continue
            bends.append(_snap_scalar_half_module(float(tx)))
            lx = float(tx)
        else:
            if abs(ly - ty) <= eps:
                h = True
                continue
            bends.append(_snap_scalar_half_module(float(ty)))
            ly = float(ty)
        h = not h


def _pin_instance_id(block: VariableBlockItem | OperatorBlockItem | FmuBlockItem) -> UUID | None:
    if isinstance(block, VariableBlockItem):
        return block.variable().id
    if isinstance(block, OperatorBlockItem):
        return block.operator().id
    return block.elementary().id


def _pin_is_free(model, instance_id: UUID, pin_name: str, *, is_output: bool) -> bool:
    root = model.root
    children = getattr(root, "children", None) or []
    for ch in children:
        if not isinstance(ch, Connector):
            continue
        if is_output and ch.source_instance_id == instance_id and ch.source_pin == pin_name:
            return False
        if not is_output and ch.target_instance_id == instance_id and ch.target_pin == pin_name:
            return False
    return True


def _build_new_connector_command(
    src_token: str,
    dst_token: str,
    source_pin: str,
    target_pin: str,
    bends: list[float],
) -> str:
    parts = [
        "new",
        "Connector",
        shlex.quote(src_token),
        shlex.quote(dst_token),
        f"source_pin={source_pin}",
        f"target_pin={target_pin}",
    ]
    if bends:
        csv = ",".join(f"{float(v):.12g}" for v in bends)
        parts.append(f"orthogonal_bends={csv}")
    return " ".join(parts)


def _pen_cursor() -> QCursor:
    """
    Mechanical-pen style cursor (~45°): tip bottom-left, hotspot on the nib tip (per design spec).
    """
    w, h = 32, 32
    pm = QPixmap(w, h)
    pm.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    stroke = QPen(QColor(24, 24, 28), 2.25)
    stroke.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    stroke.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(stroke)
    painter.setBrush(QColor(255, 255, 255))

    # Nib tip at bottom-left (hotspot); body runs toward top-right.
    tip = QPointF(3.0, 27.5)
    p1 = QPointF(8.5, 22.0)  # nib shoulder inner
    p2 = QPointF(10.0, 23.2)
    shaft_a = QPointF(11.0, 22.0)
    shaft_b = QPointF(25.0, 8.0)
    shaft_c = QPointF(23.2, 6.2)
    shaft_d = QPointF(9.2, 20.2)

    nib = QPolygonF([tip, p2, p1])
    painter.drawPolygon(nib)

    body = QPainterPath()
    body.moveTo(shaft_d)
    body.lineTo(shaft_a)
    body.lineTo(shaft_b)
    body.quadTo(QPointF(27.0, 6.0), QPointF(26.2, 8.8))
    body.lineTo(shaft_c)
    body.closeSubpath()
    painter.drawPath(body)

    # Clip (upper side of barrel, toward top-left of pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawLine(QPointF(12.5, 19.0), QPointF(14.0, 17.2))
    painter.drawLine(QPointF(14.0, 17.2), QPointF(20.5, 10.5))

    painter.end()
    return QCursor(pm, int(tip.x()), int(tip.y()))


class ConnectorRouteSketchItem(QGraphicsObject):
    """Solid preview polyline while routing (same hue as block selection highlight)."""

    def __init__(self, parent: QGraphicsItem | None = None) -> None:
        super().__init__(parent)
        self.setZValue(100.0)
        self._sx = 0.0
        self._sy = 0.0
        self._bends: list[float] = []
        self._phase_h = True
        self._mx = 0.0
        self._my = 0.0
        line_color = QColor(MARK_HIGHLIGHT_COLOR)
        line_color.setAlpha(255)
        self._pen = QPen(line_color, max(CONNECTOR_LINE_WIDTH * 1.35, 2.0))
        self._pen.setStyle(Qt.PenStyle.SolidLine)
        self._pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

    def set_state(
        self,
        sx: float,
        sy: float,
        bends: list[float],
        phase_h: bool,
        mx: float,
        my: float,
    ) -> None:
        self.prepareGeometryChange()
        self._sx = sx
        self._sy = sy
        self._bends = list(bends)
        self._phase_h = phase_h
        self._mx = mx
        self._my = my
        self.update()

    def _preview_points(self) -> list[QPointF]:
        pts: list[QPointF] = [QPointF(self._sx, self._sy)]
        cx, cy = self._sx, self._sy
        for i, b in enumerate(self._bends):
            if i % 2 == 0:
                cx = float(b)
            else:
                cy = float(b)
            pts.append(QPointF(cx, cy))
        rx, ry = _rubber_xy(self._sx, self._sy, self._bends, self._phase_h, self._mx, self._my)
        pts.append(QPointF(rx, ry))
        return pts

    def boundingRect(self) -> QRectF:
        pts = self._preview_points()
        if len(pts) < 2:
            return QRectF(QPointF(self._sx, self._sy), QSizeF(1.0, 1.0))
        r = QRectF(pts[0], pts[0])
        for p in pts[1:]:
            r = r.united(QRectF(p, p))
        return r.adjusted(-12.0, -12.0, 12.0, 12.0)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        pts = self._preview_points()
        if len(pts) < 2:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(self._pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        path = _rounded_orthogonal_chain(pts, radius=14.0)
        painter.drawPath(path)
        painter.restore()


class ConnectorRouteTool(QObject):
    """State machine: output pin → alternating H/V clicks → free input pin."""

    finished = Signal(str)

    def __init__(self, controller: MinimalController, scene: QGraphicsScene, view: QWidget) -> None:
        super().__init__(view)
        self._controller = controller
        self._scene = scene
        self._view = view
        self._sketch: ConnectorRouteSketchItem | None = None
        self._src_block: VariableBlockItem | OperatorBlockItem | FmuBlockItem | None = None
        self._src_pin = ""
        self._sx = 0.0
        self._sy = 0.0
        self._bends: list[float] = []
        self._phase_h = True
        self._mx = 0.0
        self._my = 0.0

    def active(self) -> bool:
        return self._src_block is not None

    def _model(self):
        return self._controller.model

    def _sync_sketch(self) -> None:
        if self._sketch is not None:
            self._sketch.set_state(self._sx, self._sy, self._bends, self._phase_h, self._mx, self._my)

    def start(self, block: VariableBlockItem | OperatorBlockItem | FmuBlockItem, pin_name: str, sx: float, sy: float) -> None:
        self._src_block = block
        self._src_pin = pin_name
        self._sx, self._sy = sx, sy
        self._bends = []
        self._phase_h = True
        self._mx, self._my = sx, sy
        if self._sketch is None:
            self._sketch = ConnectorRouteSketchItem()
            self._scene.addItem(self._sketch)
        self._sync_sketch()
        self._view.setDragMode(self._view.DragMode.NoDrag)
        self._view.viewport().setCursor(_pen_cursor())

    def cancel(self) -> None:
        if self._sketch is not None:
            self._scene.removeItem(self._sketch)
            self._sketch = None
        self._src_block = None
        self._bends = []
        self._view.setDragMode(self._view.DragMode.RubberBandDrag)
        vp = self._view.viewport()
        vp.setCursor(self._view._arrow_cursor)
        self._view._cursor_hint_empty_canvas(vp.mapFromGlobal(QCursor.pos()))

    def move_mouse_scene(self, scene_pos: QPointF) -> None:
        if not self.active():
            return
        mx, my = scene_pos.x(), scene_pos.y()
        # Same half-module grid as block moves / bend drag (orthogonal leg: snap active axis only).
        if self._phase_h:
            self._mx = _snap_scalar_half_module(mx)
            self._my = my
        else:
            self._mx = mx
            self._my = _snap_scalar_half_module(my)
        self._sync_sketch()

    def try_start_from_release(self, scene_pos: QPointF, top_item: QGraphicsItem | None) -> bool:
        """Begin routing after a full click (call from left-button release) on a free output pin."""
        if self.active():
            return False
        hit = diagram_pin_from_graphics_item(top_item)
        if hit is None:
            for it in self._scene.items(scene_pos):
                hit = diagram_pin_from_graphics_item(it)
                if hit is not None:
                    break
        if hit is None:
            return False
        pin_item, block = hit
        if not pin_item.is_output_pin():
            return False
        eid = _pin_instance_id(block)
        if eid is None:
            return False
        pin_name = pin_item.logical_pin_name()
        if not _pin_is_free(self._model(), eid, pin_name, is_output=True):
            return False
        start = block.connection_point(pin_name)
        self.start(block, pin_name, start.x(), start.y())
        self.move_mouse_scene(scene_pos)
        return True

    def on_left_release(self, scene_pos: QPointF, top_item: QGraphicsItem | None) -> bool:
        if not self.active() or self._src_block is None:
            return False

        hit = diagram_pin_from_graphics_item(top_item)
        if hit is None:
            for it in self._scene.items(scene_pos):
                hit = diagram_pin_from_graphics_item(it)
                if hit is not None:
                    break

        if hit is not None:
            pin_item, block = hit
            if pin_item.is_output_pin():
                if block is self._src_block and pin_item.logical_pin_name() == self._src_pin:
                    return True
                self._commit_corner()
                return True
            eid = _pin_instance_id(block)
            if eid is None:
                return True
            tpin = pin_item.logical_pin_name()
            if not _pin_is_free(self._model(), eid, tpin, is_output=False):
                return True
            if block is self._src_block and tpin == self._src_pin:
                return True
            self._complete_to_block(block, tpin)
            return True

        self._commit_corner()
        return True

    def _commit_corner(self) -> None:
        rx, ry = _rubber_xy(self._sx, self._sy, self._bends, self._phase_h, self._mx, self._my)
        if self._phase_h:
            self._bends.append(_snap_scalar_half_module(rx))
        else:
            self._bends.append(_snap_scalar_half_module(ry))
        self._phase_h = not self._phase_h
        self._sync_sketch()

    def _complete_to_block(
        self, dst_block: VariableBlockItem | OperatorBlockItem | FmuBlockItem, target_pin: str
    ) -> None:
        assert self._src_block is not None
        src_id = _pin_instance_id(self._src_block)
        dst_id = _pin_instance_id(dst_block)
        if src_id is None or dst_id is None:
            self.cancel()
            return
        tpt = dst_block.connection_point(target_pin)
        tx, ty = tpt.x(), tpt.y()
        bends = list(self._bends)
        lx, ly = _endpoint_after_bends(self._sx, self._sy, bends)
        _append_orthogonal_to_target(bends, lx, ly, self._phase_h, tx, ty)

        src_tok = self._src_block.controller_select_token()
        dst_tok = dst_block.controller_select_token()
        cmd = _build_new_connector_command(src_tok, dst_tok, self._src_pin, target_pin, bends)
        self.cancel()
        self.finished.emit(cmd)

    def hover_free_pin_cursor(
        self,
        scene_pos: QPointF,
        viewport_pos: QPoint,
        top_item: QGraphicsItem | None,
    ) -> None:
        if self.active():
            return
        hit = diagram_pin_from_graphics_item(top_item)
        if hit is None:
            for it in self._scene.items(scene_pos):
                hit = diagram_pin_from_graphics_item(it)
                if hit is not None:
                    break
        vp = self._view.viewport()
        if hit is None:
            self._view._cursor_hint_empty_canvas(viewport_pos)
            return
        pin_item, block = hit
        eid = _pin_instance_id(block)
        if eid is None:
            self._view._cursor_hint_empty_canvas(viewport_pos)
            return
        name = pin_item.logical_pin_name()
        free = _pin_is_free(self._model(), eid, name, is_output=pin_item.is_output_pin())
        if free:
            vp.setCursor(_pen_cursor())
        else:
            self._view._cursor_hint_empty_canvas(viewport_pos)

