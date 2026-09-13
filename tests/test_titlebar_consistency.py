"""标题栏结构性护栏（离屏回归锁，不依赖平台字体）。

锁定三类历史事故的契约：
T1 弹片系控件样式一致性——combo/下拉按钮必须与 `_migrated_btn_qss` 同一款
   透明 QSS（防"全部"下拉框 Fluent 白底弹片盒 + 内容盒 31px>28px 下边框
   截断事故回归；也防"单独漏换 QSS"）。
T2 右锚布局契约——hBoxLayout 弹性 stretch 必须在 vBoxLayout 之前存在、
   buttonLayout 必须 AlignRight|AlignVCenter（防 36px 贴不到右缘事故回归）。
T3 高度契约——全部迁移控件高度统一 == rss_compact_btn_height（防错位）。
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing

_, QtCore, QtGui, QtWidgets = import_qt()

from PySide6.QtWidgets import QApplication

_qapp = QApplication.instance() or QApplication(sys.argv)

from titlebar_helpers import _DuckPage, migrated_controls, make_module_window


def _opened_page():
    dlg = make_module_window("rss_consistency")
    try:
        return dlg, dlg.findChild(_DuckPage)
    finally:
        pass  # 由调用方 hide/deleteLater


def test_migrated_controls_share_uniform_qss():
    """T1：combo 与 5 个弹片按钮全部使用同一款迁移 QSS（半透明底 + 1px 边框）。

    根因事故：combo 只 setFixedWidth/Height 未换 QSS，遗留 Fluent 白底弹片盒
    与 border-bottom → 下拉框"太大/不一样、下边框被截断"。
    """
    dlg, page = _opened_page()
    try:
        buttons = (page.btn_date_filter, page.btn_filter, page.btn_read_ops,
                   page.btn_batch_ops, page.btn_thumb)
        qss = page.combo_search_field.styleSheet()
        # 迁移 QSS 契约：半透明底 + 1px 边框 + 左对齐 + 右 padding 预留自绘箭头区
        # （Fluent DropDownButtonBase 箭头自绘于 width()-22，sizeHint 不含箭头宽）
        assert "border: 1px solid" in qss, qss
        assert "text-align: left" in qss, qss
        assert "padding: 0 26px 0 8px" in qss, qss
        for b in buttons:
            assert b.styleSheet() == qss, (
                f"{b} 的 QSS 与 combo 不一致：{'<空>' if not b.styleSheet() else b.styleSheet()}")
    finally:
        dlg.hide()
        dlg.deleteLater()


def test_migrated_controls_uniform_height():
    """T3：combo / 搜索框 / 5 弹片按钮高度统一 == rss_compact_btn_height。"""
    dlg, page = _opened_page()
    try:
        target = int(sizing()["rss_compact_btn_height"])
        for w in migrated_controls(page) + (page.search_input,):
            assert w.height() == target, (
                f"{w.__class__.__name__} 高 {w.height()}px != rss_compact_btn_height({target})")
    finally:
        dlg.hide()
        dlg.deleteLater()


def test_titlebar_right_anchor_layout_contract():
    """T2：右锚契约——Expanding stretch 在 vBox 之前 + buttonLayout 右对齐垂直居中。

    根因事故：迁移控件时移除 stretch 且未恢复 → vBoxLayout 不伸展（QLayout
    sizePolicy 默认 Preferred），按钮停留在距右缘 36px 处。
    """
    dlg = make_module_window("rss_cons_anchor")
    try:
        tb = dlg.titleBar
        hl = tb.hBoxLayout
        vbox_idx = None
        stretch_before_vbox = False
        for i in range(hl.count()):
            item = hl.itemAt(i)
            if item.layout() is tb.vBoxLayout:
                vbox_idx = i
                break
            sp = item.spacerItem()
            if sp is not None and sp.sizePolicy().horizontalPolicy() == QtWidgets.QSizePolicy.Expanding:
                stretch_before_vbox = True
        assert vbox_idx is not None, "hBoxLayout 中找不到 vBoxLayout"
        assert stretch_before_vbox, "vBoxLayout 之前缺失弹性 stretch——按钮将无法贴右缘"

        bl = tb.buttonLayout
        assert bl is not None
        assert bl.alignment() == (
            QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter), (
            f"buttonLayout.alignment()={bl.alignment()}"
            f" 应为 AlignRight|AlignVCenter")
        # vBoxLayout 内不应残留 stretch（stretch 兄弟会吸走垂直 slack，AlignVCenter 失效）
        vb = tb.vBoxLayout
        for i in range(vb.count()):
            assert vb.itemAt(i).spacerItem() is None, (
                "vBoxLayout 残留 stretch——按钮组垂直对齐失效")
    finally:
        dlg.hide()
        dlg.deleteLater()