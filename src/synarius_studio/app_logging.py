"""Central logging: rotating files, uncaught exceptions, optional Qt GUI handler."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from synarius_apps_diagnostics import (
    configure_file_logging as _diagnostics_configure,
    install_qt_message_handler as _diagnostics_install_qt,
    log_directory_for_app,
    main_log_path as _diagnostics_main_log_path,
)

from .log_emitter import LogEmitter

_gui_handler_attached = False
_split_gui_handler_attached = False


def log_directory() -> Path:
    """Stable per-user log directory (creates if missing)."""
    return log_directory_for_app(appname="SynariusStudio", appauthor="Synarius")


def main_log_path() -> Path | None:
    return _diagnostics_main_log_path()


def configure_file_logging() -> Path:
    """Rotating file on root logger, warnings → logging, excepthook. Safe to call once."""
    return _diagnostics_configure(
        user_log_appname="SynariusStudio",
        log_filename="synarius-studio.log",
        uncaught_logger_name="synarius_studio.uncaught",
        root_child_logger="synarius_studio",
        debug_env_keys=("SYNARIUS_STUDIO_LOG_DEBUG",),
    )


def attach_gui_log_handler(emitter: LogEmitter, *, level: int | None = None) -> None:
    """Append all log records to a single GUI sink (legacy; prefer ``attach_split_studio_gui_log_handlers``)."""
    global _gui_handler_attached
    if _gui_handler_attached:
        return
    from .qt_log_handler import QtLogHandler

    root = logging.getLogger()
    lv = level if level is not None else (
        logging.DEBUG if os.environ.get("SYNARIUS_STUDIO_LOG_DEBUG") else logging.INFO
    )
    h = QtLogHandler(emitter)
    h.setLevel(lv)
    h.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-5s %(name)s | %(message)s", datefmt="%H:%M:%S")
    )
    root.addHandler(h)
    _gui_handler_attached = True


def attach_split_studio_gui_log_handlers(
    general: LogEmitter,
    build: LogEmitter,
    experiment: LogEmitter,
    *,
    level: int | None = None,
) -> None:
    """Route logging to general (all), build (compile / command errors), and experiment panes."""
    global _split_gui_handler_attached, _gui_handler_attached
    if _split_gui_handler_attached:
        return
    from .qt_log_handler import SplitStudioGuiLogHandler

    root = logging.getLogger()
    lv = level if level is not None else (
        logging.DEBUG if os.environ.get("SYNARIUS_STUDIO_LOG_DEBUG") else logging.INFO
    )
    h = SplitStudioGuiLogHandler(general, build, experiment, level=lv)
    h.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-5s %(name)s | %(message)s", datefmt="%H:%M:%S")
    )
    root.addHandler(h)
    _split_gui_handler_attached = True
    _gui_handler_attached = True


def install_qt_message_handler() -> None:
    """Log Qt qDebug/qWarning etc. via Python logging (call after QApplication exists)."""
    _diagnostics_install_qt()
