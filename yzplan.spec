# -*- mode: python ; coding: utf-8 -*-
# yzplan onedir spec

import os
import sys as _sys

_SPEC_DIR = os.path.abspath(SPECPATH)
_VENV = os.path.join(_SPEC_DIR, ".venv", "Lib", "site-packages")

# ---- Interpreter / conda detection -----------------------------------------
# This project can be built in two ways:
#   * Standard CPython venv  -> PyInstaller bundles every compiled extension
#                               module and native DLL it needs automatically.
#   * conda/anaconda venv    -> compiled stdlib extensions (_ctypes.pyd etc.)
#                               and supporting DLLs live in the BASE conda
#                               install (outside the venv), which PyInstaller
#                               does NOT auto-collect. Without extra binaries
#                               the frozen exe crashes with
#                               "DLL load failed while importing _ctypes".
#
# The spec therefore auto-detects a conda base and only then adds the missing
# files. On a standard CPython venv all the conda blocks below resolve to
# empty, so nothing extra is injected and the default collection is used.
# Override the base root (if auto-detection ever misfires) with YZPLAN_CONDA_ROOT.
_BASE = getattr(_sys, "base_prefix", _sys.prefix)
_IS_CONDA = os.path.isdir(os.path.join(_BASE, "conda-meta")) or os.path.isdir(
    os.path.join(_BASE, "Library", "bin")
)
_CONDA_ROOT = os.environ.get(
    "YZPLAN_CONDA_ROOT", _BASE if _IS_CONDA else os.path.expanduser("~")
)

# conda "Library\bin" DLLs (sqlite3 / libcrypto / libssl / liblzma / bz2 / ffi).
# Only present under conda; resolved to empty on a standard CPython venv where
# PyInstaller auto-collects these from the interpreter itself.
_CONDADLL = os.path.join(_CONDA_ROOT, "Library", "bin")
_CONDADLL_NAMES = (
    "sqlite3.dll",
    "libcrypto-3-x64.dll",
    "libssl-3-x64.dll",
    "liblzma.dll",
    "LIBBZ2.dll",
    "ffi.dll",
)
conda_binaries = [
    (os.path.join(_CONDADLL, name), ".")
    for name in _CONDADLL_NAMES
    if _IS_CONDA and os.path.isfile(os.path.join(_CONDADLL, name))
]

# conda base "DLLs" directory holding the compiled stdlib extension modules
# (_ctypes.pyd, _socket.pyd, _ssl.pyd, select.pyd, ...). Bundle them explicitly
# for conda builds; empty for standard CPython venvs. Skip tkinter/test modules.
_CONDADLLS = os.path.join(_CONDA_ROOT, "DLLs")
conda_stdlib_binaries = [
    (os.path.join(_CONDADLLS, name), ".")
    for name in os.listdir(_CONDADLLS)
    if name.endswith(".pyd")
    and not name.startswith("_tkinter")
    and not name.startswith("_test")
    and not name.startswith("xxlimited")
] if _IS_CONDA and os.path.isdir(_CONDADLLS) else []

a = Analysis(
    [os.path.join(_SPEC_DIR, "main.py")],
    pathex=[_SPEC_DIR],
    binaries=conda_binaries + conda_stdlib_binaries,
    datas=[
        (os.path.join(_VENV, "PySide6", "plugins"), "PySide6\\plugins"),
        (os.path.join(_VENV, "PySide6", "translations"), "translations"),
        (os.path.join(_SPEC_DIR, "qt.conf"), "."),
        (os.path.join(_SPEC_DIR, "data", "favicon.ico"), "data"),
    ],
    hiddenimports=[
        "PySide6",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "PySide6.QtNetwork",
        "shiboken6",
        "win32com",
        "win32clipboard",
        "win32com.client",
        "sqlite3",
        "ctypes.wintypes",
        "modules.path_forward",
        "modules.sys_info",
        "modules.rss_aggregator",
        "modules.page_selector",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "psutil",
        "feedparser",
        "requests",
        "chardet",
        "charset_normalizer",
    ],
    excludes=[
        "tkinter",
        "IPython",
        "PySide6.QtQuick",
        "PySide6.QtQml",
        "PySide6.Qt3DCore",
        "PySide6.QtCharts",
        "PySide6.QtMultimedia",
        "PySide6.QtPdf",
        "PySide6.QtDesigner",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="YZplan",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=os.path.join(_SPEC_DIR, "data", "favicon.ico"),
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="YZplan",
)
