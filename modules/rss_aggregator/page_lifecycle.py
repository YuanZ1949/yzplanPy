"""RSS 页面：生命周期/清理/快捷键/侧栏构建。"""

import logging
import re
import webbrowser

from core.qt_bootstrap import import_qt
from qfluentwidgets import FluentIcon

_, QtCore, QtGui, QtWidgets = import_qt()

logger = logging.getLogger("rss_aggregator")
from .dialogs_a import _FeedManageDialog
from .dialogs_d import _SettingsDialog
from .page import _RssPageWidget
from .preview import _PREVIEW_KEEP
from .text_utils import _rss_colors

class _RssPageWidget(_RssPageWidget):

    @property
    def title_bar_spec(self):
        """模块窗口定制标题栏契约：设置/导出/导入 icon+文字按钮。"""
        return {"buttons": [
            {"icon": FluentIcon.SETTING, "text": "设置", "tooltip": "模块设置",
             "cb": self._toggle_settings_section},
            {"icon": FluentIcon.SHARE, "text": "导出", "tooltip": "导出 OPML",
             "cb": self._export_opml},
            {"icon": FluentIcon.FOLDER, "text": "导入", "tooltip": "导入 OPML",
             "cb": self._import_opml},
        ]}

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
