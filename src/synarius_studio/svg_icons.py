"""Rasterize Breeze-style symbolic SVGs with a palette foreground color."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# Default ``ColorScheme-Text`` fill in many Breeze symbolic icons (dark-on-light).
_BREEZE_SYMBOLIC_HEX = re.compile(r"#232629", re.IGNORECASE)
# Inkscape / custom palette icons often hard-code dark fills in ``style``.
_PURE_BLACK_HEX = re.compile(r"#000000", re.IGNORECASE)
_DARK_CUSTOM_HEX = re.compile(r"#1c1c1c", re.IGNORECASE)


def tint_breeze_symbolic_svg_markup(svg_text: str, foreground: QColor) -> str:
    """Replace Breeze / monochrome glyph colors so ``currentColor`` and explicit fills match ``foreground``."""
    hx = foreground.name(QColor.NameFormat.HexRgb)
    s = _BREEZE_SYMBOLIC_HEX.sub(hx, svg_text)
    s = _PURE_BLACK_HEX.sub(hx, s)
    return _DARK_CUSTOM_HEX.sub(hx, s)


def icon_from_inverted_standard_icon(source: QIcon, *, logical_side: int = 24) -> QIcon:
    """Invert RGB of a (typically dark) theme ``QIcon`` for use on dark toolbars; alpha preserved."""
    app = QGuiApplication.instance()
    dpr = 1.0
    if app is not None:
        screen = app.primaryScreen()
        if screen is not None:
            dpr = max(1.0, float(screen.devicePixelRatio()))
    px = max(1, int(round(logical_side * dpr)))
    pm = source.pixmap(px, px)
    if pm.isNull():
        return source
    img = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    img.invertPixels(QImage.InvertMode.InvertRgb)
    out = QPixmap.fromImage(img)
    out.setDevicePixelRatio(pm.devicePixelRatio())
    return QIcon(out)


def icon_from_tinted_svg_file(
    svg_path: Path,
    foreground: QColor,
    *,
    logical_side: int = 24,
) -> QIcon:
    """Load an SVG file, tint Breeze symbolic gray to ``foreground``, and build a ``QIcon``."""
    raw = svg_path.read_text(encoding="utf-8")
    tinted = tint_breeze_symbolic_svg_markup(raw, foreground)
    renderer = QSvgRenderer(QByteArray(tinted.encode("utf-8")))
    if not renderer.isValid():
        return QIcon(str(svg_path))

    app = QGuiApplication.instance()
    dpr = 1.0
    if app is not None:
        screen = app.primaryScreen()
        if screen is not None:
            dpr = max(1.0, float(screen.devicePixelRatio()))

    px = max(1, int(round(logical_side * dpr)))
    img = QImage(px, px, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter, QRectF(0.0, 0.0, float(px), float(px)))
    painter.end()

    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return QIcon(pm)


# Panel toggle SVGs (gray UI mock) → light strokes/fills for black toolbars.
_TOGGLE_SVG_SUBS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"#1f2937", re.IGNORECASE), "#e8e8e8"),
    (re.compile(r"#e5e7eb", re.IGNORECASE), "#9a9a9a"),
    (re.compile(r"#9ca3af", re.IGNORECASE), "#c0c0c0"),
)


def tint_panel_toggle_svg_markup(svg_text: str) -> str:
    for pat, repl in _TOGGLE_SVG_SUBS:
        svg_text = pat.sub(repl, svg_text)
    return svg_text


def _pixmap_from_svg_markup(markup: str, logical_side: int) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(markup.encode("utf-8")))
    if not renderer.isValid():
        return QPixmap()
    app = QGuiApplication.instance()
    dpr = 1.0
    if app is not None:
        screen = app.primaryScreen()
        if screen is not None:
            dpr = max(1.0, float(screen.devicePixelRatio()))
    px = max(1, int(round(logical_side * dpr)))
    img = QImage(px, px, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter, QRectF(0.0, 0.0, float(px), float(px)))
    painter.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return pm


def _tint_panel_toggle_checked_markup(svg_text: str, fg_hex: str) -> str:
    """Same mock layout as :func:`tint_panel_toggle_svg_markup`, single color for checked (lilac toolbar) state."""
    s = svg_text
    for pat, _ in _TOGGLE_SVG_SUBS:
        s = pat.sub(fg_hex, s)
    return s


def qicon_panel_toggle_for_toolbar(
    svg_path: Path,
    *,
    logical_side: int = 24,
    checked_foreground: QColor,
) -> QIcon:
    """Unchecked: gray mock on black bar; checked: ``checked_foreground`` on ``STUDIO_TOOLBAR_ACTIVE_ACTION_BACKGROUND``."""
    raw = svg_path.read_text(encoding="utf-8")
    off_pm = _pixmap_from_svg_markup(tint_panel_toggle_svg_markup(raw), logical_side)
    on_pm = _pixmap_from_svg_markup(
        _tint_panel_toggle_checked_markup(raw, checked_foreground.name(QColor.NameFormat.HexRgb)),
        logical_side,
    )
    if off_pm.isNull() or on_pm.isNull():
        return QIcon(str(svg_path))
    icon = QIcon()
    icon.addPixmap(off_pm, QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(on_pm, QIcon.Mode.Normal, QIcon.State.On)
    return icon


def icon_from_tinted_panel_toggle_svg(
    svg_path: Path,
    *,
    logical_side: int = 24,
) -> QIcon:
    raw = svg_path.read_text(encoding="utf-8")
    tinted = tint_panel_toggle_svg_markup(raw)
    pm = _pixmap_from_svg_markup(tinted, logical_side)
    if pm.isNull():
        return QIcon(str(svg_path))
    return QIcon(pm)
