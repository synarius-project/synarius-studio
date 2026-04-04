"""Compact simulation step count control for toolbars: truncation, hover popup, centered layout."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QPainter, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLineEdit,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


def _white_triangle_icon(*, up: bool, side: int = 11) -> QIcon:
    """Reliable white arrow icons (Qt stylesheets often fail to paint spinbox arrows on Windows)."""
    px = QPixmap(side, side)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setBrush(QColor(255, 255, 255))
    p.setPen(Qt.PenStyle.NoPen)
    m = 2.0
    cx = side / 2.0
    fs = float(side)
    if up:
        poly = QPolygonF(
            [
                QPointF(cx, m),
                QPointF(fs - m, fs - m),
                QPointF(m, fs - m),
            ]
        )
    else:
        poly = QPolygonF(
            [
                QPointF(cx, fs - m),
                QPointF(m, m),
                QPointF(fs - m, m),
            ]
        )
    p.drawPolygon(poly)
    p.end()
    return QIcon(px)


class _TruncatingStepLineEdit(QLineEdit):
    """Shows full text while focused; elides with a visible \"..\" suffix when unfocused if needed."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._raw = "1"

    def raw_text(self) -> str:
        return self._raw

    def set_raw_text(self, text: str) -> None:
        self._raw = text
        if self.hasFocus():
            self.blockSignals(True)
            self.setText(text)
            self.blockSignals(False)
        else:
            self._apply_elided_display()

    def focusInEvent(self, event) -> None:  # noqa: ANN001
        self.blockSignals(True)
        self.setText(self._raw)
        self.blockSignals(False)
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: ANN001
        super().focusOutEvent(event)
        self._raw = self.text().strip() or self._raw
        self._apply_elided_display()

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        if not self.hasFocus():
            self._apply_elided_display()

    def _available_text_width(self) -> int:
        w = self.width() - 10
        return max(8, w)

    def _apply_elided_display(self) -> None:
        if self.hasFocus():
            return
        fm = QFontMetrics(self.font())
        slot = self._available_text_width()
        full = self._raw
        if fm.horizontalAdvance(full) <= slot:
            self.blockSignals(True)
            self.setText(full)
            self.blockSignals(False)
            return
        suffix = ".."
        t = full
        while len(t) > 0:
            cand = t + suffix
            if fm.horizontalAdvance(cand) <= slot:
                self.blockSignals(True)
                self.setText(cand)
                self.blockSignals(False)
                return
            t = t[:-1]
        self.blockSignals(True)
        self.setText(suffix if fm.horizontalAdvance(suffix) <= slot else ".")
        self.blockSignals(False)


class _StepMultSpinBox(QSpinBox):
    """Spin box where step up/down doubles or halves the value (integer-rounded), not additive steps."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setKeyboardTracking(False)
        self.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)

    def stepBy(self, steps: int) -> None:
        v = int(self.value())
        if steps > 0:
            for _ in range(steps):
                v = min(int(self.maximum()), v * 2)
            self.setValue(v)
        elif steps < 0:
            for _ in range(-steps):
                v = max(int(self.minimum()), int(round(v / 2.0)))
            self.setValue(v)


class _StepCountPopupPanel(QWidget):
    """Top-level frameless panel: spin field + custom white triangle buttons (no native spin arrows)."""

    def __init__(
        self,
        *,
        max_val: int,
        spin_stylesheet: str,
        tip: str,
    ) -> None:
        super().__init__(None)
        self.setObjectName("SimulationStepCountPopup")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setWindowTitle(" ")
        self.setStyleSheet(
            "QWidget#SimulationStepCountPopup { border: 1px solid #666; border-radius: 3px; "
            "background: #262626; }"
        )

        self._spin = _StepMultSpinBox(self)
        self._spin.setObjectName("SimulationStepCountPopupSpin")
        self._spin.setRange(1, max_val)
        self._spin.setSingleStep(1)
        self._spin.setStyleSheet(spin_stylesheet)
        self._spin.setMinimumHeight(24)
        self._spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._spin.setToolTip(tip)

        btn_w, btn_h = 20, 12
        ic = QSize(12, 9)
        btn_style = (
            "QToolButton { background: #383838; border: none; border-left: 1px solid #555; "
            "padding: 0; margin: 0; }"
            "QToolButton:hover { background: #484848; }"
            "QToolButton:pressed { background: #555; }"
        )

        self._btn_up = QToolButton(self)
        self._btn_up.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_up.setAutoRaise(True)
        self._btn_up.setFixedSize(btn_w, btn_h)
        self._btn_up.setIcon(_white_triangle_icon(up=True))
        self._btn_up.setIconSize(ic)
        self._btn_up.setStyleSheet(btn_style + " QToolButton { border-bottom: 1px solid #444; }")
        self._btn_up.setToolTip("Double step count (×2)")
        self._btn_up.clicked.connect(lambda: self._spin.stepBy(1))

        self._btn_down = QToolButton(self)
        self._btn_down.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_down.setAutoRaise(True)
        self._btn_down.setFixedSize(btn_w, btn_h)
        self._btn_down.setIcon(_white_triangle_icon(up=False))
        self._btn_down.setIconSize(ic)
        self._btn_down.setStyleSheet(btn_style)
        self._btn_down.setToolTip("Halve step count (÷2, rounded)")
        self._btn_down.clicked.connect(lambda: self._spin.stepBy(-1))

        col = QWidget(self)
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(self._btn_up)
        v.addWidget(self._btn_down)

        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self._spin, 1)
        h.addWidget(col, 0)

    def hover_watch_widgets(self) -> tuple[QWidget, ...]:
        return (self, self._spin, self._btn_up, self._btn_down)

    def spin(self) -> _StepMultSpinBox:
        return self._spin

    def value(self) -> int:
        return int(self._spin.value())

    def set_spin_value(self, v: int) -> None:
        self._spin.setValue(v)

    def spin_block_signals(self, b: bool) -> None:
        self._spin.blockSignals(b)


class SimulationStepCountField(QWidget):
    """Compact ticks field; hover popup. Optional horizontal expansion to center within a wide toolbar slot."""

    valueCommitted = Signal(str)

    _COMPACT_W = 28
    _POPUP_MIN_W = 80
    _HIDE_MS = 220

    def __init__(
        self,
        *,
        initial: str,
        compact_style: str,
        popup_style: str,
        max_length: int = 6,
        tooltip: str | None = None,
        expand_in_toolbar_slot: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._max_val = max(1, min(10**max_length - 1, 999_999))
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_popup_if_idle)

        self._compact = _TruncatingStepLineEdit(self)
        self._compact.setObjectName("SimulationStepCountInput")
        self._compact.setFixedWidth(self._COMPACT_W)
        self._compact.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._compact.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._compact.setMaxLength(max_length)
        self._compact.setStyleSheet(compact_style)
        self._compact.set_raw_text(initial)
        self._compact.editingFinished.connect(self._on_compact_editing_finished)
        self._compact.installEventFilter(self)

        spin_tip = (
            "Up/down buttons: double or halve the value (integer-rounded). "
            "You can still type a number directly."
        )
        self._popup = _StepCountPopupPanel(
            max_val=self._max_val,
            spin_stylesheet=popup_style,
            tip=spin_tip,
        )
        self._popup.spin().editingFinished.connect(self._on_popup_editing_finished)
        for w in self._popup.hover_watch_widgets():
            w.installEventFilter(self)
        self._apply_popup_initial_value(initial)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        if expand_in_toolbar_slot:
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            lay.addStretch(1)
            lay.addWidget(self._compact, 0, Qt.AlignmentFlag.AlignVCenter)
            lay.addStretch(1)
        else:
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self.setFixedWidth(self._COMPACT_W)
            lay.addWidget(self._compact, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        if tooltip:
            self.setToolTip(tooltip)
            self._compact.setToolTip(tooltip)

    def _apply_popup_initial_value(self, initial: str) -> None:
        try:
            v = max(1, min(self._max_val, int(str(initial).strip())))
        except Exception:
            v = 1
        self._popup.spin_block_signals(True)
        self._popup.set_spin_value(v)
        self._popup.spin_block_signals(False)

    def _popup_has_focus(self) -> bool:
        fw = QApplication.focusWidget()
        return fw is not None and (fw is self._popup or self._popup.isAncestorOf(fw))

    def set_display_value(self, text: str) -> None:
        self._compact.set_raw_text(text)
        if self._popup.isVisible():
            self._apply_popup_initial_value(text)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._compact:
            if event.type() == QEvent.Type.Enter:
                self._cancel_hide_popup()
                self._show_popup_hover()
            elif event.type() == QEvent.Type.Leave:
                self._schedule_hide_popup()
        elif watched in self._popup.hover_watch_widgets():
            if event.type() == QEvent.Type.Enter:
                self._cancel_hide_popup()
            elif event.type() == QEvent.Type.Leave:
                self._schedule_hide_popup()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        if self._popup.isVisible():
            self._position_popup()

    def moveEvent(self, event) -> None:  # noqa: ANN001
        super().moveEvent(event)
        if self._popup.isVisible():
            self._position_popup()

    def closeEvent(self, event) -> None:  # noqa: ANN001
        self._popup.hide()
        self._popup.deleteLater()
        super().closeEvent(event)

    def _show_popup_hover(self) -> None:
        self._apply_popup_initial_value(self._compact.raw_text())
        w = max(self._POPUP_MIN_W, self._compact.width() + 48)
        self._popup.setFixedWidth(w)
        self._position_popup()
        if not self._popup.isVisible():
            self._popup.show()
        self._popup.raise_()

    def _position_popup(self) -> None:
        """Left-aligned with the compact field; vertically overlaps it (covers it) with the larger control."""
        g = self._compact.mapToGlobal(QPoint(0, 0))
        y = g.y() + self._compact.height() - self._popup.height()
        self._popup.move(g.x(), y)

    def _schedule_hide_popup(self) -> None:
        self._hide_timer.start(self._HIDE_MS)

    def _cancel_hide_popup(self) -> None:
        self._hide_timer.stop()

    def _hide_popup_if_idle(self) -> None:
        if self._popup_has_focus():
            return
        if not self._popup.isVisible():
            return
        self._commit_and_hide_popup()

    def _commit_and_hide_popup(self) -> None:
        self._cancel_hide_popup()
        if not self._popup.isVisible():
            return
        text = str(self._popup.value())
        self._popup.spin_block_signals(True)
        self._popup.hide()
        self._popup.spin_block_signals(False)
        self.valueCommitted.emit(text)

    def _on_compact_editing_finished(self) -> None:
        if self._popup_has_focus():
            return
        self.valueCommitted.emit(self._compact.text().strip())

    def _on_popup_editing_finished(self) -> None:
        self._commit_and_hide_popup()
