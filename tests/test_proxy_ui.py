"""tests/test_proxy_ui.py: 代理控制模块 UI 构建与契约测试。

覆盖 ModuleBase 契约（MODULE_INFO / Module / create_home_widget / create_page）、
页面容器契约（frameless / title_bar_spec 形状），以及「构造阶段不得发起网络
请求」这条硬约束（modules/proxy_ctrl/widgets/ 与 workers.py 由子代理实现）。
"""
import pytest

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()


class _FakeConfig:
    """最小配置替身：兼容 context.config.* 与 context.* 两种访问方式。"""

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


@pytest.fixture
def module():
    from modules.proxy_ctrl import Module
    return Module(_FakeContext())


@pytest.fixture
def no_network(monkeypatch):
    """构造阶段若发起同步网络请求会直接失败——用于证明 UI 不在构造时联网。"""

    def _boom(*args, **kwargs):
        raise AssertionError("页面构造阶段不允许发起网络请求")

    import requests

    monkeypatch.setattr(requests, "get", _boom)
    monkeypatch.setattr(requests, "request", _boom)
    return _boom


def _cleanup(widget):
    """fixture 只清理自己创建的对象。"""
    try:
        widget.close()
    except Exception:
        pass
    widget.deleteLater()
    QtWidgets.QApplication.processEvents()


# ── 模块注册契约 ──────────────────────────────────────────────────────

def test_module_info_shape():
    from modules.proxy_ctrl import MODULE_INFO, Module
    assert isinstance(MODULE_INFO, dict)
    assert MODULE_INFO["id"] == "proxy_ctrl"
    assert MODULE_INFO["id"] == Module.MODULE_ID
    assert MODULE_INFO["name"].strip()
    assert MODULE_INFO["description"].strip()


def test_module_exported_by_registry():
    """modules/registry.py 靠 __init__ 的 MODULE_INFO + Module 自动发现模块。"""
    import modules.proxy_ctrl as pkg
    assert hasattr(pkg, "MODULE_INFO")
    assert hasattr(pkg, "Module")
    assert "__all__" in dir(pkg)


def test_module_base_contract(module):
    assert module.id == "proxy_ctrl"
    assert module.name.strip()
    assert module.running is False


def test_start_stop_toggle_running(module):
    module.start()
    assert module.running is True
    module.stop()
    assert module.running is False


# ── 首页小卡 ─────────────────────────────────────────────────────────

def test_home_widget_constructs(qapp, module, no_network):
    w = module.create_home_widget(None)
    try:
        assert w is not None
        assert isinstance(w, QtWidgets.QWidget)
    finally:
        _cleanup(w)


def test_home_widget_destroy_is_safe(qapp, module, no_network):
    """反复 show/destroy 不得抛异常（QTimer 清理路径）。"""
    w = module.create_home_widget(None)
    w.show()
    w.close()
    w.deleteLater()
    QtWidgets.QApplication.processEvents()


# ── 详情页 ───────────────────────────────────────────────────────────

def test_page_constructs(qapp, module, no_network):
    page = module.create_page(None)
    try:
        assert page is not None
        assert isinstance(page, QtWidgets.QWidget)
    finally:
        _cleanup(page)


def test_page_shows_without_event_loop(qapp, module, no_network):
    """offscreen 下 show() 不得抛异常或死锁。"""
    page = module.create_page(None)
    try:
        page.resize(1200, 800)
        page.show()
        QtWidgets.QApplication.processEvents()
    finally:
        _cleanup(page)


def test_page_is_frameless(qapp, module, no_network):
    """ui/module_pages.py 依据 page.frameless 决定是否套 FramelessWindow。"""
    page = module.create_page(None)
    try:
        assert page.frameless is True
    finally:
        _cleanup(page)


def test_page_title_bar_spec_shape(qapp, module, no_network):
    """title_bar_spec 契约：{"buttons":[{icon,text,tooltip,cb}], "widgets": ...}"""
    page = module.create_page(None)
    try:
        spec = page.title_bar_spec
        assert isinstance(spec, dict)
        assert "buttons" in spec
        assert "widgets" in spec
        buttons = spec["buttons"]
        assert isinstance(buttons, list) and buttons
        for b in buttons:
            assert set(("icon", "text", "tooltip", "cb")) <= set(b)
            assert b["text"].strip()
            assert callable(b["cb"])
    finally:
        _cleanup(page)


def test_page_contains_target_rows(qapp, module, no_network):
    """7 个代理目标（git/curl/wget/python/node/global/docker）都要在页面上出现。"""
    from modules.proxy_ctrl.targets import all_targets

    page = module.create_page(None)
    try:
        texts = []
        for label in page.findChildren(QtWidgets.QLabel):
            texts.append(label.text())
        blob = " ".join(texts)
        for t in all_targets():
            assert t.name in blob, f"页面上找不到目标 {t.name}"
    finally:
        _cleanup(page)


def test_page_uses_widget_factories(qapp, module, no_network):
    """AGENTS.md 规则 1：控件必须来自 ui/widgets.py 工厂（QPushButton 家族）。"""
    from ui.widgets import make_button  # noqa: F401  确认工厂可导入

    page = module.create_page(None)
    try:
        # 页面至少有若干 QPushButton（由 make_button 产出）
        assert len(page.findChildren(QtWidgets.QPushButton)) > 0
    finally:
        _cleanup(page)


def test_page_constructs_twice_without_leak(qapp, module, no_network):
    """单例页被关闭后重建不得残留线程/定时器。"""
    for _ in range(2):
        page = module.create_page(None)
        try:
            page.resize(1200, 800)
            page.show()
            QtWidgets.QApplication.processEvents()
        finally:
            _cleanup(page)



# ── 可用性快检按钮（逻辑层见 test_proxy_speedtest.py）────────────────────

def test_page_has_availability_check_button(qapp, module, no_network):
    page = module.create_page(None)
    try:
        assert page.btn_check is not None
    finally:
        _cleanup(page)


def test_check_available_runs_background_task(qapp, module, no_network,
                                              monkeypatch):
    """检测必须走后台线程 —— 逻辑层是 2~5 秒的阻塞网络请求。"""
    page = module.create_page(None)
    calls = {}

    class _Group:
        def start(self, fn, **kwargs):
            calls["started"] = True
            return True

    try:
        monkeypatch.setattr(page, "_group", _Group())
        assert page.check_available() is True
        assert calls.get("started") is True
    finally:
        _cleanup(page)


def test_check_available_declines_when_busy(qapp, module, no_network,
                                            monkeypatch):
    """上一项任务没结束时应就地拒绝返回 False，而不是排队或崩。"""
    page = module.create_page(None)

    class _Busy:
        def start(self, fn, **kwargs):
            return False

    try:
        monkeypatch.setattr(page, "_group", _Busy())
        assert page.check_available() is False
    finally:
        _cleanup(page)


def test_availability_result_sets_chip_text(qapp, module, no_network):
    page = module.create_page(None)
    try:
        page._avail_result((True, "ok"))
        assert page._avail_chip.text() == "可用"
        page._avail_result((False, "bad"))
        assert page._avail_chip.text() == "不可用"
    finally:
        _cleanup(page)


def test_availability_chip_reused_when_kind_unchanged(qapp, module, no_network):
    """kind 未变时复用同一胶囊对象 —— 避免逐帧重建导致布局抖动。"""
    page = module.create_page(None)
    try:
        first = page._avail_chip
        page._set_avail_chip("检测中", "info")
        assert page._avail_chip is first
    finally:
        _cleanup(page)


def test_availability_chip_replaced_when_kind_changes(qapp, module, no_network):
    """kind 变了必须换新胶囊 —— 复用旧对象只改文案会丢掉配色变化。"""
    page = module.create_page(None)
    try:
        first = page._avail_chip
        page._set_avail_chip("可用", "success")
        assert page._avail_chip is not first
    finally:
        _cleanup(page)
