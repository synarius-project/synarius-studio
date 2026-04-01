"""Click-to-place Variable / BasicOperator using the same block graphics as the diagram (incl. pins)."""

from __future__ import annotations

import shlex
from uuid import uuid4

from PySide6.QtCore import QObject, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QInputDialog,
    QMessageBox,
)

from synarius_core.controller import MinimalController
from synarius_core.model import BasicOperator, BasicOperatorType, Model, Variable
from synarius_core.model.diagram_geometry import variable_diagram_block_width_scene
from synarius_core.variable_naming import InvalidVariableNameError, validate_python_variable_name

from .dataflow_items import (
    OPERATOR_SIZE,
    UI_SCALE,
    VARIABLE_HEIGHT,
    VARIABLE_WIDTH,
    OperatorBlockItem,
    VariableBlockItem,
    _snap_pos_half_module,
)

# Drag from Variables panel → canvas (``QMimeData`` custom format).
VARIABLE_NAME_DRAG_MIME = "application/x-synarius-variable-name"
# Drag from Signals panel → variable block (mapping by drop on canvas).
SIGNAL_NAME_DRAG_MIME = "application/x-synarius-signal-name"
# Drag from Resources panel: UTF-8 ``<LibraryName>.<ElementId>`` (same as model ``type_key``).
LIBRARY_ELEMENT_DRAG_MIME = "application/x-synarius-library-element"


def _placing_block_size_scene(mode: str, preview: QGraphicsItem | None = None) -> tuple[float, float]:
    if mode == "var":
        if isinstance(preview, VariableBlockItem):
            r = preview.rect()
            return (r.width(), r.height())
        return (VARIABLE_WIDTH, VARIABLE_HEIGHT)
    return (OPERATOR_SIZE, OPERATOR_SIZE)


def _cursor_centered_top_left_scene(
    mode: str, scene_pos: QPointF, preview: QGraphicsItem | None = None
) -> tuple[QPointF, float, float]:
    """Snap cursor point to grid, then top-left of block so the block is centered on that point."""
    c = _snap_pos_half_module(scene_pos)
    w, h = _placing_block_size_scene(mode, preview)
    tl = QPointF(c.x() - w * 0.5, c.y() - h * 0.5)
    mx = tl.x() / UI_SCALE
    my = tl.y() / UI_SCALE
    return tl, mx, my

_OP_MODE_TO_TYPE: dict[str, BasicOperatorType] = {
    "+": BasicOperatorType.PLUS,
    "-": BasicOperatorType.MINUS,
    "*": BasicOperatorType.MULTIPLY,
    "/": BasicOperatorType.DIVIDE,
}

# Standard library arithmetic elements map to on-canvas ``BasicOperator`` (same as toolbox).
_STD_LIBRARY_OP_SYMBOL: dict[tuple[str, str], str] = {
    ("std", "Add"): "+",
    ("std", "Sub"): "-",
    ("std", "Mul"): "*",
    ("std", "Div"): "/",
}


def _make_preview_noninteractive(root: QGraphicsItem) -> None:
    stack: list[QGraphicsItem] = [root]
    while stack:
        it = stack.pop()
        it.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        it.setAcceptHoverEvents(False)
        stack.extend(it.childItems())


def _make_preview_block(mode: str) -> VariableBlockItem | OperatorBlockItem:
    if mode == "var":
        v = Variable(name="v", type_key="Variable", obj_id=uuid4())
        it: VariableBlockItem | OperatorBlockItem = VariableBlockItem(v, drop_shadow=False)
    else:
        op_t = _OP_MODE_TO_TYPE[mode]
        o = BasicOperator(
            name="_preview",
            type_key="BasicOperator",
            operation=op_t,
            obj_id=uuid4(),
        )
        it = OperatorBlockItem(o, drop_shadow=False)
    it.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
    it.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
    # Moving the ghost must not run connector notifications over the whole scene (stability + perf).
    it.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, False)
    it.setOpacity(0.92)
    it.setZValue(250.0)
    _make_preview_noninteractive(it)
    return it


def _existing_instance_names(model: Model) -> set[str]:
    names: set[str] = set()
    for ch in model.root.children:
        if isinstance(ch, (Variable, BasicOperator)):
            names.add(ch.name)
    return names


def _pick_unique_name(existing: set[str], base: str) -> str:
    if base not in existing:
        return base
    n = 2
    while f"{base}_{n}" in existing:
        n += 1
    return f"{base}_{n}"


def library_element_drop_command(controller: MinimalController, type_key: str, scene_pos: QPointF) -> str | None:
    """
    Build a ``new`` command for a Resource tile dropped on the diagram, or ``None`` if unsupported.

    Currently only the bundled standard library four arithmetic elements are placed on the canvas;
    other types need the console or future diagram support for generic ``ElementaryInstance``.
    """
    tk = type_key.strip()
    if "." not in tk:
        return None
    lib_name, elem_id = tk.split(".", 1)
    sym = _STD_LIBRARY_OP_SYMBOL.get((lib_name, elem_id))
    if sym is None:
        return None
    existing = _existing_instance_names(controller.model)
    c = _snap_pos_half_module(scene_pos)
    w, h = OPERATOR_SIZE, OPERATOR_SIZE
    tl = QPointF(c.x() - w * 0.5, c.y() - h * 0.5)
    mx = tl.x() / UI_SCALE
    my = tl.y() / UI_SCALE
    base = {"+": "op_plus", "-": "op_minus", "*": "op_mul", "/": "op_div"}[sym]
    op_name = _pick_unique_name(existing, base)
    return f"new BasicOperator {sym} {mx:.12g} {my:.12g} name={shlex.quote(op_name)}"


def variable_new_instance_command(name: str, scene_pos: QPointF) -> str:
    """``new Variable`` command for another canvas instance (same registry name, snapped grid)."""
    validate_python_variable_name(name)
    w = variable_diagram_block_width_scene(name)
    c = _snap_pos_half_module(scene_pos)
    tl = QPointF(c.x() - w * 0.5, c.y() - VARIABLE_HEIGHT * 0.5)
    mx = tl.x() / UI_SCALE
    my = tl.y() / UI_SCALE
    return f"new Variable {shlex.quote(name)} {mx:.12g} {my:.12g} 1"


class CanvasPlacementTool(QObject):
    """
    While active: shows a real Variable/Operator block (same paint + pins), snapped to the grid,
    closed-hand cursor on the view, and emits ``finished`` with a ``new`` command on left click.
    """

    finished = Signal(str)
    cancelled = Signal()

    def __init__(self, scene: QGraphicsScene, view: QGraphicsView) -> None:
        super().__init__(view)
        self._scene = scene
        self._view = view
        self._mode: str | None = None
        self._preview_block: VariableBlockItem | OperatorBlockItem | None = None

    def active(self) -> bool:
        return self._mode is not None

    def activate(self, mode: str) -> None:
        """``mode``: ``var`` | ``+`` | ``-`` | ``*`` | ``/``."""
        self.cancel(emit_cancelled=False)
        self._mode = mode
        self._preview_block = _make_preview_block(mode)
        self._scene.addItem(self._preview_block)
        self._view.setDragMode(QGraphicsView.DragMode.NoDrag)
        local = self._view.viewport().mapFromGlobal(QCursor.pos())
        if self._view.viewport().rect().contains(local):
            self.move_mouse_scene(self._view.mapToScene(local))

    def cancel(self, *, emit_cancelled: bool = False) -> None:
        if self._mode is None and self._preview_block is None:
            return
        self._mode = None
        if self._preview_block is not None:
            self._preview_block.setGraphicsEffect(None)
            self._scene.removeItem(self._preview_block)
            self._preview_block = None
        self._view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self._view.viewport().setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        if emit_cancelled:
            self.cancelled.emit()

    def move_mouse_scene(self, scene_pos: QPointF) -> None:
        if not self.active() or self._preview_block is None:
            return
        mode = self._mode
        if mode is None:
            return
        tl, _, _ = _cursor_centered_top_left_scene(mode, scene_pos, self._preview_block)
        self._preview_block.setPos(tl)

    def try_place(self, controller, scene_pos: QPointF) -> bool:
        """Build and emit ``new`` command at snapped coordinates; returns True if click consumed."""
        if not self.active():
            return False
        mode = self._mode
        if mode is None:
            return False
        _, mx, my = _cursor_centered_top_left_scene(mode, scene_pos, self._preview_block)
        model = controller.model
        existing = _existing_instance_names(model)

        self.cancel(emit_cancelled=False)

        if mode == "var":
            _invalid_name_msg = (
                "The name does not follow Python's naming convention for variables. "
                "Please correct it accordingly."
            )

            def _finish_variable_name() -> None:
                if QApplication.instance() is None:
                    return
                parent = self._view.window()
                last_text = ""
                while True:
                    dlg = QInputDialog(parent)
                    dlg.setWindowTitle("Variable")
                    dlg.setLabelText("Name:")
                    dlg.setTextValue(last_text)
                    dlg.setInputMode(QInputDialog.InputMode.TextInput)
                    dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
                    if dlg.exec() != QDialog.DialogCode.Accepted:
                        self.cancelled.emit()
                        return
                    raw = dlg.textValue().strip()
                    if not raw:
                        self.cancelled.emit()
                        return
                    try:
                        validate_python_variable_name(raw)
                    except InvalidVariableNameError:
                        QMessageBox.warning(parent, "Variable", _invalid_name_msg)
                        last_text = raw
                        continue
                    cmd = f"new Variable {shlex.quote(raw)} {mx:.12g} {my:.12g} 1"
                    self.finished.emit(cmd)
                    return

            # Defer past graphics input handling; extra delay helps some Windows/Qt builds.
            QTimer.singleShot(10, _finish_variable_name)
            return True

        sym = mode
        base = {"+": "op_plus", "-": "op_minus", "*": "op_mul", "/": "op_div"}[sym]
        op_name = _pick_unique_name(existing, base)
        cmd = f"new BasicOperator {sym} {mx:.12g} {my:.12g} name={shlex.quote(op_name)}"
        self.finished.emit(cmd)
        return True
