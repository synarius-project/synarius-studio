from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen, QStyleFactory

from .main_window import MainWindow
from .resource_paths import studio_icon_path, studio_splash_path


def run(argv: Sequence[str] | None = None) -> int:
    import sys

    from .app_logging import configure_file_logging

    args = list(argv) if argv is not None else list(sys.argv)
    configure_file_logging()
    if ("--smoke-exit" in args) or bool(os.environ.get("SYNARIUS_STUDIO_SMOKE_EXIT")):
        return 0

    # On Windows, give the process a stable AppUserModelID so the taskbar shows
    # the Synarius identity instead of generic python.exe (same pattern as Dataviewer).
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(  # type: ignore[attr-defined]
                "synarius.studio"
            )
        except Exception:
            pass

    app = QApplication(args)

    from .app_logging import install_qt_message_handler

    install_qt_message_handler()

    # Windows-Style (windowsvista) respektiert QTabBar::setExpanding / qproperty-expanding oft nicht —
    # dann wirken nur einzelne vertikale Tabs „kompakt“. Fusion verhält sich konsistent.
    _fusion = QStyleFactory.create("Fusion")
    if _fusion is not None:
        app.setStyle(_fusion)

    # Use the same app icon as Synarius Dataviewer so both applications share
    # a consistent symbol in the Windows taskbar and Alt+Tab switcher.
    try:
        from synarius_dataviewer.app import main_window as _dv_main

        dv_icon_path = Path(_dv_main.__file__).resolve().parent / "icons" / "synarius64.png"
        app.setWindowIcon(QIcon(str(dv_icon_path)))
    except Exception:
        # Fallback to the local studio icon if Dataviewer assets are not available.
        app.setWindowIcon(QIcon(str(studio_icon_path())))

    splash: QSplashScreen | None = None
    spath = studio_splash_path()
    if spath.is_file():
        raw = QPixmap(str(spath))
        if not raw.isNull():
            screen = app.primaryScreen()
            if screen is not None:
                avail = screen.availableGeometry()
                # Moderate size (not near full-screen); cap so the splash stays clearly a logo, not a wallpaper.
                max_w = max(1, min(int(avail.width() * 0.45), 720))
                max_h = max(1, min(int(avail.height() * 0.45), 480))
                scaled = raw.scaled(
                    max_w,
                    max_h,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            else:
                scaled = raw
            splash = QSplashScreen(scaled, Qt.WindowType.WindowStaysOnTopHint)
            splash.show()
            app.processEvents()

    window = MainWindow()
    window.showMaximized()
    if splash is not None:
        # Close immediately after the main window is shown. MainWindow defers heavy
        # plugin imports to the next event-loop tick so we do not block here for minutes
        # with only the splash visible.
        app.processEvents()
        splash.finish(window)
    return app.exec()

