"""Dialog: FMU-Datei wählen, Ports aus modelDescription auswählen, CCP-``new FmuInstance``-Zeile erzeugen."""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from synarius_core.fmu.bind import scalar_variables_to_fmu_ports
from synarius_core.fmu.inspection import FmuInspectError, inspect_fmu_path


def _default_instance_name_from_path(path: Path) -> str:
    base = path.stem.strip()
    candidate = re.sub(r"\W+", "_", base)
    if not candidate:
        candidate = "fmu_block_1"
    if candidate[0].isdigit():
        candidate = f"fmu_{candidate}"
    if not candidate.isidentifier():
        candidate = "fmu_block_1"
    return candidate


def build_fmu_import_command(
    *,
    fmu_path: Path,
    instance_name: str,
    model_x: float,
    model_y: float,
    model_size: float,
    selected_variable_rows: list[dict],
) -> str:
    """Return a single ``new FmuInstance`` line with ``fmu_ports`` / ``fmu_variables`` literals."""
    ports = scalar_variables_to_fmu_ports(selected_variable_rows)
    ports_literal = repr(ports)
    vars_literal = repr(selected_variable_rows)
    qpath = shlex.quote(str(fmu_path.resolve()))
    qname = shlex.quote(instance_name.strip())
    return (
        f"new FmuInstance {qname} {model_x:.12g} {model_y:.12g} {model_size:.12g} "
        f"fmu_path={qpath} fmu_ports={shlex.quote(ports_literal)} "
        f"fmu_variables={shlex.quote(vars_literal)}"
    )


class FmuImportDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, *, default_model_xy: tuple[float, float] = (120.0, 80.0)) -> None:
        super().__init__(parent)
        self.setWindowTitle("FMU importieren")
        self._path: Path | None = None
        self._inspection: dict | None = None
        self._rows: list[dict] = []
        self._default_xy = default_model_xy

        root = QVBoxLayout(self)
        form = QFormLayout()
        self._path_edit = QLineEdit(self)
        self._path_edit.setReadOnly(True)
        browse = QPushButton("Durchsuchen…", self)
        browse.clicked.connect(self._on_browse)
        ph = QHBoxLayout()
        ph.addWidget(self._path_edit, 1)
        ph.addWidget(browse)
        form.addRow("FMU-Datei:", ph)
        self._name_edit = QLineEdit(self)
        self._name_edit.setPlaceholderText("fmu_block_1")
        form.addRow("Instanzname:", self._name_edit)
        root.addLayout(form)

        hint = QLabel(
            "Nach dem Öffnen der FMU erscheinen skalare Variablen; für das Diagramm werden "
            "Ein-/Ausgänge (input, parameter, output) als Pins übernommen.",
            self,
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        self._table = QTableWidget(self)
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["Port", "Name", "VR", "Art", "Causalität"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        root.addWidget(self._table, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, parent=self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _on_browse(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "FMU wählen",
            str(Path.home()),
            "FMU archives (*.fmu);;All files (*.*)",
        )
        if not path_str:
            return
        p = Path(path_str)
        self._path_edit.setText(str(p))
        self._path = p
        if not self._name_edit.text().strip():
            auto_name = _default_instance_name_from_path(p)
            self._name_edit.setText(auto_name)
        try:
            data = inspect_fmu_path(p)
        except FmuInspectError as exc:
            self._inspection = None
            self._rows = []
            self._table.setRowCount(0)
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, "FMU", str(exc))
            return
        self._inspection = data
        raw = data.get("scalar_variables") or []
        self._rows = [dict(r) for r in raw if isinstance(r, dict)]
        self._fill_table()

    def _fill_table(self) -> None:
        eligible: list[tuple[int, dict]] = []
        for i, row in enumerate(self._rows):
            c = str(row.get("causality") or "").strip().lower()
            if c in ("input", "output", "parameter"):
                eligible.append((i, row))
        self._table.setRowCount(len(eligible))
        for table_row, (_orig_i, row) in enumerate(eligible):
            name = str(row.get("name", ""))
            vr = row.get("value_reference", "")
            dt = str(row.get("data_type", ""))
            caus = str(row.get("causality", ""))
            chk = QTableWidgetItem()
            chk.setFlags(chk.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            chk.setCheckState(Qt.CheckState.Checked)
            chk.setData(Qt.ItemDataRole.UserRole, _orig_i)
            self._table.setItem(table_row, 0, chk)
            self._table.setItem(table_row, 1, QTableWidgetItem(name))
            self._table.setItem(table_row, 2, QTableWidgetItem(str(vr)))
            self._table.setItem(table_row, 3, QTableWidgetItem(dt))
            self._table.setItem(table_row, 4, QTableWidgetItem(caus))

    def protocol_command(self) -> str:
        if self._path is None or not self._path.is_file():
            raise ValueError("Keine gültige FMU-Datei.")
        name = self._name_edit.text().strip()
        if not name and self._path is not None:
            name = _default_instance_name_from_path(self._path)
            self._name_edit.setText(name)
        if not name:
            raise ValueError("Instanzname fehlt.")
        if not name.isidentifier():
            raise ValueError("Instanzname muss ein gültiger Python-Identifier sein.")

        selected: list[dict] = []
        for r in range(self._table.rowCount()):
            it = self._table.item(r, 0)
            if it is None or it.checkState() != Qt.CheckState.Checked:
                continue
            idx = it.data(Qt.ItemDataRole.UserRole)
            if isinstance(idx, int) and 0 <= idx < len(self._rows):
                selected.append(dict(self._rows[idx]))
        if not selected:
            raise ValueError("Mindestens einen Port auswählen.")

        mx, my = self._default_xy
        return build_fmu_import_command(
            fmu_path=self._path,
            instance_name=name,
            model_x=mx,
            model_y=my,
            model_size=1.0,
            selected_variable_rows=selected,
        )
