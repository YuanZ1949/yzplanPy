"""home_tab 单元测试：验证 proxy 重建后 boundingRect 更新、排序正确、流式布局。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()

_qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from ui.home_tab import (
    _Proxy, _MIN_W, _MIN_H, _DEF_W, _GAP,
    _FlowLayout, _DRAG_THRESHOLD,
)

import pytest


# ── helpers ──

def _setup():
    scene = QtWidgets.QGraphicsScene()
    view = QtWidgets.QGraphicsView(scene)
    view.resize(800, 600)
    return scene, view


def _add_proxy(scene, x, y, w, h):
    card = QtWidgets.QWidget()
    card.setFixedSize(w, h)
    proxy = QtWidgets.QGraphicsProxyWidget()
    proxy.setWidget(card)
    proxy.setPos(x, y)
    scene.addItem(proxy)
    return proxy, card


# ── 测试 1: proxy rebuild 后 boundingRect 正确 ──

def test_rebuild_updates_bounding_rect():
    scene, _ = _setup()
    proxy, _ = _add_proxy(scene, 0, 0, 340, 240)
    br = proxy.boundingRect()
    assert br.width() == pytest.approx(340, abs=5)
    assert br.height() == pytest.approx(240, abs=5)

    scene.removeItem(proxy)
    proxy2, _ = _add_proxy(scene, 0, 0, 500, 300)
    br2 = proxy2.boundingRect()
    assert br2.width() == pytest.approx(500, abs=5)
    assert br2.height() == pytest.approx(300, abs=5)
    scene.removeItem(proxy2)


# ── 测试 2: 场景 itemsBoundingRect 反映最大 proxy ──

def test_scene_bounding_rect_after_rebuild():
    scene, _ = _setup()
    p1, _ = _add_proxy(scene, 0, 0, 340, 240)
    scene.update()
    assert scene.itemsBoundingRect().width() >= 330

    scene.removeItem(p1)
    p2, _ = _add_proxy(scene, 0, 0, 600, 400)
    scene.update()
    br = scene.itemsBoundingRect()
    assert br.width() >= 590
    assert br.height() >= 390
    scene.removeItem(p2)


# ── 测试 3: 拖拽排序交换 order ──

def test_swap_order():
    order = ["a", "b", "c"]
    di, ti = 0, 2
    order[di], order[ti] = order[ti], order[di]
    assert order == ["c", "b", "a"]


# ── 测试 4: rebuild 保留位置、更新尺寸 ──

def test_rebuild_preserves_position():
    scene, _ = _setup()
    p1, _ = _add_proxy(scene, 120, 80, 340, 240)
    assert p1.pos().x() == 120
    assert p1.pos().y() == 80

    scene.removeItem(p1)
    p2, _ = _add_proxy(scene, 120, 80, 500, 300)
    assert p2.pos().x() == 120
    assert p2.pos().y() == 80
    assert p2.widget().width() == 500
    assert p2.widget().height() == 300
    scene.removeItem(p2)


# ── 测试 5: 多个 proxy scene 范围 ──

def test_multi_proxy_scene_rect():
    scene, _ = _setup()
    p1, _ = _add_proxy(scene, 0, 0, 340, 240)
    p2, _ = _add_proxy(scene, 400, 0, 340, 240)
    scene.update()
    assert scene.itemsBoundingRect().width() >= 740

    scene.removeItem(p2)
    p2b, _ = _add_proxy(scene, 400, 0, 600, 400)
    scene.update()
    br = scene.itemsBoundingRect()
    assert br.width() >= 1000
    assert br.height() >= 400
    scene.removeItem(p1)
    scene.removeItem(p2b)


# ── 测试 6: 用 _Proxy (HomeTab 自定义) 验证移动后 pos 更新 ──

def test_proxy_drag_updates_pos():
    scene, _ = _setup()

    class FakeOwner:
        def _schedule_save(self):
            pass
        def _highlight_swap(self, p):
            pass
        def _finish_swap(self, p):
            pass
        view = type("", (), {"_sync_scene": lambda self: None})()

    owner = FakeOwner()
    proxy = _Proxy(owner)
    card = QtWidgets.QWidget()
    card.setFixedSize(340, 240)
    proxy.setWidget(card)
    proxy.setPos(100, 100)
    scene.addItem(proxy)

    assert proxy.pos().x() == 100
    assert proxy.pos().y() == 100

    proxy.setPos(200, 150)
    assert proxy.pos().x() == 200
    assert proxy.pos().y() == 150
    scene.removeItem(proxy)


# ── 测试 7: 流式布局单行换行（放不下则换行）──

def test_flow_wrap():
    fl = _FlowLayout(gap=12, margin=10)
    items = [("a", 320, 200), ("b", 320, 300), ("c", 320, 150)]
    positions, total_h = fl.compute(items, container_width=400)
    assert len(positions) == 3
    assert positions["a"][1] == 0
    assert positions["b"][1] > positions["a"][1]
    assert positions["c"][1] > positions["b"][1]
    assert total_h > 0


# ── 测试 8: 流式布局多卡片同行排列 ──

def test_flow_same_row():
    fl = _FlowLayout(gap=12, margin=10)
    items = [("a", 320, 200), ("b", 320, 300), ("c", 320, 150)]
    positions, _ = fl.compute(items, container_width=1200)
    assert positions["a"][0] != positions["b"][0]
    assert positions["a"][1] == positions["b"][1] == positions["c"][1]


# ── 测试 9: 流式布局行自动拉伸填满（填充度 >= 80%）──

def test_flow_stretch_fills_row():
    fl = _FlowLayout(gap=12, margin=10)
    items = [("a", 500, 200), ("b", 500, 200), ("c", 500, 200)]
    positions, _ = fl.compute(items, container_width=1600)
    right_edge = positions["c"][0] + positions["c"][2]
    assert right_edge == pytest.approx(1600 - fl.margin, abs=4)


# ── 测试 10: 流式布局末行填充度不足保持左对齐（不拉伸）──

def test_flow_last_row_not_stretched():
    fl = _FlowLayout(gap=12, margin=10)
    items = [("a", 500, 200), ("b", 500, 200), ("c", 500, 200), ("d", 500, 200)]
    positions, _ = fl.compute(items, container_width=1600)
    assert positions["d"][0] == fl.margin
    assert positions["d"][2] == 500


# ── 测试 11: 流式布局宽度不低于最小值 ──

def test_flow_min_width():
    fl = _FlowLayout(gap=12, margin=10)
    items = [("a", 60, 200)]
    positions, _ = fl.compute(items, container_width=500)
    assert positions["a"][2] == _MIN_W


# ── 测试 12: 旧格式迁移（col_span / 数组 → width/height）──

def test_legacy_migration_col_span():
    entry = {"col_span": 2}
    span = entry.pop("col_span")
    width = max(_MIN_W, span * _DEF_W + (span - 1) * _GAP)
    assert width == 2 * _DEF_W + _GAP


def test_legacy_migration_array():
    w = 390
    h = 300
    new_entry = {"width": max(_MIN_W, int(w)), "height": max(_MIN_H, int(h))}
    assert new_entry == {"width": 390, "height": 300}


# ── 测试 13: HomeTab._load col_span → width 迁移 ──

def _load_migration_helper(entry):
    e = dict(entry)
    if "col_span" in e:
        span = max(1, int(e.pop("col_span")))
        e.setdefault("width", span * _DEF_W + (span - 1) * _GAP)
    if "width" in e:
        e["width"] = max(_MIN_W, int(e["width"]))
    if "height" in e:
        e["height"] = max(_MIN_H, int(e["height"]))
    return e


def test_home_migration_map():
    assert _load_migration_helper({"col_span": 1}) == {"width": 340}
    assert _load_migration_helper({"col_span": 2}) == {"width": 688}
    assert _load_migration_helper({"width": 100}) == {"width": _MIN_W}
    assert _load_migration_helper({"height": 50}) == {"height": _MIN_H}


# ── 测试 14: 拖动阈值 —— 点击不触发换序 ──

def _make_proxy(owner, scene, x=0, y=0):
    proxy = _Proxy(owner)
    card = QtWidgets.QWidget()
    card.setFixedSize(340, 240)
    proxy.setWidget(card)
    proxy.setPos(x, y)
    scene.addItem(proxy)
    return proxy


def _press_move_release(proxy, dx, dy):
    press = QtWidgets.QGraphicsSceneMouseEvent()
    press.setButton(QtCore.Qt.LeftButton)
    press.setScenePos(proxy.pos() + proxy.widget().rect().center())
    proxy.mousePressEvent(press)

    move = QtWidgets.QGraphicsSceneMouseEvent()
    move.setButton(QtCore.Qt.NoButton)
    move.setButtons(QtCore.Qt.LeftButton)
    move.setScenePos(press.scenePos() + QtCore.QPointF(dx, dy))
    proxy.mouseMoveEvent(move)

    release = QtWidgets.QGraphicsSceneMouseEvent()
    release.setButton(QtCore.Qt.LeftButton)
    release.setScenePos(move.scenePos())
    proxy.mouseReleaseEvent(release)


def test_proxy_click_no_drag():
    scene, _ = _setup()
    owner = FakeDragOwner()
    proxy = _make_proxy(owner, scene)
    _press_move_release(proxy, 0, 0)
    assert proxy._dragging is False
    assert owner.swap_count == 0
    scene.removeItem(proxy)


def test_proxy_small_move_no_drag():
    scene, _ = _setup()
    owner = FakeDragOwner()
    proxy = _make_proxy(owner, scene)
    _press_move_release(proxy, _DRAG_THRESHOLD - 1, 0)
    assert proxy._dragging is False
    assert owner.swap_count == 0
    scene.removeItem(proxy)


def test_proxy_real_drag_triggers():
    scene, _ = _setup()
    owner = FakeDragOwner()
    proxy = _make_proxy(owner, scene)
    _press_move_release(proxy, _DRAG_THRESHOLD + 10, 0)
    assert owner.swap_count == 1
    scene.removeItem(proxy)


def test_proxy_move_event_real_button_state():
    scene, _ = _setup()
    owner = FakeDragOwner()
    proxy = _make_proxy(owner, scene)

    press = QtWidgets.QGraphicsSceneMouseEvent()
    press.setButton(QtCore.Qt.LeftButton)
    press.setScenePos(proxy.pos() + proxy.widget().rect().center() + QtCore.QPointF(3, 3))
    proxy.mousePressEvent(press)

    move = QtWidgets.QGraphicsSceneMouseEvent()
    move.setButton(QtCore.Qt.NoButton)
    move.setButtons(QtCore.Qt.LeftButton)
    move.setScenePos(press.scenePos() + QtCore.QPointF(_DRAG_THRESHOLD + 6, 0))
    proxy.mouseMoveEvent(move)
    assert proxy._dragging is True

    release = QtWidgets.QGraphicsSceneMouseEvent()
    release.setButton(QtCore.Qt.LeftButton)
    release.setScenePos(move.scenePos())
    proxy.mouseReleaseEvent(release)
    assert owner.swap_count == 1
    scene.removeItem(proxy)


class FakeDragOwner:
    def __init__(self):
        self.swap_count = 0
        self._order = []
        self._swap_line = None

    def _schedule_save(self, *a, **k):
        pass

    def _highlight_swap(self, p):
        pass

    def _finish_swap(self, p):
        self.swap_count += 1

    def _relayout_all(self):
        pass

    def _save_order(self):
        pass

    def _find_swap_target(self, p, cid):
        return None
