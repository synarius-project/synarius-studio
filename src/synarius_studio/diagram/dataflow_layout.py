"""Layout and populate a scene from a synarius-core ``Model`` (e.g. loaded from bundled examples)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QGraphicsScene

from synarius_core.dataflow_sim import elementary_has_fmu_path
from synarius_core.dataflow_sim._std_type_keys import STD_ARITHMETIC_OP, STD_PARAM_LOOKUP
from synarius_core.model import BasicOperator, Connector, DataViewer, ElementaryInstance, Model, Variable

from .dataflow_items import (
    ConnectorEdgeItem,
    DataViewerBlockItem,
    FmuBlockItem,
    OperatorBlockItem,
    UI_SCALE,
    VariableBlockItem,
    refresh_all_connector_crossing_strokes,
)

if TYPE_CHECKING:
    pass

# Default scene bounds (pre-scale units × UI_SCALE). Node positions come from the loaded model (``x``/``y`` on instances).
SCENE_RECT = QRectF(0.0, 0.0, 900.0 * UI_SCALE, 520.0 * UI_SCALE)


def default_sample_syn_path() -> Path:
    """Path to bundled ``resources/example_modelling.syn`` next to the ``synarius_studio`` package."""
    return Path(__file__).resolve().parent.parent / "resources" / "example_modelling.syn"


def open_syn_dialog_start_dir() -> Path:
    """
    Initial directory for *Open* / *Save* on ``.syn`` files.

    When frozen (PyInstaller / MSI install), bundled example ``.syn`` files sit next to ``sys.executable``.
    In development, default to the package ``resources`` folder.
    """
    import sys

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        # Prefer locations that actually contain bundled .syn examples.
        candidates: list[Path] = [exe_dir]
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "synarius_studio" / "resources")
        start_dir = exe_dir
        for candidate in candidates:
            try:
                if candidate.is_dir() and any(candidate.glob("*.syn")):
                    start_dir = candidate
                    break
            except Exception:
                continue
    else:
        start_dir = default_sample_syn_path().parent
    return start_dir


def populate_scene_from_model(
    scene: QGraphicsScene,
    model: Model,
    *,
    on_connector_orthogonal_bends: Callable[[Connector, list[float]], bool] | None = None,
) -> None:
    """
    Clear ``scene`` and add items for ``Variable``, ``BasicOperator``, FMU elementaries
    (non-variable/non-operator with ``fmu.path``), ``DataViewer``, and ``Connector`` children of
    ``model.root``. Block positions follow each instance's ``x`` / ``y`` in model space.
    """
    scene.clear()
    id_to_item: dict[UUID, VariableBlockItem | OperatorBlockItem | FmuBlockItem] = {}

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
        elif isinstance(child, DataViewer):
            pos = (child.x * UI_SCALE, child.y * UI_SCALE)
            item = DataViewerBlockItem(child)
            item.setPos(pos[0], pos[1])
            scene.addItem(item)
        elif isinstance(child, ElementaryInstance) and child.type_key in STD_ARITHMETIC_OP:
            pos = (child.x * UI_SCALE, child.y * UI_SCALE)
            item = FmuBlockItem(child)
            item.setPos(pos[0], pos[1])
            scene.addItem(item)
            if child.id is not None:
                id_to_item[child.id] = item
        elif isinstance(child, ElementaryInstance) and child.type_key in STD_PARAM_LOOKUP:
            pos = (child.x * UI_SCALE, child.y * UI_SCALE)
            item = FmuBlockItem(child)
            item.setPos(pos[0], pos[1])
            scene.addItem(item)
            if child.id is not None:
                id_to_item[child.id] = item
        elif isinstance(child, ElementaryInstance) and elementary_has_fmu_path(child):
            pos = (child.x * UI_SCALE, child.y * UI_SCALE)
            item = FmuBlockItem(child)
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
        edge.set_bends_apply_fn(on_connector_orthogonal_bends)
        edge.attach_blocks(a, b, child.source_pin, child.target_pin)
        scene.addItem(edge)

    refresh_all_connector_crossing_strokes(scene)

    scene.setSceneRect(SCENE_RECT)
