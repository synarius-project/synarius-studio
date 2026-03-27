"""Layout and populate a scene from a synarius-core ``Model`` (e.g. loaded from ``test.syn``)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtWidgets import QGraphicsScene

from synarius_core.model import BasicOperator, Connector, Model, Variable

from .dataflow_items import (
    ConnectorEdgeItem,
    OperatorBlockItem,
    UI_SCALE,
    VariableBlockItem,
)

if TYPE_CHECKING:
    pass

# Pre-scale layout (M = reference module 15); multiplied by UI_SCALE in scene coords.
# Operator pins sit at local y = M, 2M, 1.5M — variable out at py+M matches when py = op_y or py = op_y+M.
# Lower branch (c,d) starts below the first variable column (vtx_c at op_mul_a row).
_LAYOUT_M = 15.0
_Y0 = 40.0

_BASE_POSITIONS: dict[str, tuple[float, float]] = {
    "vtx_a": (24.0, _Y0),
    "vtx_b": (24.0, _Y0 + _LAYOUT_M),
    "op_add": (188.0, _Y0),
    "v_sum": (368.0, _Y0 + 0.5 * _LAYOUT_M),
    "vtx_c": (24.0, _Y0 + 4.0 * _LAYOUT_M),
    "vtx_d": (24.0, _Y0 + 5.0 * _LAYOUT_M),
    "op_mul_a": (188.0, _Y0 + 4.0 * _LAYOUT_M),
    "v_prod": (368.0, _Y0 + 4.5 * _LAYOUT_M),
    "op_mul_b": (528.0, _Y0 + 0.5 * _LAYOUT_M),
    "v_out": (708.0, _Y0 + _LAYOUT_M),
}

_POSITIONS: dict[str, tuple[float, float]] = {
    name: (x * UI_SCALE, y * UI_SCALE) for name, (x, y) in _BASE_POSITIONS.items()
}

SCENE_RECT = QRectF(0.0, 0.0, 900.0 * UI_SCALE, 520.0 * UI_SCALE)


def default_sample_syn_path() -> Path:
    """Path to bundled ``resources/test.syn`` next to the ``synarius_studio`` package."""
    return Path(__file__).resolve().parent.parent / "resources" / "test.syn"


def populate_scene_from_model(scene: QGraphicsScene, model: Model) -> None:
    """
    Clear ``scene`` and add items for all ``Variable``, ``BasicOperator``, and ``Connector``
    children of ``model.root``. Uses fixed positions for the ``test.syn`` naming convention.
    """
    scene.clear()
    id_to_item: dict[UUID, VariableBlockItem | OperatorBlockItem] = {}

    root = model.root
    for child in root.children:
        if isinstance(child, Variable):
            pos = _POSITIONS.get(child.name, (40.0, 40.0))
            item = VariableBlockItem(child)
            item.setPos(pos[0], pos[1])
            scene.addItem(item)
            if child.id is not None:
                id_to_item[child.id] = item
        elif isinstance(child, BasicOperator):
            pos = _POSITIONS.get(child.name, (200.0, 200.0))
            item = OperatorBlockItem(child)
            item.setPos(pos[0], pos[1])
            scene.addItem(item)
            if child.id is not None:
                id_to_item[child.id] = item

    for child in root.children:
        if not isinstance(child, Connector):
            continue
        src = model.find_by_id(child.source_instance_id)
        dst = model.find_by_id(child.target_instance_id)
        if src is None or dst is None or src.id is None or dst.id is None:
            continue
        a = id_to_item.get(src.id)
        b = id_to_item.get(dst.id)
        if a is None or b is None:
            continue
        edge = ConnectorEdgeItem()
        edge.attach_blocks(a, b, child.source_pin, child.target_pin)
        scene.addItem(edge)

    scene.setSceneRect(SCENE_RECT)
