"""Layout and populate a scene from a synarius-core ``Model`` (e.g. loaded from bundled examples)."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QGraphicsScene

from synarius_core.dataflow_sim import elementary_has_fmu_path
from synarius_core.model import BasicOperator, Connector, DataViewer, ElementaryInstance, Model, Variable

from .dataflow_items import (
    ConnectorEdgeItem,
    DataViewerBlockItem,
    FmuBlockItem,
    OperatorBlockItem,
    UI_SCALE,
    VariableBlockItem,
)

if TYPE_CHECKING:
    pass

# Default scene bounds (pre-scale units × UI_SCALE). Node positions come from the loaded model (``x``/``y`` on instances).
SCENE_RECT = QRectF(0.0, 0.0, 900.0 * UI_SCALE, 520.0 * UI_SCALE)


def _agent_debug_log(*, run_id: str, hypothesis_id: str, message: str, data: dict[str, object]) -> None:
    # region agent log
    try:
        payload = {
            "sessionId": "743d05",
            "runId": run_id,
            "hypothesisId": hypothesis_id,
            "location": "dataflow_layout.py:open_syn_dialog_start_dir",
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        log_path = Path(__file__).resolve().parents[3] / "debug-743d05.log"
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # endregion


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
        candidates: list[tuple[str, Path]] = [("exe_dir", exe_dir)]
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(("meipass_resources", Path(meipass) / "synarius_studio" / "resources"))
        selected_source = "exe_dir_fallback"
        start_dir = exe_dir
        for source, candidate in candidates:
            try:
                if candidate.is_dir() and any(candidate.glob("*.syn")):
                    start_dir = candidate
                    selected_source = source
                    break
            except Exception:
                continue
    else:
        start_dir = default_sample_syn_path().parent
        selected_source = "dev_resources"
    try:
        syn_files = sorted(p.name for p in start_dir.glob("*.syn"))
    except Exception:
        syn_files = []
    _agent_debug_log(
        run_id="pre-fix",
        hypothesis_id="H_OPEN_DIR",
        message="open_syn_dialog_start_dir",
        data={
            "frozen": bool(getattr(sys, "frozen", False)),
            "sys_executable": str(getattr(sys, "executable", "")),
            "resolved_start_dir": str(start_dir),
            "selected_source": selected_source,
            "syn_files": syn_files,
        },
    )
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

    scene.setSceneRect(SCENE_RECT)
