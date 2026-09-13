"""标题栏筛查测试的共享替身页面与窗口工厂。

L1（offscreen 结构性护栏）与 L2（windows QPA 像素级取证）共用。
样式敏感控件必须用 Fluent 真实类型（ComboBox/DropDownPushButton 均为
QPushButton 子类），`_migrated_btn_qss` 的 `QPushButton{}` 选择器才真实生效；
原生 QComboBox 不吃该选择器会造成假阴性。

本模块只定义类/函数，绝不创建 QApplication——平台取决于各测试文件
import 本模块前的环境变量与 QApplication 创建顺序。
"""

import sys
import types

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from qfluentwidgets import (
    ComboBox,
    DropDownPushButton,
    PrimaryDropDownPushButton,
    PushButton,
    SearchLineEdit,
)

import modules.rss_aggregator.page_lifecycle as _lifecycle_mod
from modules.rss_aggregator.page_theme import _RssPageWidget as _ThemePage


class _DuckPage(QtWidgets.QWidget):
    """实现 _build_title_bar_widgets 全部接口的页面替身。

    控件类型对齐真实页面：字段下拉/弹片按钮用 Fluent 真实组件，迁移 QSS
    与渲染路径与线上一致；兼容 offscreen 与 windows QPA 两平台。
    """

    frameless = True

    def __init__(self):
        super().__init__()
        self._title_bar_migrated = False
        self._show_thumbnails = False
        self.owner = types.SimpleNamespace(context=types.SimpleNamespace(config={}))
        self.btn_thumb = PushButton("缩略图")
        self._search_wg = QtWidgets.QFrame()
        self._search_wg.setObjectName("rssSearchBox")
        self.btn_date_filter = DropDownPushButton("时间筛选")
        self.btn_filter = DropDownPushButton("筛选")
        self.btn_read_ops = DropDownPushButton("阅读")
        self.btn_batch_ops = PrimaryDropDownPushButton("批量")
        self.search_input = SearchLineEdit()
        self.combo_search_field = ComboBox()
        self.combo_search_field.addItems(["全部", "标题", "描述", "链接"])
        self.tool_bar = QtWidgets.QWidget()

    def _toggle_thumbnails(self, _checked):
        pass

    def _update_thumbnail_btn_text(self):
        pass

    @staticmethod
    def _noop():
        pass

    @property
    def title_bar_spec(self):
        from qfluentwidgets import FluentIcon

        return {"buttons": [
            {"icon": FluentIcon.SETTING, "text": "设置", "tooltip": "设置",
             "cb": self._noop},
            {"icon": FluentIcon.SHARE, "text": "导出", "tooltip": "导出",
             "cb": self._noop},
            {"icon": FluentIcon.FOLDER, "text": "导入", "tooltip": "导入",
             "cb": self._noop},
        ], "widgets": True}


def _duck_paint_event(self, event):
    """替身页面最小渲染：铺不透明底色即可。

    生产 paintEvent 的 `super().paintEvent(event)` 在非继承链实例上会崩
    TypeError（鸭子绑定副产物）；L1 已用 mock 覆盖生产"先底色后壁纸"契约，
    此处只需保证真实渲染（show/grab）不崩且窗口不透明。
    """
    painter = QtGui.QPainter(self)
    try:
        painter.fillRect(self.rect(), self.palette().color(QtGui.QPalette.Window))
    finally:
        painter.end()


# 绑定真实实现：标题栏迁移 + 迁移按钮 QSS（纯函数绑定，无副作用）；
# paintEvent 用替身实现（见 _duck_paint_event 注释）。
_DuckPage._build_title_bar_widgets = _lifecycle_mod._RssPageWidget._build_title_bar_widgets
_DuckPage._migrated_btn_qss = _ThemePage._migrated_btn_qss
_DuckPage.paintEvent = _duck_paint_event


def _make_mod(mod_id):
    class _Mod:
        name = "RSS"
        id = mod_id

        def create_page(self, _parent):
            return _DuckPage()

    return _Mod()


def make_module_window(mod_id="rss_tb_window"):
    """构造 _ModuleWindow（构造即触发 _build_title_bar_widgets 迁移）。不 show。"""
    from ui.module_pages import _ModuleWindow

    return _ModuleWindow(_make_mod(mod_id), _DuckPage(), (940, 580), (940, 580))


def open_module_window(mod_id="rss_tb_open"):
    """经 open_module_page 打开独立模块窗口（真实入口，含单例去重）。"""
    from ui.module_pages import open_module_page

    return open_module_page(_make_mod(mod_id))


def migrated_controls(page):
    """迁移进标题栏、必须统一为同一款迁移 QSS 的弹片系控件清单。"""
    return (page.combo_search_field, page.btn_date_filter, page.btn_filter,
            page.btn_read_ops, page.btn_batch_ops, page.btn_thumb)