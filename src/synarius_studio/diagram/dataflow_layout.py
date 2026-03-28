"""Layout and populate a scene from a synarius-core ``Model`` (e.g. loaded from ``test.syn``)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from PySide6.QtCore import QRectF
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

# Default scene bounds (pre-scale units × UI_SCALE). Node positions come from the loaded model (``x``/``y`` on instances).
SCENE_RECT = QRectF(0.0, 0.0, 900.0 * UI_SCALE, 520.0 * UI_SCALE)


def default_sample_syn_path() -> Path:
    """Path to bundled ``resources/test.syn`` next to the ``synarius_studio`` package."""
    return Path(__file__).resolve().parent.parent / "resources" / "test.syn"


def open_syn_dialog_start_dir() -> Path:
    """
    Initial directory for *Open* / *Save* on ``.syn`` files.

    When frozen (PyInstaller / MSI install), sample ``test.syn`` sits next to ``sys.executable``.
    In development, default to the package ``resources`` folder.
    """
    import sys

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return default_sample_syn_path().parent


def populate_scene_from_model(scene: QGraphicsScene, model: Model) -> None:
    """
    Clear ``scene`` and add items for all ``Variable``, ``BasicOperator``, and ``Connector``
    children of ``model.root``. Block positions are ``(x, y)`` from each instance in the model
    (as set by ``new Variable … x y size`` / ``new BasicOperator … x y …`` in the loaded script).
    """
    scene.clear()
    id_to_item: dict[UUID, VariableBlockItem | OperatorBlockItem] = {}

    root = model.root
    for child in root.children:
        if isinstance(child, Variable):
            pos = (child.x * UI_SCALE, child.y * UI_SCALE)
            item = VariableBlockItem(child)
            item.setPos(pos[0], pos[1])
            scene.addItem(item)
            if child.id is not None:
                id_to_item[child.id] = item
        elif isinstance(child, BasicOperator):
            pos = (child.x * UI_SCALE, child.y * UI_SCALE)
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
        edge.set_domain_connector(child)
        edge.attach_blocks(a, b, child.source_pin, child.target_pin)
        scene.addItem(edge)

    scene.setSceneRect(SCENE_RECT)
