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

from synarius_core.dataflow_sim import stimulation as stim
from synarius_core.model import Variable


_STIM_LABELS = (
    ("none", "None (uses Variable.value; first field below)"),
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
        return str(var.get(stim.STIM_KIND_ATTR)).strip().lower()
    except (KeyError, TypeError, ValueError):
        return "none"


class StimulationDialog(QDialog):
    """Maps to ``stim_kind`` and per-kind attributes (see ``synarius_core.dataflow_sim.stimulation``)."""

    def __init__(self, variable: Variable, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._variable = variable
        stim.ensure_variable_stimulation_schema(variable)
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
        if kind in ("none", "off", ""):
            try:
                base_v = float(v.value)
            except (TypeError, ValueError):
                base_v = _safe_float(v, stim.STIM_CONSTANT_VALUE, 0.0)
            self._p0.setValue(base_v)
            self._p1.setValue(1.0)
            self._p2.setValue(1.0)
            self._p3.setValue(0.0)
        elif kind == "constant":
            self._p0.setValue(_safe_float(v, stim.STIM_CONSTANT_VALUE, 0.0))
            self._p1.setValue(1.0)
            self._p2.setValue(1.0)
            self._p3.setValue(0.0)
        elif kind == "ramp":
            self._p0.setValue(_safe_float(v, stim.STIM_RAMP_OFFSET, 0.0))
            self._p1.setValue(_safe_float(v, stim.STIM_RAMP_SLOPE, 1.0))
            self._p2.setValue(1.0)
            self._p3.setValue(0.0)
        elif kind == "sine":
            self._p0.setValue(_safe_float(v, stim.STIM_SINE_OFFSET, 0.0))
            self._p1.setValue(_safe_float(v, stim.STIM_SINE_AMPLITUDE, 1.0))
            self._p2.setValue(_safe_float(v, stim.STIM_SINE_FREQUENCY_HZ, 1.0))
            self._p3.setValue(_safe_float(v, stim.STIM_SINE_PHASE_DEG, 0.0))
        elif kind == "step":
            self._p0.setValue(_safe_float(v, stim.STIM_STEP_LOW, 0.0))
            self._p1.setValue(_safe_float(v, stim.STIM_STEP_SWITCH_TIME_S, 0.0))
            self._p2.setValue(_safe_float(v, stim.STIM_STEP_HIGH, 1.0))
            self._p3.setValue(0.0)
        else:
            self._p0.setValue(0.0)
            self._p1.setValue(1.0)
            self._p2.setValue(1.0)
            self._p3.setValue(0.0)

    def _update_param_hints(self) -> None:
        k = self._kind.currentData()
        hints = {
            "none": ("Value (written to Variable.value)", "(unused)", "(unused)", "(unused)"),
            "constant": ("stim_constant_value", "(unused)", "(unused)", "(unused)"),
            "ramp": ("stim_ramp_offset", "stim_ramp_slope", "(unused)", "(unused)"),
            "sine": ("stim_sine_offset", "stim_sine_amplitude", "stim_sine_frequency_hz", "stim_sine_phase_deg"),
            "step": ("stim_step_low", "stim_step_switch_time_s", "stim_step_high", "(unused)"),
        }
        labels = hints.get(str(k), hints["none"])
        for lab, text in zip(self._param_labels, labels):
            lab.setText(text)

    def protocol_commands(self) -> list[str]:
        """``set`` lines to apply this configuration (quoted ``hash_name``)."""
        h = shlex.quote(self._variable.hash_name)
        kind = str(self._kind.currentData())
        p0, p1, p2, p3 = self._p0.value(), self._p1.value(), self._p2.value(), self._p3.value()
        lines = [f"set {h}.{stim.STIM_KIND_ATTR} {kind}"]
        if kind in ("none", "off"):
            lines.append(f"set {h}.value {p0}")
            return lines
        if kind == "constant":
            lines.append(f"set {h}.{stim.STIM_CONSTANT_VALUE} {p0}")
            return lines
        if kind == "ramp":
            lines.append(f"set {h}.{stim.STIM_RAMP_OFFSET} {p0}")
            lines.append(f"set {h}.{stim.STIM_RAMP_SLOPE} {p1}")
            return lines
        if kind == "sine":
            lines.append(f"set {h}.{stim.STIM_SINE_OFFSET} {p0}")
            lines.append(f"set {h}.{stim.STIM_SINE_AMPLITUDE} {p1}")
            lines.append(f"set {h}.{stim.STIM_SINE_FREQUENCY_HZ} {p2}")
            lines.append(f"set {h}.{stim.STIM_SINE_PHASE_DEG} {p3}")
            return lines
        if kind == "step":
            lines.append(f"set {h}.{stim.STIM_STEP_LOW} {p0}")
            lines.append(f"set {h}.{stim.STIM_STEP_SWITCH_TIME_S} {p1}")
            lines.append(f"set {h}.{stim.STIM_STEP_HIGH} {p2}")
            return lines
        return lines
