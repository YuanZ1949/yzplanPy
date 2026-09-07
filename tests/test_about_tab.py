import sys

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from core.config import AppConfig
from modules.registry import ModuleContext
from ui.about_tab import AboutTab


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    return app


def _make_tab():
    _app()
    config = AppConfig()
    context = ModuleContext(config=config, host_window=None, app=_app())
    return AboutTab(context)


def test_about_tab_has_project_links():
    # 关于页应包含「项目地址」「主页」两个 HyperlinkButton，指向正确 URL
    from qfluentwidgets import HyperlinkButton
    tab = _make_tab()
    links = tab.widget.findChildren(HyperlinkButton)
    texts = {c.text(): c.url.toString() for c in links}
    assert texts.get("项目地址") == "https://github.com/YuanZ1949"
    assert texts.get("主页") == "https://yuanz1949.github.io/"


def test_about_tab_dev_info_updated():
    # 开发者信息占位文案应替换为 YuanZ1949
    from qfluentwidgets import BodyLabel
    tab = _make_tab()
    dev = [c for c in tab.widget.findChildren(BodyLabel) if "开发者信息" in c.text()]
    assert dev, "应存在开发者信息标签"
    assert "YuanZ1949" in dev[0].text()
    assert "占位" not in dev[0].text()


def test_about_tab_links_not_html_labels():
    # 链接必须用 HyperlinkButton，不得用 QLabel + HTML <a>
    tab = _make_tab()
    for lbl in tab.widget.findChildren(QtWidgets.QLabel):
        assert "<a " not in lbl.text() and "<a>" not in lbl.text(), \
            "链接不应使用 QLabel + HTML <a>"