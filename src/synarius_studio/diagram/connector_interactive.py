"""Interactive orthogonal connector routing (click free pin → H/V bends → opposite pin).

For the full connector rendering pipeline (bend storage format, drag-release mechanics, the
dual-path invariant between studio and core geometry) see
``docs/developer/connector_rendering.rst``.
"""

from __future__ import annotations

import math
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

from synarius_core.controller import SynariusController
from synarius_core.model import Connector
from synarius_core.model.connector_routing import encode_bends_from_polyline, orthogonal_polyline

from .dataflow_items import (
    CONNECTOR_CROSSING_BRIDGE_R,
    CONNECTOR_LINE_WIDTH,
    FmuBlockItem,
    OperatorBlockItem,
    VariableBlockItem,
    _rounded_orthogonal_chain,
    _snap_scalar_half_module,
    diagram_pin_from_graphics_item,
    vertical_obstacles_from_connector_edges,
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
            bends.append(float(tx))
            lx = float(tx)
        else:
            if abs(ly - ty) <= eps:
                h = True
                continue
            bends.append(float(ty))
            ly = float(ty)
        h = not h


def _normalize_final_bends(bends: list[float], tx: float, ty: float, *, eps: float = 1e-3) -> list[float]:
    """
    Persist only the essential support coordinates for new connectors.

    During interactive routing the final segment always terminates at the target pin's y
    coordinate (enforced by the routing finish functions), so the trailing y-bend is
    redundant and can be dropped for any even-length list.  This prevents extra visual
    steps caused by imprecise placement of the last bend point.
    """
    out = [float(x) for x in bends]
    # Strip trailing y-coordinate for any even-length list: routing derives it from ty.
    if len(out) >= 2 and len(out) % 2 == 0:
        out = out[:-1]
    # Avoid degenerate "same x as target" first support; this causes visual U-detours.
    if len(out) == 1 and abs(out[0] - tx) <= eps:
        return []
    return out


def _pin_instance_id(block: VariableBlockItem | OperatorBlockItem | FmuBlockItem) -> UUID | None:
    if isinstance(block, VariableBlockItem):
        return block.variable().id
    if isinstance(block, OperatorBlockItem):
        return block.operator().id
    return block.elementary().id


def _pin_is_free(model, instance_id: UUID, pin_name: str, *, is_output: bool) -> bool:
    """Output pins allow multiple connectors (fan-out); input pins allow at most one."""
    if is_output:
        return True
    root = model.root
    children = getattr(root, "children", None) or []
    for ch in children:
        if not isinstance(ch, Connector):
            continue
        if ch.target_instance_id == instance_id and ch.target_pin == pin_name:
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


# Ein gemeinsamer Stift: historische Pixelkoordinaten, Spitze bei (3, 27.5); alles relativ zur Spitze zeichnen.
_PEN_TIP_X = 3.0
_PEN_TIP_Y = 27.5
# Richtung Körper → Spitze (Spitze zeigt nach unten links), für Rotationsabgleich mit Kantennormale.
_PEN_NIB_DX = -5.5
_PEN_NIB_DY = 5.5

_PEN_CURSOR_SIZE = 48
_PEN_CURSOR_HOT = _PEN_CURSOR_SIZE // 2


def _draw_connector_pen_at_tip_origin(painter: QPainter) -> None:
    """Stift mit Spitze in (0,0); Spitze zeigt nach unten links (45°-Haltung zum Schreiben)."""
    tx, ty = _PEN_TIP_X, _PEN_TIP_Y

    def p(x: float, y: float) -> QPointF:
        return QPointF(x - tx, y - ty)

    nib = QPolygonF([p(3.0, 27.5), p(10.0, 23.2), p(8.5, 22.0)])
    painter.drawPolygon(nib)

    body = QPainterPath()
    body.moveTo(p(9.2, 20.2))
    body.lineTo(p(11.0, 22.0))
    body.lineTo(p(25.0, 8.0))
    body.quadTo(p(27.0, 6.0), p(26.2, 8.8))
    body.lineTo(p(23.2, 6.2))
    body.closeSubpath()
    painter.drawPath(body)

    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawLine(p(12.5, 19.0), p(14.0, 17.2))
    painter.drawLine(p(14.0, 17.2), p(20.5, 10.5))


def _inward_normal_at_pin_on_block(block: QGraphicsItem, pin: QGraphicsItem) -> tuple[float, float]:
    """
    Einheitsvektor in Szene-Koordinaten (y nach unten): von außen auf die Pinposition / ins Innere des Blocks.
    Senkrecht zur betroffenen Rechteckkante (links, rechts, oben, unten).
    """
    br = block.sceneBoundingRect()
    pc = pin.sceneBoundingRect().center()
    d_left = abs(pc.x() - br.left())
    d_right = abs(pc.x() - br.right())
    d_top = abs(pc.y() - br.top())
    d_bottom = abs(pc.y() - br.bottom())
    m = min(d_left, d_right, d_top, d_bottom)
    if m == d_left:
        return (1.0, 0.0)
    if m == d_right:
        return (-1.0, 0.0)
    if m == d_top:
        return (0.0, 1.0)
    return (0.0, -1.0)


def _rotation_deg_align_nib_to(tx: float, ty: float) -> float:
    """Drehwinkel (QPainter, positiv = Uhrzeigersinn), sodass die Stiftspitze in Richtung (tx,ty) zeigt."""
    ln = math.hypot(tx, ty)
    if ln < 1e-9:
        return 0.0
    tx, ty = tx / ln, ty / ln
    nx0, ny0 = _PEN_NIB_DX, _PEN_NIB_DY
    ln0 = math.hypot(nx0, ny0)
    nx0, ny0 = nx0 / ln0, ny0 / ln0
    a0 = math.degrees(math.atan2(ny0, nx0))
    a1 = math.degrees(math.atan2(ty, tx))
    return a1 - a0


def _render_connector_pen_cursor(rotation_deg: float) -> QCursor:
    s = _PEN_CURSOR_SIZE
    hot = _PEN_CURSOR_HOT
    pm = QPixmap(s, s)
    pm.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    stroke = QPen(QColor(24, 24, 28), 2.25)
    stroke.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    stroke.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(stroke)
    painter.setBrush(QColor(255, 255, 255))
    painter.translate(float(hot), float(hot))
    painter.rotate(rotation_deg)
    _draw_connector_pen_at_tip_origin(painter)
    painter.end()
    return QCursor(pm, hot, hot)


def _pen_drawing_cursor() -> QCursor:
    """Zeichnen: gleicher Stift, Spitze nach unten links (~45° zur Horizontalen), Rotation 0."""
    return _render_connector_pen_cursor(0.0)


def _pen_ready_cursor_for_pin(pin_item: QGraphicsItem, block: QGraphicsItem) -> QCursor:
    """Anschlussbereitschaft: gleicher Stift, gedreht — Spitze senkrecht zur Kante, zeigt auf den Pin."""
    tx, ty = _inward_normal_at_pin_on_block(block, pin_item)
    return _render_connector_pen_cursor(_rotation_deg_align_nib_to(tx, ty))


class ConnectorRouteSketchItem(QGraphicsObject):
    """Solid grey preview polyline while routing."""

    def __init__(self, parent: QGraphicsItem | None = None) -> None:
        super().__init__(parent)
        self.setZValue(100.0)
        self._sx = 0.0
        self._sy = 0.0
        self._bends: list[float] = []
        self._phase_h = True
        self._mx = 0.0
        self._my = 0.0
        line_color = QColor(120, 120, 120)
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
        # Extend the temporary route to the actual mouse position, so the preview
        # reaches the cursor tip instead of stopping at the last orthogonal knee.
        if abs(self._mx - rx) > 1e-6 or abs(self._my - ry) > 1e-6:
            pts.append(QPointF(self._mx, self._my))
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
        verts = vertical_obstacles_from_connector_edges(self.scene())
        path = _rounded_orthogonal_chain(
            pts,
            14.0,
            vertical_obstacles=verts,
            bridge_radius=CONNECTOR_CROSSING_BRIDGE_R,
        )
        painter.drawPath(path)
        painter.restore()


class ConnectorRouteTool(QObject):
    """Orthogonal routing: freier Aus- oder Eingangspin → Knickpunkte → freier Gegenpin (In/Out)."""

    finished = Signal(str)

    def __init__(self, controller: SynariusController, scene: QGraphicsScene, view: QWidget) -> None:
        super().__init__(view)
        self._controller = controller
        self._scene = scene
        self._view = view
        self._sketch: ConnectorRouteSketchItem | None = None
        self._src_block: VariableBlockItem | OperatorBlockItem | FmuBlockItem | None = None
        self._src_pin = ""
        self._anchor_is_output = True
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

    def start(
        self,
        block: VariableBlockItem | OperatorBlockItem | FmuBlockItem,
        pin_name: str,
        sx: float,
        sy: float,
        *,
        anchor_is_output: bool,
    ) -> None:
        self._src_block = block
        self._src_pin = pin_name
        self._anchor_is_output = anchor_is_output
        self._sx, self._sy = sx, sy
        self._bends = []
        self._phase_h = True
        self._mx, self._my = sx, sy
        if self._sketch is None:
            self._sketch = ConnectorRouteSketchItem()
            self._scene.addItem(self._sketch)
        self._sync_sketch()
        self._view.setDragMode(self._view.DragMode.NoDrag)
        self._view.viewport().setCursor(_pen_drawing_cursor())

    def cancel(self) -> None:
        if self._sketch is not None:
            self._scene.removeItem(self._sketch)
            self._sketch = None
        self._src_block = None
        self._anchor_is_output = True
        self._bends = []
        self._view.setDragMode(self._view.DragMode.RubberBandDrag)
        vp = self._view.viewport()
        vp.setCursor(self._view._arrow_cursor)
        self._view._cursor_hint_empty_canvas(vp.mapFromGlobal(QCursor.pos()))

    def move_mouse_scene(self, scene_pos: QPointF) -> None:
        if not self.active():
            return
        mx, my = scene_pos.x(), scene_pos.y()
        if self._phase_h:
            self._mx = _snap_scalar_half_module(mx)
            self._my = my
        else:
            self._mx = mx
            self._my = _snap_scalar_half_module(my)
        self._sync_sketch()

    def update_active_cursor(
        self,
        scene_pos: QPointF,
        viewport_pos: QPoint,
        top_item: QGraphicsItem | None,
    ) -> None:
        """Über gültigem Zielpin: Stift mit Spitze zum Pin; sonst Zeichenhaltung (Spitze unten links)."""
        if not self.active():
            return
        vp = self._view.viewport()
        ch = self._valid_completion_hit(scene_pos, top_item)
        if ch is not None:
            pin_item, block = ch
            vp.setCursor(_pen_ready_cursor_for_pin(pin_item, block))
        else:
            vp.setCursor(_pen_drawing_cursor())

    def _valid_completion_hit(
        self, scene_pos: QPointF, top_item: QGraphicsItem | None
    ) -> tuple[QGraphicsItem, VariableBlockItem | OperatorBlockItem | FmuBlockItem] | None:
        if not self.active() or self._src_block is None:
            return None
        hit = diagram_pin_from_graphics_item(top_item)
        if hit is None:
            for it in self._scene.items(scene_pos):
                hit = diagram_pin_from_graphics_item(it)
                if hit is not None:
                    break
        if hit is None:
            return None
        pin_item, block = hit
        end_out = pin_item.is_output_pin()
        if end_out == self._anchor_is_output:
            return None
        if block is self._src_block and pin_item.logical_pin_name() == self._src_pin:
            return None
        eid = _pin_instance_id(block)
        if eid is None:
            return None
        name = pin_item.logical_pin_name()
        if not _pin_is_free(self._model(), eid, name, is_output=end_out):
            return None
        return pin_item, block

    def _cursor_on_valid_completion_pin(
        self, scene_pos: QPointF, top_item: QGraphicsItem | None
    ) -> bool:
        return self._valid_completion_hit(scene_pos, top_item) is not None

    def try_start_from_release(self, scene_pos: QPointF, top_item: QGraphicsItem | None) -> bool:
        """Routing starten nach Loslassen auf einem freien Aus- oder Eingangspin."""
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
        eid = _pin_instance_id(block)
        if eid is None:
            return False
        pin_name = pin_item.logical_pin_name()
        is_out = pin_item.is_output_pin()
        if not _pin_is_free(self._model(), eid, pin_name, is_output=is_out):
            return False
        start = block.connection_point(pin_name)
        self.start(block, pin_name, start.x(), start.y(), anchor_is_output=is_out)
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
            end_out = pin_item.is_output_pin()
            if end_out == self._anchor_is_output:
                if block is self._src_block and pin_item.logical_pin_name() == self._src_pin:
                    return True
                self._commit_corner()
                return True
            eid = _pin_instance_id(block)
            if eid is None:
                return True
            epin = pin_item.logical_pin_name()
            if not _pin_is_free(self._model(), eid, epin, is_output=end_out):
                return True
            if block is self._src_block and epin == self._src_pin:
                return True
            self._finish_at_pin(block, epin, end_pin_is_output=end_out)
            return True

        self._commit_corner()
        return True

    def _commit_corner(self) -> None:
        if self._bends:
            self._phase_h = not self._phase_h
            self._sync_sketch()
            return
        rx, ry = _rubber_xy(self._sx, self._sy, self._bends, self._phase_h, self._mx, self._my)
        if self._phase_h:
            self._bends.append(_snap_scalar_half_module(rx))
        else:
            self._bends.append(_snap_scalar_half_module(ry))
        self._phase_h = not self._phase_h
        self._sync_sketch()

    def _finish_at_pin(
        self,
        end_block: VariableBlockItem | OperatorBlockItem | FmuBlockItem,
        end_pin: str,
        *,
        end_pin_is_output: bool,
    ) -> None:
        assert self._src_block is not None
        BlockPin = tuple[VariableBlockItem | OperatorBlockItem | FmuBlockItem, str]

        def pair_source_and_target() -> tuple[BlockPin, BlockPin] | None:
            if _pin_instance_id(self._src_block) is None or _pin_instance_id(end_block) is None:
                return None
            if self._anchor_is_output and not end_pin_is_output:
                return (self._src_block, self._src_pin), (end_block, end_pin)
            if not self._anchor_is_output and end_pin_is_output:
                return (end_block, end_pin), (self._src_block, self._src_pin)
            return None

        def bends_command(ox: float, oy: float, ix: float, iy: float) -> list[float]:
            bends = list(self._bends)
            lx, ly = _endpoint_after_bends(self._sx, self._sy, bends)
            if self._anchor_is_output:
                _append_orthogonal_to_target(bends, lx, ly, self._phase_h, ix, iy)
                return _normalize_final_bends(bends, ix, iy)
            _append_orthogonal_to_target(bends, lx, ly, self._phase_h, ox, oy)
            try:
                poly_io = orthogonal_polyline(self._sx, self._sy, ox, oy, bends)
                poly_oi = list(reversed(poly_io))
                enc = encode_bends_from_polyline(ox, oy, ix, iy, poly_oi)
            except ValueError:
                enc = []
            return _normalize_final_bends(enc, ix, iy)

        ends = pair_source_and_target()
        if ends is None:
            self.cancel()
            return
        (out_block, out_pin), (in_block, in_pin) = ends
        o_pt = out_block.connection_point(out_pin)
        i_pt = in_block.connection_point(in_pin)
        cmd = _build_new_connector_command(
            out_block.controller_select_token(),
            in_block.controller_select_token(),
            out_pin,
            in_pin,
            bends_command(o_pt.x(), o_pt.y(), i_pt.x(), i_pt.y()),
        )
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
            vp.setCursor(_pen_ready_cursor_for_pin(pin_item, block))
        else:
            self._view._cursor_hint_empty_canvas(viewport_pos)

