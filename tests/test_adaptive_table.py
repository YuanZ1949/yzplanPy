import sys

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()
from ui.adaptive_table import make_adaptive_table


def _make_qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    return app


def _build(ncols=4, nrows=5):
    table = QtWidgets.QTableWidget()
    table.setColumnCount(ncols)
    table.setHorizontalHeaderLabels([f"C{i}" for i in range(ncols)])
    table.setRowCount(nrows)
    for r in range(nrows):
        for c in range(ncols):
            table.setItem(r, c, QtWidgets.QTableWidgetItem(f"cell {r}-{c}"))
    return table


def test_all_columns_interactive():
    _make_qapp()
    table = _build()
    filt = make_adaptive_table(table)
    assert filt is not None
    header = table.horizontalHeader()
    for c in range(table.columnCount()):
        assert header.sectionResizeMode(c) == QtWidgets.QHeaderView.Interactive


def test_first_measure_sets_bases_and_reflow():
    _make_qapp()
    table = _build()
    filt = make_adaptive_table(table)
    table.resize(600, 300)
    table.show()
    # 触发首次测量 + reflow
    QtCore.QTimer.singleShot(50, QtWidgets.QApplication.quit)
    QtWidgets.QApplication.exec()
    assert filt._ready
    assert filt._base_widths is not None
    assert len(filt._base_widths) == table.columnCount()
    # 右边界贴合 viewport
    total = sum(filt._header.sectionSize(c) for c in range(table.columnCount()))
    assert abs(total - table.viewport().width()) <= 2


def test_user_drag_updates_base():
    _make_qapp()
    table = _build(ncols=3)
    filt = make_adaptive_table(table)
    table.resize(600, 300)
    table.show()
    QtCore.QTimer.singleShot(50, QtWidgets.QApplication.quit)
    QtWidgets.QApplication.exec()
    assert filt._base_widths is not None
    before = filt._base_widths[1]
    # 模拟用户拖拽：触发 sectionResized（绕过缩放标志）
    filt._resizing = False
    filt._header.resizeSection(1, before + 30)  # 直接改宽度会触发 sectionResized
    assert filt._base_widths[1] == before + 30


def test_resize_scales_proportionally():
    _make_qapp()
    table = _build(ncols=3)
    filt = make_adaptive_table(table)
    table.resize(600, 300)
    table.show()
    QtCore.QTimer.singleShot(50, QtWidgets.QApplication.quit)
    QtWidgets.QApplication.exec()
    assert filt._base_widths is not None
    base = list(filt._base_widths)
    total_before = sum(base)
    # 拉伸窗口宽度
    table.resize(900, 300)
    QtCore.QTimer.singleShot(50, QtWidgets.QApplication.quit)
    QtWidgets.QApplication.exec()
    now = [filt._header.sectionSize(c) for c in range(3)]
    total_after = sum(now)
    # 整体放大；各列比例约等于原比例（容忍取整）
    assert total_after > total_before
    for c in range(3):
        if c < 2:
            ratio_before = base[c] / total_before
            ratio_after = now[c] / total_after
            assert abs(ratio_after - ratio_before) < 0.05
    # 右边界贴合新宽度
    assert abs(total_after - table.viewport().width()) <= 2


def _total_width(h):
    return sum(h.sectionSize(c) for c in range(h.count()))


def _reflow_driver(win, table, filt, width):
    win.resize(width, 300)
    # 处理事件：延迟 reflow 应在此后落定
    for _ in range(5):
        QtWidgets.QApplication.processEvents()


def test_resize_reflows_to_hug_viewport():
    # 回归：表格 Resize 事件触发时 viewport 仍为旧宽，reflow 必须延迟到落定后，
    # 否则列宽恒为旧值（窗口特定宽度处“卡住/突然还原”）。
    _make_qapp()
    win = QtWidgets.QWidget()
    lay = QtWidgets.QVBoxLayout(win)
    table = _build(ncols=4)
    lay.addWidget(table, 1)
    filt = make_adaptive_table(table)
    win.resize(700, 300)
    win.show()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    h = table.horizontalHeader()
    _reflow_driver(win, table, filt, 400)
    assert abs(_total_width(h) - table.viewport().width()) <= 2
    _reflow_driver(win, table, filt, 900)
    assert abs(_total_width(h) - table.viewport().width()) <= 2
    _reflow_driver(win, table, filt, 380)
    assert abs(_total_width(h) - table.viewport().width()) <= 2


def test_drag_base_preserved_after_reflow():
    # 用户拖拽某列 → 记录为基准；后续 resize 后仍保持该相对比例
    _make_qapp()
    win = QtWidgets.QWidget()
    lay = QtWidgets.QVBoxLayout(win)
    table = _build(ncols=3)
    lay.addWidget(table, 1)
    filt = make_adaptive_table(table)
    win.resize(700, 300)
    win.show()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    h = table.horizontalHeader()
    col0 = _total_width(h)
    # 模拟用户拉宽第 0 列
    filt._resizing = False
    h.resizeSection(0, h.sectionSize(0) + 60)
    assert filt._base_widths is not None
    dragged_base = filt._base_widths[0]
    assert dragged_base > 0
    # 重新缩放窗口后仍贴合
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    _reflow_driver(win, table, filt, 900)
    assert abs(_total_width(h) - table.viewport().width()) <= 2


class FakeConfig:
    """扁平 dot-path 键的配置替身。"""

    def __init__(self):
        self._data = {}

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value


def _persist_ready(filt, cfg, key):
    """完成首次测量 + 一次用户拖拽，直接触发保存（绕过 600ms 防抖）。"""
    win = QtWidgets.QWidget()
    lay = QtWidgets.QVBoxLayout(win)
    table = filt.table
    lay.addWidget(table, 1)
    win.resize(700, 300)
    win.show()
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    h = table.horizontalHeader()
    filt._resizing = False
    h.resizeSection(1, h.sectionSize(1) + 30)
    filt._save()
    return table, win


def test_persist_key_saves_and_restores_roundtrip():
    # 1) 表 A：拖拽后保存列宽到配置
    _make_qapp()
    cfg = FakeConfig()
    table_a = _build(ncols=3)
    filt_a = make_adaptive_table(table_a, persist_key="t.widths", config=cfg)
    table_a, win_a = _persist_ready(filt_a, cfg, "t.widths")
    saved = cfg.get("t.widths")
    assert isinstance(saved, list) and len(saved) == 3
    assert filt_a._base_widths is not None
    assert saved == [int(w) for w in filt_a._base_widths]
    win_a.close()

    # 2) 表 B：同一 persist_key + config → 直接加载已存宽度，无需重测
    table_b = _build(ncols=3)
    filt_b = make_adaptive_table(table_b, persist_key="t.widths", config=cfg)
    assert filt_b._ready, "持久化表应跳过首次测量直接就绪"
    assert filt_b._base_widths == saved


def test_persist_key_without_config_is_noop():
    # 只传 persist_key 不传 config → 与现在的行为一致（不持久化、不崩溃）
    _make_qapp()
    table = _build(ncols=3)
    filt = make_adaptive_table(table, persist_key="t.widths")
    assert filt._persist_key == "t.widths"
    assert filt._config is None
    assert filt._save_timer is None or not filt._save_timer.isActive()


def test_no_persist_key_unchanged_behavior():
    # 不传 persist_key：拖拽后不写任何配置，也不创建定时器
    _make_qapp()
    cfg = FakeConfig()
    table = _build(ncols=3)
    filt = make_adaptive_table(table, config=cfg)
    filt._save()  # 应是无操作
    assert not cfg._data
    assert filt._persist_key is None

