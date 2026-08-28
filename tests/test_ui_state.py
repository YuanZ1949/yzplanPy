import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.ui_state import UiStateStore


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
