"""Select existing data viewers and/or create a new one."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from synarius_core.model import Model, Variable


def _measure_ids_on_variable(variable: Variable) -> list[int]:
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


def _last_selected_id(model: Model) -> int:
    try:
        return int(model.root.get("last_selected_dataviewer_id"))
    except (KeyError, TypeError, ValueError):
        return -1


class SelectDataViewerDialog(QDialog):
    """
    One checkbox per existing :class:`~synarius_core.model.DataViewer` plus *New data viewer*.

    If at least one viewer exists, *New data viewer* is **off** by default and the **last used**
    viewer (``@main.last_selected_dataviewer_id``) is checked when the variable has no
    measurement binding yet.
    """

    def __init__(self, model: Model, variable: Variable, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = model
        self._variable = variable
        self.setWindowTitle("Data viewer")
        self.setModal(True)

        viewers = model.iter_dataviewers()
        vids = [int(d.get("dataviewer_id")) for d in viewers]
        sel = set(_measure_ids_on_variable(variable))
        sel_in_model = sorted(sel.intersection(vids))
        last = _last_selected_id(model)

        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"Assign measurement for variable “{variable.name}”:", self))

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        inner = QWidget(scroll)
        inner_layout = QVBoxLayout(inner)
        self._boxes: dict[int, QCheckBox] = {}
        for d in viewers:
            vid = int(d.get("dataviewer_id"))
            cb = QCheckBox(f"Data viewer {vid}", inner)
            inner_layout.addWidget(cb)
            self._boxes[vid] = cb

        self._new_cb = QCheckBox("New data viewer", inner)
        inner_layout.addWidget(self._new_cb)

        if not vids:
            self._new_cb.setChecked(True)
        else:
            self._new_cb.setChecked(False)
            if sel_in_model:
                for vid in sel_in_model:
                    if vid in self._boxes:
                        self._boxes[vid].setChecked(True)
            elif last >= 0 and last in self._boxes:
                self._boxes[last].setChecked(True)
            else:
                self._boxes[vids[-1]].setChecked(True)
        inner_layout.addStretch(1)
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            Qt.Orientation.Horizontal,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def selected_viewer_ids(self) -> list[int]:
        return [vid for vid, cb in sorted(self._boxes.items()) if cb.isChecked()]

    def want_new_viewer(self) -> bool:
        return self._new_cb.isChecked()
