"""Central logging: rotating files, uncaught exceptions, optional Qt GUI handler."""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

from .log_emitter import LogEmitter

_main_log_path: Path | None = None
_file_configured = False
_gui_handler_attached = False
_prev_excepthook = None


def log_directory() -> Path:
    """Stable per-user log directory (creates if missing)."""
    try:
        from platformdirs import user_log_dir

        base = user_log_dir(appname="SynariusStudio", appauthor="Synarius")
    except ImportError:
        if sys.platform.startswith("win"):
            local = os.environ.get("LOCALAPPDATA", "")
            base = str(Path(local) / "Synarius" / "SynariusStudio" / "Logs") if local else str(Path.home() / ".synarius-studio" / "logs")
        elif sys.platform == "darwin":
            base = str(Path.home() / "Library" / "Logs" / "SynariusStudio")
        else:
            base = str(Path.home() / ".local" / "share" / "SynariusStudio" / "logs")
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def main_log_path() -> Path | None:
    return _main_log_path


def configure_file_logging() -> Path:
    """Rotating file on root logger, warnings → logging, excepthook. Safe to call once."""
    global _file_configured, _main_log_path
    if _file_configured:
        return _main_log_path.parent if _main_log_path is not None else log_directory()

    log_dir = log_directory()
    log_path = log_dir / "synarius-studio.log"
    _main_log_path = log_path

    level = logging.DEBUG if os.environ.get("SYNARIUS_STUDIO_LOG_DEBUG") else logging.INFO

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    target = str(log_path.resolve())
    has_same = any(
        isinstance(h, logging.handlers.RotatingFileHandler) and getattr(h, "baseFilename", None) == target
        for h in root.handlers
    )
    if not has_same:
        fh = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=9,
            encoding="utf-8",
        )
        fh.setLevel(level)
        fh.setFormatter(fmt)
        root.addHandler(fh)

    root.setLevel(level)
    logging.getLogger("synarius_studio").setLevel(level)
    for noisy in ("urllib3", "matplotlib", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.captureWarnings(True)
    _install_excepthook()

    logging.getLogger(__name__).info("Logging initialized; log file: %s", log_path)
    _file_configured = True
    return log_dir


def _install_excepthook() -> None:
    global _prev_excepthook
    if _prev_excepthook is not None:
        return
    _prev_excepthook = sys.excepthook

    def _hook(exc_type, exc, tb) -> None:
        logging.getLogger("synarius_studio.uncaught").critical(
            "Uncaught exception",
            exc_info=(exc_type, exc, tb),
        )
        if _prev_excepthook is not None:
            _prev_excepthook(exc_type, exc, tb)

    sys.excepthook = _hook


def attach_gui_log_handler(emitter: LogEmitter, *, level: int | None = None) -> None:
    """Append log records to the GUI via ``LogEmitter.message`` (thread-safe via Qt queued slots)."""
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


def install_qt_message_handler() -> None:
    """Log Qt qDebug/qWarning etc. via Python logging (call after QApplication exists)."""
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    _map = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
        QtMsgType.QtInfoMsg: logging.INFO,
    }

    def _qt_handler(mode, context, message: str) -> None:
        lvl = _map.get(mode, logging.WARNING)
        extra = ""
        if context.file:
            extra = f" ({context.file}:{context.line})"
        logging.getLogger("qt").log(lvl, "%s%s", message, extra)

    qInstallMessageHandler(_qt_handler)
