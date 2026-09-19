"""RSS 分类筛选下拉回归测试（Task 27: 分类筛选下拉显示条目）。

覆盖：
(a) 分类筛选 combo_tag 的模型包含预期分类条目（> 0，含 store 标签）；
(b) 弹窗视图非空（首行 visualRect 非空）且背景为主题色（非纯黑 #000000）。

UI 构建 + 主题应用放在子进程（0xC0000005 崩溃隔离 + apply_app_theme 全局
主题副作用隔离），父测试断言子进程退出码。_child 用例在主套件一律 skip，
只在父用例 spawn 的子进程里运行（_YZ_SUBPROCESS_CHILD=1）。
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent

# 子进程隔离（0xC0000005 崩溃保护 + apply_app_theme/apply_global_stylesheet 全局
# 主题副作用隔离）：_child 用例只在其父用例 spawn 的子进程里运行。主套件收集到
# _child 时一律 skip——子进程里由父用例注入 _YZ_SUBPROCESS_CHILD=1。
# 背景：_child 用例在主进程跑会 apply_app_theme("dark") + apply_global_stylesheet(...)，
# 全局 QSS/主题残留导致后续 test_rss_sidebar.py::test_build_title_bar_widgets_migration
# 断言 combo_search_field.minimumHeight()==28 失败（实测 22）。
_SUBPROCESS_CHILD = pytest.mark.skipif(
    "os.environ.get('_YZ_SUBPROCESS_CHILD') != '1'",
    reason="仅在子进程隔离中运行（0xC0000005 崩溃保护 + 全局主题副作用隔离）；主套件跳过",
)


def _run_child(child_name):
    result = subprocess.run(
        [sys.executable, "-m", "pytest", f"tests/test_rss_category_filter_popup.py::{child_name}", "-q"],
        timeout=120,
        capture_output=True,
        cwd=str(_ROOT),
        env={**os.environ, "_YZ_SUBPROCESS_CHILD": "1"},
    )
    if result.returncode != 0:
        print("STDOUT:", result.stdout.decode(errors="replace"))
        print("STDERR:", result.stderr.decode(errors="replace"))
    assert result.returncode == 0, (
        f"Child test crashed or failed (returncode={result.returncode})\n"
        f"stdout: {result.stdout.decode(errors='replace')}\n"
        f"stderr: {result.stderr.decode(errors='replace')}"
    )


def test_category_filter_popup():
    """Subprocess isolation: 分类筛选下拉模型非空 + 弹窗已主题化。"""
    _run_child("test_category_filter_popup_child")


@_SUBPROCESS_CHILD
def test_category_filter_popup_child(qapp):
    """Child: 构建 RSS 页面，断言筛选下拉模型/弹窗（离屏）。"""
    import tempfile

    from core.qt_bootstrap import import_qt
    _, _, QtGui, _ = import_qt()
    from modules import rss_aggregator as m
    from modules.rss_store import RssStore
    from core.theme.app_theme import apply_app_theme
    from core.theme.styles import apply_global_stylesheet
    from core.theme.tokens import theme_palette

    store = RssStore(os.path.join(tempfile.mkdtemp(), "s.db"))
    store.ingest("科技", [{"title": "科技新闻一", "link": "http://a.com/1"}])
    store.ingest("新闻", [{"title": "新闻二", "link": "http://a.com/2"}])
    store.ingest("财经", [{"title": "财经三", "link": "http://a.com/3"}])

    class _FakeConfig(dict):
        def __init__(self):
            super().__init__()
            self._data = {}

        def get(self, key, default=None):
            dct = {**self._data, **dict(self)}
            return dct.get(key, default)

        def set(self, key, value):
            self._data[key] = value

        def unset(self, key):
            self._data.pop(key, None)

    class _FakeCtx:
        def __init__(self):
            self.config = _FakeConfig()

    class _FakeOwner:
        def __init__(self, store):
            self.store = store
            self.context = _FakeCtx()

        def scan_hashes(self, limit=200):
            pass

        def refresh_favicons(self):
            pass

        def refresh_now(self):
            pass

    page = m._RssPageWidget(_FakeOwner(store), None)
    page.resize(1200, 800)
    page.show()
    qapp.processEvents()

    combo = page.combo_tag

    # (a) 模型包含预期分类条目（> 0）
    assert combo.count() > 0, "分类筛选下拉模型为空"
    texts = [combo.itemText(i) for i in range(combo.count())]
    for expected in ("全部标签", "磁链", "文章", "科技", "新闻", "财经"):
        assert expected in texts, f"分类筛选缺少条目: {expected}"

    # (b) 弹窗视图已主题化（非纯黑）且显示条目
    apply_app_theme("dark")
    apply_global_stylesheet(acrylic=False, dark=True)
    qapp.processEvents()

    combo._showComboMenu()
    qapp.processEvents()
    menu = combo.dropMenu
    assert menu is not None, "弹窗未打开"
    view = menu.view
    assert view.count() > 0, "弹窗视图为空"
    idx = view.model().index(0, 0)
    rect = view.visualRect(idx)
    assert rect.isValid() and not rect.isEmpty(), "弹窗首行不可见"

    bg = view.palette().color(QtGui.QPalette.Base)
    assert bg.name() != "#000000", "弹窗背景退化为纯黑"
    hex_vals = {v for v in theme_palette().values() if isinstance(v, str) and v.startswith("#")}
    assert bg.name() in hex_vals, f"弹窗背景 {bg.name()} 不在 theme_palette() 中"

    page.close()
    page.deleteLater()