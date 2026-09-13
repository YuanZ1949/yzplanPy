"""RSS 对话框页面选择器导入冒烟测试。

轮1 审查标记 a.py L102 / b.py L118 的 `from ..page_selector import PageSelectorDialog`
为潜伏 ImportError（应直接导入 dialog_actions）。本测试验证 _open_selector 的惰性导入
路径可解析且能构造出 PageSelectorDialog——若导入路径错误会抛 ImportError。

离屏运行，patch 掉 PageSelectorDialog 与 QDialog.exec 避免真实 WebEngine / 模态阻塞。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, patch

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

_qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def _patch_selector():
    """patch 掉 _open_selector 惰性导入的目标类（防真实 WebEngine 构造）。"""
    return patch("modules.page_selector.dialog_actions.PageSelectorDialog")


def test_edit_feed_dialog_open_selector_no_importerror():
    """a.py _EditFeedDialog._open_selector：惰性导入不抛 ImportError 且结果被采纳。"""
    from modules.rss_aggregator.dialogs.a import _EditFeedDialog

    feed = {"id": 1, "name": "t", "url": "https://example.com",
            "feed_type": "scrape", "scrape_options": "{}"}
    dlg = _EditFeedDialog(feed, MagicMock())
    try:
        with _patch_selector() as mock_cls:
            mock_cls.return_value.exec.return_value = QtWidgets.QDialog.Accepted
            mock_cls.return_value.options.return_value = {"mode": "single", "selector": "div.a"}
            dlg._open_selector()  # 导入路径错误时此处抛 ImportError
        assert dlg._scrape_options == {"mode": "single", "selector": "div.a"}
        assert "div.a" in dlg.lb_scrape.text()
    finally:
        dlg.hide()


def test_add_feed_dialog_open_selector_no_importerror():
    """b.py _AddFeedDialog._open_selector：惰性导入不抛 ImportError 且结果被采纳。"""
    from modules.rss_aggregator.dialogs.b import _AddFeedDialog

    dlg = _AddFeedDialog(MagicMock())
    try:
        dlg.in_url.setText("https://example.com")
        with _patch_selector() as mock_cls:
            mock_cls.return_value.exec.return_value = QtWidgets.QDialog.Accepted
            mock_cls.return_value.options.return_value = {"mode": "list", "selector": "ul.items"}
            dlg._open_selector()  # 导入路径错误时此处抛 ImportError
        assert dlg._scrape_options == {"mode": "list", "selector": "ul.items"}
        assert "ul.items" in dlg.lb_scrape.text()
    finally:
        dlg.hide()


def test_add_feed_dialog_open_selector_empty_url_guard():
    """b.py 未填 URL 时 _open_selector 直接提示返回，不触发导入。"""
    from modules.rss_aggregator.dialogs.b import _AddFeedDialog

    dlg = _AddFeedDialog(MagicMock())
    try:
        with patch("modules.rss_aggregator.dialogs.b.QtWidgets.QMessageBox") as mock_mb:
            dlg._open_selector()
        mock_mb.information.assert_called_once()
        assert dlg._scrape_options is None
    finally:
        dlg.hide()


def test_dialogs_construct_smoke():
    """a.py / b.py 对话框可直接实例化（模块导入链无 ImportError）。"""
    from modules.rss_aggregator.dialogs.a import _EditFeedDialog
    from modules.rss_aggregator.dialogs.b import _AddFeedDialog

    feed = {"id": 1, "name": "t", "url": "https://example.com",
            "feed_type": "scrape", "scrape_options": "{}"}
    dlg_a = _EditFeedDialog(feed, MagicMock())
    dlg_b = _AddFeedDialog(MagicMock())
    try:
        assert hasattr(dlg_a, "btn_selector")
        assert hasattr(dlg_b, "btn_selector")
    finally:
        dlg_a.hide()
        dlg_b.hide()