"""Qt bootstrap: workaround for Windows system-built icuuc.dll resolution
bug (import chain of Qt6Core fails with WinError 127 unless icuuc.dll is
preloaded into the process first).
"""
import ctypes
import importlib.util
import os
import sys

_PRED = None
_LOADED_QT = None


def _find_pyside6_dir():
    spec = importlib.util.find_spec("PySide6")
    if spec and spec.submodule_search_locations:
        for loc in spec.submodule_search_locations:
            return str(loc)
    site = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "site-packages")
    return os.path.abspath(site)


def _force_dll_directory():
    d = _find_pyside6_dir()
    if os.path.isdir(d):
        os.add_dll_directory(d)
    return d


def _preload_icu():
    s32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    for name in ("icuuc.dll", "icuin.dll", "icu.dll"):
        path = os.path.join(s32, name)
        if os.path.exists(path):
            try:
                ctypes.WinDLL(path)
            except OSError:
                pass


# Windows 系统 Qt6Core 需要 ICU：qfluentwidgets 等库顶层直接 import PySide6，
# 必须在任何 Qt 导入前先预载，否则触发 WinError 127（入口点找不到）。
if sys.platform == "win32":
    _preload_icu()


def _detect_proc_not_found(exc):
    msg = str(exc).lower()
    return "dll load failed" in msg or "procedure" in msg or "import" in exc.__class__.__name__ in ("ImportError",)


def import_qt(retry=True):
    """Import PySide6 modules with a fallback that preloads the ICU DLLs."""
    global _LOADED_QT, _PRED
    if _LOADED_QT is not None:
        return _LOADED_QT
    try:
        import PySide6
        from PySide6 import QtCore, QtGui, QtWidgets
    except ImportError:
        if not retry:
            raise
        _force_dll_directory()
        _preload_icu()
        import PySide6
        from PySide6 import QtCore, QtGui, QtWidgets
    _LOADED_QT = (PySide6, QtCore, QtGui, QtWidgets)
    return _LOADED_QT