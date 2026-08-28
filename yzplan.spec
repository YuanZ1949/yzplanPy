# -*- mode: python ; coding: utf-8 -*-
# yzplan onedir spec

import os

_SPEC_DIR = os.path.abspath(SPECPATH)
_VENV = os.path.join(_SPEC_DIR, ".venv", "Lib", "site-packages")
# Path to the conda/anaconda "Library\bin" directory that provides sqlite3.dll,
# libcrypto, libssl, liblzma, LIBBZ2 and ffi.dll for the PyInstaller build.
# Make it portable across machines: set the YZPLAN_CONDA_BIN environment
# variable before building (e.g. YZPLAN_CONDA_BIN="C:\...\anaconda3\Library\bin"),
# otherwise fall back to the factory default below.
_CONDADLL = os.environ.get(
    "YZPLAN_CONDA_BIN",
    os.path.join(os.path.expanduser("~"), "anaconda3", "Library", "bin"),
)

a = Analysis(
    [os.path.join(_SPEC_DIR, "main.py")],
    pathex=[_SPEC_DIR],
    binaries=[
        (os.path.join(_CONDADLL, "sqlite3.dll"), "."),
        (os.path.join(_CONDADLL, "libcrypto-3-x64.dll"), "."),
        (os.path.join(_CONDADLL, "libssl-3-x64.dll"), "."),
        (os.path.join(_CONDADLL, "liblzma.dll"), "."),
        (os.path.join(_CONDADLL, "LIBBZ2.dll"), "."),
        (os.path.join(_CONDADLL, "ffi.dll"), "."),
    ],
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
        "psutil",
        "feedparser",
        "requests",
        "chardet",
        "charset_normalizer",
    ],
    excludes=[
        "tkinter",
        "IPython",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
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
