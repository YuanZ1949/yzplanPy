"""RSS 对话框 A：编辑订阅源与订阅源管理。"""

import json
import logging
import re

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from .styles import _btn_primary_style, _btn_style
from .text_utils import _parse_keywords, _rss_colors
from .utils import _bind_geometry
from .dialogs_b import _AddFeedDialog

logger = logging.getLogger("rss_aggregator")

class _EditFeedDialog(QtWidgets.QDialog):
    def __init__(self, feed, store, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑订阅源")
        self.setMinimumWidth(450)
        _bind_geometry(self, "rss_edit_feed")
        self.feed = feed
        self.store = store

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        form = QtWidgets.QFormLayout()
        self.in_name = QtWidgets.QLineEdit(feed.get("name", ""))
        self.in_url = QtWidgets.QLineEdit(feed.get("url", ""))
        feed_tags = feed.get("tags") or ([feed.get("tag")] if feed.get("tag") else [])
        self.in_tag = QtWidgets.QLineEdit(", ".join(t for t in feed_tags if t))
        self.in_tag.setPlaceholderText("多个标签用逗号分隔，例如：科技, 资讯")
        self.in_group = QtWidgets.QLineEdit(feed.get("group_name", ""))
        self.in_interval = QtWidgets.QSpinBox()
        self.in_interval.setRange(60, 86400)
        self.in_interval.setSingleStep(60)
        self.in_interval.setValue(feed.get("refresh_interval", 1800))
        self.in_interval.setSuffix(" 秒")
        form.addRow("名称", self.in_name)
        form.addRow("URL", self.in_url)
        form.addRow("标签", self.in_tag)
        form.addRow("分组", self.in_group)
        form.addRow("刷新间隔", self.in_interval)
        lay.addLayout(form)

        if feed.get("last_error"):
            err_label = QtWidgets.QLabel(f"错误: {feed['last_error']}")
            err_label.setStyleSheet("QLabel { color: red; }")
            lay.addWidget(err_label)

        if feed.get("feed_type") == "scrape":
            self._scrape_options = json.loads(feed.get("scrape_options") or "{}")
            self.chk_rendered = QtWidgets.QCheckBox("需要 JS 渲染时才抓取（动态网页较慢）")
            self.chk_rendered.setChecked(bool(feed.get("rendered")))
            lay.addWidget(self.chk_rendered)
            sel_row = QtWidgets.QHBoxLayout()
            self.btn_selector = QtWidgets.QPushButton("重新选择元素")
            self.btn_selector.setStyleSheet(_btn_primary_style())
            self.btn_selector.clicked.connect(self._open_selector)
            sel_row.addWidget(self.btn_selector)
            self.lb_scrape = QtWidgets.QLabel(self._scrape_label())
            self.lb_scrape.setWordWrap(True)
            self.lb_scrape.setStyleSheet(f"color:{_rss_colors()['accent']};")
            sel_row.addWidget(self.lb_scrape, 1)
            lay.addLayout(sel_row)

            kw_row = QtWidgets.QHBoxLayout()
            kw_row.addWidget(QtWidgets.QLabel("关键词过滤"))
            self.in_keywords = QtWidgets.QLineEdit()
            self.in_keywords.setPlaceholderText("逗号/空格分隔，命中任一即保留；留空=接受全部")
            self.in_keywords.setClearButtonEnabled(True)
            kw_row.addWidget(self.in_keywords, 1)
            lay.addLayout(kw_row)
            kws = (self._scrape_options or {}).get("keywords") or []
            self.in_keywords.setText(", ".join(kws))
        else:
            self._scrape_options = None

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        btn_cancel = QtWidgets.QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QtWidgets.QPushButton("保存")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._do_save)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        lay.addLayout(btn_row)

    def _scrape_label(self):
        sel = (self._scrape_options or {}).get("selector", "")
        mode = "列表" if (self._scrape_options or {}).get("mode") == "list" else "单元素"
        return f"[{mode}] {sel}"

    def _open_selector(self):
        from ..page_selector import PageSelectorDialog
        dlg = PageSelectorDialog(self.feed.get("url", ""), self, initial_options=self._scrape_options)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._scrape_options = dlg.options()
            self.lb_scrape.setText(self._scrape_label())

    def _do_save(self):
        name = self.in_name.text().strip()
        url = self.in_url.text().strip()
        feed_tags = [t.strip() for t in self.in_tag.text().replace("，", ",").split(",") if t.strip()] or [name]
        tag = feed_tags[0]
        group = self.in_group.text().strip()
        interval = self.in_interval.value()
        if not name or not url:
            return
        kwargs = dict(name=name, url=url, tag=tag, tags=feed_tags, group_name=group, refresh_interval=interval)
        if self.feed.get("feed_type") == "scrape":
            if not (self._scrape_options or {}).get("selector"):
                QtWidgets.QMessageBox.warning(self, "提示", "请先用页面选择器锁定要监控的元素")
                return
            opts = dict(self._scrape_options)
            opts["keywords"] = _parse_keywords(self.in_keywords.text())
            kwargs["scrape_options"] = opts
            kwargs["rendered"] = 1 if self.chk_rendered.isChecked() else 0
        self.store.update_feed(self.feed["id"], **kwargs)
        self.accept()


class _FeedManageDialog(QtWidgets.QDialog):
    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.setWindowTitle("管理订阅源")
        self.setMinimumSize(600, 400)
        _bind_geometry(self, "rss_feed_manage", default_size=(600, 400))
        self.owner = owner

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        self.feed_list = QtWidgets.QListWidget()
        self.feed_list.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.feed_list.model().rowsMoved.connect(self._on_feed_order_changed)
        lay.addWidget(self.feed_list, 1)

        btn_row = QtWidgets.QHBoxLayout()
        btn_add = QtWidgets.QPushButton("添加订阅")
        btn_add.setStyleSheet(_btn_primary_style())
        btn_add.clicked.connect(self._show_add_dialog)
        btn_edit = QtWidgets.QPushButton("编辑选中")
        btn_edit.setStyleSheet(_btn_style())
        btn_edit.clicked.connect(self._edit_feed)
        btn_del = QtWidgets.QPushButton("删除选中")
        btn_del.setStyleSheet(_btn_style())
        btn_del.clicked.connect(self._remove_feed)
        btn_toggle = QtWidgets.QPushButton("启用/停用")
        btn_toggle.setStyleSheet(_btn_style())
        btn_toggle.clicked.connect(self._toggle_feed)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_edit)
        btn_row.addWidget(btn_del)
        btn_row.addWidget(btn_toggle)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        self._load_feeds()

    def _load_feeds(self):
        self.feed_list.clear()
        for f in self.owner.store.list_feeds():
            status = "✓" if f["enabled"] else "✗"
            group = f" [{f['group_name']}]" if f.get("group_name") else ""
            error = f" ⚠{f['last_error'][:30]}" if f.get("last_error") else ""
            kind = " [监控]" if f.get("feed_type") == "scrape" else ""
            text = "{}{} {}{}{} — {}{}".format(status, kind, f["name"], group, "", f["url"], error)
            tags = f.get("tags") or ([f["tag"]] if f.get("tag") else [])
            tags = [t for t in tags if t and t != f["name"]]
            if tags:
                text += "  (标签: {})".format(", ".join(tags))
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, f["id"])
            item.setData(QtCore.Qt.UserRole + 1, f["enabled"])
            self.feed_list.addItem(item)

    def _on_feed_order_changed(self):
        feed_ids = []
        for i in range(self.feed_list.count()):
            item = self.feed_list.item(i)
            feed_ids.append(item.data(QtCore.Qt.UserRole))
        self.owner.store.update_feed_order(feed_ids)

    def _show_add_dialog(self):
        dlg = _AddFeedDialog(self.owner, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._load_feeds()

    def _edit_feed(self):
        item = self.feed_list.currentItem()
        if item is None:
            return
        fid = item.data(QtCore.Qt.UserRole)
        feed = self.owner.store.get_feed_by_id(fid)
        if not feed:
            return
        dlg = _EditFeedDialog(feed, self.owner.store, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._load_feeds()

    def _remove_feed(self):
        item = self.feed_list.currentItem()
        if item is None:
            return
        fid = item.data(QtCore.Qt.UserRole)
        self.owner.store.remove_feed(fid)
        self._load_feeds()

    def _toggle_feed(self):
        item = self.feed_list.currentItem()
        if item is None:
            return
        fid = item.data(QtCore.Qt.UserRole)
        enabled = item.data(QtCore.Qt.UserRole + 1)
        self.owner.store.set_feed_enabled(fid, not enabled)
        self._load_feeds()
