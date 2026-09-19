"""截图模块：全屏拖拽选区覆盖层（region_overlay.RegionOverlay）测试。

覆盖：
1) 拖拽 press(100,100) → release(300,250) 发射 QRect(100,100,200,150)（Qt 归一化）；
2) 反向拖拽（从右下到左上）同样归一化；
3) Esc 取消：不发射 rect 且覆盖层关闭；
4) 右键取消：不发射 rect 且覆盖层关闭。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from modules.screenshot.region_overlay import RegionOverlay


def _press(widget, x, y, button=QtCore.Qt.LeftButton):
    ev = QtGui.QMouseEvent(QtCore.QEvent.MouseButtonPress,
                           QtCore.QPointF(x, y), QtCore.QPointF(x, y),
                           button, button, QtCore.Qt.NoModifier)
    widget.mousePressEvent(ev)


def _move(widget, x, y):
    ev = QtGui.QMouseEvent(QtCore.QEvent.MouseMove,
                           QtCore.QPointF(x, y), QtCore.QPointF(x, y),
                           QtCore.Qt.NoButton, QtCore.Qt.LeftButton,
                           QtCore.Qt.NoModifier)
    widget.mouseMoveEvent(ev)


def _release(widget, x, y):
    ev = QtGui.QMouseEvent(QtCore.QEvent.MouseButtonRelease,
                           QtCore.QPointF(x, y), QtCore.QPointF(x, y),
                           QtCore.Qt.LeftButton, QtCore.Qt.NoButton,
                           QtCore.Qt.NoModifier)
    widget.mouseReleaseEvent(ev)


def _escape(widget):
    ev = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Escape,
                         QtCore.Qt.NoModifier)
    widget.keyPressEvent(ev)


def _make_overlay(qapp):
    overlay = RegionOverlay()
    overlay.show()
    qapp.processEvents()
    assert overlay.isVisible()
    return overlay


def test_drag_emits_normalized_rect(qapp):
    overlay = _make_overlay(qapp)
    received = []
    overlay.region_selected.connect(received.append)
    _press(overlay, 100, 100)
    _move(overlay, 300, 250)
    _release(overlay, 300, 250)
    assert received == [QtCore.QRect(100, 100, 200, 150)]
    assert not overlay.isVisible(), "释放后覆盖层应关闭"


def test_reverse_drag_normalizes(qapp):
    overlay = _make_overlay(qapp)
    received = []
    overlay.region_selected.connect(received.append)
    _press(overlay, 300, 250)
    _move(overlay, 100, 100)
    _release(overlay, 100, 100)
    assert received == [QtCore.QRect(100, 100, 200, 150)]
    assert not overlay.isVisible()


def test_escape_cancels_without_emitting(qapp):
    overlay = _make_overlay(qapp)
    received = []
    cancelled = []
    overlay.region_selected.connect(received.append)
    overlay.cancelled.connect(lambda: cancelled.append(1))
    _press(overlay, 100, 100)
    _escape(overlay)
    assert received == [], "Esc 取消后不应发射选区"
    assert cancelled == [1], "Esc 应发射 cancelled"
    assert not overlay.isVisible(), "Esc 后覆盖层应关闭"


def test_right_click_cancels_without_emitting(qapp):
    overlay = _make_overlay(qapp)
    received = []
    cancelled = []
    overlay.region_selected.connect(received.append)
    overlay.cancelled.connect(lambda: cancelled.append(1))
    _press(overlay, 100, 100)
    _press(overlay, 200, 200, button=QtCore.Qt.RightButton)
    assert received == [], "右键取消后不应发射选区"
    assert cancelled == [1], "右键应发射 cancelled"
    assert not overlay.isVisible(), "右键后覆盖层应关闭"