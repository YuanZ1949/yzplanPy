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


def test_page_has_five_tabs(qapp, module):
    """总览 / 在线终端 / 服务管理 / 配置编辑 / 宽带账号 五个 Tab。"""
    page = module.create_page(None)
    try:
        tabs = [w for w in page.findChildren(QtWidgets.QTabWidget) if w.count() == 5]
        assert tabs, "未找到 5 个 Tab 的 QTabWidget"
        titles = [tabs[0].tabText(i) for i in range(tabs[0].count())]
        assert titles == ["总览", "在线终端", "服务管理", "配置编辑", "宽带账号"], titles
        assert page.findChildren(QtWidgets.QWidget)
    finally:
        _cleanup(page)


REAL_STATUS = {"up": True, "pending": False, "available": True,
               "uptime_s": 13327, "proto": "pppoe", "device": "eth0",
               "l3_device": "pppoe-wan", "ipv4": "100.67.227.167",
               "netmask": 32, "ptp": "100.67.227.1",
               "ipv6": "240e:3b0:3498:278f::1",
               "dns": ["202.96.134.33", "202.96.128.86"], "error": None}

REAL_ACCOUNT = {"present": True, "proto": "pppoe", "username": "user@1",
                "has_password": True, "ifname": "eth0", "mtu": "1500",
                "ipv6": "auto", "text_len": 1688}


def test_wan_tab_password_is_masked(qapp, module):
    """宽带口令框必须遮蔽——账号口令是敏感值，不能明文显示。"""
    page = module.create_page(None)
    try:
        masked = [e for e in page.wan.findChildren(QtWidgets.QLineEdit)
                  if e.echoMode() == QtWidgets.QLineEdit.Password]
        assert masked, "宽带 Tab 未找到遮蔽的口令输入框"
    finally:
        _cleanup(page)


def test_wan_tab_password_not_prefilled(qapp, module):
    """读回账号后口令框必须留空——明文口令不回填进 UI。"""
    page = module.create_page(None)
    try:
        tab = page.wan
        tab._apply_account(dict(REAL_ACCOUNT))
        assert tab.edit_user.text() == "user@1", "用户名应回填"
        assert tab.edit_pass.text() == "", "口令绝不能回填明文"
        assert tab.edit_pass.echoMode() == QtWidgets.QLineEdit.Password
    finally:
        _cleanup(page)


def test_wan_tab_has_redial_and_save_buttons(qapp, module):
    """必须同时有「保存账号」与「重新拨号」两个独立动作。"""
    page = module.create_page(None)
    try:
        labels = {b.text() for b in page.wan.findChildren(QtWidgets.QPushButton)}
        assert "保存账号" in labels, sorted(labels)
        assert "重新拨号" in labels, sorted(labels)
    finally:
        _cleanup(page)


def test_wan_tab_empty_password_means_keep(qapp, module):
    """口令框留空 = 不修改，必须翻译成 password=None 而不是空串。"""
    page = module.create_page(None)
    try:
        tab = page.wan
        tab.edit_user.setText("new@1")
        tab.edit_pass.setText("")
        assert tab._collect() == ("new@1", None)
    finally:
        _cleanup(page)


def test_wan_tab_collect_trims_user_keeps_password_spaces(qapp, module):
    """用户名去首尾空白；口令保留内部空格（PPPoE 口令可能含空格）。"""
    page = module.create_page(None)
    try:
        tab = page.wan
        tab.edit_user.setText("  new@1  ")
        tab.edit_pass.setText("ab cd12")
        assert tab._collect() == ("new@1", "ab cd12")
    finally:
        _cleanup(page)


def test_wan_tab_renders_status(qapp, module):
    """状态渲染：IPv4 与在线时长要真的出现在界面上。"""
    page = module.create_page(None)
    try:
        tab = page.wan
        tab._apply_status(dict(REAL_STATUS))
        texts = " ".join(w.text() for w in tab.findChildren(QtWidgets.QLabel))
        assert "100.67.227.167" in texts
        assert "在线" in texts
    finally:
        _cleanup(page)


def test_wan_tab_never_renders_plaintext_password(qapp, module):
    """渲染状态与账号后，页面上都不得出现口令明文。"""
    page = module.create_page(None)
    try:
        tab = page.wan
        tab._apply_status(dict(REAL_STATUS))
        tab._apply_account(dict(REAL_ACCOUNT))
        texts = " ".join(w.text() for w in tab.findChildren(QtWidgets.QLabel))
        assert "100.67.227.167" in texts
        assert "fakepw01" not in texts
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
