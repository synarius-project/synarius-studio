"""Logging handler that forwards formatted records via ``LogEmitter.message``."""

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
