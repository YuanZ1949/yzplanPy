"""RSS 模块窗口标题栏回归测试。

修复目标（用户反馈）：
1. 窗口控制按钮（最小化/最大化/关闭）跑到标题栏中间 —— 按钮组应右对齐；
2. 按钮组与左侧控件垂直错位 —— 应与左侧控件同一条水平中线；
3. 预览后“半白变透明” —— 初始即彻底关闭 DWM Mica backdrop，前后视觉一致。
"""
import os
import sys
import types
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()

_qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from modules.rss_aggregator.page_lifecycle import _RssPageWidget as _RssLifecycle
from qfluentwidgets import FluentIcon
from ui.dwm_compat import disable_mica_backdrop
from ui.module_pages import _ModuleWindow, open_module_page


class _DuckPage(QtWidgets.QWidget):
    """实现 _build_title_bar_widgets 全部接口的页面替身，复用真实迁移实现。"""

    frameless = True

    def __init__(self):
        super().__init__()
        self._title_bar_migrated = False
        self._show_thumbnails = False
        # paintEvent 读取 owner.context.config 取壁纸配置
        self.owner = types.SimpleNamespace(
            context=types.SimpleNamespace(config={}))
        self.btn_thumb = QtWidgets.QPushButton("缩略图")
        self._search_wg = QtWidgets.QFrame()
        self._search_wg.setObjectName("rssSearchBox")
        self.btn_date_filter = QtWidgets.QPushButton("时间")
        self.btn_filter = QtWidgets.QPushButton("筛选")
        self.btn_read_ops = QtWidgets.QPushButton("阅读")
        self.btn_batch_ops = QtWidgets.QPushButton("批量")
        self.search_input = QtWidgets.QLineEdit()
        self.combo_search_field = QtWidgets.QComboBox()
        self.tool_bar = QtWidgets.QWidget()

    def _toggle_thumbnails(self, _checked):
        pass

    def _migrated_btn_qss(self):
        return "QPushButton { background: transparent; }"

    def _update_thumbnail_btn_text(self):
        pass

    @staticmethod
    def _noop():
        pass

    @property
    def title_bar_spec(self):
        return {"buttons": [
            {"icon": FluentIcon.SETTING, "text": "设置", "tooltip": "设置",
             "cb": self._noop},
            {"icon": FluentIcon.SHARE, "text": "导出", "tooltip": "导出",
             "cb": self._noop},
            {"icon": FluentIcon.FOLDER, "text": "导入", "tooltip": "导入",
             "cb": self._noop},
        ], "widgets": True}


# 绑定真实迁移实现（unbound 方法赋给类属性，实例访问时自动绑定 self）
_DuckPage._build_title_bar_widgets = _RssLifecycle._build_title_bar_widgets
_DuckPage.paintEvent = _RssLifecycle.paintEvent


def _open(mod_id):
    """打开一个自定义标题栏模块窗口（独立单例 id，避免跨测试冲突）。"""

    class Mod:
        name = "RSS"
        id = mod_id

        def create_page(self, _parent):
            return _DuckPage()

    return open_module_page(Mod())


def test_window_button_group_right_aligned_vcentered():
    """问题1+2：窗口按钮组右对齐贴右缘 + 垂直居中与左侧控件同中线。"""
    dlg = _open("rss_tb_align")
    try:
        tb = dlg.titleBar
        # 布局对齐契约：AlignRight 水平贴右 + AlignVCenter 垂直居中
        align = tb.buttonLayout.alignment()
        assert align == (QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter), (
            f"buttonLayout.alignment()={align}，应为 AlignRight|AlignVCenter")
        # 几何验证：关闭按钮右缘贴窗口右缘（问题1“跑到中间”的回归护栏）
        dlg.show()
        QtWidgets.QApplication.processEvents()
        cb = tb.closeBtn
        right_gap = dlg.width() - (cb.x() + cb.width())
        assert right_gap < 12, (
            f"关闭按钮距右缘 {right_gap}px，未右对齐（按钮组漂移到中间）")
        # 垂直：关闭按钮中线与标题栏中线偏差在 6px 内（问题2 的回归护栏）
        cb_cy = cb.y() + cb.height() // 2
        tb_cy = tb.height() // 2
        assert abs(cb_cy - tb_cy) <= 6, (
            f"关闭按钮中线 {cb_cy} 偏离标题栏中线 {tb_cy}")
    finally:
        dlg.hide()


def test_module_window_disables_mica_backdrop():
    """问题3：_ModuleWindow 构建时必须彻底关闭 DWM Mica backdrop（防“半白变透明”）。"""
    with mock.patch("ui.module_pages.disable_mica_backdrop",
                    create=True, return_value=False) as m:
        dlg = _open("rss_tb_dwm")
        try:
            m.assert_called_once()
        finally:
            dlg.hide()


def test_disable_mica_backdrop_hwnd0_is_noop():
    """离屏/无窗口句柄：容错静默返回 False，不得抛异常。"""
    assert disable_mica_backdrop(0) is False


def test_vbox_layout_expanding_for_right_anchor():
    """问题1（真实平台复现）：vBox 前必须恢复弹性 stretch 才能贴右缘。

    根因：迁移时 takeAt 移除了 hBoxLayout 的 stretch，而 QLayout 默认
    sizePolicy 为 Preferred（非 Expanding）→ buttonLayout 只占最小宽
    （338px）→ 真实 windows 下按钮组右缘距窗右缘 36px（offscreen 恰好
    不触发该差异）。在 vBoxLayout 之前插回 stretch 驱动其贴右。
    """
    dlg = _open("rss_vbox_exp")
    try:
        lay = dlg.titleBar.hBoxLayout
        vbox_idx = next(i for i in range(lay.count())
                        if lay.itemAt(i).layout() is not None)
        stretch_idx = next(
            (i for i in range(lay.count())
             if lay.itemAt(i).spacerItem() is not None
             and lay.itemAt(i).sizePolicy().horizontalPolicy()
             == QtWidgets.QSizePolicy.Expanding),
            None)
        assert stretch_idx is not None, "hBoxLayout 无弹性 stretch（按钮组贴不到右缘）"
        assert stretch_idx < vbox_idx, (
            f"stretch@ {stretch_idx} 应在 vBoxLayout@{vbox_idx} 之前")
    finally:
        dlg.hide()


def _fake_glass(w, p, cfg):
    """模拟 paint_wallpaper_glass：照常调用 painter.drawPixmap 画壁纸。"""
    p.drawPixmap(QtCore.QRect(0, 0, 10, 10), QtGui.QPixmap())
    return True


def test_module_window_paints_background_under_wallpaper():
    """问题4：壁纸路径下 _ModuleWindow 必须先铺不透明底色再画壁纸。

    根因：paint_wallpaper_glass 全程半透明（壁纸 opacity 0.35 + 遮罩 alpha~91），
    Mica backdrop 关闭后无底色承托 → 透明壁纸直接透出其他程序窗口。
    """
    from ui.module_pages import _ModuleWindow

    class Mod:
        name = "RSS"
        id = "rss_paint_win"
        context = types.SimpleNamespace(config={})

        def create_page(self, _parent):
            return _DuckPage()

    dlg = _ModuleWindow(Mod(), _DuckPage(), (940, 580), (940, 580))
    try:
        with mock.patch.object(QtGui, "QPainter") as MP, \
                mock.patch("ui.module_pages.paint_wallpaper_glass",
                           side_effect=_fake_glass) as glass_mock:
            painter = MP.return_value
            dlg.paintEvent(None)
            names = [c[0] for c in painter.method_calls]
            assert glass_mock.called
            assert "fillRect" in names, names
            assert names.index("fillRect") < names.index("drawPixmap"), (
                f"壁纸路径未先铺底色，绘制顺序 {names}")
    finally:
        dlg.hide()


def test_page_paints_background_under_wallpaper():
    """问题4：RSS 页面 paintEvent 在壁纸路径下同样先铺不透明底色。"""
    page = _DuckPage()
    try:
        with mock.patch.object(QtGui, "QPainter") as MP, \
                mock.patch("core.theme.paint_wallpaper_glass",
                           side_effect=_fake_glass) as glass_mock:
            painter = MP.return_value
            page.paintEvent(None)
            names = [c[0] for c in painter.method_calls]
            assert glass_mock.called
            assert "fillRect" in names, names
            assert names.index("fillRect") < names.index("drawPixmap"), (
                f"页面壁纸路径未先铺底色，绘制顺序 {names}")
    finally:
        page.deleteLater()


def test_migrated_btn_qss_reserves_arrow_space():
    """迁移按钮 QSS：text-align 左对齐 + 右 padding 26px 预留 Fluent 下拉箭头区
    （DropDownButtonBase 自绘箭头在 width()-22 处，sizeHint 不含箭头宽度），
    文字不再与自绘箭头重叠。"""
    from modules.rss_aggregator.page_theme import _RssPageWidget as ThemePage
    qss = ThemePage._migrated_btn_qss(object())
    assert "text-align: left" in qss, qss
    assert "padding: 0 26px 0 8px" in qss, qss


def test_combo_field_matches_migrated_button_style():
    """字段下拉（全部/标题/…）必须与迁移按钮同一透明 QSS：Fluent ComboBox 自带
    border-bottom + padding(5,31,6,11) 内容盒 31px 超过 28px 物理高 → 下边框被截断、
    视觉上比透明无框的邻居按钮大（用户反馈）。统一后箭头自绘不受影响。"""
    class Mod:
        name = "RSS"
        id = "rss_combo_qss"
        context = types.SimpleNamespace(config={})

        def create_page(self, _parent):
            return _DuckPage()

    dlg = _ModuleWindow(Mod(), _DuckPage(), (940, 580), (940, 580))
    try:
        page = dlg.findChild(_DuckPage)
        assert page.combo_search_field.styleSheet() == page._migrated_btn_qss(), (
            "字段下拉未与迁移按钮同 QSS：Fluent 边框盒在 28px 高下截断下边框")
    finally:
        dlg.hide()