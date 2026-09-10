"""RSS 页面：生命周期/清理/快捷键/侧栏构建。"""

import logging
import re
import webbrowser

from core.qt_bootstrap import import_qt
from qfluentwidgets import FluentIcon, PushButton

_, QtCore, QtGui, QtWidgets = import_qt()

logger = logging.getLogger("rss_aggregator")
from .dialogs_a import _FeedManageDialog
from .dialogs_d import _SettingsDialog
from .page import _RssPageWidget
from .preview import _PREVIEW_KEEP
from .text_utils import _rss_colors

class _RssPageWidget(_RssPageWidget):  # type: ignore[reportGeneralTypeIssues]

    @property
    def title_bar_spec(self):
        """模块窗口定制标题栏契约：设置/导出/导入 icon+文字按钮 + 迁移页面工具条控件。"""
        return {"buttons": [
            {"icon": FluentIcon.SETTING, "text": "设置", "tooltip": "模块设置",
             "cb": self._toggle_settings_section},
            {"icon": FluentIcon.SHARE, "text": "导出", "tooltip": "导出 OPML",
             "cb": self._export_opml},
            {"icon": FluentIcon.FOLDER, "text": "导入", "tooltip": "导入 OPML",
             "cb": self._import_opml},
        ], "widgets": True}

    def _build_title_bar_widgets(self, tb):
        """把页面工具条控件迁移进自定义标题栏（独立模块窗口时调用）。

        搜索框/时间筛选/筛选/阅读/批量/缩略图插入标题栏主布局（窗口标题之后、
        右侧设置按钮组之前），移除原有 stretch 让搜索框自适应宽度。观感统一为
        Fluent 标题栏按钮风格（对齐"设置"按钮）：清除工具条弹片 QSS、全部按钮
        统一 30px 高留出呼吸空间、组内 8px / 组缘 12px 均匀间隔。信号绑定自动保留。
        """
        if getattr(self, "_title_bar_migrated", False):
            return
        self._title_bar_migrated = True

        # 缩略图按钮：普通 QPushButton 换成 Fluent PushButton（风格与明暗主题随动）
        thumb = PushButton(self.btn_thumb.text(), tb)
        thumb.setCheckable(True)
        thumb.setChecked(self._show_thumbnails)
        thumb.setToolTip(self.btn_thumb.toolTip())
        thumb.toggled.connect(self._toggle_thumbnails)
        self.btn_thumb = thumb

        widgets = [self._search_wg, self.btn_date_filter, self.btn_filter,
                   self.btn_read_ops, self.btn_batch_ops, self.btn_thumb]
        if hasattr(tb, "hBoxLayout") and hasattr(tb, "vBoxLayout"):
            # 优先插入主 hBoxLayout：找到 title 之后的 stretch（Expanding spacer）
            lay = tb.hBoxLayout
            pos = None
            for i in range(lay.count()):
                sp = lay.itemAt(i).spacerItem()
                if sp is not None and sp.sizePolicy().horizontalPolicy() == QtWidgets.QSizePolicy.Expanding:
                    pos = i
                    break
            if pos is None:
                pos = lay.count()
            else:
                lay.takeAt(pos)  # 移除 stretch：多余宽度让搜索框吸收
            k = 0
            lay.insertSpacing(pos + k, 12); k += 1  # 窗口标题与搜索块之间
            for idx, w in enumerate(widgets):
                lay.insertWidget(pos + k, w); k += 1
                if idx < len(widgets) - 1:
                    lay.insertSpacing(pos + k, 8); k += 1
            lay.insertSpacing(pos + k, 12); k += 1  # 操作组与右侧设置/窗口组之间
            # 搜索框自适应横向宽度；操作按钮垂直居中与左侧控件一致
            self.search_input.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding, self.search_input.sizePolicy().verticalPolicy())
            try:
                tb.buttonLayout.setAlignment(QtCore.Qt.AlignCenter)
            except Exception:
                pass
        else:
            # 兼容性回退：无 hBoxLayout 的假标题栏（测试/其他宿主）走旧 buttonLayout 左插
            lay = tb.buttonLayout
            for i, w in enumerate(widgets):
                lay.insertWidget(i, w)

        # —— 风格统一：对齐"设置"按钮（Fluent 默认外观 + 30px 高 + 均匀间隔）——
        for b in (self.btn_date_filter, self.btn_filter, self.btn_read_ops):
            b.setStyleSheet("")  # 清除工具条弹片 QSS，回 Fluent 按钮默认外观
        self.combo_search_field.setFixedWidth(44)
        self.search_input.setMinimumWidth(150)
        for w in (self.combo_search_field, self.search_input,
                  self.btn_date_filter, self.btn_filter, self.btn_read_ops,
                  self.btn_batch_ops, self.btn_thumb):
            w.setFixedHeight(30)  # 36px 标题栏内上下各留 ~3px 呼吸空间
        # 搜索框去掉"盒子"感：QFrame 背景透明，边框交给 Fluent SearchLineEdit 自绘
        self._search_wg.setStyleSheet(
            "QFrame#rssSearchBox { background: transparent; border: none; }")
        # 右侧"设置/导出/导入"与迁移控件同高
        # （窗口钮 FluentTitleBarButton 非 PushButton，自动跳过）
        try:
            for i in range(tb.buttonLayout.count()):
                w = tb.buttonLayout.itemAt(i).widget()
                if isinstance(w, PushButton):
                    w.setFixedHeight(30)
        except Exception:
            pass
        self.tool_bar.setVisible(False)
        self._update_thumbnail_btn_text()

    def _cleanup_preview(self):
        """页面销毁时清理本地引用，但保留全局 WebEngine 单例。

        旧代码在 destroyed 时清除 _PREVIEW_KEEP["view"]，导致下次打开模块
        重新创建 QWebEngineProfile → 新 Chromium 子进程 → 线程无限增长。
        新逻辑：先把视图从 QStackedWidget 中摘除（避免 Qt 父子析构链销毁
        C++ 对象），再清空本地引用，但保留 _PREVIEW_KEEP 让下次打开可复用。"""
        global _PREVIEW_KEEP
        try:
            self._preview_timer.stop()
        except Exception:
            pass
        # 从 stack 中摘除视图，防止 Qt 销毁子控件时连带销毁 C++ 视图
        if self._preview_browser_view is not None:
            try:
                self._preview_stack.removeWidget(self._preview_browser_view)
                self._preview_browser_view.setParent(None)
            except Exception:
                pass
        self._preview_browser_view = None
        self._preview_text_view = None
        self.preview_browser = None

    def paintEvent(self, event):
        # 独立页窗口：与主窗口一致的壁纸+毛玻璃背景（无壁纸时回退默认渲染）
        try:
            from core.theme import paint_wallpaper_glass
            cfg = self.owner.context.config
            painter = QtGui.QPainter(self)
            painted = paint_wallpaper_glass(self, painter, cfg)
            painter.end()
            if not painted:
                super().paintEvent(event)
        except Exception:
            super().paintEvent(event)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_J:
            row = self.item_list.currentRow()
            if row < self.item_list.count() - 1:
                self.item_list.setCurrentRow(row + 1)
        elif event.key() == QtCore.Qt.Key_K:
            row = self.item_list.currentRow()
            if row > 0:
                self.item_list.setCurrentRow(row - 1)
        elif event.key() == QtCore.Qt.Key_Return or event.key() == QtCore.Qt.Key_Enter:
            item = self.item_list.currentItem()
            if item:
                self._open_item(item)
        elif event.key() == QtCore.Qt.Key_S:
            item = self.item_list.currentItem()
            if item:
                h = item.data(QtCore.Qt.UserRole)
                self.owner.store.toggle_favorite(h)
                self._load_items()
        elif event.key() == QtCore.Qt.Key_R:
            item = self.item_list.currentItem()
            if item:
                h = item.data(QtCore.Qt.UserRole)
                if self.owner.store.is_read(h):
                    self.owner.store.mark_unread(h)
                else:
                    self.owner.store.mark_read(h)
                self._load_items()
        elif event.key() == QtCore.Qt.Key_C:
            item = self.item_list.currentItem()
            if item:
                h = item.data(QtCore.Qt.UserRole)
                text = self.owner.store.share_item(h)
                if text:
                    QtWidgets.QApplication.clipboard().setText(text)
                    self.lb_status.setText("已复制到剪贴板")
        else:
            super().keyPressEvent(event)

    def _update_date_filter_ui(self):
        """同步时间筛选按钮文字与快捷项勾选状态。"""
        dr = self._current_date_range
        act_map = self._date_quick_actions
        for key, act in act_map.items():
            act.setChecked(dr == key)
        if not dr:
            self.btn_date_filter.setText("时间筛选")
        elif isinstance(dr, str):
            self.btn_date_filter.setText(f"时间：{self._date_preset_labels.get(dr, dr)}")
        else:
            date_from, date_to = dr[1], dr[2]
            label_from = date_from[5:] if len(date_from) == 10 else date_from
            label_to = date_to[5:] if len(date_to) == 10 else date_to
            self.btn_date_filter.setText(f"时间：{label_from}~{label_to}")

    def _set_date_preset(self, key):
        """设置快捷时间区间（today/week/month），key=None 表示清除。"""
        if key in self._date_preset_labels:
            self._current_date_range = key
        else:
            self._current_date_range = None
        self._update_date_filter_ui()
        self._load_items()

    def _apply_date_range(self):
        """应用自定义起止日期范围。"""
        date_from = self.date_from.date().toString("yyyy-MM-dd")
        date_to = self.date_to.date().toString("yyyy-MM-dd")
        if date_from > self.date_to.date().toString("yyyy-MM-dd"):
            QtWidgets.QMessageBox.information(self, "日期范围", "开始日期不应晚于结束日期。")
            return
        self._current_date_range = ("range", date_from, date_to)
        self._update_date_filter_ui()
        self._date_menu.close()
        self._load_items()

    def _build_feed_section(self):
        self.feed_section = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(self.feed_section)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self.feed_list = QtWidgets.QListWidget()
        self.feed_list.setMinimumHeight(80)
        self.feed_list.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.feed_list.model().rowsMoved.connect(self._on_feed_order_changed)
        lay.addWidget(self.feed_list, 1)

        btn_row = QtWidgets.QHBoxLayout()
        btn_add = QtWidgets.QPushButton("添加订阅")
        btn_add.clicked.connect(self._show_add_dialog)
        btn_edit = QtWidgets.QPushButton("编辑选中")
        btn_edit.clicked.connect(self._edit_feed)
        btn_del = QtWidgets.QPushButton("删除选中")
        btn_del.clicked.connect(self._remove_feed)
        btn_toggle = QtWidgets.QPushButton("启用/停用")
        btn_toggle.clicked.connect(self._toggle_feed)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_edit)
        btn_row.addWidget(btn_del)
        btn_row.addWidget(btn_toggle)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        self.feed_section.setVisible(False)

        root = self.layout()
        root.insertWidget(0, self.feed_section)
        self._load_feeds()

    def _toggle_feed_section(self):
        dlg = _FeedManageDialog(self.owner, self)
        dlg.exec()
        self._load_tag_filter()
        self._load_items(preserve_scroll=True)

    def _toggle_settings_section(self):
        dlg = _SettingsDialog(self.owner, self)
        dlg.exec()
        self._load_items(preserve_scroll=True)
