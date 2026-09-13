"""windows QPA 标题栏像素级取证测试（L2，真实字体/真实样式渲染）。

覆盖离屏结构性护栏抓不到的"真实渲染"类事故：
- Fluent ComboBox 白底弹片盒（"全部"下拉框比其他按钮大）→ alpha 采样
- border-bottom 被 28px 高截断（下边框截断）→ 底部行 alpha 采样
- 文字与自绘箭头重叠 → 真实 fontMetrics 几何
- 内容垂直居中 → 非透明像素包围盒

要求独立进程：QT_QPA_PLATFORM=windows 必须在首个 Qt 初始化前设置；
若本进程 QApplication 已被 offscreen 测试先行创建 → 整模块 skip。
"""

import os
import sys

from PySide6.QtWidgets import QApplication

if QApplication.instance() is not None:
    import pytest

    pytest.skip("qpa 像素测试需独立进程（本进程已存在 offscreen QApplication）",
                allow_module_level=True)

os.environ["QT_QPA_PLATFORM"] = "windows"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from _qpa_pixel import (
    assert_content_vcentered,
    assert_no_bottom_border,
    assert_no_box_background,
    assert_text_not_overlapped_by_arrow,
    grab,
)
from titlebar_helpers import _DuckPage, migrated_controls, make_module_window

_app = QApplication.instance() or QApplication(sys.argv)


@pytest.fixture()
def shown_window():
    dlg = make_module_window("rss_qpa_render")
    dlg.show()
    _app.processEvents()
    yield dlg
    dlg.hide()
    dlg.deleteLater()
    _app.processEvents()


@pytest.mark.qpa
def test_combo_has_no_white_box_background(shown_window):
    """T4：'全部'下拉框无 Fluent 白底弹片盒（曾比邻居按钮大、下边框截断）。"""
    page = shown_window.findChild(_DuckPage)
    combo = page.combo_search_field
    img = grab(combo)
    assert_no_box_background(img, combo.width(), combo.height())


@pytest.mark.qpa
def test_combo_has_no_bottom_border(shown_window):
    """T5：'全部'下拉框底部无 border-bottom 深色线（28px 高截断事故）。"""
    page = shown_window.findChild(_DuckPage)
    combo = page.combo_search_field
    img = grab(combo)
    assert_no_bottom_border(img, combo.width(), combo.height())


@pytest.mark.qpa
def test_migrated_buttons_free_of_box_and_border(shown_window):
    """T6：5 个弹片按钮同样无盒底/无边框（与 combo 同款透明 QSS）。"""
    page = shown_window.findChild(_DuckPage)
    for b in migrated_controls(page)[1:]:
        img = grab(b)
        assert_no_box_background(img, b.width(), b.height())
        assert_no_bottom_border(img, b.width(), b.height())


@pytest.mark.qpa
def test_dropdown_text_not_overlapped_by_arrow(shown_window):
    """T7：下拉按钮文字与自绘箭头无重叠（真实 Segoe UI 字宽计算）。"""
    page = shown_window.findChild(_DuckPage)
    for b in (page.btn_date_filter, page.btn_filter, page.btn_read_ops,
              page.btn_batch_ops):
        assert_text_not_overlapped_by_arrow(b, b.text())


@pytest.mark.qpa
def test_migrated_controls_contents_vcentered(shown_window):
    """T8：迁移控件内容垂直居中（防与左侧控件的水平中线错位事故）。"""
    page = shown_window.findChild(_DuckPage)
    for w in migrated_controls(page) + (page.search_input,):
        if w.width() <= 0 or w.height() <= 0:
            continue
        img = grab(w)
        assert_content_vcentered(img, w.height())
