from __future__ import annotations

import logging
import re
import shlex
import time
from dataclasses import dataclass, field
from typing import Callable, cast
from uuid import UUID
import numpy as np
from PySide6.QtCore import (
    QByteArray,
    QMimeData,
    QObject,
    QSize,
    Qt,
    QThread,
    QTimer,
    Signal as QtSignal,
    Slot,
    QMetaObject,
    Q_ARG,
)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QDrag,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QIcon,
    QKeySequence,
    QPainter,
    QPixmap,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QGraphicsItem,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QSizePolicy,
    QSplitter,
    QStyle,
    QTabBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
    QHeaderView,
)
from pathlib import Path

from .app_logging import attach_split_studio_gui_log_handlers, main_log_path
from .log_emitter import LogEmitter
from ._version import __version__
from synarius_core.controller import CommandError, SynariusController
from synarius_core.dataflow_sim import (
    DataflowCompilePass,
    SimpleRunEngine,
    SimulationContext,
    elementary_has_fmu_path,
    generate_fmfl_document,
    generate_unrolled_python_step_document,
)
from synarius_core.io import load_timeseries_file
from synarius_core.library import LibraryCatalog
from synarius_core.model import (
    Connector,
    DataViewer,
    ElementaryInstance,
    ModelElementType,
    Signal,
    SignalContainer,
    Variable,
)
from synarius_core.model.syn_script_export import export_root_diagram_syn_text
from synarius_core.plugins.registry import PluginRegistry
from synarius_core.recording import export_recording_buffers
from synariustools.tools.terminal_console import TerminalConsoleWidget

from .resources_panel import RESOURCES_PANEL_MIN_WIDTH, build_resources_panel
from .theme import (
    CONSOLE_CHROME_BACKGROUND,
    CONSOLE_TAB_TEXT,
    LIBRARY_HEADER_BUTTON_HOVER,
    SELECTION_HIGHLIGHT,
    SELECTION_HIGHLIGHT_TEXT,
    STUDIO_TOOLBAR_FOREGROUND,
    qss_widget_id_background,
    studio_tab_bar_stylesheet,
    studio_toolbar_stylesheet,
    with_tooltip_qss,
)
from .studio_paths import studio_library_extra_roots, studio_lib_dir, studio_plugins_dir
from .variables_tab_panel import build_variables_tab_panel
from .parameters_tab_panel import build_parameters_tab_panel, open_parameter_viewer_for_record
from .diagram import DataflowGraphicsView, populate_scene_from_model
from .diagram.dataflow_items import (
    UI_SCALE,
    ConnectorEdgeItem,
    DataViewerBlockItem,
    FmuBlockItem,
    OperatorBlockItem,
    VariableBlockItem,
)
from .diagram.diagram_scene import SynariusDiagramScene
from .diagram.dataflow_canvas import (
    CANVAS_BACKGROUND_COLOR,
    CANVAS_SIMULATION_BACKGROUND_COLOR,
    SCROLLBAR_STYLE_QSS,
)
from .diagram.dataflow_layout import SCENE_RECT, open_syn_dialog_start_dir
from .diagram.placement_interactive import VARIABLE_NAME_DRAG_MIME
from .diagram.placement_interactive import SIGNAL_NAME_DRAG_MIME
from .code_view import ReadOnlyCodeView
from .dataviewer_select_dialog import SelectDataViewerDialog
from .experiment_codegen import compile_dataflow_for_view
from .fmu_import_dialog import FmuImportDialog
from .resource_paths import prepend_dev_synarius_apps_src
from .simulation_step_count_field import SimulationStepCountField
from .stimulation_dialog import StimulationDialog
from .svg_icons import icon_from_inverted_standard_icon, icon_from_tinted_svg_file, qicon_panel_toggle_for_toolbar

DEFAULT_OUTPUT_COLOR = "#ADD8E6"  # light blue
DEFAULT_PROMPT_COLOR = "#90EE90"  # light green
DEFAULT_INPUT_COLOR = "#FFFFFF"  # terminal-like user input
ERROR_COLOR = "#FF6666"

_CMD_LOG = logging.getLogger("synarius_studio.console")
_EXP_LOG = logging.getLogger("synarius_studio.experiment")
_MW_LOG = logging.getLogger("synarius_studio.main_window")

def _studio_library_catalog() -> LibraryCatalog:
    """Defer heavy library scan when supported; tolerate older synarius-core without ``defer_initial_load``."""
    try:
        return LibraryCatalog(extra_roots=(), defer_initial_load=True)
    except TypeError:
        return LibraryCatalog(extra_roots=())


def _studio_plugin_registry() -> PluginRegistry:
    """Optional ``defer_initial_load`` when supported (older synarius-core omits it)."""
    try:
        return PluginRegistry(extra_plugin_containers=(), defer_initial_load=True)
    except TypeError:
        return PluginRegistry(extra_plugin_containers=())


# Internal drag-and-drop for Measurements list row reordering.
RECORDINGS_ROW_DRAG_MIME = "application/x-synarius-studio-recordings-row"


@dataclass
class _History:
    entries: list[str] = field(default_factory=list)
    index: int = 0

    def push(self, line: str) -> None:
        if line.strip() == "":
            return
        self.entries.append(line)
        self.index = len(self.entries)

    def prev(self) -> str | None:
        if not self.entries:
            return None
        self.index = max(0, self.index - 1)
        return self.entries[self.index]

    def next(self) -> str:
        if not self.entries:
            return ""
        self.index = min(len(self.entries), self.index + 1)
        if self.index >= len(self.entries):
            return ""
        return self.entries[self.index]


_TerminalConsole = TerminalConsoleWidget


class _SignalsMappingTable(QTableWidget):
    """Signals table supporting variable-name drop onto a signal row."""

    def __init__(self, on_map_drop: Callable[[str, str], None], parent: QWidget | None = None) -> None:
        super().__init__(0, 3, parent)
        self._on_map_drop = on_map_drop
        self.setAcceptDrops(True)
        self.setDragDropOverwriteMode(False)

    @staticmethod
    def _mime_variable_name(md: QMimeData) -> str | None:
        if md.hasFormat(VARIABLE_NAME_DRAG_MIME):
            raw = bytes(md.data(VARIABLE_NAME_DRAG_MIME).data()).decode("utf-8").strip()
            return raw or None
        if md.hasText():
            txt = md.text().strip()
            return txt or None
        return None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._mime_variable_name(event.mimeData()) is not None:
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._mime_variable_name(event.mimeData()) is not None:
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        variable_name = self._mime_variable_name(event.mimeData())
        if variable_name is None:
            event.ignore()
            return
        row = self.rowAt(int(event.position().y()))
        if row < 0:
            event.ignore()
            return
        signal_item = self.item(row, 0)
        if signal_item is None:
            event.ignore()
            return
        signal_name = signal_item.text().strip()
        if not signal_name:
            event.ignore()
            return
        self._on_map_drop(signal_name, variable_name)
        event.acceptProposedAction()

    def startDrag(self, supportedActions) -> None:  # noqa: ANN001
        row = self.currentRow()
        if row < 0:
            return
        sig_item = self.item(row, 0)
        if sig_item is None:
            return
        signal_name = sig_item.text().strip()
        if not signal_name:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(SIGNAL_NAME_DRAG_MIME, signal_name.encode("utf-8"))
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction, Qt.DropAction.CopyAction)


class _RecordingsTable(QTableWidget):
    """Measurements list: reorder rows by drag-and-drop within the table."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, 2, parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QTableWidget.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragDropOverwriteMode(False)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(RECORDINGS_ROW_DRAG_MIME):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasFormat(RECORDINGS_ROW_DRAG_MIME):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    @staticmethod
    def _mime_source_row(md: QMimeData) -> int | None:
        if not md.hasFormat(RECORDINGS_ROW_DRAG_MIME):
            return None
        qba = md.data(RECORDINGS_ROW_DRAG_MIME)
        try:
            payload = cast(bytes, qba.data()).decode("ascii").strip()
            return int(payload)
        except (TypeError, ValueError):
            return None

    def dropEvent(self, event: QDropEvent) -> None:
        src_row = self._mime_source_row(event.mimeData())
        if src_row is None or event.source() is not self:
            super().dropEvent(event)
            return
        n = self.rowCount()
        if src_row < 0 or src_row >= n:
            event.ignore()
            return
        y = int(event.position().y())
        dest_row = self.rowAt(y)
        if dest_row < 0:
            dest_row = n
        if dest_row == src_row:
            event.acceptProposedAction()
            return
        items = [self.takeItem(src_row, c) for c in range(self.columnCount())]
        self.removeRow(src_row)
        if dest_row > src_row:
            dest_row -= 1
        dest_row = max(0, min(dest_row, self.rowCount()))
        self.insertRow(dest_row)
        for c, it in enumerate(items):
            self.setItem(dest_row, c, it)
        self.selectRow(dest_row)
        event.acceptProposedAction()

    def startDrag(self, supportedActions) -> None:  # noqa: ANN001
        rows = sorted({idx.row() for idx in self.selectedIndexes()})
        if not rows:
            return
        row = rows[0]
        if row < 0 or self.item(row, 0) is None:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(RECORDINGS_ROW_DRAG_MIME, QByteArray(str(row).encode("ascii")))
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction, Qt.DropAction.MoveAction)


class _RunLoopWorker(QObject):
    """Run SimpleRunEngine in a dedicated thread and publish live values."""

    # Use object payload for robust queued cross-thread delivery.
    tick = QtSignal(float, object)  # simulation time_s (model clock), payload dict
    started_ok = QtSignal()
    start_failed = QtSignal(str)
    stopped = QtSignal()

    #: Wall-clock seconds budget per timer callback when not in realtime pacing (best-effort max speed).
    _MAX_RATE_WALL_BUDGET_S = 0.05
    #: Safety cap on steps per timer callback in max-rate mode.
    _MAX_RATE_STEP_CAP = 100_000

    def __init__(
        self,
        model,
        *,
        dt_s: float = 0.02,
        tick_interval_ms: int | None = None,
        realtime_pacing: bool = True,
        plugin_registry: PluginRegistry | None = None,
        model_directory: Path | str | None = None,
        apply_fmu_params_on_init: bool = True,
    ) -> None:
        super().__init__()
        self._model = model
        self._dt_s = float(dt_s)
        self._explicit_tick_interval_ms = tick_interval_ms
        self._realtime_pacing = bool(realtime_pacing)
        self._plugin_registry = plugin_registry
        self._model_directory = model_directory
        self._apply_fmu_params_on_init = bool(apply_fmu_params_on_init)
        self._engine: SimpleRunEngine | None = None
        self._timer: QTimer | None = None
        self._stop_requested = False
        self._paused = False
        self._diag_emit_idx = 0

    def _effective_tick_interval_ms(self) -> int:
        """QTimer interval: 0 = fire as fast as the event loop allows (max-rate mode)."""
        if not self._realtime_pacing:
            return 0
        if self._explicit_tick_interval_ms is not None:
            return max(1, int(self._explicit_tick_interval_ms))
        return max(1, int(round(self._dt_s * 1000.0)))

    def _apply_pacing_option(self) -> None:
        if self._engine is None:
            return
        self._engine.context.options["simulation_pacing"] = "realtime" if self._realtime_pacing else "max_rate"

    @Slot(bool)
    def set_realtime_pacing(self, enabled: bool) -> None:
        """Toggle wall-clock-aligned steps vs. best-effort maximum simulation throughput."""
        self._realtime_pacing = bool(enabled)
        self._apply_pacing_option()
        if self._timer is not None:
            self._timer.setInterval(self._effective_tick_interval_ms())

    @Slot()
    def start(self) -> None:
        try:
            self._engine = SimpleRunEngine(
                self._model,
                dt_s=self._dt_s,
                plugin_registry=self._plugin_registry,
                model_directory=self._model_directory,
                param_runtime=self._model.parameter_runtime(),
            )
            self._engine.context.options["fmu_apply_parameters_on_init"] = bool(
                self._apply_fmu_params_on_init
            )
            self._engine.init()
            self._diag_emit_idx = len(list(getattr(self._engine.context, "diagnostics", []) or []))
            if self._engine.context.artifacts.get("dataflow") is None:
                self.start_failed.emit("Cannot simulate: invalid dataflow (e.g. cycle).")  # type: ignore[attr-defined]
                self.stopped.emit()  # type: ignore[attr-defined]
                return
            self._apply_pacing_option()
            self._stop_requested = False
            self._paused = False
            self._timer = QTimer(self)
            self._timer.setInterval(self._effective_tick_interval_ms())
            self._timer.timeout.connect(self._on_tick)
            self._timer.start()
            self.started_ok.emit()  # type: ignore[attr-defined]
        except Exception as exc:
            self.start_failed.emit(str(exc))  # type: ignore[attr-defined]
            self.stopped.emit()  # type: ignore[attr-defined]

    @Slot()
    def request_stop(self) -> None:
        self._stop_requested = True

    @Slot()
    def request_pause(self) -> None:
        self._paused = True

    @Slot()
    def request_resume(self) -> None:
        self._paused = False

    def _flush_new_diagnostics(self) -> None:
        if self._engine is None:
            return
        diags = list(getattr(self._engine.context, "diagnostics", []) or [])
        if self._diag_emit_idx < len(diags):
            for line in diags[self._diag_emit_idx :]:
                _EXP_LOG.error("%s", str(line))
            self._diag_emit_idx = len(diags)

    def _emit_tick_payload(self) -> None:
        if self._engine is None:
            return
        values: dict[str, float] = {}
        for node in self._model.iter_objects():
            if not isinstance(node, Variable):
                continue
            val = node.value
            if isinstance(val, (int, float, np.integer, np.floating)) and not isinstance(val, bool):
                values[str(node.name)] = float(val)
        fmu_ws: dict[str, float] = {}
        compiled = self._engine.context.artifacts.get("dataflow")
        ws = self._engine.context.scalar_workspace
        if compiled is not None and ws is not None:
            node_by_id = getattr(compiled, "node_by_id", None)
            if isinstance(node_by_id, dict):
                for uid, node in node_by_id.items():
                    if not isinstance(node, ElementaryInstance) or not elementary_has_fmu_path(node):
                        continue
                    raw = ws.get(uid, 0.0)
                    try:
                        fv = float(raw)
                    except (TypeError, ValueError):
                        fv = float("nan")
                    fmu_ws[str(node.name)] = fv
        payload = {"variables": values, "fmu_workspace": fmu_ws}
        self.tick.emit(float(self._engine.context.time_s), payload)  # type: ignore[attr-defined]

    @Slot()
    def _on_tick(self) -> None:
        if self._stop_requested:
            if self._timer is not None:
                self._timer.stop()
            self.stopped.emit()  # type: ignore[attr-defined]
            return
        if self._paused:
            return
        if self._engine is None:
            self.stopped.emit()  # type: ignore[attr-defined]
            return
        try:
            if self._realtime_pacing:
                self._engine.step()
                self._flush_new_diagnostics()
                self._emit_tick_payload()
                return

            t0 = time.perf_counter()
            n = 0
            while n < self._MAX_RATE_STEP_CAP and (time.perf_counter() - t0) < self._MAX_RATE_WALL_BUDGET_S:
                if self._stop_requested or self._paused:
                    break
                self._engine.step()
                n += 1
            self._flush_new_diagnostics()
            self._emit_tick_payload()
        except Exception:
            self.stopped.emit()  # type: ignore[attr-defined]


class MainWindow(QMainWindow):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Synarius Studio {__version__}")
        # Shared Synarius icon for Studio main window (same as Dataviewer), from local icons folder.
        studio_icon = QIcon(str(Path(__file__).resolve().parent / "icons" / "synarius64.png"))
        self.setWindowIcon(studio_icon)
        self.resize(1200, 750)
        # Avoid studio_library_extra_roots() here: iterdir() on %LOCALAPPDATA%/Synarius/Lib can block
        # (network/cloud path) while the splash is still the only visible UI.
        _MW_LOG.info(
            "MainWindow __init__: build_marker=ctlr_catalog_tryexcept title_version=%s",
            __version__,
        )
        self._controller = SynariusController(
            library_catalog=_studio_library_catalog(),
            plugin_registry=_studio_plugin_registry(),
        )
        self._history = _History()
        self._default_output_color = DEFAULT_OUTPUT_COLOR
        self._run_engine: SimpleRunEngine | None = None
        self._simulation_running = False
        self._simulation_paused = False
        self._run_thread: QThread | None = None
        self._run_worker: _RunLoopWorker | None = None
        self._sim_mode_suppress_action = False
        self._sim_play_suppress_action = False
        self._last_applied_simulation_mode: bool | None = None
        # Laufende dynamische DataViewer-Fenster pro Viewer-ID.
        self._live_dataviewers: dict[int, QWidget] = {}
        # Beim Verlassen des Experimentier-Modus geschlossene Viewer-IDs (werden beim erneuten Aktivieren wieder geöffnet).
        self._live_dataviewers_reopen_after_sim: list[int] = []
        self._live_series_buffers: dict[str, tuple[list[float], list[float]]] = {}
        self._live_series_t0 = time.perf_counter()
        self._live_viewer_autorange_tick = 0
        # Recording UI state (experiment mode, canvas toolbar).
        self._record_last_dir: Path | None = None
        self._record_last_basename: str = "measurement"
        self._record_last_format: str = "mdf"
        # Recording: per-variable time-series buffers for experiment mode.
        self._record_series_buffers: dict[str, tuple[list[float], list[float]]] = {}
        self._record_series_t0: float = 0.0
        self._recordings_table: QTableWidget | None = None
        self._signals_table: QTableWidget | None = None
        self._sim_step_count: int = 10
        self._sim_steps_remaining: int = 0
        self._sim_hold_reinit_pending: bool = False
        self._sim_restart_after_hold_pending: bool = False
        self._sim_time_offset_s: float = 0.0
        self._sim_time_last_s: float = 0.0
        self._sim_step_count_fields: list[SimulationStepCountField] = []
        self._sim_step_count_actions: list[QWidgetAction] = []
        self._active_run_dt_s: float = 0.02
        #: Nach frischem Simulationsstart (nicht Hold-Resume): FMFL/Python-Tabs ggf. wieder anlegen/aktualisieren.
        self._refresh_experiment_tabs_after_worker_start: bool = False
        self._fmfl_code_view: ReadOnlyCodeView | None = None
        self._python_code_view: ReadOnlyCodeView | None = None
        self._experiment_codegen_debounce = QTimer(self)
        self._experiment_codegen_debounce.setSingleShot(True)
        self._experiment_codegen_debounce.setInterval(200)
        self._experiment_codegen_debounce.timeout.connect(self._refresh_experiment_codegen_views)  # type: ignore[arg-type]

        central = QWidget(self)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(8)

        self._diagram_scene = SynariusDiagramScene(self)
        self._diagram_scene.setSceneRect(SCENE_RECT)
        self._diagram_scene.variable_sim_binding_toggle.connect(self._on_variable_sim_binding_toggle)
        self._diagram_scene.open_dataviewer_requested.connect(
            self._on_dataviewer_canvas_open_widget_command
        )
        self._diagram_scene.open_kenngroesse_requested.connect(
            self._on_kenngroesse_canvas_open_editor
        )
        # Strong refs to scene wrappers from ``items()``; PySide6 may drop items when these go away.
        self._diagram_item_refs: list[QGraphicsItem] = []

        self._create_actions()
        self._create_menu()
        self._build_main_layout(root_layout)
        self._variables_panel.refresh()
        self._parameters_panel.refresh()
        self._dataflow_view.attach_connector_route_tool(self._controller)
        self._dataflow_view.attach_placement_tool(self._controller)
        self._dataflow_view.connector_route_command.connect(self._on_connector_route_command)
        self._dataflow_view.placement_command.connect(self._on_placement_canvas_command)
        self._dataflow_view.signal_mapping_drop.connect(self._on_canvas_signal_mapping_drop)
        self._dataflow_view.placement_cancelled.connect(self._uncheck_diagram_palette_actions)
        self._dataflow_view.scene_left_release.connect(self._sync_scene_selection_to_controller)
        self._dataflow_view.block_move_finished.connect(self._sync_diagram_move_to_controller)
        self._dataflow_view.delete_selection_requested.connect(self._delete_selected_via_controller)
        self._create_toolbar()

        self.setStatusBar(self.statusBar())
        self.statusBar().showMessage("Ready.")
        self.setCentralWidget(central)
        self._sync_simulation_mode_from_model()

        self._general_log_emitter = LogEmitter(self)
        self._build_log_emitter = LogEmitter(self)
        self._experiment_log_emitter = LogEmitter(self)
        self._general_log_emitter.message.connect(self._append_general_log_view)
        self._build_log_emitter.message.connect(self._append_build_log_view)
        self._experiment_log_emitter.message.connect(self._append_experiment_log_view)
        attach_split_studio_gui_log_handlers(
            self._general_log_emitter,
            self._build_log_emitter,
            self._experiment_log_emitter,
        )
        QTimer.singleShot(0, self._deferred_startup_library_and_plugins)

    @Slot()
    def _deferred_startup_library_and_plugins(self) -> None:
        try:
            cat = self._controller.library_catalog
            cat.set_extra_roots(studio_library_extra_roots())
            cat.reload()
            self._controller.alias_roots["@libraries"] = cat.root
            self._refresh_resources_panel()
        except Exception:
            _EXP_LOG.exception("deferred library catalog load failed")
        try:
            reg = self._controller.plugin_registry
            try:
                pd = studio_plugins_dir()
                reg.set_extra_plugin_containers([pd] if pd.is_dir() else [])
            except OSError:
                reg.set_extra_plugin_containers([])
            reg.reload()
        except Exception:
            _EXP_LOG.exception("deferred plugin registry load failed")

    def _create_actions(self) -> None:
        self._icons_dir = Path(__file__).resolve().parent / "icons"

        self.open_action = QAction("Open", self)
        self.save_action = QAction("Save", self)
        self.undo_action = QAction("Undo", self)
        self.redo_action = QAction("Redo", self)
        self.open_action.setToolTip("Open…")
        self.save_action.setToolTip("Save…")
        self.undo_action.setToolTip("Undo last change")
        self.redo_action.setToolTip("Redo")
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self.undo_action.triggered.connect(lambda: self._execute_controller_line_for_ui("undo 1"))
        self.redo_action.triggered.connect(lambda: self._execute_controller_line_for_ui("redo 1"))
        self.exit_action = QAction("Exit Synarius", self)
        self.toggle_right_panel_action = QAction("", self)
        self.toggle_bottom_panel_action = QAction("", self)

        self.toggle_right_panel_action.setCheckable(True)
        self.toggle_bottom_panel_action.setCheckable(True)
        self.toggle_right_panel_action.setChecked(True)
        self.toggle_bottom_panel_action.setChecked(True)
        _panel_toggle_fg = QColor(STUDIO_TOOLBAR_FOREGROUND)
        self.toggle_right_panel_action.setIcon(
            qicon_panel_toggle_for_toolbar(self._icons_dir / "toggle_right_panel.svg", checked_foreground=_panel_toggle_fg)
        )
        self.toggle_bottom_panel_action.setIcon(
            qicon_panel_toggle_for_toolbar(self._icons_dir / "toggle_bottom_panel.svg", checked_foreground=_panel_toggle_fg)
        )
        self.toggle_right_panel_action.setToolTip("Toggle right panel")
        self.toggle_bottom_panel_action.setToolTip("Toggle bottom panel")

        self.open_action.triggered.connect(self._open_project)
        self.save_action.triggered.connect(self._save_project)
        self.exit_action.triggered.connect(self.close)
        self.toggle_right_panel_action.toggled.connect(self._toggle_right_panel)
        self.toggle_bottom_panel_action.toggled.connect(self._toggle_bottom_panel)

        self.sim_mode_action = QAction("Simulation", self)
        self.sim_mode_action.setCheckable(True)
        self.sim_mode_action.setToolTip("Runs: set @main.simulation_mode true|false; stays checked while active.")
        self.sim_mode_action.toggled.connect(self._on_sim_mode_action_toggled)

        _st = QApplication.instance().style() if QApplication.instance() else self.style()
        self.play_action = QAction("Play", self)
        self.play_action.setIcon(
            icon_from_inverted_standard_icon(_st.standardIcon(QStyle.StandardPixmap.SP_MediaPlay), logical_side=24)
        )
        self.play_action.setToolTip("Start or resume simulation")
        self.play_action.setCheckable(True)
        self.play_action.setEnabled(False)
        self.play_action.toggled.connect(self._on_play_action_toggled)

        self.pause_action = QAction("Pause", self)
        self.pause_action.setToolTip("Pause simulation (keeps current signals)")
        self.pause_action.setCheckable(True)
        self.pause_action.setEnabled(False)
        self.pause_action.triggered.connect(self._on_simulation_pause)

        self.stop_action = QAction("Stop", self)
        self.stop_action.setIcon(
            icon_from_inverted_standard_icon(_st.standardIcon(QStyle.StandardPixmap.SP_MediaStop), logical_side=24)
        )
        self.stop_action.setToolTip("Stop simulation")
        self.stop_action.setEnabled(False)
        self.stop_action.triggered.connect(self._on_simulation_stop)
        self.step_action = QAction("Step", self)
        self.step_action.setToolTip("Run N simulation steps and then pause")
        self.step_action.setEnabled(False)
        self.step_action.triggered.connect(self._on_simulation_step_action_triggered)
        self.stop_hold_action = QAction("Stop/Hold", self)
        self.stop_hold_action.setToolTip(
            "Pause simulation and force model re-initialization before next resume"
        )
        self.stop_hold_action.setCheckable(True)
        self.stop_hold_action.setEnabled(False)
        self.stop_hold_action.triggered.connect(self._on_simulation_stop_hold)

        self._sync_breeze_file_action_icons()

    def _sync_breeze_file_action_icons(self) -> None:
        """White Breeze symbolic icons on the black studio toolbar."""
        fg = QColor(STUDIO_TOOLBAR_FOREGROUND)
        self.open_action.setIcon(
            icon_from_tinted_svg_file(self._icons_dir / "document-open-folder-symbolic.svg", fg)
        )
        self.save_action.setIcon(
            icon_from_tinted_svg_file(self._icons_dir / "document-save-symbolic.svg", fg)
        )
        self.undo_action.setIcon(icon_from_tinted_svg_file(self._icons_dir / "edit-undo-symbolic.svg", fg))
        self.redo_action.setIcon(icon_from_tinted_svg_file(self._icons_dir / "edit-redo-symbolic.svg", fg))
        sim_icon_path = self._icons_dir / "office-chart-line-stacked.svg"
        if sim_icon_path.exists():
            self.sim_mode_action.setIcon(icon_from_tinted_svg_file(sim_icon_path, fg))
        pause_icon_path = self._icons_dir / "kt-pause.svg"
        if pause_icon_path.exists():
            self.pause_action.setIcon(icon_from_tinted_svg_file(pause_icon_path, fg))
        self.stop_hold_action.setIcon(self._outlined_stop_square_icon(fg, logical_side=24))
        steps_icon_path = self._icons_dir / "steps.svg"
        if steps_icon_path.exists():
            self.step_action.setIcon(icon_from_tinted_svg_file(steps_icon_path, fg))
        if hasattr(self, "_canvas_pause_action"):
            self._canvas_pause_action.setIcon(self.pause_action.icon())
        if hasattr(self, "_canvas_stop_hold_action"):
            self._canvas_stop_hold_action.setIcon(self.stop_hold_action.icon())
        if hasattr(self, "_canvas_step_action"):
            self._canvas_step_action.setIcon(self.step_action.icon())

    @staticmethod
    def _outlined_stop_square_icon(color: QColor, logical_side: int = 24) -> QIcon:
        side = max(12, int(logical_side))
        px = QPixmap(side, side)
        px.fill(Qt.GlobalColor.transparent)
        painter = QPainter(px)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        pen = painter.pen()
        pen.setColor(color)
        pen.setWidth(max(1, side // 8))
        painter.setPen(pen)
        inset = max(2, side // 4)
        painter.drawRect(inset, inset, side - (2 * inset), side - (2 * inset))
        painter.end()
        return QIcon(px)

    _DIAGRAM_PALETTE_ICON_FILES: dict[str, str] = {
        "var": "var.svg",
        "+": "plus.svg",
        "-": "minus.svg",
        "*": "mult.svg",
        "/": "div.svg",
    }

    def _sync_diagram_palette_action_icons(self) -> None:
        grp = getattr(self, "_diagram_palette_group", None)
        if grp is None:
            return
        fg = QColor(STUDIO_TOOLBAR_FOREGROUND)
        base = Path(__file__).resolve().parent / "icons" / "diagram_palette"
        for act in grp.actions():
            mode = act.property("placement_mode")
            if not mode:
                continue
            fn = self._DIAGRAM_PALETTE_ICON_FILES.get(str(mode))
            if fn is not None:
                px = int(getattr(self, "_diagram_palette_icon_px", 20))
                act.setIcon(icon_from_tinted_svg_file(base / fn, fg, logical_side=px))

    def _sync_all_tinted_toolbar_icons(self) -> None:
        self._sync_breeze_file_action_icons()
        self._sync_diagram_palette_action_icons()

    def _apply_unified_toolbar_chrome(self) -> None:
        qss = studio_toolbar_stylesheet()
        for tb in (getattr(self, "_main_toolbar", None), getattr(self, "_diagram_palette_toolbar", None)):
            if tb is None:
                continue
            tb.setStyleSheet(qss)
            for btn in tb.findChildren(QToolButton):
                btn.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def _create_menu(self) -> None:
        # Classic menu bar is intentionally hidden; File/Edit are exposed via toolbar menu buttons.
        self.menuBar().setVisible(False)

        file_menu = QMenu("File", self)
        menu_open = QAction("Open…", self)
        menu_open.triggered.connect(self._open_project)
        file_menu.addAction(menu_open)
        menu_save = QAction("Save…", self)
        menu_save.triggered.connect(self._save_project)
        file_menu.addAction(menu_save)
        menu_install = QAction("Install extension (ZIP)…", self)
        menu_install.triggered.connect(self._install_extension_zip)
        file_menu.addAction(menu_install)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

        edit_menu = QMenu("Edit", self)
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)
        self._file_menu = file_menu
        self._edit_menu = edit_menu

    def _create_toolbar(self) -> None:
        toolbar = QToolBar("Main Toolbar", self)
        self._main_toolbar = toolbar
        toolbar.setMovable(False)
        # First entries: File/Edit dropdowns (replacing classic menu bar).
        file_btn = QToolButton(self)
        file_btn.setText("File")
        file_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        file_btn.setMenu(self._file_menu)
        toolbar.addWidget(file_btn)

        edit_btn = QToolButton(self)
        edit_btn.setText("Edit")
        edit_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        edit_btn.setMenu(self._edit_menu)
        toolbar.addWidget(edit_btn)

        diagram_btn = QToolButton(self)
        diagram_btn.setText("Diagram")
        diagram_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        diagram_menu = QMenu(self)
        act_fmu_import = QAction("FMU importieren…", self)
        act_fmu_import.triggered.connect(self._on_import_fmu)
        diagram_menu.addAction(act_fmu_import)
        diagram_btn.setMenu(diagram_menu)
        toolbar.addWidget(diagram_btn)

        toolbar.addSeparator()
        toolbar.addAction(self.open_action)
        toolbar.addAction(self.save_action)
        toolbar.addSeparator()
        toolbar.addAction(self.undo_action)
        toolbar.addAction(self.redo_action)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel("Zoom:", self))
        self._zoom_combo = QComboBox(self)
        self._zoom_combo.setEditable(True)
        self._zoom_combo.setMinimumWidth(88)
        for z in ("60%", "80%", "100%", "120%", "140%"):
            self._zoom_combo.addItem(z)
        self._zoom_combo.setCurrentText("100%")
        zoom_le = self._zoom_combo.lineEdit()
        if zoom_le is not None:
            zoom_le.setPlaceholderText("100%")
            zoom_le.returnPressed.connect(self._on_zoom_combo_return)
        toolbar.addWidget(self._zoom_combo)
        self._zoom_combo.activated.connect(self._on_zoom_combo_activated)
        self._dataflow_view.zoom_percent_changed.connect(self._sync_zoom_combo_from_view)

        spacer = QWidget(self)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        toolbar.addAction(self.toggle_right_panel_action)
        toolbar.addAction(self.toggle_bottom_panel_action)

        self.addToolBar(toolbar)
        self._apply_unified_toolbar_chrome()
        self._sync_diagram_palette_action_icons()

    @staticmethod
    def _parse_zoom_percent_text(text: str) -> float | None:
        t = text.strip().upper().replace("%", "").strip()
        try:
            v = float(t.replace(",", "."))
        except ValueError:
            return None
        if 5.0 <= v <= 500.0:
            return v
        return None

    def _on_zoom_combo_activated(self, index: int) -> None:
        if index < 0:
            return
        pct = self._parse_zoom_percent_text(self._zoom_combo.itemText(index))
        if pct is not None:
            self._dataflow_view.set_zoom_percent(pct)

    def _on_zoom_combo_return(self) -> None:
        pct = self._parse_zoom_percent_text(self._zoom_combo.currentText())
        if pct is not None:
            self._dataflow_view.set_zoom_percent(pct)
        else:
            self._sync_zoom_combo_from_view(self._dataflow_view.zoom_percent())

    def _sync_zoom_combo_from_view(self, percent: float) -> None:
        self._zoom_combo.blockSignals(True)
        self._zoom_combo.setCurrentText(f"{int(round(percent))}%")
        self._zoom_combo.blockSignals(False)

    @staticmethod
    def _tab_bar_compact_only_needed(tw: QTabWidget) -> None:
        """Tabs strecken nicht entlang der ganzen Kante (Windows-Style ignoriert oft nur setExpanding)."""
        tw.tabBar().setExpanding(False)
        compact_qss = "QTabWidget QTabBar { qproperty-expanding: false; }"
        cur = (tw.styleSheet() or "").strip()
        if "qproperty-expanding" in cur:
            return
        tw.setStyleSheet(f"{cur}\n{compact_qss}".strip() if cur else compact_qss)

    def _build_main_layout(self, root_layout: QVBoxLayout) -> None:
        left_tabs = QTabWidget(self)
        left_tabs.setTabPosition(QTabWidget.TabPosition.East)
        left_tabs.setDocumentMode(True)
        left_tabs.setStyleSheet(
            "QTabWidget::pane { border: 0; margin: 0; padding: 0; }\n"
            + studio_tab_bar_stylesheet(selected_tab_bg=LIBRARY_HEADER_BUTTON_HOVER)
        )
        self._left_tabs = left_tabs
        self._variables_panel = build_variables_tab_panel(self._controller, self)
        self._parameters_panel = build_parameters_tab_panel(
            self._controller,
            lambda cmd: self._controller_execute_logged(cmd, source="parameters_panel"),
            self,
        )
        self._resources_panel_widget = build_resources_panel(self._controller, self)
        left_tabs.addTab(self._resources_panel_widget, "Librarys")
        left_tabs.addTab(self._variables_panel, "Elements")
        left_tabs.addTab(self._parameters_panel, "Parameters")
        left_tabs.setCurrentWidget(self._resources_panel_widget)
        MainWindow._tab_bar_compact_only_needed(left_tabs)
        _resource_tab_strip_w = max(left_tabs.tabBar().sizeHint().width(), 28)
        _left_resources_w = RESOURCES_PANEL_MIN_WIDTH + _resource_tab_strip_w
        left_tabs.setMinimumWidth(_left_resources_w)
        left_tabs.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        canvas_host = QWidget(self)
        canvas_host.setMinimumWidth(260)
        canvas_host.setStyleSheet("background-color: transparent; border: none;")
        canvas_host_layout = QHBoxLayout(canvas_host)
        canvas_host_layout.setContentsMargins(0, 0, 0, 0)
        canvas_host_layout.setSpacing(0)

        self._diagram_palette_icon_px = 20
        self._diagram_palette_toolbar = QToolBar(canvas_host)
        self._diagram_palette_toolbar.setOrientation(Qt.Orientation.Vertical)
        self._diagram_palette_toolbar.setMovable(False)
        self._diagram_palette_toolbar.setIconSize(QSize(self._diagram_palette_icon_px, self._diagram_palette_icon_px))
        self._diagram_palette_group = QActionGroup(self)
        self._diagram_palette_group.setExclusive(True)
        self._diagram_palette_actions: list[QAction] = []
        # Mode toggle: top of canvas toolbar, separated from placement/sim controls below.
        self._diagram_palette_toolbar.addAction(self.sim_mode_action)
        self._diagram_palette_toolbar.addSeparator()
        mode_gap = QWidget(canvas_host)
        mode_gap.setFixedHeight(8)
        mode_gap.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._diagram_palette_toolbar.addWidget(mode_gap)
        _palette_specs: tuple[tuple[str, str], ...] = (
            ("Place variable", "var"),
            ("Place + operator", "+"),
            ("Place − operator", "-"),
            ("Place × operator", "*"),
            ("Place ÷ operator", "/"),
        )
        for tip, mode in _palette_specs:
            act = QAction(self)
            act.setIcon(QIcon())
            act.setCheckable(True)
            act.setToolTip(tip)
            act.setProperty("placement_mode", mode)
            self._diagram_palette_group.addAction(act)
            self._diagram_palette_toolbar.addAction(act)
            self._diagram_palette_actions.append(act)
            act.toggled.connect(self._on_diagram_palette_toggled)

        # Reserve exactly the palette column height in sim mode (measured in edit mode / before hide).
        self._diagram_palette_measured_stack_h = 0
        self._diagram_palette_measured_width = 0
        self._diagram_palette_mode_spacer = QWidget(canvas_host)
        self._diagram_palette_mode_spacer.setFixedHeight(0)
        self._diagram_palette_mode_spacer.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._diagram_palette_mode_spacer.setVisible(False)
        self._diagram_palette_toolbar.addWidget(self._diagram_palette_mode_spacer)

        # Canvas-local Play/Pause/Stop (not on the main toolbar); visible only in simulation (experiment) mode.
        self._canvas_play_action = QAction(self)
        self._canvas_play_action.setIcon(self.play_action.icon())
        self._canvas_play_action.setToolTip(self.play_action.toolTip())
        self._canvas_play_action.setCheckable(True)
        self._canvas_play_action.toggled.connect(self._on_play_action_toggled)
        self._canvas_play_action.setVisible(False)
        self._canvas_pause_action = QAction(self)
        self._canvas_pause_action.setIcon(self.pause_action.icon())
        self._canvas_pause_action.setToolTip(self.pause_action.toolTip())
        self._canvas_pause_action.setCheckable(True)
        self._canvas_pause_action.triggered.connect(self._on_simulation_pause)
        self._canvas_pause_action.setVisible(False)
        self._canvas_stop_action = QAction(self)
        self._canvas_stop_action.setIcon(self.stop_action.icon())
        self._canvas_stop_action.setToolTip(self.stop_action.toolTip())
        self._canvas_stop_action.triggered.connect(self._on_simulation_stop)
        self._canvas_stop_action.setVisible(False)
        self._canvas_stop_hold_action = QAction(self)
        self._canvas_stop_hold_action.setIcon(self.stop_hold_action.icon())
        self._canvas_stop_hold_action.setToolTip(self.stop_hold_action.toolTip())
        self._canvas_stop_hold_action.setCheckable(True)
        self._canvas_stop_hold_action.triggered.connect(self._on_simulation_stop_hold)
        self._canvas_stop_hold_action.setVisible(False)
        self._canvas_step_action = QAction(self)
        self._canvas_step_action.setIcon(self.step_action.icon())
        self._canvas_step_action.setToolTip(self.step_action.toolTip())
        self._canvas_step_action.triggered.connect(self._on_simulation_step_action_triggered)
        self._canvas_step_action.setVisible(False)
        self._canvas_step_count_action = self._create_step_count_widget_action(self._diagram_palette_toolbar)
        self._canvas_step_count_action.setVisible(False)
        self._canvas_record_action = QAction(self)
        self._canvas_record_action.setCheckable(True)
        self._canvas_record_action.setToolTip(
            "Record all variable values at the end of the next simulation run"
        )
        rec_icon_path = self._icons_dir / "media-record-symbolic.svg"
        if rec_icon_path.exists():
            self._canvas_record_action.setIcon(QIcon(str(rec_icon_path)))
        self._canvas_record_action.setVisible(False)

        self._canvas_realtime_action = QAction(self)
        self._canvas_realtime_action.setCheckable(True)
        self._canvas_realtime_action.setChecked(True)
        self._canvas_realtime_action.setToolTip(
            "Realtime pacing: one model step per wall-clock tick aligned to the step size (default 20 ms). "
            "Turn off to advance simulation as fast as the CPU allows (UI updates once per burst)."
        )
        _rt_icon = self._icons_dir / "chronometer-stopwatch.svg"
        if _rt_icon.exists():
            self._canvas_realtime_action.setIcon(
                icon_from_tinted_svg_file(
                    _rt_icon,
                    QColor(STUDIO_TOOLBAR_FOREGROUND),
                    logical_side=int(self._diagram_palette_icon_px),
                )
            )
        self._canvas_realtime_action.setVisible(False)
        self._canvas_realtime_action.toggled.connect(self._on_canvas_realtime_pacing_toggled)

        self._diagram_palette_toolbar.addSeparator()
        self._diagram_palette_toolbar.addAction(self._canvas_play_action)
        self._diagram_palette_toolbar.addAction(self._canvas_pause_action)
        self._diagram_palette_toolbar.addAction(self._canvas_stop_hold_action)
        self._diagram_palette_toolbar.addAction(self._canvas_stop_action)
        self._diagram_palette_toolbar.addAction(self._canvas_step_action)
        self._diagram_palette_toolbar.addAction(self._canvas_step_count_action)
        self._diagram_palette_toolbar.addSeparator()
        self._diagram_palette_toolbar.addAction(self._canvas_record_action)
        self._diagram_palette_toolbar.addAction(self._canvas_realtime_action)

        canvas_host_layout.addWidget(self._diagram_palette_toolbar, 0)

        self._diagram_view_host = QWidget(canvas_host)
        self._diagram_view_host.setStyleSheet(f"background-color: {CANVAS_BACKGROUND_COLOR}; border: none;")
        view_host_layout = QVBoxLayout(self._diagram_view_host)
        view_host_layout.setContentsMargins(0, 0, 0, 0)
        view_host_layout.setSpacing(0)
        self._dataflow_view = DataflowGraphicsView(self._diagram_scene, self._diagram_view_host)
        view_host_layout.addWidget(self._dataflow_view)
        canvas_host_layout.addWidget(self._diagram_view_host, 1)

        self._canvas_center_tabs = QTabWidget(self)
        self._canvas_center_tabs.setDocumentMode(True)
        self._canvas_center_tabs.setTabsClosable(True)
        self._canvas_center_tabs.setMovable(False)
        self._canvas_center_tabs.setStyleSheet(
            "QTabWidget::pane { border: 0; margin: 0; padding: 0; }\n"
            + studio_tab_bar_stylesheet(selected_tab_bg=LIBRARY_HEADER_BUTTON_HOVER)
        )
        MainWindow._tab_bar_compact_only_needed(self._canvas_center_tabs)
        self._canvas_center_tabs.addTab(canvas_host, "Canvas")
        self._canvas_center_tabs.tabBar().setTabButton(0, QTabBar.ButtonPosition.RightSide, None)
        self._canvas_center_tabs.tabCloseRequested.connect(self._on_canvas_center_tab_close_requested)

        self.right_tabs = QTabWidget(self)
        self.right_tabs.setTabPosition(QTabWidget.TabPosition.West)
        self.right_tabs.addTab(self._build_experiment_panel(), "Measurements")
        self.right_tabs.addTab(self._build_signals_panel(), "Signals")
        self.right_tabs.setStyleSheet(
            "QTabWidget::pane { border: 0; margin: 0; padding: 0; }\n"
            + studio_tab_bar_stylesheet(selected_tab_bg=LIBRARY_HEADER_BUTTON_HOVER)
        )
        MainWindow._tab_bar_compact_only_needed(self.right_tabs)
        self.right_tabs.setMinimumWidth(140)
        self.right_tabs.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        self.bottom_tabs = QTabWidget(self)
        self.bottom_tabs.setDocumentMode(True)
        self.bottom_tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.bottom_tabs.setStyleSheet(
            f"QTabWidget::pane {{ border: 0; margin: 0; padding: 0; background-color: {CONSOLE_CHROME_BACKGROUND}; }}"
            + studio_tab_bar_stylesheet(selected_tab_bg=CONSOLE_CHROME_BACKGROUND)
        )
        self.bottom_tabs.addTab(self._build_console_panel(), "Console")
        self.bottom_tabs.addTab(self._build_general_log_panel(), "Log")
        self.bottom_tabs.addTab(self._build_build_log_panel(), "Build")
        self.bottom_tabs.addTab(self._build_experiment_log_panel(), "Experiment")
        self.bottom_tabs.addTab(self._build_fmu_debug_panel(), "FMU")
        MainWindow._tab_bar_compact_only_needed(self.bottom_tabs)
        self.bottom_tabs.setMinimumHeight(100)

        self.center_split = QSplitter(self)
        self.center_split.setOrientation(Qt.Orientation.Vertical)
        self.center_split.addWidget(self._canvas_center_tabs)
        self.center_split.addWidget(self.bottom_tabs)
        self.center_split.setStretchFactor(0, 1)
        self.center_split.setStretchFactor(1, 0)
        self.center_split.setSizes([560, 180])

        self.horizontal_split = QSplitter(self)
        self.horizontal_split.setOrientation(Qt.Orientation.Horizontal)
        self.horizontal_split.addWidget(left_tabs)
        self.horizontal_split.addWidget(self.center_split)
        self.horizontal_split.addWidget(self.right_tabs)
        self.horizontal_split.setStretchFactor(0, 0)
        self.horizontal_split.setStretchFactor(1, 1)
        self.horizontal_split.setStretchFactor(2, 0)
        self.horizontal_split.setSizes([_left_resources_w, 712, 220])  # initial; user can drag

        root_layout.addWidget(self.horizontal_split, 1)

    def _on_canvas_center_tab_close_requested(self, index: int) -> None:
        if index <= 0:
            return
        w = self._canvas_center_tabs.widget(index)
        if w in (self._fmfl_code_view, self._python_code_view):
            self._canvas_center_tabs.removeTab(index)

    def _on_canvas_realtime_pacing_toggled(self, checked: bool) -> None:
        w = self._run_worker
        if w is None:
            return
        QMetaObject.invokeMethod(
            w,
            "set_realtime_pacing",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(bool, bool(checked)),
        )

    def _ensure_experiment_code_tabs(self) -> None:
        """FMFL- und Python-Tab nur im Experimentiermodus; Inhalt via :meth:`_refresh_experiment_codegen_views`."""
        if not self.sim_mode_action.isChecked():
            return
        tw = self._canvas_center_tabs
        if self._fmfl_code_view is None:
            self._fmfl_code_view = ReadOnlyCodeView(self)
        if self._python_code_view is None:
            self._python_code_view = ReadOnlyCodeView(self)
        if tw.indexOf(self._fmfl_code_view) < 0:
            tw.addTab(self._fmfl_code_view, "FMFL")
        if tw.indexOf(self._python_code_view) < 0:
            tw.addTab(self._python_code_view, "Python")

    def _remove_experiment_code_tabs(self) -> None:
        tw = getattr(self, "_canvas_center_tabs", None)
        if tw is None:
            return
        for w in (self._fmfl_code_view, self._python_code_view):
            if w is None:
                continue
            idx = tw.indexOf(w)
            if idx >= 0:
                tw.removeTab(idx)

    def _schedule_experiment_codegen_refresh(self) -> None:
        """Debounced refresh of FMFL/Python tabs after diagram or model changes (experiment mode)."""
        if not self.sim_mode_action.isChecked():
            return
        self._experiment_codegen_debounce.start()

    def _refresh_experiment_codegen_views(self) -> None:
        if not self.sim_mode_action.isChecked():
            return
        self._ensure_experiment_code_tabs()
        view = compile_dataflow_for_view(self._controller.model)
        dt = float(getattr(self, "_active_run_dt_s", 0.02) or 0.02)
        if self._fmfl_code_view is not None:
            self._fmfl_code_view.set_plain_text(
                generate_fmfl_document(view.compiled, dt_s=dt, diagnostics=view.diagnostics)
            )
        if self._python_code_view is not None:
            self._python_code_view.set_plain_text(
                generate_unrolled_python_step_document(view.compiled, dt_s=dt, diagnostics=view.diagnostics)
            )

    def _reload_library_and_plugins(self) -> None:
        self._controller.library_catalog = LibraryCatalog(extra_roots=studio_library_extra_roots())
        self._controller.alias_roots["@libraries"] = self._controller.library_catalog.root
        self._controller.plugin_registry.reload()

    def _refresh_resources_panel(self) -> None:
        tabs = getattr(self, "_left_tabs", None)
        panel = getattr(self, "_resources_panel_widget", None)
        if tabs is None or panel is None:
            return
        idx = tabs.indexOf(panel)
        if idx < 0:
            return
        # removeTab/insertTab can move the current tab (e.g. to Variables); restore selection below.
        had_focus = tabs.currentWidget()
        tabs.removeTab(idx)
        panel.deleteLater()
        self._resources_panel_widget = build_resources_panel(self._controller, self)
        tabs.insertTab(idx, self._resources_panel_widget, "Librarys")
        if had_focus is panel:
            tabs.setCurrentWidget(self._resources_panel_widget)
        elif had_focus is not None:
            tabs.setCurrentWidget(had_focus)

    def _install_extension_zip(self) -> None:
        from synarius_core.plugins.install import install_distribution_archive

        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Install extension (ZIP)",
            str(Path.home()),
            "Zip archives (*.zip)",
        )
        if not path_str:
            return
        studio_plugins_dir().mkdir(parents=True, exist_ok=True)
        studio_lib_dir().mkdir(parents=True, exist_ok=True)
        try:
            summary = install_distribution_archive(
                Path(path_str),
                plugins_container=studio_plugins_dir(),
                lib_container=studio_lib_dir(),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Install extension", str(exc))
            return
        self._reload_library_and_plugins()
        self._refresh_resources_panel()
        self._variables_panel.refresh()
        parts: list[str] = []
        if summary.get("plugins"):
            parts.append("Plugins:\n" + "\n".join(str(p) for p in summary["plugins"]))
        if summary.get("lib"):
            parts.append("Libraries:\n" + "\n".join(str(p) for p in summary["lib"]))
        QMessageBox.information(self, "Install extension", "\n\n".join(parts) or "Done.")
        self.statusBar().showMessage("Extensions installed; library and plugin lists reloaded.")

    def _warn_if_fmu_without_runtime_plugin(self) -> bool:
        _lp = self._controller.plugin_registry.plugin_for_capability("runtime:fmu")
        if _lp:
            return True
        from synarius_core.model import BasicOperator, ElementaryInstance, Variable

        for obj in self._controller.model.iter_objects():
            if not isinstance(obj, ElementaryInstance):
                continue
            if isinstance(obj, (Variable, BasicOperator)):
                continue
            try:
                fm = obj.get("fmu")
            except KeyError:
                continue
            if isinstance(fm, dict) and str(fm.get("path") or "").strip():
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Icon.Warning)
                box.setWindowTitle("FMU blocks")
                box.setText(
                    "The diagram contains FMU (or similar) elementary block(s), but no plugin "
                    "registers capability runtime:fmu. The built-in scalar engine will not "
                    "execute these blocks (outputs stay at zero). Continue anyway?"
                )
                box.setStandardButtons(
                    QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
                )
                return box.exec() == QMessageBox.StandardButton.Ok
        return True

    def _refresh_diagram(self) -> None:
        populate_scene_from_model(
            self._diagram_scene,
            self._controller.model,
            on_connector_orthogonal_bends=self._apply_connector_orthogonal_bends,
        )
        self._diagram_item_refs = list(self._diagram_scene.items())
        try:
            sim_on = self._coerce_root_bool(self._controller.model.root.get("simulation_mode"))
        except (KeyError, TypeError):
            sim_on = False
        self._apply_diagram_edit_capabilities(not sim_on)
        self._sync_live_value_overlays(sim_on)
        self._sync_dataviewer_items_visibility(sim_on)

    def _sync_dataviewer_items_visibility(self, sim_on: bool) -> None:
        for it in self._diagram_item_refs:
            if isinstance(it, DataViewerBlockItem):
                it.set_sim_canvas_visible(sim_on)

    def _sync_live_value_overlays(self, sim_on: bool) -> None:
        for it in self._diagram_item_refs:
            if isinstance(it, VariableBlockItem):
                it.set_live_value_overlay(sim_on)
                if sim_on:
                    it.refresh_value_display()

    def _apply_diagram_edit_capabilities(self, editable: bool) -> None:
        for it in self._diagram_item_refs:
            if isinstance(it, (VariableBlockItem, OperatorBlockItem, FmuBlockItem)):
                it.set_diagram_editing_enabled(editable)
            elif isinstance(it, ConnectorEdgeItem):
                it.set_route_editing_enabled(editable)

    def _refresh_variable_value_labels(self) -> None:
        for it in self._diagram_item_refs:
            if isinstance(it, VariableBlockItem):
                if it.live_value_overlay_enabled():
                    it.refresh_value_display()

    @staticmethod
    def _coerce_root_bool(value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    def _diagram_palette_action_stack_height(self) -> int:
        """Total vertical extent of the placement action column (toolbar coordinates)."""
        tb = self._diagram_palette_toolbar
        top = 0
        bottom = 0
        found = False
        for act in getattr(self, "_diagram_palette_actions", []):
            w = tb.widgetForAction(act)
            if w is None or not w.isVisible():
                continue
            g = w.geometry()
            if g.height() <= 0:
                continue
            if not found:
                top, bottom = g.top(), g.bottom()
                found = True
            else:
                top = min(top, g.top())
                bottom = max(bottom, g.bottom())
        if not found:
            return 0
        return max(bottom - top + 1, 1)

    def _diagram_palette_spacer_fallback_height(self) -> int:
        row = max(22, self._diagram_palette_icon_px + 2)
        return 5 * row

    def _prepare_diagram_palette_mode_spacer_height(self) -> None:
        if not hasattr(self, "_diagram_palette_mode_spacer"):
            return
        h = self._diagram_palette_action_stack_height()
        if h >= 8:
            self._diagram_palette_measured_stack_h = h
        else:
            h = self._diagram_palette_measured_stack_h or self._diagram_palette_spacer_fallback_height()
        self._diagram_palette_mode_spacer.setFixedHeight(max(h, 8))
        self._apply_diagram_palette_reference_width()

    def _diagram_palette_width(self) -> int:
        tb = self._diagram_palette_toolbar
        # Use hint-based width only; current widget width may be stale/forced from a previous mode.
        w = max(tb.sizeHint().width(), tb.minimumSizeHint().width())
        return int(max(28, w))

    def _apply_diagram_palette_reference_width(self) -> None:
        if not hasattr(self, "_diagram_palette_toolbar"):
            return
        ref_w = int(getattr(self, "_diagram_palette_measured_width", 0) or 0)
        if ref_w <= 0:
            return
        self._diagram_palette_toolbar.setMinimumWidth(ref_w)
        self._diagram_palette_toolbar.setMaximumWidth(ref_w)

    def _cache_diagram_palette_stack_height_after_layout(self) -> None:
        if self.sim_mode_action.isChecked():
            return
        h = self._diagram_palette_action_stack_height()
        if h >= 8:
            self._diagram_palette_measured_stack_h = h
        w = self._diagram_palette_width()
        if w >= 28:
            self._diagram_palette_measured_width = w
            self._apply_diagram_palette_reference_width()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._after_shown_diagram_palette_toolbar)

    def _after_shown_diagram_palette_toolbar(self) -> None:
        if not hasattr(self, "_diagram_palette_toolbar"):
            return
        if self.sim_mode_action.isChecked():
            if self._diagram_palette_measured_stack_h >= 8:
                self._diagram_palette_mode_spacer.setFixedHeight(self._diagram_palette_measured_stack_h)
            self._apply_diagram_palette_reference_width()
            return
        self._cache_diagram_palette_stack_height_after_layout()

    def _sync_simulation_mode_from_model(self) -> None:
        try:
            raw = self._controller.model.root.get("simulation_mode")
        except (KeyError, TypeError):
            raw = False
        on = self._coerce_root_bool(raw)
        self._sim_mode_suppress_action = True
        self.sim_mode_action.setChecked(on)
        self._sim_mode_suppress_action = False
        if on == self._last_applied_simulation_mode:
            return
        was_on = self._last_applied_simulation_mode is True
        self._last_applied_simulation_mode = on
        if was_on and not on:
            self._close_live_dataviewers_for_sim_mode_exit()
        self._apply_simulation_mode_visuals(on)
        if not was_on and on:
            self._reopen_live_dataviewers_after_sim_mode_enter()

    def _apply_simulation_mode_visuals(self, on: bool) -> None:
        if not on and self._simulation_running:
            self._on_simulation_stop()
        self._diagram_scene.set_simulation_mode(on)
        self._dataflow_view.set_interaction_locked(on)
        chrome = CANVAS_SIMULATION_BACKGROUND_COLOR if on else CANVAS_BACKGROUND_COLOR
        self._diagram_view_host.setStyleSheet(f"background-color: {chrome}; border: none;")
        self._dataflow_view.set_viewport_canvas_color(chrome)
        self._diagram_scene.setBackgroundBrush(QColor(chrome))
        self._apply_diagram_edit_capabilities(not on)
        self._sync_live_value_overlays(on)
        self._sync_dataviewer_items_visibility(on)
        # Internal runtime actions (canvas toolbar only in simulation mode): keep enabled state in sync.
        self.play_action.setEnabled(on)
        pause_may = (
            on
            and self._simulation_running
            and not self._simulation_paused
            and not self._sim_hold_reinit_pending
        )
        self.pause_action.setEnabled(pause_may)
        self.stop_action.setEnabled(on and self._simulation_running)
        self._set_stop_hold_actions_enabled(on and self._stop_hold_actions_may_be_enabled())
        self._sync_stop_hold_actions_checked(on and self._sim_hold_reinit_pending)
        if self._sim_hold_reinit_pending:
            self._sync_pause_actions_checked(False)
        self.step_action.setEnabled(on)
        alive_step_actions: list[QWidgetAction] = []
        for act in self._sim_step_count_actions:
            try:
                act.setEnabled(on)
                act.setVisible(on)
                alive_step_actions.append(act)
            except RuntimeError:
                continue
        self._sim_step_count_actions = alive_step_actions
        if on:
            self._sync_play_actions_checked(self._simulation_running)
        else:
            self._sync_play_actions_checked(False)
            self._cache_diagram_palette_stack_height_after_layout()
        # Canvas toolbar: hide placement palette in simulation; show runtime controls only then.
        if on:
            self._prepare_diagram_palette_mode_spacer_height()
        for act in getattr(self, "_diagram_palette_actions", []):
            act.setVisible(not on)
        if hasattr(self, "_diagram_palette_mode_spacer"):
            self._diagram_palette_mode_spacer.setVisible(on)
        if not on:
            QTimer.singleShot(0, self._cache_diagram_palette_stack_height_after_layout)
        self._apply_diagram_palette_reference_width()
        if (
            hasattr(self, "_canvas_play_action")
            and hasattr(self, "_canvas_pause_action")
            and hasattr(self, "_canvas_stop_action")
            and hasattr(self, "_canvas_stop_hold_action")
            and hasattr(self, "_canvas_step_action")
            and hasattr(self, "_canvas_step_count_action")
            and hasattr(self, "_canvas_record_action")
            and hasattr(self, "_canvas_realtime_action")
        ):
            self._canvas_play_action.setVisible(on)
            self._canvas_pause_action.setVisible(on)
            self._canvas_stop_action.setVisible(on)
            self._canvas_stop_hold_action.setVisible(on)
            self._canvas_step_action.setVisible(on)
            self._canvas_step_count_action.setVisible(on)
            self._canvas_record_action.setVisible(on)
            self._canvas_realtime_action.setVisible(on)
            self._canvas_play_action.setEnabled(on)
            self._canvas_pause_action.setEnabled(pause_may)
            self._canvas_stop_action.setEnabled(on and self._simulation_running)
            self._canvas_step_action.setEnabled(on)
            self._canvas_step_count_action.setEnabled(on)
            self._canvas_record_action.setEnabled(on)
            self._canvas_realtime_action.setEnabled(on)
        self.statusBar().showMessage("Simulation mode" if on else "Ready.")
        for tb in (self._main_toolbar, self._diagram_palette_toolbar):
            btn = tb.widgetForAction(self.sim_mode_action)
            if isinstance(btn, QToolButton):
                btn.setCheckable(True)
                btn.setChecked(on)
        if on:
            self._ensure_experiment_code_tabs()
            self._refresh_experiment_codegen_views()
        else:
            self._remove_experiment_code_tabs()

    def _on_sim_mode_action_toggled(self, checked: bool) -> None:
        if self._sim_mode_suppress_action:
            return
        cmd = f"set @main.simulation_mode {'true' if checked else 'false'}"
        self._execute_controller_line_for_ui(cmd)

    def _on_variable_sim_binding_toggle(self, variable: object, action: str, new_on: bool) -> None:
        if not isinstance(variable, Variable):
            return
        v = variable
        if action == "stimulate":
            was = str(v.get("stim_kind")).strip().lower() not in ("", "none")
            if new_on and not was:
                dlg = StimulationDialog(v, self)
                if dlg.exec() != QDialog.DialogCode.Accepted:
                    self._refresh_diagram()
                    return
                self._run_protocol_lines_as_console(dlg.protocol_commands())
            elif not new_on and was:
                h = shlex.quote(v.hash_name)
                self._run_protocol_lines_as_console([f"set {h}.stim_kind none"])
            self._refresh_diagram()
            return
        if action == "measure":
            try:
                raw = v.get("dataviewer_measure_ids")
            except (KeyError, TypeError, ValueError):
                raw = []
            was_meas = bool(raw) if isinstance(raw, (list, tuple)) else bool(raw)
            if not new_on:
                if was_meas:
                    h = shlex.quote(v.hash_name)
                    self._run_protocol_lines_as_console([f"set {h}.dataviewer_measure_ids []"])
                self._refresh_diagram()
                return
            dlg = SelectDataViewerDialog(self._controller.model, v, self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                self._refresh_diagram()
                return
            self._apply_measure_selection_from_dialog(v, dlg)
            self._refresh_diagram()

    def _apply_measure_selection_from_dialog(self, v: Variable, dlg: SelectDataViewerDialog) -> None:
        model = self._controller.model
        ids = list(dlg.selected_viewer_ids())
        new_id: int | None = None
        if dlg.want_new_viewer():
            try:
                hn_raw = self._controller_execute_logged("new DataViewer", source="dialog")
            except CommandError as exc:
                self.console.insert_log_before_current_prompt(f"error: {exc}", ERROR_COLOR)
                return
            hn = str(hn_raw or "").strip()
            if hn:
                for node in model.iter_objects():
                    if node.hash_name == hn and hasattr(node, "get"):
                        try:
                            new_id = int(node.get("dataviewer_id"))
                        except (KeyError, TypeError, ValueError):
                            new_id = None
                        break
            if new_id is not None:
                ids.append(new_id)
        ids = sorted({int(x) for x in ids})
        h = shlex.quote(v.hash_name)
        if not ids:
            self._run_protocol_lines_as_console([f"set {h}.dataviewer_measure_ids []"])
            return
        id_lit = "[" + ",".join(str(i) for i in ids) + "]"
        last_id = new_id if new_id is not None else ids[-1]
        self._run_protocol_lines_as_console(
            [
                f"set {h}.dataviewer_measure_ids {id_lit}",
                f"set @main.last_selected_dataviewer_id {last_id}",
            ]
        )

    def _run_protocol_lines_as_console(self, lines: list[str]) -> None:
        prompt = str(self._controller.current.get("prompt_path"))
        for ln in lines:
            self.console.insert_log_before_current_prompt(f"{prompt}> {ln}", DEFAULT_PROMPT_COLOR)
            try:
                result = self._controller_execute_logged(ln, source="batch")
            except CommandError as exc:
                self.console.insert_log_before_current_prompt(f"error: {exc}", ERROR_COLOR)
                self._sync_simulation_mode_from_model()
                return
            except Exception:
                self.console.insert_log_before_current_prompt(
                    "error: unexpected exception (see log file)", ERROR_COLOR
                )
                self._sync_simulation_mode_from_model()
                return
            if result is not None and result != "":
                self.console.insert_log_before_current_prompt(result, self._get_output_color())

    def _sync_play_actions_checked(self, checked: bool) -> None:
        """Keep internal and canvas Play actions in the same check state without re-entering toggle logic."""
        self._sim_play_suppress_action = True
        self.play_action.setChecked(checked)
        if hasattr(self, "_canvas_play_action"):
            self._canvas_play_action.setChecked(checked)
        self._sim_play_suppress_action = False

    def _sync_pause_actions_checked(self, checked: bool) -> None:
        self.pause_action.setChecked(checked)
        if hasattr(self, "_canvas_pause_action"):
            self._canvas_pause_action.setChecked(checked)

    def _sync_stop_hold_actions_checked(self, checked: bool) -> None:
        self.stop_hold_action.setChecked(checked)
        if hasattr(self, "_canvas_stop_hold_action"):
            self._canvas_stop_hold_action.setChecked(checked)

    def _stop_hold_actions_may_be_enabled(self) -> bool:
        """Stop/Hold is only available while running, not while Pause is latched, and not while hold is active."""
        return bool(
            self._simulation_running
            and not self.pause_action.isChecked()
            and not self._sim_hold_reinit_pending
        )

    def _set_stop_hold_actions_enabled(self, enabled: bool) -> None:
        self.stop_hold_action.setEnabled(enabled)
        if hasattr(self, "_canvas_stop_hold_action"):
            self._canvas_stop_hold_action.setEnabled(enabled)

    def _create_step_count_widget_action(
        self, parent: QObject, *, expand_in_toolbar_slot: bool = True
    ) -> QWidgetAction:
        act = QWidgetAction(parent)
        compact_qss = with_tooltip_qss(
            "QLineEdit { min-height: 16px; max-height: 16px; font-size: 9px; "
            "padding: 0px 2px; border: 1px solid #666; border-radius: 2px; "
            "background: #262626; color: #f5f5f5; }"
        )
        # Popup uses a composite widget: QSpinBox without native buttons + QToolButtons with painted arrows.
        popup_qss = with_tooltip_qss(
            "QSpinBox { min-height: 24px; max-height: 24px; font-size: 12px; "
            "padding: 2px 6px; border: none; background: #262626; color: #f5f5f5; }"
        )
        tip = "Number of simulation steps for the Step action"
        field = SimulationStepCountField(
            initial=str(max(1, int(self._sim_step_count))),
            compact_style=compact_qss,
            popup_style=popup_qss,
            max_length=6,
            tooltip=tip,
            expand_in_toolbar_slot=expand_in_toolbar_slot,
        )
        field.valueCommitted.connect(self._on_step_count_value_committed)
        act.setDefaultWidget(field)
        self._sim_step_count_fields.append(field)
        self._sim_step_count_actions.append(act)
        return act

    def _normalized_step_count(self, raw: str) -> int:
        try:
            val = int(str(raw).strip())
        except Exception:
            return max(1, int(self._sim_step_count))
        return max(1, val)

    def _on_step_count_value_committed(self, raw: str) -> None:
        new_count = self._normalized_step_count(raw)
        changed = new_count != self._sim_step_count
        self._sim_step_count = new_count
        text = str(self._sim_step_count)
        alive: list[SimulationStepCountField] = []
        for fld in self._sim_step_count_fields:
            try:
                fld.set_display_value(text)
                alive.append(fld)
            except RuntimeError:
                continue
        self._sim_step_count_fields = alive
        if changed:
            self._execute_controller_line_for_ui(f"set @main.simulation_steps {text}")

    def _on_simulation_step_action_triggered(self) -> None:
        if not self.sim_mode_action.isChecked():
            return
        self._sim_steps_remaining = max(1, int(self._sim_step_count))
        if not self._simulation_running:
            self._sync_play_actions_checked(True)
            self._try_start_simulation()
        elif self._simulation_paused:
            self._on_simulation_resume()
        self.statusBar().showMessage(f"Simulation stepping: {self._sim_steps_remaining} steps queued.")

    def _on_simulation_stop_hold(self) -> None:
        if not self._simulation_running:
            return
        if self.pause_action.isChecked() or self._simulation_paused:
            self.statusBar().showMessage("Stop/Hold has no effect while Pause is active.")
            return
        self._sim_steps_remaining = 0
        if not self._simulation_paused:
            self._on_simulation_pause()
        self._sync_pause_actions_checked(False)
        self._sim_hold_reinit_pending = True
        self._sync_stop_hold_actions_checked(True)
        self._set_stop_hold_actions_enabled(False)
        self.statusBar().showMessage("Simulation hold active. Next resume re-initializes the model.")

    def _on_play_action_toggled(self, checked: bool) -> None:
        if self._sim_play_suppress_action:
            return
        if not self.sim_mode_action.isChecked():
            self._sync_play_actions_checked(False)
            return
        self._sim_play_suppress_action = True
        self.play_action.setChecked(checked)
        if hasattr(self, "_canvas_play_action"):
            self._canvas_play_action.setChecked(checked)
        self._sim_play_suppress_action = False
        if checked:
            if self._simulation_running:
                self._on_simulation_resume()
            else:
                self._try_start_simulation()
        elif self._simulation_running and not self._simulation_paused:
            self._on_simulation_pause()

    def _try_start_simulation(self) -> None:
        if self._sim_hold_reinit_pending and self._simulation_running:
            self._sim_restart_after_hold_pending = True
            if self._run_worker is not None:
                self._run_worker.request_stop()
            return
        if not self.sim_mode_action.isChecked():
            return
        preserve_series = bool(self._sim_hold_reinit_pending)
        if not preserve_series:
            self._clear_experiment_log_view()
            # Jede Simulation mit frischer Zeitachse und leeren Live-Buffern starten,
            # damit keine Totzeit/Altwerte aus vorherigen Läufen sichtbar bleiben.
            self._live_series_buffers.clear()
            self._live_series_t0 = time.perf_counter()
            self._sim_time_offset_s = 0.0
            self._sim_time_last_s = 0.0
            self._reset_open_live_dataviewers_for_new_run()
        else:
            self._sim_time_offset_s = max(0.0, float(self._sim_time_last_s))
        _EXP_LOG.info(
            "simulation start: reset live buffers (size=%d), live_t0=%.6f",
            len(self._live_series_buffers),
            self._live_series_t0,
        )
        # Reset recording buffers at the start of a run if experiment recording is enabled.
        if (not preserve_series) and hasattr(self, "_canvas_record_action") and self._canvas_record_action.isChecked():
            self._record_series_buffers.clear()
            self._record_series_t0 = time.perf_counter()
            _EXP_LOG.info(
                "simulation start: recording enabled, reset record buffers (size=%d), record_t0=%.6f",
                len(self._record_series_buffers),
                self._record_series_t0,
            )
        elif preserve_series and hasattr(self, "_canvas_record_action") and self._canvas_record_action.isChecked():
            _EXP_LOG.info("simulation hold-resume: keep existing recording buffers")
        else:
            _EXP_LOG.info("simulation start: recording disabled")
        self._refresh_experiment_tabs_after_worker_start = (not preserve_series) and bool(
            self.sim_mode_action.isChecked()
        )
        if not self._warn_if_fmu_without_runtime_plugin():
            self._refresh_experiment_tabs_after_worker_start = False
            self._sync_play_actions_checked(False)
            return
        _md = None
        _lp = getattr(self._controller, "last_loaded_script_path", None)
        if _lp is not None:
            _md = _lp.parent
        # Dedicated run-loop worker thread (GUI remains responsive).
        self._run_thread = QThread(self)
        self._active_run_dt_s = 0.02
        self._run_worker = _RunLoopWorker(
            self._controller.model,
            dt_s=self._active_run_dt_s,
            tick_interval_ms=None,
            realtime_pacing=bool(
                not hasattr(self, "_canvas_realtime_action")
                or self._canvas_realtime_action.isChecked()
            ),
            plugin_registry=self._controller.plugin_registry,
            model_directory=_md,
            # Always apply diagram-sourced FMU parameters at init; must not depend on hold/series flags
            # (previously tied to preserve_series, so a normal Play left defaults like g=-9.81 and ignored ±g).
            apply_fmu_params_on_init=True,
        )
        self._run_worker.moveToThread(self._run_thread)
        self._run_thread.started.connect(self._run_worker.start)
        self._run_worker.started_ok.connect(self._on_worker_started)  # type: ignore[attr-defined]
        self._run_worker.start_failed.connect(self._on_worker_start_failed)  # type: ignore[attr-defined]
        self._run_worker.tick.connect(self._on_worker_tick)  # type: ignore[attr-defined]
        self._run_worker.stopped.connect(self._on_worker_stopped)  # type: ignore[attr-defined]
        self._run_worker.stopped.connect(self._run_thread.quit)  # type: ignore[attr-defined]
        self._run_thread.finished.connect(self._on_run_thread_finished)
        # Mark as running before first tick arrives (queued signal order across threads).
        self._simulation_running = True
        self._simulation_paused = False
        self.pause_action.setEnabled(True)
        self.stop_action.setEnabled(True)
        self._set_stop_hold_actions_enabled(True)
        self.step_action.setEnabled(True)
        if (
            hasattr(self, "_canvas_play_action")
            and hasattr(self, "_canvas_pause_action")
            and hasattr(self, "_canvas_stop_action")
            and hasattr(self, "_canvas_stop_hold_action")
            and hasattr(self, "_canvas_step_action")
        ):
            self._canvas_pause_action.setEnabled(True)
            self._canvas_stop_action.setEnabled(True)
            self._canvas_step_action.setEnabled(True)
        self._sim_hold_reinit_pending = False
        self._sync_stop_hold_actions_checked(False)
        self._sync_pause_actions_checked(False)
        self._run_thread.start()

    def _on_simulation_pause(self) -> None:
        if self._sim_hold_reinit_pending:
            self.statusBar().showMessage("Simulation hold active. Pause has no effect.")
            return
        if not self._simulation_running or self._simulation_paused:
            return
        if self._run_worker is not None:
            self._run_worker.request_pause()
        self._simulation_paused = True
        self._sim_steps_remaining = 0
        self.pause_action.setEnabled(False)
        if hasattr(self, "_canvas_pause_action"):
            self._canvas_pause_action.setEnabled(False)
        self._sync_pause_actions_checked(True)
        self._sync_play_actions_checked(False)
        self._set_stop_hold_actions_enabled(False)
        self.statusBar().showMessage("Simulation paused.")

    def _on_simulation_resume(self) -> None:
        if not self._simulation_running or not self._simulation_paused:
            return
        if self._sim_hold_reinit_pending:
            self._sync_stop_hold_actions_checked(False)
            self._sim_restart_after_hold_pending = True
            if self._run_worker is not None:
                self._run_worker.request_stop()
            self.statusBar().showMessage("Re-initializing model for hold/resume...")
            return
        if self._run_worker is not None:
            self._run_worker.request_resume()
        self._simulation_paused = False
        self.pause_action.setEnabled(True)
        if hasattr(self, "_canvas_pause_action"):
            self._canvas_pause_action.setEnabled(True)
        self._sync_pause_actions_checked(False)
        self._sync_play_actions_checked(True)
        if self.sim_mode_action.isChecked():
            self._set_stop_hold_actions_enabled(self._stop_hold_actions_may_be_enabled())
        self.statusBar().showMessage("Simulation running.")

    def _on_simulation_stop(self) -> None:
        # Stop request is asynchronous; final UI/state reset happens in _on_worker_stopped.
        if self._run_worker is not None:
            self._run_worker.request_stop()
        self._sim_steps_remaining = 0
        self._sim_hold_reinit_pending = False
        self._sim_restart_after_hold_pending = False
        self._sync_stop_hold_actions_checked(False)
        self._simulation_paused = False
        self._sync_pause_actions_checked(False)
        self.pause_action.setEnabled(False)
        self._set_stop_hold_actions_enabled(False)
        if self.sim_mode_action.isChecked():
            self.stop_action.setEnabled(False)
            if (
                hasattr(self, "_canvas_play_action")
                and hasattr(self, "_canvas_pause_action")
                and hasattr(self, "_canvas_stop_action")
                and hasattr(self, "_canvas_stop_hold_action")
            ):
                self._canvas_pause_action.setEnabled(False)
                self._canvas_stop_action.setEnabled(False)

    def _on_worker_started(self) -> None:
        # Already marked running in _try_start_simulation.
        self._refresh_variable_value_labels()
        if self._refresh_experiment_tabs_after_worker_start:
            self._refresh_experiment_tabs_after_worker_start = False
            if self.sim_mode_action.isChecked():
                self._ensure_experiment_code_tabs()
                self._refresh_experiment_codegen_views()

    def _reset_open_live_dataviewers_for_new_run(self) -> None:
        """Reset plotted series in already-open live DataViewer dialogs before a new run starts."""
        for w in self._live_dataviewers.values():
            names = [str(n) for n in getattr(w, "_dv_var_names", [])]
            sh = getattr(w, "_dv_shell", None)
            viewer = getattr(sh, "viewer", None) if sh is not None else None
            if viewer is None:
                continue
            for name in names:
                # Keep series empty until the first real tick arrives.
                try:
                    viewer.set_channel_data(
                        name,
                        np.asarray([], dtype=np.float64),
                        np.asarray([], dtype=np.float64),
                    )
                except Exception:
                    continue

    def _on_worker_start_failed(self, message: str) -> None:
        self.statusBar().showMessage(message or "Cannot start simulation.")
        _EXP_LOG.error("simulation start failed: %s", message or "unknown")
        self._refresh_experiment_tabs_after_worker_start = False
        self._simulation_running = False
        self._simulation_paused = False
        self._sim_steps_remaining = 0
        self._sim_hold_reinit_pending = False
        self._sim_restart_after_hold_pending = False
        self._sync_stop_hold_actions_checked(False)
        self._sync_pause_actions_checked(False)
        self.pause_action.setEnabled(False)
        self.stop_action.setEnabled(False)
        self._set_stop_hold_actions_enabled(False)
        if hasattr(self, "_canvas_pause_action"):
            self._canvas_pause_action.setEnabled(False)
        if hasattr(self, "_canvas_stop_action"):
            self._canvas_stop_action.setEnabled(False)
        self._sync_play_actions_checked(False)

    def _on_worker_tick(self, sim_time_s: float, value_by_name: object) -> None:
        sim_time_total = self._sim_time_offset_s + float(sim_time_s)
        self._sim_time_last_s = max(self._sim_time_last_s, sim_time_total)
        vars_map: dict[str, float] = {}
        fmu_map: dict[str, float] = {}
        if isinstance(value_by_name, dict) and "variables" in value_by_name:
            vm = value_by_name.get("variables")
            vars_map = vm if isinstance(vm, dict) else {}
            fw = value_by_name.get("fmu_workspace")
            fmu_map = fw if isinstance(fw, dict) else {}
        elif isinstance(value_by_name, dict):
            vars_map = {
                str(k): float(v)
                for k, v in value_by_name.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            }
        self._refresh_variable_value_labels()
        self._append_live_series_samples(value_by_name=vars_map, t_override=sim_time_total)
        self._update_live_dataviewers(value_by_name=vars_map, t_override=sim_time_total)
        self._update_fmu_debug_table(fmu_map)
        if self._sim_steps_remaining > 0:
            self._sim_steps_remaining -= 1
            if self._sim_steps_remaining <= 0 and self._simulation_running and not self._simulation_paused:
                self._on_simulation_pause()

    def _update_fmu_debug_table(self, fmu_map: dict[str, float]) -> None:
        tbl = getattr(self, "_fmu_debug_table", None)
        if tbl is None:
            return
        keys = sorted(fmu_map.keys())
        tbl.setRowCount(len(keys))
        for i, k in enumerate(keys):
            v = fmu_map[k]
            tbl.setItem(i, 0, QTableWidgetItem(str(k)))
            tbl.setItem(i, 1, QTableWidgetItem(str(v)))

    def _on_worker_stopped(self) -> None:
        if self._sim_restart_after_hold_pending:
            self._sim_restart_after_hold_pending = False
            self._simulation_running = False
            self._simulation_paused = False
            self._run_engine = None
            self._try_start_simulation()
            return
        self._simulation_running = False
        self._simulation_paused = False
        self._run_engine = None
        self._sim_steps_remaining = 0
        self._sim_hold_reinit_pending = False
        self._sim_restart_after_hold_pending = False
        self._sync_stop_hold_actions_checked(False)
        self._sync_pause_actions_checked(False)
        self._refresh_variable_value_labels()
        self._variables_panel.refresh()
        self.pause_action.setEnabled(False)
        self.stop_action.setEnabled(False)
        self._set_stop_hold_actions_enabled(False)
        if hasattr(self, "_canvas_pause_action"):
            self._canvas_pause_action.setEnabled(False)
        if hasattr(self, "_canvas_stop_action"):
            self._canvas_stop_action.setEnabled(False)
        self._sync_play_actions_checked(False)
        self.statusBar().showMessage("Simulation stopped.")
        # In experiment mode, offer to record results when the Record action is checked.
        if (
            self.sim_mode_action.isChecked()
            and hasattr(self, "_canvas_record_action")
            and self._canvas_record_action.isChecked()
        ):
            self._maybe_save_recording_after_run()

    def _on_run_thread_finished(self) -> None:
        sender_obj = self.sender()
        if self._run_thread is not None and sender_obj is not self._run_thread:
            return
        self._run_worker = None
        self._run_thread = None

    def closeEvent(self, event) -> None:  # noqa: ANN001
        """Stop the simulation thread gracefully before the window is destroyed.

        Without this, Qt destroys ``_run_thread`` as a child object while the
        thread is still running, which triggers the fatal
        ``QThread: Destroyed while thread '' is still running`` abort.
        """
        if self._run_thread is not None and self._run_thread.isRunning():
            if self._run_worker is not None:
                self._run_worker.request_stop()
            self._run_thread.quit()
            self._run_thread.wait(3000)  # max 3 s; then force-terminate
            if self._run_thread.isRunning():
                self._run_thread.terminate()
                self._run_thread.wait(1000)
        super().closeEvent(event)

    def _record_default_dir(self) -> Path:
        if self._record_last_dir is not None and self._record_last_dir.is_dir():
            return self._record_last_dir
        return open_syn_dialog_start_dir()

    def _next_record_filename(self) -> Path:
        base_dir = self._record_default_dir()
        fmt = self._record_last_format or "mdf"
        # MDF-Dateien werden von asammdf standardmäßig als *.mf4 gespeichert;
        # diesen Suffix verwenden wir daher auch als Default.
        ext = ".mf4" if fmt == "mdf" else ".parquet" if fmt == "parquet" else ".csv"
        stem = self._record_last_basename or "measurement"
        candidate = base_dir / f"{stem}{ext}"
        if not candidate.exists():
            return candidate
        idx = 1
        while True:
            candidate = base_dir / f"{stem}_{idx}{ext}"
            if not candidate.exists():
                return candidate
            idx += 1

    def _maybe_save_recording_after_run(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        suggested = self._next_record_filename()
        fmt = self._record_last_format or "mdf"
        filters = "MDF files (*.mdf *.mf4 *.dat);;Parquet files (*.parquet *.pq);;CSV files (*.csv)"
        if fmt == "parquet":
            selected_filter = "Parquet files (*.parquet *.pq)"
        elif fmt == "csv":
            selected_filter = "CSV files (*.csv)"
        else:
            selected_filter = "MDF files (*.mdf *.mf4 *.dat)"

        path_str, chosen_filter = QFileDialog.getSaveFileName(
            self,
            "Save recording",
            str(suggested),
            filters,
            selected_filter,
        )
        if not path_str:
            _EXP_LOG.info("recording: user cancelled save dialog")
            return

        out_path = Path(path_str)
        self._record_last_dir = out_path.parent
        self._record_last_basename = out_path.stem
        suf = out_path.suffix.lower()
        if "parquet" in chosen_filter or suf in (".parquet", ".pq"):
            self._record_last_format = "parquet"
        elif "csv" in chosen_filter or suf == ".csv":
            self._record_last_format = "csv"
        else:
            self._record_last_format = "mdf"

        try:
            _EXP_LOG.info(
                "recording: saving buffers (%d channels) to %s as %s",
                len(self._record_series_buffers),
                out_path,
                self._record_last_format,
            )
            self._save_recording_to_path(out_path, self._record_last_format)
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, "Recording", f"Could not save recording:\n{exc}")
            return

        # Register a successfully saved recording in the Measurements list.
        self._register_recording_entry(out_path)

    def _register_recording_entry(self, path: Path) -> None:
        table = self._recordings_table
        if table is None:
            return
        from datetime import datetime

        ts = datetime.now().strftime("%H:%M:%S")
        _EXP_LOG.info("recording: registered %s at %s", path, ts)
        table.insertRow(0)
        name_item = QTableWidgetItem(path.name)
        time_item = QTableWidgetItem(ts)
        name_item.setTextAlignment(int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter))
        time_item.setTextAlignment(int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter))
        name_item.setData(Qt.ItemDataRole.UserRole, str(path))
        table.setItem(0, 0, name_item)
        table.setItem(0, 1, time_item)

    def _on_recordings_context_menu(self, pos) -> None:
        table = self._recordings_table
        if table is None:
            return
        idx = table.indexAt(pos)
        if not idx.isValid():
            return
        row = idx.row()
        name_item = table.item(row, 0)
        if name_item is None:
            return
        raw = name_item.data(Qt.ItemDataRole.UserRole)
        path_str = str(raw).strip() if isinstance(raw, str) else ""
        menu = QMenu(self)
        # Two actions: list-only remove vs. delete file on disk.
        act_list_only = QAction("Remove from list only", self)
        act_list_only.triggered.connect(lambda _checked=False, r=row: self._recordings_remove_row(r, delete_file=False))
        menu.addAction(act_list_only)
        menu.addSeparator()
        act_delete_disk = QAction("Delete file from disk…", self)
        act_delete_disk.setEnabled(bool(path_str))
        act_delete_disk.setToolTip(
            "Deletes the file on disk and removes the entry from the list."
            if path_str
            else 'No saved file path — only "Remove from list only" is available.'
        )
        act_delete_disk.triggered.connect(lambda _checked=False, r=row: self._recordings_remove_row(r, delete_file=True))
        menu.addAction(act_delete_disk)
        menu.exec(table.viewport().mapToGlobal(pos))

    def _recordings_remove_row(self, row: int, *, delete_file: bool) -> None:
        table = self._recordings_table
        if table is None or row < 0 or row >= table.rowCount():
            return
        name_item = table.item(row, 0)
        path_str = ""
        if name_item is not None:
            raw = name_item.data(Qt.ItemDataRole.UserRole)
            if isinstance(raw, str):
                path_str = raw.strip()
        if delete_file:
            if not path_str:
                return
            p = Path(path_str)
            reply = QMessageBox.question(
                self,
                "Delete file",
                f"Delete this file from disk?\n\n{p.name}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            try:
                if p.is_file():
                    p.unlink()
                    _EXP_LOG.info("recording: deleted file %s", p)
                elif p.exists():
                    QMessageBox.warning(self, "Delete file", f"Not a regular file:\n{p}")
                    return
                else:
                    _EXP_LOG.info("recording: file already missing, removing list entry %s", p)
            except OSError as exc:
                QMessageBox.warning(self, "Delete file", f"The file could not be deleted:\n{exc}")
                return
        table.removeRow(row)

    def _save_recording_to_path(self, path: Path, fmt: str) -> None:
        if self._record_series_buffers:
            export_recording_buffers(self._record_series_buffers, path, fmt=fmt)
            return
        # Fallback: Snapshot am Ende (eine Probe pro Variable, t=0)
        snap: dict[str, tuple[list[float], list[float]]] = {}
        for node in self._controller.model.iter_objects():
            if not isinstance(node, Variable):
                continue
            val = node.value
            if isinstance(val, (int, float, np.integer, np.floating)) and not isinstance(val, bool):
                snap[str(node.name)] = ([0.0], [float(val)])
        if not snap:
            return
        export_recording_buffers(snap, path, fmt=fmt)

    def _on_recording_cell_double_clicked(self, row: int, column: int) -> None:
        table = self._recordings_table
        if table is None:
            return
        item = table.item(row, 0)
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, str) or not data:
            return
        rec_path = Path(data)
        if not rec_path.is_file() and rec_path.suffix.lower() == ".mdf":
            alt = rec_path.with_suffix(".mf4")
            if alt.is_file():
                _EXP_LOG.info(
                    "recording: mapped missing %s to existing %s", rec_path, alt
                )
                rec_path = alt
                # Pfad im Modell korrigieren, damit zukünftige Klicks direkt passen.
                item.setData(Qt.ItemDataRole.UserRole, str(rec_path))
        _EXP_LOG.info("recording: double-click on %s (exists=%s)", rec_path, rec_path.is_file())

        # Dev-only monorepo fallback (installed bundle should import from site-packages).
        prepend_dev_synarius_apps_src()

        try:
            from synarius_dataviewer.widgets.data_viewer import DataViewerShell
            from synarius_dataviewer.io import load_timeseries_file
        except Exception as exc:
            _EXP_LOG.error("recording: could not import DataViewer; %s", exc)
            return

        try:
            bundle = load_timeseries_file(rec_path)
        except FileNotFoundError:
            # Datei nicht gefunden: Name + Datum rot & durchgestrichen markieren.
            name_item = item
            time_item = table.item(row, 1)
            for it in (name_item, time_item):
                if it is None:
                    continue
                font = it.font()
                font.setStrikeOut(True)
                it.setFont(font)
                it.setForeground(QColor("red"))
            _EXP_LOG.warning("recording: file not found when opening: %s", rec_path)
            return
        except Exception as exc:
            _EXP_LOG.error("recording: error loading %s: %s", rec_path, exc)
            return

        # Einfacher Dialog mit einem DataViewerShell, der alle Kanäle der Messung lädt.
        dlg = QDialog(self)
        dlg.setWindowTitle(rec_path.name)
        dlg.setWindowFlags(
            dlg.windowFlags()
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)

        def _resolve_series(name: str):
            return bundle.get_series(name)

        def _resolve_unit(name: str) -> str:
            return bundle.channel_unit(name)

        shell = DataViewerShell(
            _resolve_series,
            dlg,
            enable_walking_axis=False,
            resolve_channel_unit=_resolve_unit,
            mode="static",
            legend_visible_at_start=True,
        )
        shell.viewer.recording_saved.connect(
            lambda path_str: self._register_recording_entry(Path(path_str))
        )
        lay.addWidget(shell, 1)

        for name in bundle.channel_names():
            try:
                shell.viewer.add_channel(name)
            except Exception:
                continue

        dlg.resize(900, 480)
        dlg.show()

    def _on_simulation_timer_tick(self) -> None:
        if self._run_engine is None:
            return
        self._run_engine.step()
        self._refresh_variable_value_labels()
        self._append_live_series_samples()
        self._update_live_dataviewers()

    def _on_dataviewer_canvas_open_widget_command(self, dv: DataViewer) -> None:
        """Canvas double-click: same as CCP ``set <DataViewer>.open_widget true``."""
        h = shlex.quote(dv.hash_name)
        self._run_protocol_lines_as_console([f"set {h}.open_widget true"])

    def _on_kenngroesse_canvas_open_editor(self, el: ElementaryInstance) -> None:
        """Canvas double-click on Kennwert / Kennlinie / Kennfeld: open the parameter viewer."""
        try:
            ref = str(el.get("parameter_ref"))
            rt = self._controller.model.parameter_runtime()
            cal_param_node = rt.resolve_cal_param_node(ref)
            record = rt.repo.get_record(cal_param_node.id)
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Parameter", f"Kein Parameter verknüpft:\n{exc}")
            return
        open_parameter_viewer_for_record(record, self)

    def _close_live_dataviewers_for_sim_mode_exit(self) -> None:
        """Remember open live DataViewer dialogs and close them when leaving experiment mode."""
        if not self._live_dataviewers:
            self._live_dataviewers_reopen_after_sim.clear()
            return
        self._live_dataviewers_reopen_after_sim = sorted(self._live_dataviewers.keys())
        for w in list(self._live_dataviewers.values()):
            try:
                w.close()
            except RuntimeError:
                continue

    def _reopen_live_dataviewers_after_sim_mode_enter(self) -> None:
        """Reopen DataViewer windows that were auto-closed when experiment mode was left."""
        ids = list(self._live_dataviewers_reopen_after_sim)
        self._live_dataviewers_reopen_after_sim.clear()
        for vid in ids:
            if vid in self._live_dataviewers:
                continue
            dv = self._dataviewer_model_instance_for_id(vid)
            if dv is None:
                continue
            self._open_live_dataviewer_dialog(dv)

    def _dataviewer_model_instance_for_id(self, vid: int) -> DataViewer | None:
        for dv in self._controller.model.iter_dataviewers():
            try:
                if int(dv.get("dataviewer_id")) == int(vid):
                    return dv
            except Exception:
                continue
        return None

    def _flush_dataviewer_open_widget_from_model(self) -> None:
        """If core marked ``open_widget`` true, open/focus the dialog and clear the flag (no extra CCP line)."""
        for dv in self._controller.model.iter_dataviewers():
            try:
                if "open_widget" not in dv.attribute_dict:
                    continue
                if not bool(dv.get("open_widget")):
                    continue
                self._open_live_dataviewer_dialog(dv)
                dv.set("open_widget", False)
            except Exception:
                continue

    def _open_live_dataviewer_dialog(self, dv: DataViewer) -> None:
        """Show or focus the Synarius DataViewer window for this model instance."""
        try:
            vid = int(dv.get("dataviewer_id"))
        except Exception:
            return
        if vid in self._live_dataviewers:
            w = self._live_dataviewers[vid]
            w.show()
            w.raise_()
            w.activateWindow()
            return

        # Variablen ermitteln, die an diesen DataViewer gebunden sind.
        variables = self._bound_variables_for_dataviewer_id(vid)
        names = [str(v.name) for v in variables]

        # Dev-only monorepo fallback (installed bundle should import from site-packages).
        prepend_dev_synarius_apps_src()

        try:
            from synarius_dataviewer.widgets.data_viewer import DataViewerShell
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, "Dataviewer", f"Dataviewer widget not available:\n{exc}")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(f"DataViewer {vid}")
        dlg.setWindowFlags(
            dlg.windowFlags()
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(0, 0, 0, 0)

        shell = DataViewerShell(
            self._resolve_live_series,
            dlg,
            enable_walking_axis=True,
            resolve_channel_unit=self._resolve_live_unit,
            mode="dynamic",
            legend_visible_at_start=True,
        )
        self._attach_canvas_runtime_actions_to_dynamic_dataviewer(shell)
        shell.viewer.recording_saved.connect(
            lambda path_str: self._register_recording_entry(Path(path_str))
        )
        layout.addWidget(shell, 1)
        for name in names:
            self._ensure_live_series_seed(name)
            try:
                shell.viewer.add_channel(name)
            except Exception:
                continue

        # Simulation: Walking axis aktivieren und einmal Autoscale, damit Signale sofort sichtbar sind.
        try:
            wa = getattr(shell.viewer, "_walk_action", None)
            if wa is not None:
                wa.setChecked(True)
            scope = getattr(shell.viewer, "_scope", None)
            if scope is not None:
                scope.auto_range()
        except Exception:
            pass

        def _on_closed(_result: int) -> None:
            self._live_dataviewers.pop(vid, None)

        dlg.finished.connect(_on_closed)
        self._live_dataviewers[vid] = dlg
        dlg._dv_var_names = names  # type: ignore[attr-defined]
        dlg._dv_shell = shell  # type: ignore[attr-defined]
        dlg.resize(900, 480)
        dlg.show()

    def _attach_canvas_runtime_actions_to_dynamic_dataviewer(self, shell: QWidget) -> None:
        """Append canvas Record/Play/Stop actions to dynamic DataViewer toolbar."""
        viewer = getattr(shell, "viewer", None)
        if viewer is None:
            return
        add_group = getattr(viewer, "add_toolbar_action_group", None)
        if not callable(add_group):
            return
        if not (
            hasattr(self, "_canvas_record_action")
            and hasattr(self, "_canvas_realtime_action")
            and hasattr(self, "_canvas_play_action")
            and hasattr(self, "_canvas_pause_action")
            and hasattr(self, "_canvas_stop_action")
            and hasattr(self, "_canvas_stop_hold_action")
            and hasattr(self, "_canvas_step_action")
        ):
            return

        dv_step_count_action = self._create_step_count_widget_action(
            viewer, expand_in_toolbar_slot=False
        )
        # Extra spacing before Studio runtime controls, so they appear as an extra group.
        add_group(
            "studio-runtime",
            [
                self._canvas_play_action,
                self._canvas_pause_action,
                self._canvas_stop_hold_action,
                self._canvas_stop_action,
                self._canvas_step_action,
                dv_step_count_action,
            ],
            separator=True,
            spacing_px=12,
        )
        add_group(
            "studio-runtime-record",
            [self._canvas_record_action],
            separator=True,
            spacing_px=8,
        )
        add_group(
            "studio-runtime-realtime",
            [self._canvas_realtime_action],
            separator=True,
            spacing_px=8,
        )

    def _bound_variables_for_dataviewer_id(self, vid: int) -> list[Variable]:
        vars_for_viewer: list[Variable] = []
        for node in self._controller.model.iter_objects():
            if not isinstance(node, Variable):
                continue
            try:
                ids = list(node.get("dataviewer_measure_ids") or [])
            except Exception:
                continue
            if vid in ids:
                vars_for_viewer.append(node)
        return vars_for_viewer

    def _refresh_live_dataviewer_bindings(self) -> dict[int, list[str]]:
        """Refresh variable bindings for open live DataViewer dialogs from current model state."""
        by_vid: dict[int, list[str]] = {}
        for vid, dlg in self._live_dataviewers.items():
            names = [str(v.name) for v in self._bound_variables_for_dataviewer_id(vid)]
            by_vid[vid] = names
            dlg._dv_var_names = names  # type: ignore[attr-defined]
        return by_vid

    def _sync_open_live_dataviewers_channels(self) -> None:
        """Apply current variable bindings immediately to open DataViewer widgets."""
        if not self._live_dataviewers:
            return
        by_vid = self._refresh_live_dataviewer_bindings()
        for vid, dlg in self._live_dataviewers.items():
            desired = set(by_vid.get(vid, []))
            sh = getattr(dlg, "_dv_shell", None)
            viewer = getattr(sh, "viewer", None) if sh is not None else None
            if viewer is None:
                continue
            current: set[str] = set()
            reg = getattr(viewer, "_registry", None)
            if reg is not None and callable(getattr(reg, "names", None)):
                names_obj = reg.names()
                if isinstance(names_obj, dict):
                    current = set(str(k) for k in names_obj.keys())
            # Add newly bound channels immediately.
            for name in sorted(desired - current):
                try:
                    self._ensure_live_series_seed(name)
                    viewer.add_channel(name)
                except Exception:
                    continue
            # Remove channels that are no longer bound.
            for name in sorted(current - desired):
                try:
                    viewer.remove_channel(name)
                except Exception:
                    continue

    def _ensure_live_series_seed(self, name: str) -> None:
        if name in self._live_series_buffers:
            return
        # Start empty so the first displayed sample is the first simulation value, not an artificial 0-seed.
        self._live_series_buffers[name] = ([], [])

    def _append_live_series_samples(
        self,
        *,
        value_by_name: dict[str, float] | None = None,
        t_override: float | None = None,
    ) -> None:
        t = float(t_override) if t_override is not None else (time.perf_counter() - self._live_series_t0)
        # Nur Signale pflegen, die in offenen DataViewern genutzt werden.
        needed: set[str] = set()
        by_vid = self._refresh_live_dataviewer_bindings()
        for names in by_vid.values():
            needed.update(str(n) for n in names)
        if needed:
            if value_by_name is None:
                value_by_name = {}
                for node in self._controller.model.iter_objects():
                    if isinstance(node, Variable) and str(node.name) in needed and isinstance(node.value, (int, float)):
                        value_by_name[str(node.name)] = float(node.value)
            for name in needed:
                self._ensure_live_series_seed(name)
                xs, ys = self._live_series_buffers[name]
                xs.append(t)
                ys.append(value_by_name.get(name, ys[-1] if ys else 0.0))
                if len(xs) > 4000:
                    del xs[:-2000]
                    del ys[:-2000]

        # Optional: vollständige Aufzeichnung aller Variablen für den Experiment-Recorder
        # (unabhängig davon, ob Live-DataViewer geöffnet sind).
        self._append_recording_sample_if_enabled(value_by_name=value_by_name, t_override=t)

    def _append_recording_sample_if_enabled(
        self,
        *,
        value_by_name: dict[str, float] | None = None,
        t_override: float | None = None,
    ) -> None:
        # Only record in experiment mode when the canvas Record action is checked.
        if not (
            self.sim_mode_action.isChecked()
            and hasattr(self, "_canvas_record_action")
            and self._canvas_record_action.isChecked()
        ):
            return
        t = float(t_override) if t_override is not None else (time.perf_counter() - self._record_series_t0)
        _EXP_LOG.debug("recording tick at t=%.6f", t)
        if value_by_name is None:
            value_by_name = {}
            for node in self._controller.model.iter_objects():
                if not isinstance(node, Variable):
                    continue
                name = str(node.name)
                val = node.value
                if isinstance(val, bool):
                    continue
                if not isinstance(val, (int, float, np.integer, np.floating)):
                    continue
                value_by_name[name] = float(val)
        for name, val_f in value_by_name.items():
            buf = self._record_series_buffers.get(name)
            if buf is None:
                xs: list[float] = []
                ys: list[float] = []
                self._record_series_buffers[name] = (xs, ys)
            else:
                xs, ys = buf
            xs.append(t)
            ys.append(float(val_f))

    def _resolve_live_series(self, name: str) -> tuple[np.ndarray, np.ndarray]:
        self._ensure_live_series_seed(name)
        xs, ys = self._live_series_buffers[name]
        return np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)

    def _resolve_live_unit(self, name: str) -> str:
        for node in self._controller.model.iter_objects():
            if isinstance(node, Variable) and str(node.name) == name:
                try:
                    return str(node.unit)
                except Exception:
                    return ""
        return ""

    def _update_live_dataviewers(
        self,
        *,
        value_by_name: dict[str, float] | None = None,
        t_override: float | None = None,
    ) -> None:
        """Während der Simulation neue Samples in offene DataViewer pushen + Achsen im Blick behalten."""
        if not self._live_dataviewers or not self._simulation_running:
            return
        t = float(t_override) if t_override is not None else (time.perf_counter() - self._live_series_t0)
        needed: set[str] = set()
        shells: list[object] = []
        by_vid = self._refresh_live_dataviewer_bindings()
        for vid, w in self._live_dataviewers.items():
            names = by_vid.get(vid, [])
            needed.update(str(n) for n in names)
            sh = getattr(w, "_dv_shell", None)
            if sh is not None:
                shells.append(sh)
        if not needed:
            return

        if value_by_name is None:
            value_by_name = {}
            for node in self._controller.model.iter_objects():
                if isinstance(node, Variable) and str(node.name) in needed and isinstance(node.value, (int, float)):
                    value_by_name[str(node.name)] = float(node.value)

        t_arr = np.asarray([t], dtype=np.float64)
        for sh in shells:
            viewer = getattr(sh, "viewer", None)
            if viewer is None:
                continue
            for name in needed:
                y = value_by_name.get(name)
                if y is None:
                    continue
                try:
                    viewer.append_samples(name, t_arr, np.asarray([y], dtype=np.float64), max_points=200_000)
                except Exception as exc:
                    _EXP_LOG.debug("live-dv append failed for %s: %s", name, exc)
                    continue
        # Keep axis handling fully inside the scope widget's live update path.
        # Periodic explicit auto_range() caused visible jumps/flicker during simulation.
        self._live_viewer_autorange_tick += 1

    @staticmethod
    def _format_orthogonal_bends_list(bends: list[float]) -> str:
        """Format as Python list literal so ``parse_value`` always returns a list, not a bare number."""
        parts: list[str] = []
        for v in bends:
            s = f"{float(v):.12g}"
            if "." in s:
                s = s.rstrip("0").rstrip(".")
            parts.append(s)
        return "[" + ",".join(parts) + "]"

    def _apply_connector_orthogonal_bends(self, connector: Connector, bends: list[float]) -> bool:
        """Persist connector routing via Controller Command Protocol (loggable ``set``)."""
        token = connector.hash_name
        lst = self._format_orthogonal_bends_list(bends)
        cmd = f"set {token}.orthogonal_bends {lst}"
        prompt = str(self._controller.current.get("prompt_path"))
        self.console.insert_log_before_current_prompt(f"{prompt}> {cmd}", DEFAULT_PROMPT_COLOR)
        try:
            result = self._controller_execute_logged(cmd, source="diagram")
        except CommandError as exc:
            self.console.insert_log_before_current_prompt(f"error: {exc}", ERROR_COLOR)
            return False
        except Exception:
            self.console.insert_log_before_current_prompt(
                "error: unexpected exception (see log file)", ERROR_COLOR
            )
            return False
        if result is not None and result != "":
            self.console.insert_log_before_current_prompt(result, self._get_output_color())
        return True

    @staticmethod
    def _graphics_item_model_id(item: QGraphicsItem) -> UUID | None:
        if isinstance(item, VariableBlockItem):
            return item.variable().id
        if isinstance(item, OperatorBlockItem):
            return item.operator().id
        if isinstance(item, FmuBlockItem):
            return item.elementary().id
        if isinstance(item, DataViewerBlockItem):
            return item.dataviewer().id
        if isinstance(item, ConnectorEdgeItem):
            c = item.domain_connector
            return c.id if c is not None else None
        return None

    def _apply_controller_selection_to_scene(self) -> None:
        """Highlight scene items that match ``controller.selection`` (e.g. after console ``select``)."""
        desired: set[UUID] = {obj.id for obj in self._controller.selection if obj.id is not None}
        scene = self._diagram_scene
        scene.clearSelection()
        for it in self._diagram_item_refs:
            if it.parentItem() is not None:
                continue
            oid = self._graphics_item_model_id(it)
            if oid is None:
                continue
            it.setSelected(oid in desired)

    @staticmethod
    def _console_command_needs_diagram_rebuild(line: str) -> bool:
        s = line.strip().lower()
        if s.startswith("load ") or s.startswith("new ") or s.startswith("del "):
            return True
        if s.startswith("undo") or s.startswith("redo") or s.startswith("mv "):
            return True
        if s.startswith("fmu bind") or s.startswith("fmu reload") or s.startswith("sync "):
            return True
        return False

    def _execute_controller_line_for_ui(self, cmd: str) -> None:
        """Run a protocol line from toolbar/menu: log like the console and refresh views."""
        prompt = str(self._controller.current.get("prompt_path"))
        self.console.insert_log_before_current_prompt(f"{prompt}> {cmd}", DEFAULT_PROMPT_COLOR)
        try:
            result = self._controller_execute_logged(cmd, source="ui")
        except CommandError as exc:
            self.console.insert_log_before_current_prompt(f"error: {exc}", ERROR_COLOR)
            self._sync_simulation_mode_from_model()
            return
        except Exception:
            self.console.insert_log_before_current_prompt("error: unexpected exception (see log file)", ERROR_COLOR)
            self._sync_simulation_mode_from_model()
            return
        if result is not None and result != "":
            self.console.insert_log_before_current_prompt(result, self._get_output_color())

    def _sync_diagram_view_from_core_after_console(self, command_line: str) -> None:
        """Keep canvas aligned with core model and controller selection after a console command."""
        if self._console_command_needs_diagram_rebuild(command_line):
            self._refresh_diagram()
            self._flush_compile_diagnostics_to_build_log()
        elif command_line.strip().lower().startswith("set "):
            self._refresh_variable_value_labels()
        # Keep open DataViewer dialogs in sync with changed measure bindings immediately.
        self._sync_open_live_dataviewers_channels()
        self._flush_dataviewer_open_widget_from_model()
        self._sync_simulation_mode_from_model()
        self._apply_controller_selection_to_scene()
        self._variables_panel.refresh()
        self._parameters_panel.refresh()
        self._schedule_experiment_codegen_refresh()

    def _on_connector_route_command(self, cmd: str) -> None:
        """Run connector route built interactively on the canvas (same path as typing in the console)."""
        prompt = str(self._controller.current.get("prompt_path"))
        self.console.insert_log_before_current_prompt(f"{prompt}> {cmd}", DEFAULT_PROMPT_COLOR)
        try:
            result = self._controller_execute_logged(cmd, source="canvas")
        except CommandError as exc:
            self.console.insert_log_before_current_prompt(f"error: {exc}", ERROR_COLOR)
            return
        except Exception:
            self.console.insert_log_before_current_prompt("error: unexpected exception (see log file)", ERROR_COLOR)
            return
        if result is not None and result != "":
            self.console.insert_log_before_current_prompt(result, self._get_output_color())

    def _on_placement_canvas_command(self, cmd: str) -> None:
        self._uncheck_diagram_palette_actions()
        self._on_connector_route_command(cmd)

    def _uncheck_diagram_palette_actions(self) -> None:
        grp = getattr(self, "_diagram_palette_group", None)
        if grp is None:
            return
        grp.blockSignals(True)
        for a in grp.actions():
            a.setChecked(False)
        grp.blockSignals(False)

    def _on_diagram_palette_toggled(self, checked: bool) -> None:
        action = self.sender()
        if not isinstance(action, QAction):
            return
        mode = action.property("placement_mode")
        if checked:
            self._dataflow_view.cancel_interactive_route()
            pt = self._dataflow_view.placement_tool()
            if pt is not None and mode is not None:
                pt.activate(str(mode))
        else:
            QTimer.singleShot(0, self._deferred_stop_placement_if_palette_cleared)

    def _deferred_stop_placement_if_palette_cleared(self) -> None:
        grp = getattr(self, "_diagram_palette_group", None)
        if grp is not None and any(a.isChecked() for a in grp.actions()):
            return
        pt = self._dataflow_view.placement_tool()
        if pt is not None and pt.active():
            pt.cancel(emit_cancelled=False)

    @staticmethod
    def _controller_select_tokens_from_items(items: list[QGraphicsItem]) -> list[str]:
        tokens: list[str] = []
        for it in items:
            if isinstance(it, (VariableBlockItem, OperatorBlockItem, DataViewerBlockItem, FmuBlockItem)):
                tokens.append(it.controller_select_token())
            elif isinstance(it, ConnectorEdgeItem):
                t = it.controller_select_token()
                if t is not None:
                    tokens.append(t)
        return sorted(set(tokens))

    def _sync_scene_selection_to_controller(self) -> None:
        selected = self._diagram_scene.selectedItems()
        tokens = self._controller_select_tokens_from_items(selected)
        if tokens:
            cmd = "select " + " ".join(shlex.quote(t) for t in tokens)
        else:
            cmd = "select"
        prompt = str(self._controller.current.get("prompt_path"))
        self.console.insert_log_before_current_prompt(f"{prompt}> {cmd}", DEFAULT_PROMPT_COLOR)
        try:
            result = self._controller_execute_logged(cmd, source="selection")
        except CommandError as exc:
            self.console.insert_log_before_current_prompt(f"error: {exc}", ERROR_COLOR)
            return
        except Exception:
            self.console.insert_log_before_current_prompt(
                "error: unexpected exception (see log file)", ERROR_COLOR
            )
            return
        if result is not None and result != "":
            self.console.insert_log_before_current_prompt(result, self._get_output_color())

    def _delete_selected_via_controller(self) -> None:
        selected = self._diagram_scene.selectedItems()
        tokens = self._controller_select_tokens_from_items(selected)
        if not tokens:
            return
        prompt = str(self._controller.current.get("prompt_path"))
        select_cmd = "select " + " ".join(shlex.quote(t) for t in tokens)
        del_cmd = "del @selected"
        self.console.insert_log_before_current_prompt(f"{prompt}> {select_cmd}", DEFAULT_PROMPT_COLOR)
        try:
            sel_result = self._controller_execute_logged(select_cmd, source="delete")
        except CommandError as exc:
            self.console.insert_log_before_current_prompt(f"error: {exc}", ERROR_COLOR)
            return
        except Exception:
            self.console.insert_log_before_current_prompt(
                "error: unexpected exception (see log file)", ERROR_COLOR
            )
            return
        if sel_result is not None and sel_result != "":
            self.console.insert_log_before_current_prompt(sel_result, self._get_output_color())

        self.console.insert_log_before_current_prompt(f"{prompt}> {del_cmd}", DEFAULT_PROMPT_COLOR)
        try:
            result = self._controller_execute_logged(del_cmd, source="delete")
        except CommandError as exc:
            self.console.insert_log_before_current_prompt(f"error: {exc}", ERROR_COLOR)
            return
        except Exception:
            self.console.insert_log_before_current_prompt(
                "error: unexpected exception (see log file)", ERROR_COLOR
            )
            return
        if result is not None and result != "":
            self.console.insert_log_before_current_prompt(result, self._get_output_color())
        try:
            self._controller_execute_logged("select", source="delete")
        except Exception:
            pass

    def _sync_diagram_move_to_controller(self, dx_scene: float, dy_scene: float) -> None:
        """Apply a uniform scene delta to the core via ``set -p @selection position`` (after selection sync)."""
        dx_m = dx_scene / UI_SCALE
        dy_m = dy_scene / UI_SCALE
        cmd = f"set -p @selection position {dx_m:.12g} {dy_m:.12g}"
        prompt = str(self._controller.current.get("prompt_path"))
        self.console.insert_log_before_current_prompt(f"{prompt}> {cmd}", DEFAULT_PROMPT_COLOR)
        try:
            result = self._controller_execute_logged(cmd, source="diagram_move")
        except CommandError as exc:
            self.console.insert_log_before_current_prompt(f"error: {exc}", ERROR_COLOR)
            return
        except Exception:
            self.console.insert_log_before_current_prompt(
                "error: unexpected exception (see log file)", ERROR_COLOR
            )
            return
        if result is not None and result != "":
            self.console.insert_log_before_current_prompt(result, self._get_output_color())

    def _panel_label(self, text: str) -> QWidget:
        widget = QWidget(self)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        lab = QLabel(text, widget)
        lab.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        lab.setWordWrap(True)
        lab.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout.addWidget(lab, 0, Qt.AlignmentFlag.AlignTop)
        layout.addStretch(1)
        return widget

    def _build_experiment_panel(self) -> QWidget:
        """Right-side Experiment panel with a recordings table (similar chrome to Variables panel)."""
        from .theme import (
            LIBRARY_HEADER_BACKGROUND,
            LIBRARY_HEADER_SEPARATOR,
            LIBRARY_HEADER_TEXT,
            RESOURCES_PANEL_ALTERNATE_ROW,
            RESOURCES_PANEL_BACKGROUND,
        )

        widget = QWidget(self)
        widget.setObjectName("syn_experiment_panel_root")
        widget.setStyleSheet(qss_widget_id_background("syn_experiment_panel_root", RESOURCES_PANEL_BACKGROUND))
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        table = _RecordingsTable(widget)
        table.setHorizontalHeaderLabels(["File name", "Saved at"])
        header = table.horizontalHeader()
        header.setVisible(True)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.verticalHeader().setDefaultSectionSize(20)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table.setStyleSheet(
            f"QTableWidget {{ background-color: {RESOURCES_PANEL_BACKGROUND}; "
            f"alternate-background-color: {RESOURCES_PANEL_ALTERNATE_ROW}; border: none; font-size: 12px; }}"
            f"QHeaderView::section {{ background-color: {LIBRARY_HEADER_BACKGROUND}; "
            f"color: {LIBRARY_HEADER_TEXT}; border: none; "
            f"border-bottom: 1px solid {LIBRARY_HEADER_SEPARATOR}; "
            "font-weight: 600; padding: 2px 6px; text-align: left; }}"
            "QTableWidget::item { color: #000000; padding: 0px 4px; text-align: left; }"
            f"QTableWidget::item:selected {{ background-color: {SELECTION_HIGHLIGHT}; color: {SELECTION_HIGHLIGHT_TEXT}; }}"
        )
        table.cellDoubleClicked.connect(self._on_recording_cell_double_clicked)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(self._on_recordings_context_menu)

        layout.addWidget(table, 1)

        self._recordings_table = table
        return widget

    def _build_signals_panel(self) -> QWidget:
        from .theme import (
            LIBRARY_HEADER_BACKGROUND,
            LIBRARY_HEADER_SEPARATOR,
            LIBRARY_HEADER_TEXT,
            RESOURCES_PANEL_ALTERNATE_ROW,
            RESOURCES_PANEL_BACKGROUND,
        )

        widget = QWidget(self)
        widget.setObjectName("syn_signals_panel_root")
        widget.setStyleSheet(qss_widget_id_background("syn_signals_panel_root", RESOURCES_PANEL_BACKGROUND))
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        action_bar = QToolBar(widget)
        action_bar.setMovable(False)
        # Dunkler Hintergrund wie der Tabellen-Header; kleine, invertierte Symbole.
        action_bar.setIconSize(QSize(16, 16))
        action_bar.setStyleSheet(studio_toolbar_stylesheet(background_color=LIBRARY_HEADER_BACKGROUND))

        act_load = QAction("Load Signal File", self)
        act_load.triggered.connect(self._on_load_signal_file_clicked)
        act_load.setIcon(self.open_action.icon())
        act_map = QAction("map by names", self)
        act_map.triggered.connect(self._on_map_signals_by_names_clicked)
        map_icon = self._icons_dir / "mapping-symbolic.svg"
        if map_icon.exists():
            # invertiert/hell auf dunklem Hintergrund
            act_map.setIcon(icon_from_tinted_svg_file(map_icon, QColor("#ffffff")))
        act_unmap = QAction("delete mapping", self)
        act_unmap.triggered.connect(self._on_delete_mapping_clicked)
        del_icon = self._icons_dir / "mapping-del-symbolic.svg"
        if del_icon.exists():
            act_unmap.setIcon(icon_from_tinted_svg_file(del_icon, QColor("#ffffff")))
        action_bar.addAction(act_load)
        action_bar.addAction(act_map)
        action_bar.addAction(act_unmap)

        table = _SignalsMappingTable(self._on_signals_row_drop, widget)
        table.setHorizontalHeaderLabels(["Signal", "", "Variable"])
        table.setDragEnabled(True)
        table.setDragDropMode(QTableWidget.DragDropMode.DragOnly)
        table.setDefaultDropAction(Qt.DropAction.IgnoreAction)
        hdr = table.horizontalHeader()
        hdr.setVisible(True)
        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.verticalHeader().setDefaultSectionSize(20)
        hdr.setFixedHeight(34)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table.setStyleSheet(
            f"QTableWidget {{ background-color: {RESOURCES_PANEL_BACKGROUND}; "
            f"alternate-background-color: {RESOURCES_PANEL_ALTERNATE_ROW}; border: none; font-size: 12px; }}"
            f"QHeaderView::section {{ background-color: {LIBRARY_HEADER_BACKGROUND}; color: {LIBRARY_HEADER_TEXT}; "
            f"border: none; border-bottom: 1px solid {LIBRARY_HEADER_SEPARATOR}; font-weight: 600; "
            "padding: 2px 6px; text-align: left; }}"
            "QTableWidget::item { color: #000000; padding: 0px 4px; text-align: left; }"
            f"QTableWidget::item:selected {{ background-color: {SELECTION_HIGHLIGHT}; color: {SELECTION_HIGHLIGHT_TEXT}; }}"
        )

        layout.addWidget(action_bar, 0)
        layout.addWidget(table, 1)
        self._signals_table = table
        self._refresh_signals_table()
        return widget

    def _refresh_signals_table(self) -> None:
        table = self._signals_table
        if table is None:
            return
        model = self._controller.model
        stimuli = model.get_root_by_type(ModelElementType.MODEL_STIMULI)
        # Reverse map: signal -> first mapped variable name from SQL registry rows.
        mapped_var_by_signal: dict[str, str] = {}
        for var_name, _count, sig_name in model.variable_registry.rows_ordered_by_name():
            sig = str(sig_name).strip()
            if not sig or sig == "None":
                continue
            if sig not in mapped_var_by_signal:
                mapped_var_by_signal[sig] = str(var_name)
        rows: list[tuple[str, int, str]] = []
        if isinstance(stimuli, SignalContainer):
            for child in stimuli.children:
                if not isinstance(child, Signal):
                    continue
                xs, _ys = stimuli.get_series(child)
                mapped_var = mapped_var_by_signal.get(child.name, "")
                rows.append((child.name, len(xs), mapped_var))
        rows.sort(key=lambda x: x[0].lower())
        table.setRowCount(len(rows))
        _EXP_LOG.info(
            "signals: refresh table rows=%d mapped_signals=%d",
            len(rows),
            len(mapped_var_by_signal),
        )
        for i, (name, samples, mapped_var) in enumerate(rows):
            n = QTableWidgetItem(name)
            arrow = QTableWidgetItem("\u25b6" if mapped_var else "")
            v = QTableWidgetItem(mapped_var)
            n.setTextAlignment(int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter))
            arrow.setTextAlignment(int(Qt.AlignmentFlag.AlignCenter))
            v.setTextAlignment(int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter))
            table.setItem(i, 0, n)
            table.setItem(i, 1, arrow)
            table.setItem(i, 2, v)

    def _on_load_signal_file_clicked(self) -> None:
        path_str, _chosen = QFileDialog.getOpenFileName(
            self,
            "Load signal file",
            str(open_syn_dialog_start_dir()),
            "Signal files (*.mf4 *.mdf *.dat *.csv *.parquet *.pq)",
        )
        if not path_str:
            return
        path = Path(path_str)
        try:
            bundle = load_timeseries_file(path)
            stimuli = self._controller.model.get_root_by_type(ModelElementType.MODEL_STIMULI)
            if not isinstance(stimuli, SignalContainer):
                raise RuntimeError("stimuli container not available")
            # Replace existing stimuli signals with the loaded file channels.
            stimuli.clear_all_series()
            for child in list(stimuli.children):
                if child.id is not None:
                    self._controller.model.delete(stimuli, child.id)
            for sig_name in bundle.channel_names():
                sig = Signal(name=str(sig_name))
                self._controller.model.attach(sig, parent=stimuli, reserve_existing=False, remap_ids=False)
                tx, ty = bundle.get_series(sig_name)
                stimuli.set_series(sig, tx, ty)
            if "source_file" not in stimuli.attribute_dict:
                dict.__setitem__(stimuli.attribute_dict, "source_file", (str(path), None, None, True, True))
            else:
                stimuli.set("source_file", str(path))
            _EXP_LOG.info(
                "signals: loaded %d channels from %s into stimuli",
                len(bundle.channel_names()),
                path,
            )
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, "Signals", f"Could not load signal file:\n{exc}")
            return
        self._refresh_signals_table()
        self._variables_panel.refresh()

    def _on_map_signals_by_names_clicked(self) -> None:
        model = self._controller.model
        stimuli = model.get_root_by_type(ModelElementType.MODEL_STIMULI)
        db = model.get_variable_database()
        if not isinstance(stimuli, SignalContainer) or db is None:
            return
        signals = {child.name for child in stimuli.children if isinstance(child, Signal)}
        mapped = 0
        for child in db.children:
            if not hasattr(child, "name"):
                continue
            var_name = str(child.name)
            if var_name not in signals:
                continue
            target = f"@main/variables_db/{child.hash_name}.mapped_signal"
            cmd = f"set {shlex.quote(target)} {shlex.quote(var_name)}"
            try:
                self._controller_execute_logged(cmd, source="signals_map")
                mapped += 1
            except Exception:
                continue
        self._variables_panel.refresh()
        self._refresh_signals_table()
        _EXP_LOG.info("signals: map-by-names mapped=%d", mapped)
        self.statusBar().showMessage(f"Mapped {mapped} variable(s) by name.")

    def _on_delete_mapping_clicked(self) -> None:
        model = self._controller.model
        db = model.get_variable_database()
        if db is None:
            return
        table = self._signals_table
        if table is not None and table.currentRow() >= 0:
            # Nur Mapping für die selektierte Signalzeile löschen.
            row = table.currentRow()
            sig_item = table.item(row, 0)
            if sig_item is not None:
                sig_name = sig_item.text().strip()
                if sig_name:
                    # Bestimme alle Variablennamen, die aktuell auf dieses Signal gemappt sind.
                    updated = 0
                    for child in db.children:
                        var_name = str(child.name)
                        if model.variable_mapped_signal(var_name) != sig_name:
                            continue
                        target = f"@main/variables_db/{child.hash_name}.mapped_signal"
                        cmd = f"set {shlex.quote(target)} None"
                        try:
                            self._controller_execute_logged(cmd, source="signals_unmap_one")
                            updated += 1
                        except Exception:
                            continue
                    self._variables_panel.refresh()
                    self.statusBar().showMessage(f"Removed mapping for {updated} variable(s) for signal {sig_name}.")
                    self._refresh_signals_table()
                    _EXP_LOG.info("signals: unmap selected signal=%s removed=%d", sig_name, updated)
                    return
        # Keine Zeile selektiert -> gesamtes Mapping löschen (mit Nachfrage).
        from PySide6.QtWidgets import QMessageBox

        reply = QMessageBox.question(
            self,
            "Delete mapping",
            "Delete all signal-to-variable mappings?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        updated = 0
        for child in db.children:
            target = f"@main/variables_db/{child.hash_name}.mapped_signal"
            cmd = f"set {shlex.quote(target)} None"
            try:
                self._controller_execute_logged(cmd, source="signals_unmap_all")
                updated += 1
            except Exception:
                continue
        self._variables_panel.refresh()
        self._refresh_signals_table()
        _EXP_LOG.info("signals: unmap all removed=%d", updated)
        self.statusBar().showMessage(f"Removed mapping for {updated} variable(s).")

    def _on_canvas_signal_mapping_drop(self, signal_name: str, variable_name: str) -> None:
        # Drag from Signals table to a Variable block on canvas.
        self._on_signals_row_drop(signal_name, variable_name)

    def _on_signals_row_drop(self, signal_name: str, variable_name: str) -> None:
        model = self._controller.model
        db = model.get_variable_database()
        if db is None:
            return
        for child in db.children:
            var_name = str(child.name)
            if var_name != variable_name:
                continue
            target = f"@main/variables_db/{child.hash_name}.mapped_signal"
            cmd = f"set {shlex.quote(target)} {shlex.quote(signal_name)}"
            try:
                self._controller_execute_logged(cmd, source="signals_drop_map")
            except Exception:
                return
            break
        self._variables_panel.refresh()
        self._refresh_signals_table()

    def _build_console_panel(self) -> QWidget:
        widget = QWidget(self)
        widget.setStyleSheet(f"background-color: {CONSOLE_CHROME_BACKGROUND};")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.console = _TerminalConsole(self._on_console_enter, self._history_prev, self._history_next, widget)
        self.console.setStyleSheet(
            f"QTextEdit {{ background-color: {CONSOLE_CHROME_BACKGROUND}; color: {CONSOLE_TAB_TEXT}; "
            f"font-family: Consolas, 'Courier New', monospace; "
            f"selection-background-color: {SELECTION_HIGHLIGHT}; selection-color: {SELECTION_HIGHLIGHT_TEXT}; }}\n"
            + SCROLLBAR_STYLE_QSS
        )
        layout.addWidget(self.console, 1)

        self._append_console_line("synarius-core minimal CLI", self._get_output_color())
        self._append_console_line("Type 'help' for commands, 'exit' to quit.", self._get_output_color())
        self._show_prompt()
        return widget

    def _plain_log_edit(self, parent: QWidget) -> QPlainTextEdit:
        ed = QPlainTextEdit(parent)
        ed.setReadOnly(True)
        ed.setMaximumBlockCount(12_000)
        ed.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        ed.setStyleSheet(
            f"QPlainTextEdit {{ background-color: {CONSOLE_CHROME_BACKGROUND}; color: {CONSOLE_TAB_TEXT}; "
            f"font-family: Consolas, 'Courier New', monospace; font-size: 11px; "
            f"selection-background-color: {SELECTION_HIGHLIGHT}; selection-color: {SELECTION_HIGHLIGHT_TEXT}; }}\n"
            + SCROLLBAR_STYLE_QSS
        )
        return ed

    def _build_general_log_panel(self) -> QWidget:
        widget = QWidget(self)
        widget.setStyleSheet(f"background-color: {CONSOLE_CHROME_BACKGROUND};")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 4, 8, 8)
        layout.setSpacing(4)
        path = main_log_path()
        path_txt = str(path) if path else "(not configured)"
        info = QLabel(
            f"Allgemeines Logging (alle Meldungen; auch Datei: {path_txt}).",
            widget,
        )
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {CONSOLE_TAB_TEXT}; font-size: 11px;")
        layout.addWidget(info)
        self._general_log_view = self._plain_log_edit(widget)
        layout.addWidget(self._general_log_view, 1)
        return widget

    def _build_build_log_panel(self) -> QWidget:
        widget = QWidget(self)
        widget.setStyleSheet(f"background-color: {CONSOLE_CHROME_BACKGROUND};")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 4, 8, 8)
        layout.setSpacing(4)
        lab = QLabel(
            "Build / Compile / Modell und Protokoll-Fehler (wird vor jedem Diagramm-Compile geleert).",
            widget,
        )
        lab.setWordWrap(True)
        lab.setStyleSheet(f"color: {CONSOLE_TAB_TEXT}; font-size: 11px;")
        layout.addWidget(lab)
        self._build_log_view = self._plain_log_edit(widget)
        layout.addWidget(self._build_log_view, 1)
        return widget

    def _build_experiment_log_panel(self) -> QWidget:
        widget = QWidget(self)
        widget.setStyleSheet(f"background-color: {CONSOLE_CHROME_BACKGROUND};")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 4, 8, 8)
        layout.setSpacing(4)
        info = QLabel(
            "Experiment / Simulation / Messungen / Aufzeichnung (wird vor jedem Simulationsstart geleert).",
            widget,
        )
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {CONSOLE_TAB_TEXT}; font-size: 11px;")
        layout.addWidget(info)
        self._experiment_log_view = self._plain_log_edit(widget)
        layout.addWidget(self._experiment_log_view, 1)
        return widget

    def _build_fmu_debug_panel(self) -> QWidget:
        widget = QWidget(self)
        widget.setStyleSheet(f"background-color: {CONSOLE_CHROME_BACKGROUND};")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 4, 8, 8)
        layout.setSpacing(4)
        hint = QLabel(
            "Letzte Simulations-Tick: skalarer Workspace-Wert pro FMU-Block (ein Slot pro Knoten).",
            widget,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {CONSOLE_TAB_TEXT}; font-size: 11px;")
        layout.addWidget(hint)
        self._fmu_debug_table = QTableWidget(0, 2, widget)
        self._fmu_debug_table.setHorizontalHeaderLabels(["FMU-Block", "Workspace"])
        self._fmu_debug_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._fmu_debug_table.setStyleSheet(
            f"QTableWidget {{ background-color: {CONSOLE_CHROME_BACKGROUND}; color: {CONSOLE_TAB_TEXT}; "
            f"font-size: 11px; gridline-color: #555; }}"
        )
        layout.addWidget(self._fmu_debug_table, 1)
        return widget

    def _on_import_fmu(self) -> None:
        dlg = FmuImportDialog(self, default_model_xy=(120.0, 80.0))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            cmd = dlg.protocol_command()
        except ValueError as exc:
            QMessageBox.warning(self, "FMU importieren", str(exc))
            return
        self._execute_controller_line_for_ui(cmd)

    def _append_general_log_view(self, text: str) -> None:
        view = getattr(self, "_general_log_view", None)
        if view is None:
            return
        view.appendPlainText(text)
        bar = view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _append_build_log_view(self, text: str) -> None:
        view = getattr(self, "_build_log_view", None)
        if view is None:
            return
        view.appendPlainText(text)
        bar = view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _append_experiment_log_view(self, text: str) -> None:
        view = getattr(self, "_experiment_log_view", None)
        if view is None:
            return
        view.appendPlainText(text)
        bar = view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _clear_build_log_view(self) -> None:
        view = getattr(self, "_build_log_view", None)
        if view is not None:
            view.clear()

    def _clear_experiment_log_view(self) -> None:
        view = getattr(self, "_experiment_log_view", None)
        if view is not None:
            view.clear()

    def _flush_compile_diagnostics_to_build_log(self) -> None:
        self._clear_build_log_view()
        ctx = SimulationContext(model=self._controller.model)
        DataflowCompilePass().run(ctx)
        ts = time.strftime("%H:%M:%S")
        ok = ctx.artifacts.get("dataflow") is not None
        blog = logging.getLogger("synarius_studio.build")
        blog.info("[%s] compile: dataflow=%s", ts, "ok" if ok else "missing")
        for line in ctx.diagnostics:
            blog.info("  %s", line)

    @staticmethod
    def _truncate_for_log(text: str, max_len: int = 4000) -> str:
        if len(text) <= max_len:
            return text
        return text[:max_len] + "…"

    def _ensure_legacy_dataviewer_open_widget_attrs(self) -> int:
        """Pinned synarius-core (e.g. git install in release) may lack ``open_widget`` on DataViewer; CCP expects it."""
        model = self._controller.model
        n_patched = 0
        for dv in model.iter_dataviewers():
            if "open_widget" in dv.attribute_dict:
                continue
            dict.__setitem__(dv.attribute_dict, "open_widget", (False, None, None, True, True))
            n_patched += 1
        return n_patched

    def _controller_execute_logged(self, cmd: str, *, source: str) -> str | None:
        """Single entry for ``SynariusController.execute``: logs every command and **always** syncs
        canvas/panels afterwards.

        The sync is guaranteed for both the success path and clean ``CommandError`` failures
        (where the model is unchanged).  It is intentionally skipped for unexpected exceptions
        because the model may be in an indeterminate state in that case.

        All callers therefore receive a consistent UI for free — no call site needs to call
        ``_sync_diagram_view_from_core_after_console`` manually.
        """
        line = cmd.strip()
        self._ensure_legacy_dataviewer_open_widget_attrs()
        _CMD_LOG.info("command [%s]: %s", source, line)
        try:
            result = self._controller.execute(cmd)
        except CommandError as exc:
            _CMD_LOG.error("command [%s] failed: %s | %s", source, line, exc)
            # Sync even on clean failure: model is unchanged but panels must stay consistent
            # (e.g. selection state, parameter list).
            self._sync_diagram_view_from_core_after_console(line)
            raise
        except Exception:
            _CMD_LOG.exception("command [%s] raised: %s", source, line)
            raise  # do NOT sync — model may be in an indeterminate state
        # ``load`` replaces ``self._controller.model`` inside ``execute``; patch again for script lines / next UI cmd.
        first_tok = line.split(None, 1)[0].lower() if line else ""
        if first_tok == "load":
            self._ensure_legacy_dataviewer_open_widget_attrs()
        if result is not None and str(result) != "":
            _CMD_LOG.info(
                "command [%s] ok: %s → %s",
                source,
                line,
                MainWindow._truncate_for_log(str(result)),
            )
        else:
            _CMD_LOG.info("command [%s] ok: %s", source, line)
        self._sync_diagram_view_from_core_after_console(line)
        return result


    def _get_output_color(self) -> str:
        try:
            value = self._controller.model.root.get("output_color")
            if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                return value
        except Exception:
            pass
        return self._default_output_color

    def _show_prompt(self) -> None:
        prompt = str(self._controller.current.get("prompt_path"))
        self.console.show_prompt(f"{prompt}> ", DEFAULT_PROMPT_COLOR)

    def _append_console_line(self, text: str, color: str) -> None:
        self.console.append_output(text, color)

    def _request_ok_to_discard_or_save_before_model_replace(self) -> bool:
        """
        If the controller undo stack is non-empty, ask whether to save the current diagram first.

        Returns False when the user cancels (load/open shall not proceed). ``load`` already replaces
        the model and clears undo when executed; this gate only decides whether to run ``load``.
        """
        if not self._controller.has_undoable_changes():
            return True
        mb = QMessageBox(self)
        mb.setIcon(QMessageBox.Icon.Question)
        mb.setWindowTitle("Modell ersetzen")
        mb.setText(
            "Das aktuelle Modell wurde geändert (Rückgängig-Verlauf ist nicht leer).\n"
            "Möchten Sie es vor dem Laden speichern?"
        )
        save_btn = mb.addButton("Speichern…", QMessageBox.ButtonRole.AcceptRole)
        mb.addButton("Verwerfen", QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = mb.addButton("Abbrechen", QMessageBox.ButtonRole.RejectRole)
        mb.setDefaultButton(cancel_btn)
        mb.exec()
        clicked = mb.clickedButton()
        if clicked == cancel_btn or clicked is None:
            return False
        if clicked == save_btn:
            return self._save_diagram_syn_interactive()
        return True

    def _save_diagram_syn_interactive(self) -> bool:
        """Pick a ``.syn`` path, export the root-level diagram, clear undo on success."""
        file_name, _ = QFileDialog.getSaveFileName(
            self,
            "Synarius-Projekt speichern",
            str(open_syn_dialog_start_dir()),
            "Synarius Project (*.syn);;All Files (*)",
        )
        if not file_name:
            return False
        out = Path(file_name)
        if not out.suffix:
            out = out.with_suffix(".syn")
        try:
            text = export_root_diagram_syn_text(self._controller.model)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Speichern", f"Datei konnte nicht geschrieben werden:\n{exc}")
            return False
        except ValueError as exc:
            QMessageBox.warning(self, "Speichern", str(exc))
            return False
        except Exception as exc:
            QMessageBox.warning(self, "Speichern", f"Unerwarteter Fehler:\n{exc}")
            return False
        self._controller.clear_undo_history()
        self.statusBar().showMessage(f"Gespeichert: {out}", 5000)
        return True

    def _on_console_enter(self, line: str) -> None:
        stripped = line.strip()
        if stripped == "":
            self._show_prompt()
            return
        self._history.push(line)

        if stripped in {"exit", "quit"}:
            _CMD_LOG.info("command [repl]: %s", stripped)
            self.close()
            return
        if stripped == "help":
            _CMD_LOG.info("command [repl]: help")
            self._append_console_line("Built-in commands:", self._get_output_color())
            self._append_console_line("  help                    Show this help", self._get_output_color())
            self._append_console_line("  exit | quit             Exit CLI", self._get_output_color())
            self._append_console_line("  load <file.syn>         Load command-stack script", self._get_output_color())
            self._append_console_line("", self._get_output_color())
            self._append_console_line("Protocol commands:", self._get_output_color())
            self._append_console_line(
                "  ls, lsattr [-l], cd <path>, new ..., select ..., set ... (set -p @selection …), get ..., del ... | del @selected",
                self._get_output_color(),
            )
            self._append_console_line(
                "  set @main.simulation_mode true|false   Toggle simulation canvas (read-only, stim menu)",
                self._get_output_color(),
            )
            self._show_prompt()
            return

        try:
            tokens = shlex.split(stripped)
        except ValueError as exc:
            self._append_console_line(f"error: {exc}", ERROR_COLOR)
            self._show_prompt()
            return

        if len(tokens) >= 2 and tokens[0].lower() == "load":
            if not self._request_ok_to_discard_or_save_before_model_replace():
                self._append_console_line("load abgebrochen (Modell unverändert).", ERROR_COLOR)
                self._show_prompt()
                return

        try:
            result = self._controller_execute_logged(stripped, source="repl")
        except CommandError as exc:
            self._append_console_line(f"error: {exc}", ERROR_COLOR)
            self._sync_simulation_mode_from_model()
            self._show_prompt()
            return
        except Exception:
            self._append_console_line("error: unexpected exception (see log file)", ERROR_COLOR)
            self._sync_simulation_mode_from_model()
            self._show_prompt()
            return

        if result is not None and result != "":
            self._append_console_line(result, self._get_output_color())
        self._show_prompt()

    def _history_prev(self) -> None:
        prev_line = self._history.prev()
        if prev_line is not None:
            self.console.replace_current_input(prev_line)

    def _history_next(self) -> None:
        self.console.replace_current_input(self._history.next())

    def _open_project(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Open Synarius Project",
            str(open_syn_dialog_start_dir()),
            "Synarius Project (*.syn *.json *.yaml);;All Files (*)",
        )
        if not file_name:
            self.statusBar().showMessage("Open canceled")
            return
        if not self._request_ok_to_discard_or_save_before_model_replace():
            self.statusBar().showMessage("Open canceled")
            return
        self.statusBar().showMessage(f"Opened: {file_name}")
        prompt = str(self._controller.current.get("prompt_path"))
        load_cmd = f'load "{file_name}"'
        self._append_console_line(f"{prompt}> {load_cmd}", DEFAULT_PROMPT_COLOR)
        try:
            result = self._controller_execute_logged(load_cmd, source="file")
            if result:
                self._append_console_line(result, self._get_output_color())
        except CommandError as exc:
            self._append_console_line(f"error: {exc}", ERROR_COLOR)
        except Exception:
            self._append_console_line("error: unexpected exception (see log file)", ERROR_COLOR)
        self._show_prompt()

    def _save_project(self) -> None:
        if self._save_diagram_syn_interactive():
            pass
        else:
            self.statusBar().showMessage("Save canceled")

    def _toggle_right_panel(self, visible: bool) -> None:
        self.right_tabs.setVisible(visible)
        lw = self.horizontal_split.sizes()[0]
        if visible:
            self.horizontal_split.setSizes([lw, 712, 220])
        else:
            self.horizontal_split.setSizes([lw, 932, 0])

    def _toggle_bottom_panel(self, visible: bool) -> None:
        self.bottom_tabs.setVisible(visible)
        if visible:
            self.center_split.setSizes([560, 180])
        else:
            self.center_split.setSizes([740, 0])

