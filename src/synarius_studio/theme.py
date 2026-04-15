"""Studio colors (resources tab; toolbar remains native)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication


def _rgb_hex_scale(hex_rgb: str, factor: float) -> str:
    """Scale ``#RRGGBB`` channels by ``factor`` (e.g. 0.9 for a slightly darker stripe)."""
    s = hex_rgb.strip().removeprefix("#")
    if len(s) != 6:
        raise ValueError(f"expected #RRGGBB, got {hex_rgb!r}")
    r, g, b = (int(s[i : i + 2], 16) for i in (0, 2, 4))
    r = max(0, min(255, int(round(r * factor))))
    g = max(0, min(255, int(round(g * factor))))
    b = max(0, min(255, int(round(b * factor))))
    return f"#{r:02x}{g:02x}{b:02x}"


# Left strip (resources / variables): light fill; alternating table rows use a derived darker tone.
RESOURCES_PANEL_BACKGROUND = "#c8e3fb"
RESOURCES_PANEL_ALTERNATE_ROW = _rgb_hex_scale(RESOURCES_PANEL_BACKGROUND, 0.90)

# Console / bottom tab chrome (match QTextEdit terminal background).
CONSOLE_CHROME_BACKGROUND = "#2f2f2f"
CONSOLE_TAB_TEXT = "#e0e0e0"

# Library section headers: dark strip aligned with typical dark QToolBar chrome.
LIBRARY_HEADER_BACKGROUND = "#353535"
LIBRARY_HEADER_TEXT = "#ffffff"
LIBRARY_HEADER_SEPARATOR = "#505050"
LIBRARY_HEADER_BUTTON_HOVER = "#454545"


def qss_widget_id_background(object_name: str, background_hex: str) -> str:
    """Paint ``background_hex`` only on ``#object_name`` (no bare rules that cascade to QToolTip)."""
    return f"#{object_name} {{ background-color: {background_hex}; }}"


def studio_tab_bar_stylesheet(*, selected_tab_bg: str) -> str:
    """QTabBar wie der Kopfstreifen im Variables-Tab (LIBRARY_HEADER_*); aktiver Tab: ``selected_tab_bg``."""
    hb, ht, hov = LIBRARY_HEADER_BACKGROUND, LIBRARY_HEADER_TEXT, LIBRARY_HEADER_BUTTON_HOVER
    return (
        f"QTabBar {{ background-color: {hb}; border: none; }}"
        f"QTabBar::tab {{ background-color: {hb}; color: {ht}; padding: 6px 14px; border: none; }}"
        f"QTabBar::tab:selected {{ background-color: {selected_tab_bg}; color: {ht}; }}"
        f"QTabBar::tab:hover:!selected {{ background-color: {hov}; }}"
    )

# Main window + diagram palette toolbars (fixed black chrome, light icons in code).
STUDIO_TOOLBAR_BACKGROUND = "#000000"
STUDIO_TOOLBAR_FOREGROUND = "#ffffff"
STUDIO_TOOLBAR_HOVER = "#2a2a2a"
# Combo / dropdown surface on black toolbars (not the same as checked tool actions).
STUDIO_TOOLBAR_COMBO_BACKGROUND = "#333333"
STUDIO_TOOLBAR_COMBO_BORDER = "#555555"

# Checked tool actions: canvas placement palette + main-toolbar panel visibility toggles (single accent source).
STUDIO_TOOLBAR_ACTIVE_ACTION_BACKGROUND = "#586cd4"

# Diagram selection, console/table/rubber-band: same hue as ``STUDIO_TOOLBAR_ACTIVE_ACTION_BACKGROUND``.
SELECTION_HIGHLIGHT = STUDIO_TOOLBAR_ACTIVE_ACTION_BACKGROUND
SELECTION_HIGHLIGHT_ALPHA = 190
SELECTION_HIGHLIGHT_TEXT = "#ffffff"

# Active-dataset marker in the Parameters tab: same violet as ParaWiz's CCP-select overlay.
ACTIVE_DATASET_BACKGROUND = "#8b5cf6"
ACTIVE_DATASET_FOREGROUND = "#ffffff"
# Toolbar icon buttons: hover/press ramp from active-action hue; combo box keeps gray hover above.
STUDIO_TOOLBAR_ACTION_HOVER = _rgb_hex_scale(STUDIO_TOOLBAR_ACTIVE_ACTION_BACKGROUND, 0.40)
STUDIO_TOOLBAR_ACTION_PRESSED = _rgb_hex_scale(STUDIO_TOOLBAR_ACTIVE_ACTION_BACKGROUND, 0.72)


def selection_highlight_qcolor(*, opaque: bool = False) -> QColor:
    """QColor for diagram painting (semi-transparent by default) or solid (e.g. ``QPalette`` / rubber band)."""
    c = QColor(SELECTION_HIGHLIGHT)
    c.setAlpha(255 if opaque else SELECTION_HIGHLIGHT_ALPHA)
    return c


# Diagram canvas (scene coordinates, px): uniform selection halo for Variable/Operator/FMU/DataViewer
# blocks and connector edges. (Blocks intentionally use no QGraphicsDropShadowEffect so pins stay shadow-free.)
DIAGRAM_SELECTION_OVERHANG_PX = 3.5
DIAGRAM_SELECTION_HALO_CORNER_RADIUS_PX = 3.0

# Application-wide tooltips (Libs, canvas, dialogs, toolbars). QToolTip is a separate window and
# does not inherit QToolBar stylesheets — use these constants for QSS + QPalette together.
STUDIO_TOOLTIP_FOREGROUND = "#ffffff"
STUDIO_TOOLTIP_BACKGROUND = "#2b2b2b"
STUDIO_TOOLTIP_BORDER = "#5a5a5a"
STUDIO_TOOLTIP_PADDING = "4px 6px"

# Pre-built QToolTip rule — single source of truth used by all widget-level stylesheets.
#
# Background: Qt resolves QToolTip styling from the *nearest ancestor* (including the widget
# itself) that has a non-empty styleSheet().  If that ancestor's stylesheet lacks a QToolTip
# rule, Qt falls back to OS-native tooltip styling — ignoring the app-level stylesheet set in
# apply_dark_palette().  Therefore every widget that calls setStyleSheet() AND hosts tooltips
# (directly or via child items/actions) must include TOOLTIP_QSS.  Use with_tooltip_qss() as
# the canonical way to do this.
TOOLTIP_QSS = (
    f"QToolTip {{ color: {STUDIO_TOOLTIP_FOREGROUND} !important; "
    f"background-color: {STUDIO_TOOLTIP_BACKGROUND} !important; "
    f"border: 1px solid {STUDIO_TOOLTIP_BORDER} !important; "
    f"padding: {STUDIO_TOOLTIP_PADDING} !important; }}"
)


def studio_tooltip_stylesheet() -> str:
    """QToolTip rules for the whole Studio app (applied on ``QApplication``)."""
    return TOOLTIP_QSS


def with_tooltip_qss(qss: str) -> str:
    """Append ``TOOLTIP_QSS`` to a widget-level stylesheet.

    Call this whenever you assign a stylesheet to a widget (or a scroll-area ancestor
    whose viewport hosts tooltipped items) so that Qt uses the app theme rather than
    OS-native tooltip styling.
    """
    return f"{qss} {TOOLTIP_QSS}"


def studio_toolbar_stylesheet(*, background_color: str | None = None) -> str:
    """Shared QSS for all studio ``QToolBar`` instances (main + canvas + signals)."""
    bg = background_color or STUDIO_TOOLBAR_BACKGROUND
    fg = STUDIO_TOOLBAR_FOREGROUND
    combo_hover = STUDIO_TOOLBAR_HOVER
    combo_bg = STUDIO_TOOLBAR_COMBO_BACKGROUND
    tb_hover = STUDIO_TOOLBAR_ACTION_HOVER
    tb_pressed = STUDIO_TOOLBAR_ACTION_PRESSED
    action_checked = STUDIO_TOOLBAR_ACTIVE_ACTION_BACKGROUND
    bdr = STUDIO_TOOLBAR_COMBO_BORDER
    return (
        f"QToolBar {{ background-color: {bg}; border: none; padding: 3px; spacing: 4px; }}"
        f"QToolBar QLabel {{ color: {fg}; }}"
        f"QToolBar QComboBox {{ color: {fg}; background-color: {combo_bg}; border: 1px solid {bdr};"
        f" border-radius: 3px; padding: 2px 8px; min-height: 20px; }}"
        f"QToolBar QComboBox:hover {{ background-color: {combo_hover}; }}"
        f"QToolBar QComboBox::drop-down {{ border: none; width: 18px; }}"
        f"QToolBar QComboBox QAbstractItemView {{ background-color: {combo_bg}; color: {fg}; }}"
        f"QToolBar QLineEdit {{ color: {fg}; background-color: transparent; border: none; }}"
        f"QToolBar QToolButton {{ background-color: {bg}; border: none; border-radius: 4px; padding: 4px; }}"
        f"QToolBar QToolButton:hover {{ background-color: {tb_hover}; }}"
        f"QToolBar QToolButton:pressed {{ background-color: {tb_pressed}; }}"
        f"QToolBar QToolButton:checked {{ background-color: {action_checked}; }}"
        f"QToolBar QToolButton:checked:hover {{ background-color: {action_checked}; }}"
        f"QToolBar QToolButton::menu-indicator {{ image: none; width: 0px; height: 0px; }}"
        f" {TOOLTIP_QSS}"
    )


def apply_dark_palette(app: QApplication) -> None:
    """Force a dark QPalette on *app* regardless of the OS color scheme.

    Must be called after ``app.setStyle("Fusion")``; Fusion fully respects the
    application palette, so this overrides any OS light/dark preference.
    The highlight color is taken from ``STUDIO_TOOLBAR_ACTIVE_ACTION_BACKGROUND``
    to keep the palette consistent with the existing toolbar chrome.
    """
    hl = QColor(STUDIO_TOOLBAR_ACTIVE_ACTION_BACKGROUND)

    p = QPalette()

    # --- Active / Normal color group -----------------------------------------
    p.setColor(QPalette.ColorRole.Window,          QColor(53, 53, 53))
    p.setColor(QPalette.ColorRole.WindowText,      Qt.GlobalColor.white)
    p.setColor(QPalette.ColorRole.Base,            QColor(35, 35, 35))
    p.setColor(QPalette.ColorRole.AlternateBase,   QColor(53, 53, 53))
    p.setColor(QPalette.ColorRole.ToolTipBase,     QColor(STUDIO_TOOLTIP_BACKGROUND))
    p.setColor(QPalette.ColorRole.ToolTipText,     QColor(STUDIO_TOOLTIP_FOREGROUND))
    p.setColor(QPalette.ColorRole.Text,            Qt.GlobalColor.white)
    p.setColor(QPalette.ColorRole.Button,          QColor(53, 53, 53))
    p.setColor(QPalette.ColorRole.ButtonText,      Qt.GlobalColor.white)
    p.setColor(QPalette.ColorRole.BrightText,      Qt.GlobalColor.red)
    p.setColor(QPalette.ColorRole.Link,            QColor(42, 130, 218))
    p.setColor(QPalette.ColorRole.Highlight,       hl)
    p.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.white)
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(140, 140, 140))

    # --- Disabled color group -------------------------------------------------
    disabled = QPalette.ColorGroup.Disabled
    grey = QColor(127, 127, 127)
    p.setColor(disabled, QPalette.ColorRole.WindowText,      grey)
    p.setColor(disabled, QPalette.ColorRole.Text,            grey)
    p.setColor(disabled, QPalette.ColorRole.ButtonText,      grey)
    p.setColor(disabled, QPalette.ColorRole.Highlight,       QColor(80, 80, 80))
    p.setColor(disabled, QPalette.ColorRole.HighlightedText, grey)

    app.setPalette(p)
    # QToolTip windows do not inherit toolbar QSS; one app-level sheet keeps Libs/canvas/dialogs aligned.
    app.setStyleSheet(studio_tooltip_stylesheet())
