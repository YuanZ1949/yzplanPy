import sys
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.ui_state import UiStateStore, WindowGeometry


def test_save_and_load(tmp_path):
    db = str(tmp_path / "ui.db")
    store = UiStateStore(db)
    assert store.load("main_window") is None

    store.save("main_window", 1200, 800, 10, 20, maximized=False)
    state = store.load("main_window")
    assert state["w"] == 1200
    assert state["h"] == 800
    assert state["x"] == 10
    assert state["y"] == 20
    assert state["maximized"] is False


def test_update_existing_key(tmp_path):
    db = str(tmp_path / "ui.db")
    store = UiStateStore(db)
    store.save("dlg", 600, 400, 0, 0)
    store.save("dlg", 700, 450, 5, 5)
    state = store.load("dlg")
    assert state["w"] == 700
    assert state["h"] == 450


def test_x_y_optional(tmp_path):
    db = str(tmp_path / "ui.db")
    store = UiStateStore(db)
    store.save("dlg", 500, 500)
    state = store.load("dlg")
    assert state["x"] is None
    assert state["y"] is None


def test_remove(tmp_path):
    db = str(tmp_path / "ui.db")
    store = UiStateStore(db)
    store.save("dlg", 500, 500)
    assert store.load("dlg") is not None
    store.remove("dlg")
    assert store.load("dlg") is None


def _qapp():
    from core.qt_bootstrap import import_qt
    _, QtCore, QtGui, QtWidgets = import_qt()
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def test_apply_min_fit_ratio_vetoes_small_saved_size(tmp_path):
    """保存尺寸相对屏幕偏小时，min_fit_ratio 应让 apply 返回 False（交给调用方自适应）。"""
    _qapp()
    from PySide6 import QtWidgets
    db = str(tmp_path / "ui.db")
    store = UiStateStore(db)
    # 保存一个很小(相对屏幕)的尺寸
    store.save("main_window", 320, 240, 0, 0, maximized=False)
    w = QtWidgets.QWidget()
    geom = WindowGeometry(store=store)
    # 极小尺寸应被拒绝恢复
    applied = geom.apply(w, "main_window", min_fit_ratio=0.9)
    assert applied is False


def test_apply_min_fit_ratio_keeps_large_saved_size(tmp_path):
    _qapp()
    from PySide6 import QtWidgets
    db = str(tmp_path / "ui.db")
    store = UiStateStore(db)
    store.save("main_window", 9999, 9999, 0, 0, maximized=False)
    w = QtWidgets.QWidget()
    geom = WindowGeometry(store=store)
    applied = geom.apply(w, "main_window", min_fit_ratio=0.1)
    assert applied is True
    assert w.width() == 9999
