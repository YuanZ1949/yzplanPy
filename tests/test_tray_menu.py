"""托盘分组菜单离屏构建冒烟测试。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()

_qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


class _StubStore:
    def __init__(self, unread=3):
        self._unread = unread
        self.refreshed = 0

    def get_unread_count(self):
        return self._unread


class _StubRssMod:
    id = "rss_aggregator"
    name = "RSS 聚合"
    enabled_default = True

    def __init__(self, unread=3):
        self.store = _StubStore(unread=unread)
        self.opened = 0
        self.refreshed = 0

    def refresh_now(self):
        self.refreshed += 1

    def create_page(self, _parent):
        self.opened += 1
        return QtWidgets.QWidget()


class _StubPageMod:
    id = "todo_notes"
    name = "便签待办"
    enabled_default = True
    opened = 0

    def create_page(self, _parent):
        type(self).opened += 1
        return QtWidgets.QWidget()


class _StubDisabledMod:
    id = "webview_control"
    name = "WebView2管控"
    enabled_default = False

    def create_page(self, _parent):
        return QtWidgets.QWidget()


class _StubRegistry:
    def __init__(self, mods):
        self._mods = mods

    def all(self):
        return list(self._mods)

    def get(self, module_id):
        return next((m for m in self._mods if m.id == module_id), None)

    def is_enabled(self, module_id):
        mod = self.get(module_id)
        return bool(mod and mod.enabled_default)


class _StubConfig:
    def __init__(self):
        self._data = {}

    def get(self, key, default=None):
        cur = self._data
        for part in str(key).split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def set(self, key, value):
        cur = self._data
        parts = str(key).split(".")
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = value

    def module_enabled(self, module_id, default=True):
        return self.get(f"modules.{module_id}.enabled", default)

    def set_module_config(self, module_id, cfg):
        self._data.setdefault("modules", {}).setdefault(module_id, {}).update(cfg)


class _Ctx:
    def __init__(self, registry, host):
        self.registry = registry
        self.host_window = host
        self.config = _StubConfig()
        self.si = None


def _make_tray(unread=3):
    rss = _StubRssMod(unread=unread)
    page_mod = _StubPageMod()
    disabled = _StubDisabledMod()
    host = QtWidgets.QWidget()
    ctx = _Ctx(_StubRegistry([rss, page_mod, disabled]), host)
    tray = __import__("core.tray", fromlist=["Tray"]).Tray(
        None, on_show_home=host.show, on_quit=host.close, context=ctx)
    tray._rss_mod = rss
    tray._page_mod = page_mod
    tray._host_widget = host
    return tray


def test_menu_sections_built():
    tray = _make_tray()
    m = tray.menu
    texts = [a.text() for a in m.actions()]
    assert "显示主页" in texts
    assert "退出" in texts
    # 一级菜单：RSS 快捷 / 模块 / 设置 / 关于 / 重启 全部平铺
    assert "打开 RSS 聚合" in texts
    assert "立即刷新所有源" in texts
    assert "便签待办" in texts
    assert {"程序设置", "关于", "重启程序"} <= set(texts)
    # 无二级菜单
    assert all(a.menu() is None for a in m.actions())
    # 显示主页是可勾选项
    assert tray.action_show.isCheckable()


def test_show_action_toggles_window():
    tray = _make_tray()
    host = tray._host_widget
    host.show()
    QtWidgets.QApplication.processEvents()
    assert host.isVisible()
    tray.action_show.setChecked(True)
    tray._toggle_home(True)
    QtWidgets.QApplication.processEvents()
    assert host.isVisible()
    tray._toggle_home(False)
    QtWidgets.QApplication.processEvents()
    assert not host.isVisible()


def test_rss_menu_refresh_shows_unread():
    tray = _make_tray(unread=7)
    texts = [a.text() for a in tray.menu.actions()]
    assert "当前未读：7" in texts
    assert "打开 RSS 聚合" in texts
    assert "立即刷新所有源" in texts
    # 未读数同步到 tooltip（aboutToShow 重建时 notify=True）
    tray._rebuild()
    assert "YZplan (7 未读)" == tray.tray.toolTip()


def test_modules_flat_page_modules_only():
    tray = _make_tray()
    tray._rebuild(notify=False)
    texts = [a.text() for a in tray.menu.actions()]
    assert "便签待办" in texts          # 启用 + create_page
    assert "WebView2管控" not in texts  # 禁用模块不出现
    assert "（暂无可用模块）" not in texts


def test_dialogs_keep_reference():
    tray = _make_tray()
    tray._open_settings_dialog()
    tray._open_about_dialog()
    # 非模态对话框保持引用存活，避免被 Python 回收导致窗口消失
    assert len(tray._dialogs) >= 2
    assert all(isinstance(d, QtWidgets.QDialog) for d in tray._dialogs)
    for d in list(tray._dialogs):
        d.close()
    QtWidgets.QApplication.processEvents()