"""Logging handlers that forward formatted records via ``LogEmitter.message``."""

from __future__ import annotations

import logging

from .log_emitter import LogEmitter


class QtLogHandler(logging.Handler):
    def __init__(self, emitter: LogEmitter) -> None:
        super().__init__()
        self._emitter = emitter

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._emitter.message.emit(msg)
        except RuntimeError:
            pass
        except Exception:
            self.handleError(record)


class SplitStudioGuiLogHandler(logging.Handler):
    """Routes root logging to general / build / experiment panes (build & experiment are subsets)."""

    def __init__(
        self,
        general: LogEmitter,
        build: LogEmitter,
        experiment: LogEmitter,
        *,
        level: int = logging.NOTSET,
    ) -> None:
        super().__init__(level)
        self._general = general
        self._build = build
        self._experiment = experiment

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._general.message.emit(msg)
            if self._to_build(record):
                self._build.message.emit(msg)
            if self._to_experiment(record):
                self._experiment.message.emit(msg)
        except RuntimeError:
            pass
        except Exception:
            self.handleError(record)

    @staticmethod
    def _to_build(record: logging.LogRecord) -> bool:
        name = record.name
        if name.startswith("synarius_studio.build"):
            return True
        if name == "synarius_studio.console" and record.levelno >= logging.WARNING:
            return True
        return False

    @staticmethod
    def _to_experiment(record: logging.LogRecord) -> bool:
        name = record.name
        if name.startswith("synarius_studio.experiment"):
            return True
        if name == "synarius_studio.recordings":
            return True
        return False
