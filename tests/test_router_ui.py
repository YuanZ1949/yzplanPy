"""tests/test_router_ui.py: 路由器管理模块 UI 构建与契约测试。

除 ModuleBase 契约外，额外锁定两条硬约束：
1. 页面构造阶段绝不能真的连路由器（monkeypatch TelnetSession.open 使其抛错）；
2. 口令不经明文存储/显示（store 层用 DPAPI，UI 只能拿到解密结果）。
"""
from pathlib import Path

import pytest

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

class _FakeConfig:
    def __init__(self):
        self.settings = {}

    def module_setting(self, module_id, key, default=None):
        return self.settings.get((module_id, key), default)

    def set_module_config(self, module_id, cfg):
        self.settings[(module_id, "__cfg__")] = cfg

    def get(self, key, default=None):
        return default

    def set(self, key, value):
        return True


class _FakeContext:
    def __init__(self):
        self.config = _FakeConfig()
        self.host_window = None
        self.app = None

    def module_setting(self, module_id, key, default=None):
        return self.config.module_setting(module_id, key, default)

    def set_module_config(self, module_id, cfg):
        return self.config.set_module_config(module_id, cfg)


# QApplication 一律用 tests/conftest.py 的 session 级 `qapp` fixture（AGENTS.md 规则 3），
# 本文件不得再建 QApplication。


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """AGENTS.md 规则 7：持久化资源必须重定向到 tmp_path。"""
    from modules.router_admin import backup, store

    monkeypatch.setattr(store, "SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setattr(backup, "BACKUP_DIR", str(tmp_path / "backups"))
    return tmp_path


@pytest.fixture
def module():
    from modules.router_admin import Module
    return Module(_FakeContext())


@pytest.fixture(autouse=True)
def no_router_connection(monkeypatch):
    """构造阶段若尝试连 telnet 立即失败——用于证明 UI 不在构造时联网。"""
    from modules.router_admin import telnet

    def _boom(*args, **kwargs):
        raise AssertionError("页面构造阶段不允许连接路由器")

    monkeypatch.setattr(telnet.TelnetSession, "open", _boom)
    return _boom


def _cleanup(widget):
    try:
        widget.close()
    except Exception:
        pass
    widget.deleteLater()
    QtWidgets.QApplication.processEvents()


# ── 模块注册契约 ──────────────────────────────────────────────────────

def test_module_info_shape():
    from modules.router_admin import MODULE_INFO, Module
    assert isinstance(MODULE_INFO, dict)
    assert MODULE_INFO["id"] == "router_admin"
    assert MODULE_INFO["id"] == Module.MODULE_ID
    assert MODULE_INFO["name"].strip()
    assert MODULE_INFO["description"].strip()


def test_module_exported_by_registry():
    import modules.router_admin as pkg
    assert hasattr(pkg, "MODULE_INFO")
    assert hasattr(pkg, "Module")
    assert "__all__" in dir(pkg)


def test_module_base_contract(module):
    assert module.id == "router_admin"
    assert module.name.strip()
    assert module.running is False


# ── 首页小卡 ─────────────────────────────────────────────────────────

def test_home_widget_constructs(qapp, module):
    w = module.create_home_widget(None)
    try:
        assert isinstance(w, QtWidgets.QWidget)
    finally:
        _cleanup(w)


def test_home_widget_show_close(qapp, module):
    w = module.create_home_widget(None)
    try:
        w.show()
        QtWidgets.QApplication.processEvents()
    finally:
        _cleanup(w)


# ── 详情页 ───────────────────────────────────────────────────────────

def test_page_constructs(qapp, module):
    page = module.create_page(None)
    try:
        assert isinstance(page, QtWidgets.QWidget)
    finally:
        _cleanup(page)


def test_page_shows(qapp, module):
    page = module.create_page(None)
    try:
        page.resize(1280, 860)
        page.show()
        QtWidgets.QApplication.processEvents()
    finally:
        _cleanup(page)


def test_page_is_frameless(qapp, module):
    page = module.create_page(None)
    try:
        assert page.frameless is True
    finally:
        _cleanup(page)


def test_page_title_bar_spec_shape(qapp, module):
    page = module.create_page(None)
    try:
        spec = page.title_bar_spec
        assert isinstance(spec, dict)
        assert "buttons" in spec and "widgets" in spec
        assert isinstance(spec["buttons"], list) and spec["buttons"]
        for b in spec["buttons"]:
            assert set(("icon", "text", "tooltip", "cb")) <= set(b)
            assert b["text"].strip()
            assert callable(b["cb"])
    finally:
        _cleanup(page)


def test_page_has_four_tabs(qapp, module):
    """总览 / 在线终端 / 服务管理 / 配置编辑 四个 Tab。"""
    page = module.create_page(None)
    try:
        tabs = [w for w in page.findChildren(QtWidgets.QTabWidget) if w.count() == 4]
        assert tabs, "未找到 4 个 Tab 的 QTabWidget"
        titles = [tabs[0].tabText(i) for i in range(tabs[0].count())]
        assert titles == ["总览", "在线终端", "服务管理", "配置编辑"], titles
        assert page.findChildren(QtWidgets.QWidget)
    finally:
        _cleanup(page)


def test_page_password_field_is_masked(qapp, module):
    """口令输入框必须是 Password 回显模式。"""
    page = module.create_page(None)
    try:
        edits = page.findChildren(QtWidgets.QLineEdit)
        masked = [
            e for e in edits
            if e.echoMode() == QtWidgets.QLineEdit.Password
        ]
        assert masked, "未找到口令输入框（应设 echoMode=Password）"
    finally:
        _cleanup(page)


def test_page_does_not_leak_plaintext_password(qapp, module):
    """口令绝不能以明文形式落盘，也绝不能回填进输入框。

    注意 `store.load()["password"]` **本来就该**返回解密后的明文（UI 要靠它连路由器），
    真正的安全属性是：(1) 磁盘上的 settings.json 里搜不到明文；(2) 输入框不回填。
    """
    from modules.router_admin import store

    assert store.set_password("S3cretProbeValue")
    on_disk = Path(store.SETTINGS_PATH).read_text(encoding="utf-8")
    assert "S3cretProbeValue" not in on_disk, "settings.json 泄露了明文口令"
    assert '"password_blob"' in on_disk, "口令未以 DPAPI 密文落盘"
    assert store.load()["password"] == "S3cretProbeValue", "DPAPI 往返失败"

    page = module.create_page(None)
    try:
        for e in page.findChildren(QtWidgets.QLineEdit):
            if e.echoMode() == QtWidgets.QLineEdit.Password:
                assert e.text() == "", "口令框不得预填明文"
    finally:
        _cleanup(page)


def test_page_constructs_twice(qapp, module):
    for _ in range(2):
        page = module.create_page(None)
        try:
            page.resize(1280, 860)
            page.show()
            QtWidgets.QApplication.processEvents()
        finally:
            _cleanup(page)
