# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller onedir Windows build for diagnostics/smoke tests.

This intentionally mirrors ``synarius_studio.spec`` dependencies but keeps the unpacked
layout to make missing modules/data easier to inspect in CI.
"""
from __future__ import annotations

from pathlib import Path

from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.utils.hooks import collect_all, collect_data_files

_repo = Path(SPECPATH)
_src_main = _repo / "src" / "synarius_studio" / "__main__.py"
_icon_dir = _repo / "src" / "synarius_studio" / "icons"
_resources_dir = _repo / "src" / "synarius_studio" / "resources"

datas: list[tuple[str, str]] = [
    (str(_icon_dir), "synarius_studio/icons"),
    (str(_resources_dir), "synarius_studio/resources"),
]
binaries: list = []
hiddenimports: list[str] = []

for _pkg in ("synarius_core", "synarius_dataviewer", "synariustools", "fmpy", "PySide6", "shiboken6"):
    d, b, h = collect_all(_pkg)
    datas += d
    binaries += b
    hiddenimports += h

datas += collect_data_files("synarius_studio")

hiddenimports += [
    "synarius_studio.diagram",
    "synarius_studio.diagram.dataflow_canvas",
    "synarius_studio.diagram.dataflow_items",
    "synarius_studio.diagram.dataflow_layout",
]

a = Analysis(
    [str(_src_main)],
    pathex=[str(_repo / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="synarius-studio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="synarius-studio",
)
