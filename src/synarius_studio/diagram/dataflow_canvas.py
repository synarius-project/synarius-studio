"""Zoomable graphics view for the data-flow diagram."""

from __future__ import annotations

import json
from pathlib import Path
import time as _time

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QEnterEvent,
    QGuiApplication,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPalette,
    QResizeEvent,
    QShowEvent,
    QTransform,
    QWheelEvent,
)
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView, QMessageBox

from synarius_core.controller import SynariusController
from synarius_core.dataflow_sim._std_type_keys import STD_PARAM_LOOKUP
from synarius_core.variable_naming import InvalidVariableNameError

from ..theme import SELECTION_HIGHLIGHT_TEXT, selection_highlight_qcolor

from .connector_interactive import ConnectorRouteTool
from .dataflow_items import DataViewerBlockItem, FmuBlockItem, OperatorBlockItem, VariableBlockItem
from .diagram_scene import SynariusDiagramScene
from .placement_interactive import (
    LIBRARY_ELEMENT_DRAG_MIME,
    LIBRARY_ELEMENT_NAMED_DRAG_MIME,
    SIGNAL_NAME_DRAG_MIME,
    VARIABLE_NAME_DRAG_MIME,
    CanvasPlacementTool,
    library_element_drop_command,
    library_element_named_drop_command,
    variable_new_instance_command,
)

# Light yellow canvas (frame + scene); single source of truth for diagram area color.
CANVAS_BACKGROUND_COLOR = "#f0f3f5" #"#fffef2"
# Simulation canvas background — #ecffec (light green), QColor(236, 255, 236).
CANVAS_SIMULATION_BACKGROUND_COLOR = "#ecffec"
_DEBUG_LOG_PATH = Path(__file__).resolve().parents[4] / "debug-2707a1.log"

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


def _append_debug_log(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    """Append one NDJSON debug record for session ``2707a1``."""
    try:
        with _DEBUG_LOG_PATH.open("a", encoding="utf-8") as _df:
            _df.write(
                json.dumps(
                    {
                        "sessionId": "2707a1",
                        "runId": "repro-next",
                        "hypothesisId": hypothesis_id,
                        "location": location,
                        "message": message,
                        "data": data,
                        "timestamp": int(_time.time() * 1000),
                    }
                )
                + "\n"
            )
    except OSError:
        return


class DataflowGraphicsView(QGraphicsView):
    """
    Renders a ``QGraphicsScene`` with:
    - **Wheel**: zoom anchored to cursor. When scrollbars have no range (scene fits viewport),
      ``AnchorUnderMouse`` cannot adjust position via scroll offsets; zoom uses
      ``transform() * (translate(p) * scale * translate(-p))`` in scene space instead.
      Otherwise ``AnchorUnderMouse`` + ``scale()`` with scrollbar ``valueChanged`` disconnected
      during ``scale()`` so the policy sync cannot resize the viewport mid-anchor.
    - **Ctrl + wheel**: horizontal scroll.
    - **Shift + wheel**: vertical scroll.
    - **Scroll bars**: ``ScrollBarAsNeeded`` while all diagram items are fully visible in the
      viewport; once any item is clipped, both bars switch to ``ScrollBarAlwaysOn`` so panning
      remains immediately available.
    - **Left-drag on empty background**: rubber-band rectangle to select multiple items (replace selection).
    - **Ctrl + left-drag on empty background**: pan the canvas (Qt’s Ctrl+rubber-band “add to selection” is not used).
    - **Ctrl** (over empty canvas): open-hand cursor hint; while panning, closed hand.

    ``scene_left_release`` is emitted after each left-button release so the host can sync
    scene selection to the core controller.

    ``block_move_finished`` is emitted after a left-button release when movable blocks were dragged
    together by a uniform scene delta (``dx``, ``dy`` in scene coordinates). Emitted **after**
    ``scene_left_release`` so the host can run ``set -p @selection position …`` on a fresh selection.

    **Delete** / **Backspace** emit ``delete_selection_requested`` so the host can run ``del`` on the core
    and refresh the scene (default item removal is bypassed).
    """

    zoom_percent_changed = Signal(float)
    scene_left_release = Signal()
    block_move_finished = Signal(float, float)
    delete_selection_requested = Signal()
    connector_route_command = Signal(str)
    placement_command = Signal(str)
    signal_mapping_drop = Signal(str, str)
    placement_cancelled = Signal()

    def __init__(self, scene: QGraphicsScene | None = None, parent=None) -> None:
        super().__init__(scene, parent)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setRubberBandSelectionMode(Qt.ItemSelectionMode.IntersectsItemShape)
        # Flush diagram content to the top-left when the scene is smaller than the viewport; pair
        # with :meth:`scroll_diagram_content_to_top_left` after ``load`` so opened projects are not
        # centred in the canvas (``QGraphicsView`` default ``AlignCenter``).
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        # Avoid re-centering the scene on viewport resize (``AnchorViewCenter`` fights top-left).
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setBackgroundBrush(QColor(CANVAS_BACKGROUND_COLOR))
        self.viewport().setAutoFillBackground(True)
        self.setStyleSheet(SCROLLBAR_STYLE_QSS)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        _pal = self.palette()
        _hl = selection_highlight_qcolor(opaque=True)
        _pal.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.Highlight, _hl)
        _pal.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.HighlightedText, QColor(SELECTION_HIGHLIGHT_TEXT))
        self.setPalette(_pal)

        self._open_hand = QCursor(Qt.CursorShape.OpenHandCursor)
        self._closed_hand = QCursor(Qt.CursorShape.ClosedHandCursor)
        self._placement_hand = QCursor(Qt.CursorShape.ClosedHandCursor)
        self._arrow_cursor = QCursor(Qt.CursorShape.ArrowCursor)
        self._pan_active = False
        self._pan_viewport_pos = None
        self._pan_h_scroll = 0
        self._pan_v_scroll = 0
        self._move_anchor_snapshot: dict[int, QPointF] | None = None
        self._pending_selection_change: tuple[set, set] | None = None
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.viewport().setCursor(self._arrow_cursor)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)

        self._route_tool: ConnectorRouteTool | None = None
        self._placement_tool: CanvasPlacementTool | None = None
        self._controller_for_placement: SynariusController | None = None
        self._eat_next_left_release_for_route = False
        self._interaction_locked = False
        self._deferred_scene_left_release_timer = QTimer(self)
        self._deferred_scene_left_release_timer.setSingleShot(True)
        self._deferred_scene_left_release_timer.timeout.connect(self._fire_deferred_scene_left_release)

        self._syncing_scrollbar_policy = False
        self.horizontalScrollBar().valueChanged.connect(self._sync_scrollbar_policy_for_scene_origin)
        self.verticalScrollBar().valueChanged.connect(self._sync_scrollbar_policy_for_scene_origin)

    def _scene_content_fully_visible_in_viewport(self) -> bool:
        """True iff the current item bounding box is fully inside the visible scene rect."""
        sc = self.scene()
        if sc is None:
            return True
        content = sc.itemsBoundingRect()
        if content.isEmpty() or not content.isValid():
            return True
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        eps = 0.5
        return visible.contains(content.adjusted(-eps, -eps, eps, eps))

    def _ensure_scene_rect_covers_items(self) -> None:
        """Expand scene rect to include current item bounds (important for negative coordinates)."""
        sc = self.scene()
        if sc is None:
            return
        bounds = sc.itemsBoundingRect()
        if bounds.isEmpty() or not bounds.isValid():
            return
        pad = 120.0
        target = bounds.adjusted(-pad, -pad, pad, pad)
        if not sc.sceneRect().contains(target):
            sc.setSceneRect(sc.sceneRect().united(QRectF(target)))

    def _ensure_scene_rect_covers_rect(self, rect: QRectF) -> None:
        """Expand scene rect to include an arbitrary view-space target rect."""
        sc = self.scene()
        if sc is None:
            return
        if rect.isEmpty() or not rect.isValid():
            return
        pad = 120.0
        target = rect.adjusted(-pad, -pad, pad, pad)
        if not sc.sceneRect().contains(target):
            sc.setSceneRect(sc.sceneRect().united(QRectF(target)))

    def _sync_scrollbar_policy_for_scene_origin(self) -> None:
        """
        Keep as-needed scrollbars while all scene items are fully visible. Once any
        item is clipped by the viewport, force both bars on so panning is available.
        """
        if self._syncing_scrollbar_policy:
            return
        self._syncing_scrollbar_policy = True
        hsb = self.horizontalScrollBar()
        vsb = self.verticalScrollBar()
        try:
            self._ensure_scene_rect_covers_items()
            hsb.blockSignals(True)
            vsb.blockSignals(True)
            # Showing scroll bars changes the viewport; iterate until policies match visibility.
            for _ in range(4):
                content_ok = self._scene_content_fully_visible_in_viewport()
                h_target = (
                    Qt.ScrollBarPolicy.ScrollBarAsNeeded
                    if content_ok
                    else Qt.ScrollBarPolicy.ScrollBarAlwaysOn
                )
                v_target = (
                    Qt.ScrollBarPolicy.ScrollBarAsNeeded
                    if content_ok
                    else Qt.ScrollBarPolicy.ScrollBarAlwaysOn
                )
                if (
                    self.horizontalScrollBarPolicy() == h_target
                    and self.verticalScrollBarPolicy() == v_target
                ):
                    break
                self.setHorizontalScrollBarPolicy(h_target)
                self.setVerticalScrollBarPolicy(v_target)
        finally:
            hsb.blockSignals(False)
            vsb.blockSignals(False)
            self._syncing_scrollbar_policy = False

    def scroll_diagram_content_to_top_left(self, *, margin_vp: int = 4) -> None:
        """
        Place the tight bounding box of diagram items flush to the top-left of the viewport.

        Used after ``load`` so the opened project is not presented centred. Does not change zoom;
        adjusts scroll bars so ``itemsBoundingRect().topLeft()`` maps near ``(margin_vp, margin_vp)``.
        """
        sc = self.scene()
        if sc is None:
            return
        self._sync_scrollbar_policy_for_scene_origin()
        bounds = sc.itemsBoundingRect()
        if not bounds.isValid() or bounds.isEmpty():
            return
        tl = bounds.topLeft()
        vp_tl = self.mapFromScene(tl)
        margin = QPoint(int(margin_vp), int(margin_vp))
        delta = vp_tl - margin
        if delta.x() == 0 and delta.y() == 0:
            return
        hsb = self.horizontalScrollBar()
        vsb = self.verticalScrollBar()
        hsb.setValue(hsb.value() + delta.x())
        vsb.setValue(vsb.value() + delta.y())

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._sync_scrollbar_policy_for_scene_origin()
        # region agent log
        c = self.viewport().rect().center()
        p = self.mapToScene(c)
        _append_debug_log(
            "H6",
            "dataflow_canvas.py:resizeEvent",
            "view resize baseline",
            {
                "viewport_center": [c.x(), c.y()],
                "scene_at_viewport_center": [p.x(), p.y()],
                "alignment": str(self.alignment()),
            },
        )
        # endregion

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._sync_scrollbar_policy_for_scene_origin()
        # region agent log
        c = self.viewport().rect().center()
        p = self.mapToScene(c)
        _append_debug_log(
            "H6",
            "dataflow_canvas.py:showEvent",
            "view show baseline",
            {
                "viewport_center": [c.x(), c.y()],
                "scene_at_viewport_center": [p.x(), p.y()],
                "alignment": str(self.alignment()),
            },
        )
        # endregion

    def set_viewport_canvas_color(self, hex_color: str) -> None:
        """Match scene and parent chrome: QGraphicsView draws this behind / around the scene."""
        self.setBackgroundBrush(QColor(hex_color))

    def set_interaction_locked(self, locked: bool) -> None:
        """Simulation / view-only mode: no editing; Ctrl+drag on empty canvas still pans."""
        self._interaction_locked = bool(locked)
        if locked:
            if self._placement_tool:
                self._placement_tool.cancel(emit_cancelled=False)
            if self._route_tool:
                self._route_tool.cancel()
            self.viewport().setCursor(self._arrow_cursor)
        self._pan_active = False

    def attach_connector_route_tool(self, controller: SynariusController) -> None:
        """Enable click-to-route connectors (orthogonal H/V) using the given controller model."""
        if self.scene() is None:
            return
        self._route_tool = ConnectorRouteTool(controller, self.scene(), self)
        self._route_tool.finished.connect(self.connector_route_command.emit)

    def attach_placement_tool(self, controller: SynariusController) -> None:
        if self.scene() is None:
            return
        self._controller_for_placement = controller
        self._placement_tool = CanvasPlacementTool(self.scene(), self)
        self._placement_tool.finished.connect(self.placement_command.emit)
        self._placement_tool.cancelled.connect(self.placement_cancelled.emit)

    def placement_tool(self) -> CanvasPlacementTool | None:
        return self._placement_tool

    def cancel_interactive_route(self) -> None:
        if self._route_tool and self._route_tool.active():
            self._route_tool.cancel()

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

    @staticmethod
    def _dataviewer_block_under(view: QGraphicsView, pos: QPoint) -> DataViewerBlockItem | None:
        it = view.itemAt(pos)
        while it is not None:
            if isinstance(it, DataViewerBlockItem):
                return it
            it = it.parentItem()
        return None

    def _cancel_deferred_scene_left_release(self) -> None:
        if self._deferred_scene_left_release_timer.isActive():
            self._deferred_scene_left_release_timer.stop()

    def _should_defer_left_release_for_dataviewer(self, event: QMouseEvent) -> bool:
        if event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            return False
        if not self.rubberBandRect().isNull():
            return False
        vp_pos = event.position().toPoint()
        return self._dataviewer_block_under(self, vp_pos) is not None

    def _schedule_deferred_scene_left_release(self) -> None:
        self._deferred_scene_left_release_timer.stop()
        ms = QGuiApplication.styleHints().mouseDoubleClickInterval()
        self._deferred_scene_left_release_timer.start(ms)

    def _fire_deferred_scene_left_release(self) -> None:
        self._emit_scene_left_release_maybe_skip_selection_sync()
        self._emit_block_move_finished_if_uniform()

    def _post_left_release_selection_and_block_move(self, event: QMouseEvent) -> None:
        if self._should_defer_left_release_for_dataviewer(event):
            self._schedule_deferred_scene_left_release()
            return
        self._emit_scene_left_release_maybe_skip_selection_sync()
        self._emit_block_move_finished_if_uniform()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        sc = self.scene()
        if event.button() == Qt.MouseButton.LeftButton:
            self._cancel_deferred_scene_left_release()
            self._pending_selection_change = None
        if event.button() == Qt.MouseButton.MiddleButton:
            # Middle-button drag pans the canvas independent of item hits/modifiers.
            self._cancel_deferred_scene_left_release()
            self._pending_selection_change = None
            self._move_anchor_snapshot = None
            self._pan_active = True
            self._pan_viewport_pos = pos
            self._pan_h_scroll = self.horizontalScrollBar().value()
            self._pan_v_scroll = self.verticalScrollBar().value()
            self.viewport().setCursor(self._closed_hand)
            event.accept()
            return
        if self._interaction_locked:
            dv = self._dataviewer_block_under(self, pos)
            if event.button() == Qt.MouseButton.LeftButton and dv is not None:
                _pre_sel = set(sc.selectedItems()) if sc is not None else set()
                super().mousePressEvent(event)
                if sc is not None:
                    _post_sel = set(sc.selectedItems())
                    if _post_sel != _pre_sel:
                        self._pending_selection_change = (_pre_sel, _post_sel)
                        for it in _post_sel - _pre_sel:
                            it.setSelected(False)
                        for it in _pre_sel - _post_sel:
                            it.setSelected(True)
                    self._move_anchor_snapshot = {
                        id(it): QPointF(it.pos())
                        for it in _post_sel
                        if isinstance(it, DataViewerBlockItem)
                    }
                return
            if event.button() == Qt.MouseButton.LeftButton:
                if not self._item_under(pos) and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                    # Ctrl+Drag on leerer Fläche: panning, auch im Simulationsmodus.
                    self._move_anchor_snapshot = None
                    self._pan_active = True
                    self._pan_viewport_pos = pos
                    self._pan_h_scroll = self.horizontalScrollBar().value()
                    self._pan_v_scroll = self.verticalScrollBar().value()
                    self.viewport().setCursor(self._closed_hand)
                    event.accept()
                    return
                # Sonst Standardverhalten von QGraphicsView erlauben (z.B. Rubberband-Selektion für DataViewer).
                super().mousePressEvent(event)
                return
            event.accept()
            return
        if (
            self._route_tool
            and self._route_tool.active()
            and event.button() == Qt.MouseButton.LeftButton
        ):
            event.accept()
            return
        if (
            self._placement_tool
            and self._placement_tool.active()
            and event.button() == Qt.MouseButton.LeftButton
            and self._controller_for_placement is not None
        ):
            scene_pos = self.mapToScene(pos)
            if self._placement_tool.try_place(self._controller_for_placement, scene_pos):
                self._eat_next_left_release_for_route = True
            event.accept()
            return
        if (
            event.button() == Qt.MouseButton.LeftButton
            and not self._item_under(pos)
            and (event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        ):
            self._move_anchor_snapshot = None
            self._pan_active = True
            self._pan_viewport_pos = pos
            self._pan_h_scroll = self.horizontalScrollBar().value()
            self._pan_v_scroll = self.verticalScrollBar().value()
            self.viewport().setCursor(self._closed_hand)
            event.accept()
            return
        _pre_sel = set(sc.selectedItems()) if sc is not None else set()
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and sc is not None:
            _post_sel = set(sc.selectedItems())
            if _post_sel != _pre_sel and self._item_under(pos):
                self._pending_selection_change = (_pre_sel, _post_sel)
                for it in _post_sel - _pre_sel:
                    it.setSelected(False)
                for it in _pre_sel - _post_sel:
                    it.setSelected(True)
            self._move_anchor_snapshot = {
                id(it): QPointF(it.pos())
                for it in _post_sel
                if isinstance(it, (VariableBlockItem, OperatorBlockItem, FmuBlockItem, DataViewerBlockItem))
            }

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._pan_active and self._pan_viewport_pos is not None:
            pos = event.position().toPoint()
            prev_pos = self._pan_viewport_pos
            prev_scene = self.mapToScene(prev_pos)
            now_scene = self.mapToScene(pos)
            ds = now_scene - prev_scene
            if abs(ds.x()) > 1e-9 or abs(ds.y()) > 1e-9:
                # Allow panning even when scrollbars currently have zero range.
                visible = self.mapToScene(self.viewport().rect()).boundingRect()
                self._ensure_scene_rect_covers_items()
                self._ensure_scene_rect_covers_rect(visible.translated(-ds.x(), -ds.y()))
                vc = self.viewport().rect().center()
                center_scene = self.mapToScene(vc)
                self.centerOn(center_scene.x() - ds.x(), center_scene.y() - ds.y())
            self._pan_viewport_pos = pos
            event.accept()
            return
        if self._interaction_locked:
            super().mouseMoveEvent(event)
            return
        vp_pos = event.position().toPoint()
        scene_pos = self.mapToScene(vp_pos)
        if self._placement_tool and self._placement_tool.active():
            self._placement_tool.move_mouse_scene(scene_pos)
            self.viewport().setCursor(self._placement_hand)
            event.accept()
            return
        super().mouseMoveEvent(event)
        if self._route_tool and self._route_tool.active():
            self._route_tool.move_mouse_scene(scene_pos)
            top = self.itemAt(vp_pos)
            self._route_tool.update_active_cursor(scene_pos, vp_pos, top)
            return
        if not self.rubberBandRect().isNull():
            return
        if self._route_tool:
            top = self.itemAt(vp_pos)
            self._route_tool.hover_free_pin_cursor(scene_pos, vp_pos, top)
        else:
            self._cursor_hint_empty_canvas(vp_pos)

    def _apply_pending_selection_change(self) -> None:
        """Apply a selection change that was deferred from mousePressEvent to mouseReleaseEvent."""
        pending = self._pending_selection_change
        self._pending_selection_change = None
        if pending is None or self.scene() is None:
            return
        pre, post = pending
        for it in post - pre:
            it.setSelected(True)
        for it in pre - post:
            it.setSelected(False)

    def _emit_scene_left_release_maybe_skip_selection_sync(self) -> None:
        """Emit ``scene_left_release`` unless a handled item double-click requested a one-time skip (avoids duplicate ``select``)."""
        sc = self.scene()
        if isinstance(sc, SynariusDiagramScene) and sc.take_suppress_next_left_release_selection_sync():
            return
        self.scene_left_release.emit()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton) and self._pan_active:
            self._pending_selection_change = None
            self._pan_active = False
            self._pan_viewport_pos = None
            pos = event.position().toPoint()
            self._cursor_hint_empty_canvas(pos)
            self._sync_scrollbar_policy_for_scene_origin()
            event.accept()
            return
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._eat_next_left_release_for_route
        ):
            self._eat_next_left_release_for_route = False
        elif (
            event.button() == Qt.MouseButton.LeftButton
            and self._route_tool is not None
        ):
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            vp_pos = event.position().toPoint()
            scene_pos = self.mapToScene(vp_pos)
            top = self.itemAt(vp_pos)
            if self._route_tool.active():
                self._route_tool.on_left_release(scene_pos, top)
                event.accept()
                self._apply_pending_selection_change()
                self._emit_scene_left_release_maybe_skip_selection_sync()
                self._emit_block_move_finished_if_uniform()
                return
            if self._route_tool.try_start_from_release(scene_pos, top):
                # Route tool handled release; still forward so the pin item receives
                # mouseRelease after its mousePress (super delivered press in mousePressEvent).
                event.accept()
                super().mouseReleaseEvent(event)
                self._apply_pending_selection_change()
                self._emit_scene_left_release_maybe_skip_selection_sync()
                self._emit_block_move_finished_if_uniform()
                return
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._apply_pending_selection_change()
            self._post_left_release_selection_and_block_move(event)

    def _emit_block_move_finished_if_uniform(self) -> None:
        snap = self._move_anchor_snapshot
        self._move_anchor_snapshot = None
        if not snap or self.scene() is None:
            return
        scene = self.scene()
        tol = 1e-2
        deltas: list[QPointF] = []
        for iid, old in snap.items():
            it = next((x for x in scene.items() if id(x) == iid), None)
            if it is None:
                continue
            deltas.append(it.pos() - old)
        if not deltas:
            return
        d0 = deltas[0]
        if not all(abs(d.x() - d0.x()) <= tol and abs(d.y() - d0.y()) <= tol for d in deltas):
            return
        if abs(d0.x()) <= tol and abs(d0.y()) <= tol:
            return
        self.block_move_finished.emit(d0.x(), d0.y())

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if self._interaction_locked:
            # Im Simulationsmodus: DataViewer und Kenngrößen-Blöcke erhalten Doppelklick.
            pos = event.position().toPoint()
            if event.button() == Qt.MouseButton.LeftButton:
                dv = self._dataviewer_block_under(self, pos)
                if dv is not None:
                    super().mouseDoubleClickEvent(event)
                    return
                top = self.itemAt(pos)
                while top is not None and not isinstance(top, FmuBlockItem):
                    top = top.parentItem()
                if isinstance(top, FmuBlockItem) and top._el.type_key in STD_PARAM_LOOKUP:
                    super().mouseDoubleClickEvent(event)
                    return
            event.accept()
            return
        if (
            self._placement_tool
            and self._placement_tool.active()
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._placement_tool.cancel(emit_cancelled=True)
            event.accept()
            return
        if (
            self._route_tool
            and self._route_tool.active()
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._route_tool.cancel()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape and self._placement_tool and self._placement_tool.active():
            self._placement_tool.cancel(emit_cancelled=True)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self._route_tool and self._route_tool.active():
            self._route_tool.cancel()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selection_requested.emit()
            event.accept()
            return
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
            if self._placement_tool and self._placement_tool.active():
                vp.setCursor(self._placement_hand)
            else:
                self._cursor_hint_empty_canvas(vp.mapFromGlobal(QCursor.pos()))

    def leaveEvent(self, event: QEvent) -> None:
        if not self._pan_active and not (self._route_tool and self._route_tool.active()):
            if not (self._placement_tool and self._placement_tool.active()):
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
        self._sync_scrollbar_policy_for_scene_origin()



    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        mods = event.modifiers()

        # --- 1. Scrolling (wie gehabt) ---
        if mods & Qt.KeyboardModifier.ControlModifier:
            hsb = self.horizontalScrollBar()
            hsb.setValue(hsb.value() - delta)
            self._sync_scrollbar_policy_for_scene_origin()
            event.accept()
            return
        if mods & Qt.KeyboardModifier.ShiftModifier:
            vsb = self.verticalScrollBar()
            vsb.setValue(vsb.value() - delta)
            self._sync_scrollbar_policy_for_scene_origin()
            event.accept()
            return

        # --- 2. Zoom Logik ---
        zoom_factor = 1.15 ** (delta / 240.0)
        if abs(zoom_factor - 1.0) < 1e-9:
            return

        # A) Fixpunkt vor dem Zoom sichern
        viewport_pos = event.position()
        scene_pos = self.mapToScene(viewport_pos.toPoint())

        # B) Anker deaktivieren, um Autozentrierung zu minimieren
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.NoAnchor)

        # C) Die Skalierung direkt auf die Matrix anwenden
        # Wir nutzen die mathematische Verschiebung zum Punkt, Skalierung, Rückverschiebung
        old_transform = self.transform()
        new_transform = old_transform.translate(scene_pos.x(), scene_pos.y())
        new_transform.scale(zoom_factor, zoom_factor)
        new_transform.translate(-scene_pos.x(), -scene_pos.y())
        
        self.setTransform(new_transform)

        # D) Scrollbar-Policy Sync
        self._sync_scrollbar_policy_for_scene_origin()

        # E) Korrektur für den Fall "Keine Scrollbars" oder "Viewport-Resize"
        # Wir schauen, wo scene_pos nach setTransform gelandet ist
        current_pos_in_view = self.mapFromScene(scene_pos)
        delta_pixel = current_pos_in_view - viewport_pos.toPoint()

        # Wenn ein Delta existiert (weil Qt zentriert hat oder keine Scrollbars da sind),
        # korrigieren wir das über die interne Verschiebung der Matrix.
        if not delta_pixel.isNull():
            # Wir korrigieren die Matrix direkt um den Pixel-Versatz, 
            # um die "Zentrierung" von Qt zu übersteuern.
            inv_transform, _ = self.transform().inverted()
            delta_scene = inv_transform.map(QPointF(delta_pixel)) - inv_transform.map(QPointF(0, 0))
            self.setTransform(self.transform().translate(-delta_scene.x(), -delta_scene.y()))

        self.zoom_percent_changed.emit(self.zoom_percent())
        event.accept()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._interaction_locked:
            event.ignore()
            return
        if event.mimeData().hasFormat(VARIABLE_NAME_DRAG_MIME):
            event.acceptProposedAction()
            return
        if event.mimeData().hasFormat(SIGNAL_NAME_DRAG_MIME):
            event.acceptProposedAction()
            return
        if event.mimeData().hasFormat(LIBRARY_ELEMENT_DRAG_MIME):
            event.acceptProposedAction()
            return
        if event.mimeData().hasFormat(LIBRARY_ELEMENT_NAMED_DRAG_MIME):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._interaction_locked:
            event.ignore()
            return
        if event.mimeData().hasFormat(VARIABLE_NAME_DRAG_MIME):
            event.acceptProposedAction()
            return
        if event.mimeData().hasFormat(SIGNAL_NAME_DRAG_MIME):
            event.acceptProposedAction()
            return
        if event.mimeData().hasFormat(LIBRARY_ELEMENT_DRAG_MIME):
            event.acceptProposedAction()
            return
        if event.mimeData().hasFormat(LIBRARY_ELEMENT_NAMED_DRAG_MIME):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if self._interaction_locked:
            event.ignore()
            return
        md = event.mimeData()
        if md.hasFormat(VARIABLE_NAME_DRAG_MIME):
            raw = bytes(md.data(VARIABLE_NAME_DRAG_MIME)).decode("utf-8", errors="strict").strip()
            if raw:
                if self._placement_tool and self._placement_tool.active():
                    self._placement_tool.cancel(emit_cancelled=False)
                scene_pos = self.mapToScene(event.position().toPoint())
                try:
                    cmd = variable_new_instance_command(raw, scene_pos)
                except InvalidVariableNameError:
                    event.acceptProposedAction()
                    return
                self.placement_command.emit(cmd)
            event.acceptProposedAction()
            return
        if md.hasFormat(SIGNAL_NAME_DRAG_MIME):
            raw = bytes(md.data(SIGNAL_NAME_DRAG_MIME)).decode("utf-8", errors="strict").strip()
            if raw:
                vp = event.position().toPoint()
                it = self.itemAt(vp)
                while it is not None and not isinstance(it, VariableBlockItem):
                    it = it.parentItem()
                if isinstance(it, VariableBlockItem):
                    self.signal_mapping_drop.emit(raw, str(it.variable().name))
            event.acceptProposedAction()
            return
        if md.hasFormat(LIBRARY_ELEMENT_DRAG_MIME):
            raw = bytes(md.data(LIBRARY_ELEMENT_DRAG_MIME)).decode("utf-8", errors="strict").strip()
            if raw and self._controller_for_placement is not None:
                if self._placement_tool and self._placement_tool.active():
                    self._placement_tool.cancel(emit_cancelled=False)
                scene_pos = self.mapToScene(event.position().toPoint())
                cmd = library_element_drop_command(self._controller_for_placement, raw, scene_pos)
                if cmd:
                    self.placement_command.emit(cmd)
                else:
                    QMessageBox.information(
                        self.window(),
                        "Librarys",
                        "Dragging to the diagram is only supported for standard arithmetic blocks "
                        "(Add, Sub, Mul, Div). Place other library elements via the console.",
                    )
            event.acceptProposedAction()
            return
        if md.hasFormat(LIBRARY_ELEMENT_NAMED_DRAG_MIME):
            raw = bytes(md.data(LIBRARY_ELEMENT_NAMED_DRAG_MIME)).decode("utf-8", errors="strict")
            parts = raw.split("\0", 1)
            if len(parts) == 2 and self._controller_for_placement is not None:
                type_key, inst_name = parts[0].strip(), parts[1].strip()
                if type_key and inst_name:
                    if self._placement_tool and self._placement_tool.active():
                        self._placement_tool.cancel(emit_cancelled=False)
                    scene_pos = self.mapToScene(event.position().toPoint())
                    cmd = library_element_named_drop_command(
                        self._controller_for_placement, type_key, inst_name, scene_pos
                    )
                    if cmd:
                        self.placement_command.emit(cmd)
            event.acceptProposedAction()
            return
        super().dropEvent(event)
