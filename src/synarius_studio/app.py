from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen, QStyleFactory

from .resource_paths import studio_icon_path, studio_splash_path


def _apply_core_defer_initial_load_shim() -> None:
    """Retry ``__init__`` without ``defer_initial_load`` when older synarius-core omits that parameter.

    Frozen bundles may still ship an older ``main_window`` that passes the keyword; this patches
    the core classes before :class:`~synarius_studio.main_window.MainWindow` is imported.
    """

    def _wrap(cls: type) -> None:
        _orig = cls.__init__

        def _patched(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            try:
                return _orig(self, *args, **kwargs)
            except TypeError as exc:
                if "defer_initial_load" not in str(exc):
                    raise
                kwargs = dict(kwargs)
                kwargs.pop("defer_initial_load", None)
                return _orig(self, *args, **kwargs)

        cls.__init__ = _patched  # type: ignore[method-assign]

    try:
        from synarius_core.library import LibraryCatalog

        _wrap(LibraryCatalog)
    except Exception:
        pass
    try:
        from synarius_core.plugins.registry import PluginRegistry

        _wrap(PluginRegistry)
    except Exception:
        pass


def run(argv: Sequence[str] | None = None) -> int:
    import logging
    import sys

    from synarius_apps_diagnostics import log_session_start

    from .app_logging import configure_file_logging, main_log_path

    args = list(argv) if argv is not None else list(sys.argv)
    configure_file_logging()
    try:
        from ._version import __version__ as _studio_ver
    except Exception:
        _studio_ver = "unknown"
    _log_path = main_log_path()
    log_session_start(logger_name="synarius_studio.bootstrap", app_name="Synarius Studio", version=_studio_ver)
    logging.getLogger("synarius_studio.bootstrap").info("build_marker=defer_kw_shim")
    if _log_path is not None:
        print(
            f"Synarius Studio {_studio_ver} | log file: {_log_path.resolve()}",
            file=sys.stderr,
            flush=True,
        )

    _apply_core_defer_initial_load_shim()

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
    from .theme import apply_dark_palette

    install_qt_message_handler()

    # Windows-Style (windowsvista) respektiert QTabBar::setExpanding / qproperty-expanding oft nicht —
    # dann wirken nur einzelne vertikale Tabs „kompakt”. Fusion verhält sich konsistent.
    # Dark-Palette muss nach setStyle gesetzt werden: Fusion respektiert QPalette vollständig
    # und überschreibt damit die OS-Farbeinstellung unabhängig vom System-Theme.
    _fusion = QStyleFactory.create("Fusion")
    if _fusion is not None:
        app.setStyle(_fusion)
    apply_dark_palette(app)

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

    from .main_window import MainWindow

    window = MainWindow()
    window.showMaximized()
    if splash is not None:
        # MainWindow defers heavy plugin imports to the next event-loop tick so we do not
        # block here for minutes with only the splash visible.
        app.processEvents()
        # Keep the splash on top for one second after the main window is visible.

        def _finish_splash() -> None:
            splash.finish(window)

        QTimer.singleShot(1000, _finish_splash)
    return app.exec()

