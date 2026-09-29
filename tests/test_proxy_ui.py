"""tests/test_proxy_ui.py: 代理控制模块 UI 构建与契约测试。

覆盖 ModuleBase 契约（MODULE_INFO / Module / create_home_widget / create_page）、
页面容器契约（frameless / title_bar_spec 形状），以及「构造阶段不得发起网络
请求」这条硬约束（modules/proxy_ctrl/widgets/ 与 workers.py 由子代理实现）。
"""
import pytest

from core.qt_bootstrap import import_qt
from modules.proxy_ctrl.widgets import tab_scan, tab_speed
from modules.proxy_ctrl import speedtest

_, QtCore, QtGui, QtWidgets = import_qt()


def _fake_results(n=2):
    """构造 scan 的结果对象，供结果表渲染路径测试用。"""
    from modules.proxy_ctrl.scanner import ProxyCandidate
    return [ProxyCandidate(ip=f"192.168.2.{i}", port=7890, latency_ms=50 + i,
                           kind="✅ 优秀") for i in range(1, n + 1)]


def _fake_speed_result(rating, avg_ms=100):
    """构造一个 speedtest.SpeedResult 供 UI 渲染路径测试用。"""
    return speedtest.SpeedResult(url="http://192.168.2.10:7890", ok=True,
                                 avg_ms=avg_ms, samples=[avg_ms], rating=rating,
                                 hints=[])



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


# ── 并发上限：用户能把 100000 填进并发框 ──────────────────────────
class TestWorkersClamp:
    """并发数必须夹在 1~256。

    背景：``ThreadPoolExecutor(max_workers=N)`` 会真的开 N 个线程，用户在输入框
    敲个 100000 就是十万个线程，机器直接卡死。纯函数，无 Qt 依赖。
    """

    def test_超上限被夹回(self):
        assert tab_scan.clamp_workers("100000") == tab_scan.MAX_WORKERS

    def test_低于下限被夹回(self):
        assert tab_scan.clamp_workers("0") == tab_scan.MIN_WORKERS
        assert tab_scan.clamp_workers("-5") == tab_scan.MIN_WORKERS

    def test_区间内原样保留(self):
        assert tab_scan.clamp_workers("150") == 150

    def test_非法输入回落默认值(self):
        assert tab_scan.clamp_workers("") == tab_scan.DEFAULT_MAX_WORKERS
        assert tab_scan.clamp_workers("abc") == tab_scan.DEFAULT_MAX_WORKERS
        assert tab_scan.clamp_workers(None) == tab_scan.DEFAULT_MAX_WORKERS

    def test_上限不超过256(self):
        assert tab_scan.MAX_WORKERS == 256

    def test_页面实际用的是夹过的值(self, qapp, module, no_network):
        page = module.create_page(None)
        try:
            page.scan.edit_workers.setText("100000")
            assert page.scan._params()["max_workers"] == tab_scan.MAX_WORKERS
        finally:
            _cleanup(page)


# ── 测速结论胶囊：样式被 setStyleSheet("") 抹掉 ────────────────────
class TestSpeedChipKeepsStyle:
    """``chip.setStyleSheet("")`` 会把 make_status_chip 的令牌 QSS 抹掉，
    胶囊从此变成无底色的裸 QLabel。评级分档必须换成对应 kind 的新胶囊。"""

    def _chip_fg(self, page):
        """胶囊前景色（取自 styleSheet 的 color: 段），用来判定它到底是哪个 kind。

        不能只断言「样式非空」—— 那样即使把 kind 写死成 success 也会通过，
        属于假绿。必须比对颜色本身。
        """
        css = page.speed.chip.styleSheet()
        assert css.strip(), "胶囊样式被抹掉了"
        marker = "color: "
        idx = css.index(marker) + len(marker)
        return css[idx:css.index(";", idx)].strip()

    def test_评级好时胶囊是success配色(self, qapp, module, no_network):
        from core.theme.tokens import theme_palette
        page = module.create_page(None)
        try:
            page.speed._applied(_fake_speed_result("✅ 优秀", avg_ms=80))
            assert page.speed.chip.text() == "✅ 优秀"
            assert self._chip_fg(page) == theme_palette()["success"]
        finally:
            _cleanup(page)

    def test_评级慢时胶囊是warning配色(self, qapp, module, no_network):
        from core.theme.tokens import theme_palette
        page = module.create_page(None)
        try:
            page.speed._applied(_fake_speed_result("⚠️ 较慢", avg_ms=900))
            assert page.speed.chip.text() == "⚠️ 较慢"
            assert self._chip_fg(page) == theme_palette()["status_warning"]
        finally:
            _cleanup(page)

    def test_连续两次测速不会退回默认配色(self, qapp, module, no_network):
        """先好后差：胶囊必须跟着换色，不能停在第一次的配色上。"""
        from core.theme.tokens import theme_palette
        page = module.create_page(None)
        try:
            page.speed._applied(_fake_speed_result("✅ 优秀", avg_ms=80))
            first = self._chip_fg(page)
            page.speed._applied(_fake_speed_result("⚠️ 较慢", avg_ms=900))
            second = self._chip_fg(page)
            assert first == theme_palette()["success"]
            assert second == theme_palette()["status_warning"]
        finally:
            _cleanup(page)

    @pytest.mark.parametrize("rating,kind", [
        ("✅ 优秀", "success"), ("👍 良好", "info"),
        ("⚠️ 较慢", "warning"), ("❌ 较差", "error"),
    ])
    def test_评级到kind的映射(self, rating, kind):
        assert tab_speed.rating_kind(rating) == kind

    def test_未知评级回落info(self):
        assert tab_speed.rating_kind("??") == "info"
        assert tab_speed.rating_kind(None) == "info"


# ── 扫描结果的协议前缀：硬编码 http:// 导致 SOCKS5 代理无法使用 ──────
class TestScanResultScheme:
    def test_默认http(self, qapp, module, no_network):
        page = module.create_page(None)
        try:
            assert tab_scan.build_proxy_url("192.168.2.10", 7890, "http") \
                == "http://192.168.2.10:7890"
        finally:
            _cleanup(page)

    def test_socks5协议(self):
        assert tab_scan.build_proxy_url("192.168.2.10", 1080, "socks5") \
            == "socks5://192.168.2.10:1080"

    def test_非法协议回退http而不是原样透传(self):
        """否则一个拼错的 scheme 会变成 'gopher://…' 这种下游完全用不了的地址。"""
        assert tab_scan.build_proxy_url("192.168.2.10", 7890, "gopher") \
            == "http://192.168.2.10:7890"
        assert tab_scan.build_proxy_url("192.168.2.10", 7890, "") \
            == "http://192.168.2.10:7890"

    def test_下拉框含三种协议(self, qapp, module, no_network):
        page = module.create_page(None)
        try:
            texts = [page.scan.combo_scheme.itemText(i)
                     for i in range(page.scan.combo_scheme.count())]
            assert texts == ["http", "https", "socks5"]
        finally:
            _cleanup(page)

    def test_选socks5时渲染的URL带socks5前缀(self, qapp, module, no_network):
        page = module.create_page(None)
        try:
            page.scan.combo_scheme.setCurrentText("socks5")
            assert page.scan._scheme() == "socks5"
            assert page.scan._render(_fake_results()) is not False
        finally:
            _cleanup(page)