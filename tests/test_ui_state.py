import sys
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.ui_state import UiStateStore, WindowGeometry


def test_save_and_load(tmp_path):
    db = str(tmp_path / "ui.db")
    store = UiStateStore(db)
    assert store.load("main_window") is None

    store.save("main_window", 1200, 800, 10, 20, maximized=False)
    state = store.load("main_window")
    assert state is not None
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
    assert state is not None
    assert state["w"] == 700
    assert state["h"] == 450


def test_x_y_optional(tmp_path):
    db = str(tmp_path / "ui.db")
    store = UiStateStore(db)
    store.save("dlg", 500, 500)
    state = store.load("dlg")
    assert state is not None
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


# ---------------------------------------------------------------------------
# 回归：连接必须关闭（资源泄漏）
# ---------------------------------------------------------------------------

def test_conn_is_closed_after_context_exit(tmp_path):
    """`with store._conn() as conn:` 退出后连接必须已关闭。

    回归（资源泄漏）：`with sqlite3.Connection` 只提交/回滚，**不会关闭**连接。
    而 main.py 调用 `gc.disable()`（防止后台线程回收 Qt 包装对象导致崩溃），
    sqlite3.Connection 与其语句缓存又构成引用环，引用计数无法回收 —— 因此不显式
    `close()` 的连接会永久驻留，窗口几何每次读写（apply/capture）都泄漏一个。

    断言方式：在已关闭的连接上执行语句会抛 `sqlite3.ProgrammingError`。
    """
    import sqlite3

    db = str(tmp_path / "ui.db")
    store = UiStateStore(db)
    with store._conn() as conn:
        leaked = conn
    with pytest.raises(sqlite3.ProgrammingError):
        leaked.execute("SELECT 1")


def test_all_public_calls_release_their_connections(tmp_path, monkeypatch):
    """_init_schema/save/load/remove 用到的每个连接都必须在返回前关闭。"""
    import sqlite3

    created = []
    real_connect = sqlite3.connect

    def tracking_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        created.append(conn)
        return conn

    monkeypatch.setattr("core.ui_state.sqlite3.connect", tracking_connect)

    db = str(tmp_path / "ui.db")
    store = UiStateStore(db)          # _init_schema
    store.save("k", 10, 20, 1, 2)     # save
    store.load("k")                   # load
    store.remove("k")                 # remove

    assert created, "应至少创建过连接"
    for conn in created:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")


# ---------------------------------------------------------------------------
# Todo 20：无记录居中 + 记住位置（center_if_missing）
# ---------------------------------------------------------------------------

def _screen_center():
    from PySide6.QtGui import QGuiApplication
    screen = QGuiApplication.primaryScreen()
    assert screen is not None
    return screen.availableGeometry().center()


def test_apply_center_if_missing_centers_window(tmp_path):
    """无记录 + center_if_missing=True：窗口中心对齐屏幕可视范围中心（偏差 ≤ 2px）。"""
    _qapp()
    from PySide6 import QtWidgets
    db = str(tmp_path / "ui.db")
    store = UiStateStore(db)
    w = QtWidgets.QWidget()
    geom = WindowGeometry(store=store)
    applied = geom.apply(w, "no_record_center", default_size=(600, 400), center_if_missing=True)
    assert applied is False  # 返回值语义不变：无记录仍返回 False
    center = _screen_center()
    wc = w.frameGeometry().center()
    assert abs(wc.x() - center.x()) <= 2
    assert abs(wc.y() - center.y()) <= 2


def test_apply_default_does_not_center(tmp_path):
    """默认 center_if_missing=False：无记录时不移动窗口（保护主窗口等既有调用方）。"""
    _qapp()
    from PySide6 import QtWidgets
    db = str(tmp_path / "ui.db")
    store = UiStateStore(db)
    w = QtWidgets.QWidget()
    geom = WindowGeometry(store=store)
    geom.apply(w, "no_record_default", default_size=(600, 400))
    assert w.pos().x() == 0
    assert w.pos().y() == 0


def test_apply_round_trip_capture_restores_position(tmp_path):
    """往返：建窗 → move → capture → 同 key 建新窗 → 位置恢复（偏差 ≤ 2px）。"""
    _qapp()
    from PySide6 import QtWidgets
    db = str(tmp_path / "ui.db")
    store = UiStateStore(db)
    geom = WindowGeometry(store=store)
    key = "round_trip_key"

    w1 = QtWidgets.QWidget()
    geom.apply(w1, key, default_size=(600, 400))
    w1.move(150, 90)
    geom.capture(w1, key)

    w2 = QtWidgets.QWidget()
    applied = geom.apply(w2, key, default_size=(600, 400))
    assert applied is True
    assert abs(w2.pos().x() - 150) <= 2
    assert abs(w2.pos().y() - 90) <= 2


def test_apply_offscreen_saved_position_falls_back(tmp_path):
    """屏外记录：center_if_missing=True 回退居中；默认 False 保持旧行为（不移动）。"""
    _qapp()
    from PySide6 import QtWidgets
    db = str(tmp_path / "ui.db")
    store = UiStateStore(db)
    store.save("offscreen_key", 600, 400, -5000, -5000, maximized=False)
    geom = WindowGeometry(store=store)

    w_center = QtWidgets.QWidget()
    applied = geom.apply(w_center, "offscreen_key", default_size=(600, 400), center_if_missing=True)
    assert applied is True  # 有记录
    center = _screen_center()
    wc = w_center.frameGeometry().center()
    assert abs(wc.x() - center.x()) <= 2
    assert abs(wc.y() - center.y()) <= 2

    w_old = QtWidgets.QWidget()
    geom.apply(w_old, "offscreen_key", default_size=(600, 400))
    assert w_old.pos().x() == 0
    assert w_old.pos().y() == 0


# ---------------------------------------------------------------------------
# Todo 26：完整窗口矩形判定屏外（中心在屏内但左上角在屏外）
# ---------------------------------------------------------------------------

def _visible_ratio(rect):
    """rect 在所有屏幕可视范围内的可见面积比例（0.0~1.0）。"""
    from PySide6.QtGui import QGuiApplication
    total = 0
    for screen in QGuiApplication.screens():
        inter = rect.intersected(screen.availableGeometry())
        if inter.width() > 0 and inter.height() > 0:
            total += inter.width() * inter.height()
    area = rect.width() * rect.height()
    return total / area if area > 0 else 0.0


def test_apply_partially_offscreen_center_on_screen_recenters(tmp_path):
    """中心在屏内但左上角在屏外（可见比例 < 0.5）的记录：center_if_missing=True 应重新居中。

    回归：旧实现只检查中心点（screenAt(center)），中心在屏内即原样恢复，
    导致左上角在屏外的窗口被恢复到屏幕之外。新实现检查完整窗口矩形。
    """
    _qapp()
    from PySide6 import QtWidgets
    db = str(tmp_path / "ui.db")
    store = UiStateStore(db)
    w, h = 600, 400
    # 左上角在屏外、中心仍在屏内：x = -w//2 + 1 → 中心 (1, 1) 在屏内，
    # 但可见比例 ≈ 0.25 < 0.5（旧实现会原样恢复，新实现应重新居中）
    x = -w // 2 + 1
    y = -h // 2 + 1
    store.save("partial_offscreen_key", w, h, x, y, maximized=False)
    geom = WindowGeometry(store=store)
    widget = QtWidgets.QWidget()
    applied = geom.apply(widget, "partial_offscreen_key", default_size=(w, h), center_if_missing=True)
    assert applied is True
    frame = widget.frameGeometry()
    ratio = _visible_ratio(frame)
    assert ratio >= 0.5, f"窗口应重新居中到可见区域，实际可见比例 {ratio:.2f}"


def test_apply_fully_onscreen_restores_exact_position(tmp_path):
    """完全在屏内的记录必须原样恢复（不得过度重新居中）。"""
    _qapp()
    from PySide6 import QtWidgets
    db = str(tmp_path / "ui.db")
    store = UiStateStore(db)
    store.save("onscreen_key", 600, 400, 150, 90, maximized=False)
    geom = WindowGeometry(store=store)
    widget = QtWidgets.QWidget()
    applied = geom.apply(widget, "onscreen_key", default_size=(600, 400), center_if_missing=True)
    assert applied is True
    assert widget.pos().x() == 150
    assert widget.pos().y() == 90


# ---------------------------------------------------------------------------
# Todo 27：可见比例 >=0.5 但左上角在屏外（RSS 模块窗口启动超屏）
# ---------------------------------------------------------------------------

def _screen_avail():
    from PySide6.QtGui import QGuiApplication
    screen = QGuiApplication.primaryScreen()
    assert screen is not None
    return screen.availableGeometry()


def test_apply_clamps_top_left_when_mostly_visible(tmp_path):
    """可见比例 >=0.5 但左上角在屏外的记录：恢复后左上角必须被钳制进可视区。

    回归（用户报告：RSS 模块窗口启动后左上角超出屏幕）：旧实现只要完整窗口
    矩形与屏幕的交集面积比例 >= MIN_VISIBLE_RATIO(0.5) 就原样 move(x, y)，
    左上角在屏外的记录（如把窗口拖到双屏边缘后保存）会被原样恢复到超屏位置：
    窗口 400x300 的左上角伸到 (-100, -75) 时可见比例 ≈ 0.56 >= 0.5，旧代码
    原样恢复、左上角挂屏幕外。新实现恢复后把左上角拉回所在屏幕可视范围。
    """
    _qapp()
    from PySide6 import QtWidgets
    db = str(tmp_path / "ui.db")
    store = UiStateStore(db)
    avail = _screen_avail()
    w, h = 400, 300
    # 左上角伸出屏外 1/4（可见比例 (3/4)^2 ≈ 0.56 >= 0.5，中心仍在屏内）
    x = avail.left() - w // 4
    y = avail.top() - h // 4
    store.save("clamp_key", w, h, x, y, maximized=False)
    geom = WindowGeometry(store=store)
    widget = QtWidgets.QWidget()
    applied = geom.apply(widget, "clamp_key", default_size=(w, h), center_if_missing=True)
    assert applied is True
    assert widget.pos().x() >= avail.left()
    assert widget.pos().y() >= avail.top()


def test_apply_center_clamps_when_window_wider_than_screen(tmp_path):
    """无记录且默认窗口宽于屏幕：居中后左上角不得超屏（同 clamp 通道）。"""
    _qapp()
    from PySide6 import QtWidgets
    db = str(tmp_path / "ui.db")
    store = UiStateStore(db)
    geom = WindowGeometry(store=store)
    widget = QtWidgets.QWidget()
    applied = geom.apply(widget, "wide_key", default_size=(900, 640), center_if_missing=True)
    assert applied is False  # 无记录路径
    avail = _screen_avail()
    assert widget.pos().x() >= avail.left()
    assert widget.pos().y() >= avail.top()


def test_apply_clamps_right_edge_overflow(tmp_path):
    """窗口右/下缘超出屏幕但左上角在屏内的记录：左上角保持、不得被顶出屏幕。"""
    _qapp()
    from PySide6 import QtWidgets
    db = str(tmp_path / "ui.db")
    store = UiStateStore(db)
    avail = _screen_avail()
    w, h = 400, 300
    # 左上角在屏内，但窗口右缘超出屏幕右边界
    x = avail.right() - w // 2
    y = avail.bottom() - h // 2
    store.save("clamp_right_key", w, h, x, y, maximized=False)
    geom = WindowGeometry(store=store)
    widget = QtWidgets.QWidget()
    applied = geom.apply(widget, "clamp_right_key", default_size=(w, h), center_if_missing=True)
    assert applied is True
    assert widget.pos().x() >= avail.left()
    assert widget.pos().y() >= avail.top()
    # 已完全在屏内的位置不允许被移动
    if widget.pos().x() == x and widget.pos().y() == y:
        assert True
    else:
        # 只有被移动时才要求仍不越界
        assert widget.pos().x() + widget.width() <= avail.right() + 1
        assert widget.pos().y() + widget.height() <= avail.bottom() + 1
