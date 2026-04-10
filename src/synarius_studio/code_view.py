"""Read-only plain-text code view with a line-number gutter (copy allowed)."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QTextBlock
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QSizePolicy, QWidget

from .theme import CONSOLE_CHROME_BACKGROUND, CONSOLE_TAB_TEXT


class _LineNumberBar(QWidget):
    """Left gutter showing 1-based line numbers for a :class:`QPlainTextEdit`."""

    def __init__(
        self, editor: QPlainTextEdit, parent: QWidget | None, *, gutter_bg: str, gutter_fg: str
    ) -> None:
        super().__init__(parent)
        self._editor = editor
        self._gutter_bg = QColor(gutter_bg)
        self._gutter_fg = QColor(gutter_fg)
        editor.blockCountChanged.connect(self._update_width)
        editor.updateRequest.connect(self._on_update_request)
        editor.cursorPositionChanged.connect(self.update)
        self._update_width()

    def _on_update_request(self, rect: QRect, dy: int) -> None:
        if dy:
            self.scroll(0, dy)
        else:
            self.update(0, rect.y(), self.width(), rect.height())

    def _update_width(self) -> None:
        n = max(1, self._editor.blockCount())
        digits = len(str(n))
        w = 10 + self.fontMetrics().horizontalAdvance("9") * digits
        self.setFixedWidth(max(28, w))

    def sizeHint(self) -> QSize:
        return QSize(self.width(), 0)

    def paintEvent(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        painter.fillRect(event.rect(), self._gutter_bg)
        painter.setPen(self._gutter_fg)
        painter.setFont(self._editor.font())

        block = self._editor.firstVisibleBlock()
        top = round(self._editor.blockBoundingGeometry(block).translated(self._editor.contentOffset()).top())
        width = self.width() - 4
        fm = self._editor.fontMetrics()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and top + fm.height() >= event.rect().top():
                painter.drawText(
                    QRect(0, top, width, fm.height()),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    str(block.blockNumber() + 1),
                )
            h = max(1, round(self._editor.blockBoundingRect(block).height()))
            block = block.next()
            top += h


class ReadOnlyCodeView(QWidget):
    """Typical monospace read-only editor look; selection and copy work, editing does not."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._editor = QPlainTextEdit(self)
        self._editor.setReadOnly(True)
        self._editor.setUndoRedoEnabled(False)
        self._editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        mono = QFont("Consolas")
        if not mono.exactMatch():
            mono = QFont("monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(10)
        self._editor.setFont(mono)

        bg = CONSOLE_CHROME_BACKGROUND
        fg = CONSOLE_TAB_TEXT
        gutter_bg = "#252525"
        self._editor.setStyleSheet(
            f"QPlainTextEdit {{ background-color: {bg}; color: {fg}; border: none; }}"
        )
        self._line_bar = _LineNumberBar(self._editor, self, gutter_bg=gutter_bg, gutter_fg="#8a8a8a")
        self._line_bar.setFont(mono)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._line_bar, 0)
        lay.addWidget(self._editor, 1)

    def set_plain_text(self, text: str) -> None:
        self._editor.setPlainText(text)

    def plain_text(self) -> str:
        return self._editor.toPlainText()
