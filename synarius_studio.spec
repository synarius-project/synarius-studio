# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller one-file Windows build with Qt plugins + bundled ``synarius_studio`` data.

Qt needs ``collect_all('PySide6')`` so ``platforms/qwindows.dll`` etc. are shipped.

From repo root (after ``pip install . pyinstaller``)::

    pyinstaller --noconfirm --clean synarius_studio.spec
"""
from __future__ import annotations

from pathlib import Path

from PyInstaller.building.api import EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.utils.hooks import collect_all, collect_data_files

_repo = Path(SPECPATH)
_src_main = _repo / "src" / "synarius_studio" / "__main__.py"
_icon_dir = _repo / "src" / "synarius_studio" / "icons"

datas: list[tuple[str, str]] = [(str(_icon_dir), "synarius_studio/icons")]
binaries: list = []
hiddenimports: list[str] = []

for _pkg in ("PySide6", "shiboken6"):
    d, b, h = collect_all(_pkg)
    datas += d
    binaries += b
    hiddenimports += h

datas += collect_data_files("synarius_studio")

hiddenimports += [
    "synarius_core",
    "synarius_core.controller",
    "synarius_core.controller.minimal_controller",
    "synarius_core.model",
    "synarius_core.model.data_model",
    "synarius_core.model.attribute_dict",
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="synarius-studio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
