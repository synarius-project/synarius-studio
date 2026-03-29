"""Dialog to configure variable stimulation; produces protocol ``set`` lines (console semantics)."""

from __future__ import annotations

import shlex
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from synarius_core.model import Variable


_STIM_LABELS = (
    ("none", "None (use dataflow / value)"),
    ("constant", "Constant"),
    ("ramp", "Ramp"),
    ("sine", "Sine"),
    ("step", "Step"),
)


def _safe_float(var: Variable, key: str, default: float = 0.0) -> float:
    try:
        return float(var.get(key))
    except (KeyError, TypeError, ValueError):
        return default


def _safe_kind(var: Variable) -> str:
    try:
        return str(var.get("stim_kind")).strip().lower()
    except (KeyError, TypeError, ValueError):
        return "none"


class StimulationDialog(QDialog):
    """Maps to ``stim_kind`` / ``stim_p0``…``stim_p3`` (see ``synarius_core.dataflow_sim.stimulation``)."""

    def __init__(self, variable: Variable, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._variable = variable
        self.setWindowTitle(f"Stimulation — {variable.name}")
        self.setModal(True)

        self._kind = QComboBox(self)
        for value, label in _STIM_LABELS:
            self._kind.addItem(label, userData=value)

        self._p0 = QDoubleSpinBox(self)
        self._p1 = QDoubleSpinBox(self)
        self._p2 = QDoubleSpinBox(self)
        self._p3 = QDoubleSpinBox(self)
        for sp in (self._p0, self._p1, self._p2, self._p3):
            sp.setDecimals(6)
            sp.setRange(-1e9, 1e9)
            sp.setSingleStep(0.1)

        self._param_labels: list[QLabel] = []
        form = QFormLayout()
        form.addRow("Type:", self._kind)
        for i, sp in enumerate((self._p0, self._p1, self._p2, self._p3)):
            lab = QLabel(self)
            self._param_labels.append(lab)
            form.addRow(lab, sp)

        self._kind.currentIndexChanged.connect(self._update_param_hints)
        self._load_from_variable()
        self._update_param_hints()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(buttons)

    def _load_from_variable(self) -> None:
        v = self._variable
        kind = _safe_kind(v)
        idx = next((i for i in range(self._kind.count()) if self._kind.itemData(i) == kind), 0)
        self._kind.setCurrentIndex(idx)
        self._p0.setValue(_safe_float(v, "stim_p0", 0.0))
        self._p1.setValue(_safe_float(v, "stim_p1", 1.0))
        self._p2.setValue(_safe_float(v, "stim_p2", 1.0))
        self._p3.setValue(_safe_float(v, "stim_p3", 0.0))

    def _update_param_hints(self) -> None:
        k = self._kind.currentData()
        hints = {
            "none": ("(unused)", "(unused)", "(unused)", "(unused)"),
            "constant": ("Value", "(unused)", "(unused)", "(unused)"),
            "ramp": ("Offset", "Slope (per s)", "(unused)", "(unused)"),
            "sine": ("Offset", "Amplitude", "Frequency (Hz)", "Phase (deg)"),
            "step": ("Value before t", "Switch time (s)", "Value after t", "(unused)"),
        }
        labels = hints.get(str(k), hints["none"])
        for lab, text in zip(self._param_labels, labels):
            lab.setText(text)

    def protocol_commands(self) -> list[str]:
        """``set`` lines to apply this configuration (quoted ``hash_name``)."""
        h = shlex.quote(self._variable.hash_name)
        kind = str(self._kind.currentData())
        p0, p1, p2, p3 = self._p0.value(), self._p1.value(), self._p2.value(), self._p3.value()
        return [
            f"set {h}.stim_kind {kind}",
            f"set {h}.stim_p0 {p0}",
            f"set {h}.stim_p1 {p1}",
            f"set {h}.stim_p2 {p2}",
            f"set {h}.stim_p3 {p3}",
        ]
