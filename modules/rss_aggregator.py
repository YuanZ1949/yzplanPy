"""rss_aggregator 模块：多源 RSS 聚合、合并去重、多来源标签标注。"""
import json
import logging
import threading
import webbrowser

from core.qt_bootstrap import import_qt
from .base import ModuleBase
from .rss_store import (
    RssStore, _hash, _is_magnet_or_torrent, fetch_feed,
    export_opml_file, import_opml_file, _extract_image,
)

logger = logging.getLogger("rss_aggregator")

_, QtCore, QtGui, QtWidgets = import_qt()

PAGE_SIZE = 50


MODULE_INFO = {
    "id": "rss_aggregator",
    "name": "RSS 聚合",
    "description": "多来源聚合、去重与来源标签标注",
}


class Module(ModuleBase):
    MODULE_ID = "rss_aggregator"
    MODULE_NAME = "RSS 聚合"
    MODULE_DESCRIPTION = "多来源聚合、去重与来源标签标注"

    def __init__(self, context):
        super().__init__(context)
        from core.constants import DB_PATH
        self.store = RssStore(DB_PATH)
        self._timer = None
        self._thread = None
        self._widgets = []
        self._notification_callback = None
        self._proxy = context.config.get("rss.proxy", "")
        self._retry_count = 3
        self._retry_delay = 5

    def start(self):
        if self._running:
            return
        super().start()
        from core.qt_bootstrap import import_qt
        _, QtCore, QtGui, QtWidgets = import_qt()
        self._timer = QtCore.QTimer()
        self._timer.timeout.connect(self._auto_refresh)
        self._timer.start(60 * 1000)
        self._auto_refresh()
        if self.context.config.get("rss.auto_cleanup", False):
            self.store.cleanup_old(self.context.config.get("rss.cleanup_days", 30))
        logger.info("RSS模块已启动")

    def stop(self):
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        super().stop()
        logger.info("RSS模块已停止")

    def set_notification_callback(self, callback):
        self._notification_callback = callback

    def set_proxy(self, proxy):
        self._proxy = proxy or ""
        logger.info("RSS代理已更新: %s", self._proxy or "无")

    def _auto_refresh(self):
        feeds = self.store.get_feeds_needing_refresh()
        if feeds and self._thread is None:
            logger.debug("自动刷新触发, %d个源需要更新", len(feeds))
            self._do_refresh(feeds)

    def refresh_now(self):
        feeds = [f for f in self.store.list_feeds() if f["enabled"]]
        if not feeds or self._thread is not None:
            return
        logger.info("手动刷新, %d个源", len(feeds))
        self._do_refresh(feeds)

    def _do_refresh(self, feeds):
        from core.qt_bootstrap import import_qt
        _, QtCore, QtGui, QtWidgets = import_qt()
        self._fetcher = _Fetcher(feeds, self.store, self._proxy, self._retry_count, self._retry_delay)
        self._fetcher.finished.connect(self._on_refreshed)
        self._fetcher.item_added.connect(self._on_item_added)
        self._thread = threading.Thread(target=self._fetcher.run, daemon=True)
        self._thread.start()

    def _on_item_added(self, item_info):
        if self._notification_callback:
            self._notification_callback(item_info)

    def _on_refreshed(self, counts):
        self._thread = None
        for w in self._widgets:
            w.on_refreshed(counts)

    def create_home_widget(self, parent):
        w = _RssHomeWidget(self, parent)
        self._widgets.append(w)
        return w

    def create_page(self, parent):
        return _RssPageWidget(self, parent)


class _Fetcher(QtCore.QObject):
    finished = QtCore.Signal(list)
    item_added = QtCore.Signal(dict)

    def __init__(self, feeds, store, proxy="", retry_count=3, retry_delay=5):
        super().__init__()
        self.feeds = feeds
        self.store = store
        self.proxy = proxy
        self.retry_count = retry_count
        self.retry_delay = retry_delay

    def run(self):
        counts = []
        for f in self.feeds:
            try:
                logger.debug("开始抓取: %s (%s)", f["name"], f["url"])
                entries, feed_title, etag, last_modified = fetch_feed(
                    f["url"],
                    proxy=self.proxy,
                    custom_headers=json.loads(f.get("custom_headers", "{}")),
                    etag=f.get("etag") or None,
                    last_modified=f.get("last_modified") or None,
                    retry_count=self.retry_count,
                    retry_delay=self.retry_delay,
                )
                if not entries and etag:
                    logger.debug("304 无更新: %s", f["name"])
                    self.store.update_feed_refresh_time(f["id"])
                    counts.append((f["name"], f["tag"], 0, 0))
                    continue
                entries = self.store.apply_filter_rules(entries)
                entries = [e for e in entries if not e.get("_skip")]
                for e in entries:
                    if e.get("extra_tag"):
                        e["_final_tag"] = e["extra_tag"]
                    else:
                        e["_final_tag"] = f["tag"] or f["name"]
                added = self.store.ingest(f["tag"] or f["name"], entries)
                self.store.update_feed_refresh_time(f["id"])
                if etag is not None:
                    self.store.update_feed(f["id"], etag=etag or "", last_modified=last_modified or "")
                self.store.clear_feed_error(f["id"])
                logger.info("抓取完成: %s — %d条, 新增%d条", f["name"], len(entries), added)
                for e in entries:
                    if added > 0:
                        matched_kw = self.store.check_keywords(e.get("title", ""), e.get("description", ""))
                        if matched_kw:
                            self.item_added.emit(
                                {
                                    "title": e.get("title", ""),
                                    "link": e.get("link", ""),
                                    "source": f["name"],
                                    "keywords": [kw["keyword"] for kw in matched_kw],
                                }
                            )
                counts.append((f["name"], f["tag"], len(entries), added))
            except Exception as ex:
                logger.warning("抓取失败: %s — %s", f["name"], ex)
                self.store.set_feed_error(f["id"], str(ex))
                counts.append((f["name"], f["tag"], 0, 0))
        self.finished.emit(counts)


_BTN_STYLE = (
    "QPushButton { padding: 6px 16px; border: 1px solid #bbb; border-radius: 4px; "
    "background: #f0f0f0; color: #333; font-size: 13px; min-width: 70px; min-height: 20px; }"
    "QPushButton:hover { background: #e0e0e0; border-color: #888; }"
    "QPushButton:pressed { background: #d0d0d0; }"
)
_BTN_PRIMARY_STYLE = (
    "QPushButton { padding: 6px 16px; border: none; border-radius: 4px; "
    "background: #1a73e8; color: white; font-size: 13px; font-weight: bold; min-width: 70px; min-height: 20px; }"
    "QPushButton:hover { background: #1557b0; }"
    "QPushButton:pressed { background: #104d9a; }"
)

_network_mgr = None


def _get_network_mgr():
    global _network_mgr
    if _network_mgr is None:
        from PySide6.QtNetwork import QNetworkAccessManager
        _network_mgr = QNetworkAccessManager()
    return _network_mgr


def _load_thumb_async(url, label):
    from PySide6.QtNetwork import QNetworkRequest
    req = QNetworkRequest(QtCore.QUrl(url))
    req.setTransferTimeout(5000)
    reply = _get_network_mgr().get(req)

    def _on_reply():
        if reply.error() == reply.NetworkError.NoError:
            data = reply.readAll()
            pixmap = QtGui.QPixmap()
            pixmap.loadFromData(data)
            if not pixmap.isNull():
                label.setPixmap(pixmap.scaled(40, 40, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
            else:
                label.setText("IMG")
        else:
            label.setText("IMG")
        reply.deleteLater()

    reply.finished.connect(_on_reply)


def _bind_geometry(dialog, key, default_size=None):
    """为对话框绑定几何记忆：启动恢复、关闭保存。"""
    from core.ui_state import window_geometry
    geometry = window_geometry()
    geometry.apply(dialog, key, default_size=default_size)
    dialog.finished.connect(lambda *_: geometry.capture(dialog, key))


def _make_item_row(widget, it, on_open, show_thumbnail=False, checked=False):
    tags = it["tags"] or ""
    is_read = bool(it.get("read"))
    is_fav = bool(it.get("favorite"))
    type_tag = "磁链" if _is_magnet_or_torrent(it["link"]) else "文章"

    row_widget = QtWidgets.QWidget()
    row_layout = QtWidgets.QHBoxLayout(row_widget)
    row_layout.setContentsMargins(4, 2, 4, 2)
    row_layout.setSpacing(6)

    chk = QtWidgets.QCheckBox()
    chk.setChecked(checked)
    row_layout.addWidget(chk)

    if is_fav:
        fav_label = QtWidgets.QLabel("★")
        fav_label.setStyleSheet("QLabel { color: #ffc107; font-size: 14px; }")
        fav_label.setFixedWidth(16)
        row_layout.addWidget(fav_label)

    if show_thumbnail and it.get("image_url"):
        thumb = QtWidgets.QLabel()
        thumb.setFixedSize(40, 40)
        thumb.setStyleSheet("QLabel { background: #f0f0f0; border-radius: 4px; }")
        thumb.setAlignment(QtCore.Qt.AlignCenter)
        thumb.setText("...")
        row_layout.addWidget(thumb)
        url = it["image_url"]
        if url.startswith("http"):
            _load_thumb_async(url, thumb)
        else:
            pixmap = QtGui.QPixmap(url)
            if not pixmap.isNull():
                thumb.setPixmap(pixmap.scaled(40, 40, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
            else:
                thumb.setText("IMG")

    title_text = it["title"] or it["link"]
    title_btn = QtWidgets.QPushButton(title_text)
    if is_read:
        title_btn.setStyleSheet(
            "QPushButton { text-align: left; border: none; background: transparent; "
            "color: #888; padding: 2px; }"
            "QPushButton:hover { color: #555; }"
        )
    else:
        title_btn.setStyleSheet(
            "QPushButton { text-align: left; border: none; background: transparent; color: palette(text); "
            "text-decoration: underline; padding: 2px; }"
            "QPushButton:hover { color: #1a73e8; }"
        )
    title_btn.setCursor(QtGui.Qt.PointingHandCursor)
    title_btn.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
    row_layout.addWidget(title_btn, 1)

    if tags:
        tag_label = QtWidgets.QLabel(tags)
        tag_label.setStyleSheet(
            "QLabel { background: #e8f0fe; color: #1967d2; padding: 2px 6px; border-radius: 3px; font-size: 11px; }"
        )
        tag_label.setAlignment(QtCore.Qt.AlignCenter)
        row_layout.addWidget(tag_label)

    type_label = QtWidgets.QLabel(type_tag)
    if type_tag == "磁链":
        type_label.setStyleSheet(
            "QLabel { background: #fce8e6; color: #c5221f; padding: 2px 6px; border-radius: 3px; font-size: 11px; }"
        )
    else:
        type_label.setStyleSheet(
            "QLabel { background: #e6f4ea; color: #137333; padding: 2px 6px; border-radius: 3px; font-size: 11px; }"
        )
    type_label.setAlignment(QtCore.Qt.AlignCenter)
    row_layout.addWidget(type_label)

    return row_widget, title_btn, chk


class _ItemPreviewDialog(QtWidgets.QDialog):
    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.setWindowTitle(item.get("title", "条目详情"))
        self.setMinimumSize(600, 500)
        self.resize(700, 600)
        _bind_geometry(self, "rss_item_preview", default_size=(700, 600))

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        title_label = QtWidgets.QLabel(item.get("title", ""))
        title_label.setStyleSheet("QLabel { font-size: 16px; font-weight: bold; }")
        title_label.setWordWrap(True)
        lay.addWidget(title_label)

        meta_row = QtWidgets.QHBoxLayout()
        if item.get("tags"):
            tags_label = QtWidgets.QLabel(f"来源: {item['tags']}")
            tags_label.setStyleSheet("QLabel { color: #1967d2; }")
            meta_row.addWidget(tags_label)
        if item.get("published"):
            pub_label = QtWidgets.QLabel(f"发布时间: {item['published']}")
            pub_label.setStyleSheet("QLabel { color: #666; }")
            meta_row.addWidget(pub_label)
        meta_row.addStretch(1)
        lay.addLayout(meta_row)

        browser = QtWidgets.QTextBrowser()
        browser.setOpenExternalLinks(True)
        desc = item.get("description", "")
        if desc:
            browser.setHtml(desc)
        else:
            browser.setPlainText("无描述内容")
        lay.addWidget(browser, 1)

        btn_row = QtWidgets.QHBoxLayout()
        btn_open = QtWidgets.QPushButton("在浏览器中打开")
        btn_open.clicked.connect(lambda: webbrowser.open(item.get("link", "")))
        btn_row.addStretch(1)
        btn_row.addWidget(btn_open)
        lay.addLayout(btn_row)


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
        self.in_tag = QtWidgets.QLineEdit(feed.get("tag", ""))
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

    def _do_save(self):
        name = self.in_name.text().strip()
        url = self.in_url.text().strip()
        tag = self.in_tag.text().strip() or name
        group = self.in_group.text().strip()
        interval = self.in_interval.value()
        if not name or not url:
            return
        self.store.update_feed(
            self.feed["id"],
            name=name, url=url, tag=tag, group_name=group, refresh_interval=interval,
        )
        self.accept()


class _AddFeedDialog(QtWidgets.QDialog):
    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加订阅源")
        self.setMinimumWidth(450)
        _bind_geometry(self, "rss_add_feed")
        self.owner = owner

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        form = QtWidgets.QFormLayout()
        self.in_name = QtWidgets.QLineEdit()
        self.in_name.setPlaceholderText("例如：阮一峰博客")
        self.in_url = QtWidgets.QLineEdit()
        self.in_url.setPlaceholderText("RSS/Atom feed 地址，或网站首页URL自动发现")
        self.in_tag = QtWidgets.QLineEdit()
        self.in_tag.setPlaceholderText("来源标签（可选，默认同名称）")
        self.in_group = QtWidgets.QLineEdit()
        self.in_group.setPlaceholderText("分组（可选）")
        self.in_interval = QtWidgets.QSpinBox()
        self.in_interval.setRange(60, 86400)
        self.in_interval.setSingleStep(60)
        self.in_interval.setValue(1800)
        self.in_interval.setSuffix(" 秒")
        self.in_interval.setSpecialValueText("自定义")
        form.addRow("名称", self.in_name)
        form.addRow("URL", self.in_url)
        form.addRow("标签", self.in_tag)
        form.addRow("分组", self.in_group)
        form.addRow("刷新间隔", self.in_interval)
        lay.addLayout(form)

        btn_discover = QtWidgets.QPushButton("自动发现RSS")
        btn_discover.clicked.connect(self._discover)
        lay.addWidget(btn_discover)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        btn_cancel = QtWidgets.QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QtWidgets.QPushButton("添加")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._do_add)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        lay.addLayout(btn_row)

    def _discover(self):
        url = self.in_url.text().strip()
        if not url:
            return
        feeds = self.owner.store.discover_feed(url)
        if not feeds:
            QtWidgets.QMessageBox.information(self, "发现", "未找到RSS订阅源")
            return
        if len(feeds) == 1:
            self.in_url.setText(feeds[0]["href"])
            if feeds[0].get("title") and not self.in_name.text():
                self.in_name.setText(feeds[0]["title"])
        else:
            items = [f"{f['title'] or f['href']} ({f['type']})" for f in feeds]
            item, ok = QtWidgets.QInputDialog.getItem(self, "选择订阅源", "发现多个订阅源:", items, 0, False)
            if ok:
                idx = items.index(item)
                self.in_url.setText(feeds[idx]["href"])
                if feeds[idx].get("title") and not self.in_name.text():
                    self.in_name.setText(feeds[idx]["title"])

    def _do_add(self):
        name = self.in_name.text().strip()
        url = self.in_url.text().strip()
        tag = self.in_tag.text().strip() or name
        group = self.in_group.text().strip()
        interval = self.in_interval.value()
        if not name or not url:
            return
        self.owner.store.add_feed(name, url, tag, group, interval)
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
        btn_add.setStyleSheet(_BTN_PRIMARY_STYLE)
        btn_add.clicked.connect(self._show_add_dialog)
        btn_edit = QtWidgets.QPushButton("编辑选中")
        btn_edit.setStyleSheet(_BTN_STYLE)
        btn_edit.clicked.connect(self._edit_feed)
        btn_del = QtWidgets.QPushButton("删除选中")
        btn_del.setStyleSheet(_BTN_STYLE)
        btn_del.clicked.connect(self._remove_feed)
        btn_toggle = QtWidgets.QPushButton("启用/停用")
        btn_toggle.setStyleSheet(_BTN_STYLE)
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
            text = "{} {}{} — {}{}".format(status, f["name"], group, f["url"], error)
            if f["tag"] and f["tag"] != f["name"]:
                text += "  (标签: {})".format(f["tag"])
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
        dlg = _EditFeedDialog(self.owner, feed, self)
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


class _SettingsDialog(QtWidgets.QDialog):
    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.setWindowTitle("RSS 设置")
        self.setMinimumSize(500, 600)
        _bind_geometry(self, "rss_settings", default_size=(500, 600))
        self.owner = owner
        self._apply_dialog_theme()

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        content = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(content)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        settings_group = QtWidgets.QGroupBox("代理设置")
        settings_lay = QtWidgets.QFormLayout(settings_group)
        self.in_proxy = QtWidgets.QLineEdit()
        self.in_proxy.setPlaceholderText("http://127.0.0.1:7890 或 socks5://127.0.0.1:1080")
        self.in_proxy.setText(self.owner.context.config.get("rss.proxy", ""))
        settings_lay.addRow("代理地址", self.in_proxy)
        lay.addWidget(settings_group)

        cleanup_group = QtWidgets.QGroupBox("数据清理")
        cleanup_lay = QtWidgets.QHBoxLayout(cleanup_group)
        cleanup_lay.addWidget(QtWidgets.QLabel("清理"))
        self.spin_cleanup_days = QtWidgets.QSpinBox()
        self.spin_cleanup_days.setRange(7, 365)
        self.spin_cleanup_days.setValue(self.owner.context.config.get("rss.cleanup_days", 30))
        self.spin_cleanup_days.setSuffix(" 天前的数据")
        cleanup_lay.addWidget(self.spin_cleanup_days)
        btn_cleanup = QtWidgets.QPushButton("清理")
        btn_cleanup.setStyleSheet(_BTN_PRIMARY_STYLE)
        btn_cleanup.clicked.connect(self._cleanup_old)
        cleanup_lay.addWidget(btn_cleanup)
        lay.addWidget(cleanup_group)

        notify_group = QtWidgets.QGroupBox("通知设置")
        notify_lay = QtWidgets.QFormLayout(notify_group)
        self.chk_notify = QtWidgets.QCheckBox("启用桌面通知")
        self.chk_notify.setChecked(self.owner.context.config.get("rss.notification_enabled", True))
        self.chk_notify.stateChanged.connect(lambda s: self.owner.context.config.set("rss.notification_enabled", s == QtCore.Qt.Checked))
        notify_lay.addRow(self.chk_notify)
        lay.addWidget(notify_group)

        categories_group = QtWidgets.QGroupBox("分类管理")
        categories_lay = QtWidgets.QVBoxLayout(categories_group)
        self.category_list = QtWidgets.QListWidget()
        self.category_list.setMaximumHeight(100)
        categories_lay.addWidget(self.category_list)
        cat_btn_row = QtWidgets.QHBoxLayout()
        btn_add_cat = QtWidgets.QPushButton("添加分类")
        btn_add_cat.setStyleSheet(_BTN_STYLE)
        btn_add_cat.clicked.connect(self._show_category_dialog)
        btn_edit_cat = QtWidgets.QPushButton("编辑")
        btn_edit_cat.setStyleSheet(_BTN_STYLE)
        btn_edit_cat.clicked.connect(self._edit_category)
        btn_del_cat = QtWidgets.QPushButton("删除")
        btn_del_cat.setStyleSheet(_BTN_STYLE)
        btn_del_cat.clicked.connect(self._remove_category)
        cat_btn_row.addWidget(btn_add_cat)
        cat_btn_row.addWidget(btn_edit_cat)
        cat_btn_row.addWidget(btn_del_cat)
        cat_btn_row.addStretch(1)
        categories_lay.addLayout(cat_btn_row)
        lay.addWidget(categories_group)

        keywords_group = QtWidgets.QGroupBox("关键词提醒")
        keywords_lay = QtWidgets.QVBoxLayout(keywords_group)
        self.keyword_list = QtWidgets.QListWidget()
        self.keyword_list.setMaximumHeight(100)
        keywords_lay.addWidget(self.keyword_list)
        kw_btn_row = QtWidgets.QHBoxLayout()
        btn_add_kw = QtWidgets.QPushButton("添加关键词")
        btn_add_kw.setStyleSheet(_BTN_STYLE)
        btn_add_kw.clicked.connect(self._show_keyword_dialog)
        btn_del_kw = QtWidgets.QPushButton("删除选中")
        btn_del_kw.setStyleSheet(_BTN_STYLE)
        btn_del_kw.clicked.connect(self._remove_keyword)
        kw_btn_row.addWidget(btn_add_kw)
        kw_btn_row.addWidget(btn_del_kw)
        kw_btn_row.addStretch(1)
        keywords_lay.addLayout(kw_btn_row)
        lay.addWidget(keywords_group)

        rules_group = QtWidgets.QGroupBox("过滤规则")
        rules_lay = QtWidgets.QVBoxLayout(rules_group)
        self.rule_list = QtWidgets.QListWidget()
        self.rule_list.setMaximumHeight(100)
        rules_lay.addWidget(self.rule_list)
        rule_btn_row = QtWidgets.QHBoxLayout()
        btn_add_rule = QtWidgets.QPushButton("添加规则")
        btn_add_rule.setStyleSheet(_BTN_STYLE)
        btn_add_rule.clicked.connect(self._show_filter_dialog)
        btn_del_rule = QtWidgets.QPushButton("删除选中")
        btn_del_rule.setStyleSheet(_BTN_STYLE)
        btn_del_rule.clicked.connect(self._remove_rule)
        btn_toggle_rule = QtWidgets.QPushButton("启用/禁用")
        btn_toggle_rule.setStyleSheet(_BTN_STYLE)
        btn_toggle_rule.clicked.connect(self._toggle_rule)
        rule_btn_row.addWidget(btn_add_rule)
        rule_btn_row.addWidget(btn_del_rule)
        rule_btn_row.addWidget(btn_toggle_rule)
        rule_btn_row.addStretch(1)
        rules_lay.addLayout(rule_btn_row)
        lay.addWidget(rules_group)

        history_group = QtWidgets.QGroupBox("阅读历史")
        history_lay = QtWidgets.QVBoxLayout(history_group)
        self.history_list = QtWidgets.QListWidget()
        self.history_list.setMaximumHeight(120)
        history_lay.addWidget(self.history_list)
        btn_refresh_history = QtWidgets.QPushButton("刷新历史")
        btn_refresh_history.setStyleSheet(_BTN_STYLE)
        btn_refresh_history.clicked.connect(self._load_history)
        history_lay.addWidget(btn_refresh_history)
        lay.addWidget(history_group)

        stats_group = QtWidgets.QGroupBox("统计信息")
        stats_lay = QtWidgets.QVBoxLayout(stats_group)
        self.lb_stats = QtWidgets.QLabel("")
        stats_lay.addWidget(self.lb_stats)
        btn_refresh_stats = QtWidgets.QPushButton("刷新统计")
        btn_refresh_stats.setStyleSheet(_BTN_STYLE)
        btn_refresh_stats.clicked.connect(self._load_stats)
        stats_lay.addWidget(btn_refresh_stats)
        lay.addWidget(stats_group)

        lay.addStretch(1)
        scroll.setWidget(content)
        main_lay = QtWidgets.QVBoxLayout(self)
        main_lay.addWidget(scroll)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        btn_save = QtWidgets.QPushButton("保存设置")
        btn_save.setStyleSheet(_BTN_PRIMARY_STYLE)
        btn_save.clicked.connect(self._save_settings)
        btn_close = QtWidgets.QPushButton("关闭")
        btn_close.setStyleSheet(_BTN_STYLE)
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        btn_row.addWidget(btn_save)
        main_lay.addLayout(btn_row)

        self._load_keywords()
        self._load_rules()
        self._load_stats()
        self._load_categories()
        self._load_history()

    def _save_settings(self):
        proxy = self.in_proxy.text().strip()
        self.owner.context.config.set("rss.proxy", proxy)
        self.owner.set_proxy(proxy)
        self.owner.context.config.set("rss.cleanup_days", self.spin_cleanup_days.value())
        self.accept()

    def _apply_dialog_theme(self):
        try:
            from core.theme import resolve_dark
            dark = resolve_dark("auto")
        except Exception:
            dark = None
        if dark is None:
            from qfluentwidgets import Theme, qconfig
            dark = qconfig.theme is Theme.DARK
        group_style = (
            "QGroupBox { border: 1px solid rgba(255,255,255,0.10); border-radius: 8px; "
            "margin-top: 14px; padding: 8px 10px 10px 10px; background: rgba(255,255,255,0.03); }"
            "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; color: #e0e0e0; }"
            "QSpinBox, QLineEdit { background: rgba(40,40,40,0.85); border: 1px solid rgba(255,255,255,0.10); "
            "border-radius: 6px; padding: 4px 8px; color: #e8e8e8; }"
            "QSpinBox:focus, QLineEdit:focus { border: 1px solid rgba(0,120,215,0.6); }"
        ) if dark else (
            "QGroupBox { border: 1px solid rgba(0,0,0,0.10); border-radius: 8px; "
            "margin-top: 14px; padding: 8px 10px 10px 10px; background: rgba(0,0,0,0.02); }"
            "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; color: #2c2c2c; }"
            "QSpinBox, QLineEdit { background: rgba(255,255,255,0.85); border: 1px solid rgba(0,0,0,0.12); "
            "border-radius: 6px; padding: 4px 8px; color: #1a1a1a; }"
            "QSpinBox:focus, QLineEdit:focus { border: 1px solid rgba(0,120,215,0.6); }"
        )
        self.setStyleSheet(group_style)

    def _cleanup_old(self):
        days = self.spin_cleanup_days.value()
        self.owner.store.cleanup_old(days)
        self.owner.context.config.set("rss.cleanup_days", days)
        QtWidgets.QMessageBox.information(self, "清理", f"已清理 {days} 天前的数据")

    def _load_categories(self):
        self.category_list.clear()
        for c in self.owner.store.get_categories():
            self.category_list.addItem(f"{c['name']} ({c['color']})")

    def _show_category_dialog(self):
        dlg = _CategoryDialog(self.owner, parent=self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._load_categories()

    def _edit_category(self):
        item = self.category_list.currentItem()
        if not item:
            return
        cats = self.owner.store.get_categories()
        idx = self.category_list.row(item)
        if idx < len(cats):
            dlg = _CategoryDialog(self.owner, cats[idx], self)
            if dlg.exec() == QtWidgets.QDialog.Accepted:
                self._load_categories()

    def _remove_category(self):
        item = self.category_list.currentItem()
        if not item:
            return
        cats = self.owner.store.get_categories()
        idx = self.category_list.row(item)
        if idx < len(cats):
            self.owner.store.remove_category(cats[idx]["id"])
            self._load_categories()

    def _load_keywords(self):
        self.keyword_list.clear()
        for kw in self.owner.store.get_keywords():
            text = kw["keyword"]
            if kw.get("notify"):
                text += " 🔔"
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, kw["id"])
            self.keyword_list.addItem(item)

    def _show_keyword_dialog(self):
        dlg = _KeywordDialog(self.owner, parent=self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._load_keywords()

    def _remove_keyword(self):
        item = self.keyword_list.currentItem()
        if not item:
            return
        kid = item.data(QtCore.Qt.UserRole)
        if kid is None:
            return
        self.owner.store.remove_keyword(kid)
        self._load_keywords()

    def _load_rules(self):
        self.rule_list.clear()
        for r in self.owner.store.get_filter_rules():
            status = "✓" if r.get("enabled") else "✗"
            text = f"{status} {r['name']}: {r['field']} {r['operator']} {r['value']} → {r['action']}"
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, r["id"])
            self.rule_list.addItem(item)

    def _show_filter_dialog(self):
        dlg = _FilterRuleDialog(self.owner, parent=self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._load_rules()

    def _remove_rule(self):
        item = self.rule_list.currentItem()
        if not item:
            return
        rid = item.data(QtCore.Qt.UserRole)
        self.owner.store.remove_filter_rule(rid)
        self._load_rules()

    def _toggle_rule(self):
        item = self.rule_list.currentItem()
        if not item:
            return
        rid = item.data(QtCore.Qt.UserRole)
        rules = self.owner.store.get_filter_rules()
        for r in rules:
            if r["id"] == rid:
                self.owner.store.update_filter_rule(rid, enabled=not r.get("enabled", True))
                break
        self._load_rules()

    def _load_history(self):
        self.history_list.clear()
        for h in self.owner.store.get_read_history(limit=50):
            item = QtWidgets.QListWidgetItem(f"{h['title'][:50]} ({h['read_at']})")
            item.setData(QtCore.Qt.UserRole, h["hash"])
            self.history_list.addItem(item)

    def _load_stats(self):
        feed_stats = self.owner.store.get_feed_stats()
        total = sum(s.get("total", 0) for s in feed_stats)
        unread = sum(s.get("unread", 0) for s in feed_stats)
        read = total - unread
        fav_count = 0
        with self.owner.store._conn() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM favorites").fetchone()
            fav_count = row["cnt"] if row else 0
        today_count = 0
        with self.owner.store._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM items WHERE date(published) = date('now','localtime')"
            ).fetchone()
            today_count = row["cnt"] if row else 0
        self.lb_stats.setText(
            f"总条目: {total} | 已读: {read} | 未读: {unread} | 收藏: {fav_count} | 今日新增: {today_count}"
        )


class _FilterRuleDialog(QtWidgets.QDialog):
    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加过滤规则")
        self.setMinimumWidth(400)
        _bind_geometry(self, "rss_filter_rule")
        self.owner = owner

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        form = QtWidgets.QFormLayout()
        self.in_name = QtWidgets.QLineEdit()
        self.in_name.setPlaceholderText("规则名称")
        self.combo_field = QtWidgets.QComboBox()
        self.combo_field.addItems(["标题", "描述", "链接"])
        self.combo_operator = QtWidgets.QComboBox()
        self.combo_operator.addItems(["包含", "不包含", "等于", "开头是", "结尾是", "正则"])
        self.in_value = QtWidgets.QLineEdit()
        self.in_value.setPlaceholderText("匹配值")
        self.combo_action = QtWidgets.QComboBox()
        self.combo_action.addItems(["添加标签", "跳过", "高亮"])
        self.in_action_value = QtWidgets.QLineEdit()
        self.in_action_value.setPlaceholderText("标签名称（添加标签时填写）")
        form.addRow("名称", self.in_name)
        form.addRow("字段", self.combo_field)
        form.addRow("条件", self.combo_operator)
        form.addRow("值", self.in_value)
        form.addRow("动作", self.combo_action)
        form.addRow("动作值", self.in_action_value)
        lay.addLayout(form)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        btn_cancel = QtWidgets.QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QtWidgets.QPushButton("添加")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._do_add)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        lay.addLayout(btn_row)

    def _do_add(self):
        name = self.in_name.text().strip()
        field_map = {"标题": "title", "描述": "description", "链接": "link"}
        op_map = {"包含": "contains", "不包含": "not_contains", "等于": "equals", "开头是": "starts_with", "结尾是": "ends_with", "正则": "regex"}
        action_map = {"添加标签": "tag", "跳过": "skip", "高亮": "highlight"}
        field = field_map.get(self.combo_field.currentText(), "title")
        operator = op_map.get(self.combo_operator.currentText(), "contains")
        value = self.in_value.text().strip()
        action = action_map.get(self.combo_action.currentText(), "tag")
        action_value = self.in_action_value.text().strip()
        if not name or not value:
            return
        self.owner.store.add_filter_rule(name, field, operator, value, action, action_value)
        self.accept()


class _KeywordDialog(QtWidgets.QDialog):
    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加关键词")
        self.setMinimumWidth(350)
        _bind_geometry(self, "rss_keyword")
        self.owner = owner

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        form = QtWidgets.QFormLayout()
        self.in_keyword = QtWidgets.QLineEdit()
        self.in_keyword.setPlaceholderText("关键词")
        self.in_color = QtWidgets.QLineEdit()
        self.in_color.setText("#ff6b6b")
        self.chk_notify = QtWidgets.QCheckBox("匹配时通知")
        self.chk_notify.setChecked(True)
        form.addRow("关键词", self.in_keyword)
        form.addRow("颜色", self.in_color)
        form.addRow("", self.chk_notify)
        lay.addLayout(form)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        btn_cancel = QtWidgets.QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QtWidgets.QPushButton("添加")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._do_add)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        lay.addLayout(btn_row)

    def _do_add(self):
        keyword = self.in_keyword.text().strip()
        color = self.in_color.text().strip() or "#ff6b6b"
        notify = 1 if self.chk_notify.isChecked() else 0
        if not keyword:
            return
        self.owner.store.add_keyword(keyword, color, notify)
        self.accept()


class _CategoryDialog(QtWidgets.QDialog):
    def __init__(self, owner, parent=None, category=None):
        super().__init__(parent)
        self.setWindowTitle("编辑分类" if category else "添加分类")
        self.setMinimumWidth(350)
        _bind_geometry(self, "rss_category")
        self.owner = owner
        self.category = category

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        form = QtWidgets.QFormLayout()
        self.in_name = QtWidgets.QLineEdit(category.get("name", "") if category else "")
        self.in_color = QtWidgets.QLineEdit(category.get("color", "#1a73e8") if category else "#1a73e8")
        form.addRow("名称", self.in_name)
        form.addRow("颜色", self.in_color)
        lay.addLayout(form)

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

    def _do_save(self):
        name = self.in_name.text().strip()
        color = self.in_color.text().strip() or "#1a73e8"
        if not name:
            return
        if self.category:
            self.owner.store.update_category(self.category["id"], name=name, color=color)
        else:
            self.owner.store.add_category(name, color)
        self.accept()


class _RssHomeWidget(QtWidgets.QWidget):
    def __init__(self, owner, parent):
        super().__init__(parent)
        self.owner = owner
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

        header = QtWidgets.QHBoxLayout()
        header.addWidget(QtWidgets.QLabel("RSS 聚合"))
        header.addStretch(1)

        self.lb_unread = QtWidgets.QLabel("")
        self.lb_unread.setStyleSheet("QLabel { color: #1a73e8; font-weight: bold; }")
        header.addWidget(self.lb_unread)

        self.spin_limit = QtWidgets.QSpinBox()
        self.spin_limit.setRange(100, 1000000)
        self.spin_limit.setSingleStep(1000)
        self.spin_limit.setPrefix("显示上限: ")
        self.spin_limit.setSuffix(" 条")
        self.spin_limit.setValue(self.owner.context.config.get("rss.home_limit", 100000))
        self.spin_limit.valueChanged.connect(self._on_limit_changed)
        header.addWidget(self.spin_limit)
        lay.addLayout(header)

        filter_row = QtWidgets.QHBoxLayout()
        self.combo_filter = QtWidgets.QComboBox()
        self.combo_filter.addItem("全部", None)
        self.combo_filter.addItem("未读", "unread")
        self.combo_filter.addItem("收藏", "favorite")
        self.combo_filter.addItem("磁链", "__磁链__")
        self.combo_filter.addItem("文章", "__文章__")
        self.combo_filter.currentIndexChanged.connect(self._load_items)
        filter_row.addWidget(self.combo_filter)
        filter_row.addStretch(1)

        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("搜索...")
        self.search_input.setMaximumWidth(200)
        self.search_input.returnPressed.connect(self._load_items)
        filter_row.addWidget(self.search_input)
        lay.addLayout(filter_row)

        self.lb_list = QtWidgets.QListWidget()
        self.lb_list.itemDoubleClicked.connect(self._open_item)
        self.lb_list.itemClicked.connect(self._mark_read)
        lay.addWidget(self.lb_list, 1)

        btn_row = QtWidgets.QHBoxLayout()
        self.btn = QtWidgets.QPushButton("立即刷新")
        self.btn.clicked.connect(owner.refresh_now)
        btn_row.addWidget(self.btn)

        self.btn_mark_all = QtWidgets.QPushButton("全部已读")
        self.btn_mark_all.clicked.connect(self._mark_all_read)
        btn_row.addWidget(self.btn_mark_all)
        lay.addLayout(btn_row)

    def _on_limit_changed(self, val):
        self.owner.context.config.set("rss.home_limit", val)
        self._load_items()

    def on_refreshed(self, counts):
        self._load_items()

    def _load_items(self):
        query = self.search_input.text().strip()
        if query:
            items = self.owner.store.search(query, self.spin_limit.value())
        else:
            fav = self.combo_filter.currentData() == "favorite"
            unread = self.combo_filter.currentData() == "unread"
            tag = self.combo_filter.currentData() if self.combo_filter.currentData() not in ("favorite", "unread") else None
            items = self.owner.store.recent(self.spin_limit.value(), tag_filter=tag, favorites_only=fav, unread_only=unread)
        self.lb_list.clear()
        for it in items:
            tags = it["tags"] or ""
            type_tag = "磁链" if _is_magnet_or_torrent(it["link"]) else "文章"
            is_read = bool(it.get("read"))
            is_fav = bool(it.get("favorite"))
            prefix = "  " if is_read else ""
            fav_mark = "★ " if is_fav else ""
            text = "{}{}[{}] {} [{}]".format(prefix, fav_mark, tags, it["title"], type_tag)
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, it["hash"])
            item.setData(QtCore.Qt.UserRole + 1, it["link"])
            if is_read:
                item.setForeground(QtGui.QColor("#888"))
            self.lb_list.addItem(item)
        unread = self.owner.store.get_unread_count()
        self.lb_unread.setText(f"未读: {unread}" if unread else "")

    def _mark_read(self, item):
        h = item.data(QtCore.Qt.UserRole)
        if h:
            self.owner.store.mark_read(h)
            item.setForeground(QtGui.QColor("#888"))

    def _open_item(self, item):
        link = item.data(QtCore.Qt.UserRole + 1)
        if link:
            webbrowser.open(link)

    def _mark_all_read(self):
        self.owner.store.mark_all_read()
        self._load_items()


class _RssPageWidget(QtWidgets.QWidget):
    def __init__(self, owner, parent):
        super().__init__(parent)
        self.owner = owner
        self._current_page = 0
        self._all_items = []
        self._show_thumbnails = owner.context.config.get("rss.show_thumbnails", False)
        self._last_clicked_row = -1
        self._selected_hashes = set()
        self._item_title_btns = {}
        self._item_checkboxes = {}

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        section_items = QtWidgets.QVBoxLayout()
        header_row = QtWidgets.QHBoxLayout()

        self.btn_manage = QtWidgets.QPushButton("管理订阅源")
        self.btn_manage.clicked.connect(self._toggle_feed_section)
        header_row.addWidget(self.btn_manage)

        self.btn_settings = QtWidgets.QPushButton("设置")
        self.btn_settings.clicked.connect(self._toggle_settings_section)
        header_row.addWidget(self.btn_settings)

        header_row.addWidget(QtWidgets.QLabel("RSS 条目"))
        header_row.addStretch(1)

        self.combo_search_field = QtWidgets.QComboBox()
        self.combo_search_field.addItems(["全部", "标题", "描述", "链接"])
        self.combo_search_field.setMaximumWidth(80)
        header_row.addWidget(self.combo_search_field)

        self.search_input = QtWidgets.QLineEdit()
        self.search_input.setPlaceholderText("搜索...")
        self.search_input.setMaximumWidth(200)
        self.search_input.returnPressed.connect(self._load_items)
        header_row.addWidget(self.search_input)

        self.combo_tag = QtWidgets.QComboBox()
        self.combo_tag.addItem("全部标签", None)
        self.combo_tag.addItem("磁链", "__磁链__")
        self.combo_tag.addItem("文章", "__文章__")
        self.combo_tag.setMinimumWidth(120)
        self.combo_tag.currentIndexChanged.connect(self._load_items)
        header_row.addWidget(self.combo_tag)

        self.btn_refresh = QtWidgets.QPushButton("刷新")
        self.btn_refresh.clicked.connect(self._refresh)
        header_row.addWidget(self.btn_refresh)

        self.lb_status = QtWidgets.QLabel("")
        header_row.addWidget(self.lb_status)
        section_items.addLayout(header_row)

        filter_row = QtWidgets.QHBoxLayout()
        btn_today = QtWidgets.QPushButton("今天")
        btn_today.setCheckable(True)
        btn_today.toggled.connect(lambda checked: self._set_date_range("today" if checked else None))
        filter_row.addWidget(btn_today)
        self._date_buttons = [btn_today]

        btn_week = QtWidgets.QPushButton("本周")
        btn_week.setCheckable(True)
        btn_week.toggled.connect(lambda checked: self._set_date_range("week" if checked else None))
        filter_row.addWidget(btn_week)
        self._date_buttons.append(btn_week)

        btn_month = QtWidgets.QPushButton("本月")
        btn_month.setCheckable(True)
        btn_month.toggled.connect(lambda checked: self._set_date_range("month" if checked else None))
        filter_row.addWidget(btn_month)
        self._date_buttons.append(btn_month)

        self._current_date_range = None
        filter_row.addStretch(1)

        self.chk_thumbnail = QtWidgets.QPushButton()
        self.chk_thumbnail.setCheckable(True)
        self.chk_thumbnail.setChecked(self._show_thumbnails)
        self._update_thumbnail_btn_text()
        self.chk_thumbnail.toggled.connect(self._toggle_thumbnails)
        filter_row.addWidget(self.chk_thumbnail)

        filter_row.addStretch(1)
        section_items.addLayout(filter_row)

        batch_row = QtWidgets.QHBoxLayout()
        self.chk_select_all = QtWidgets.QCheckBox("全选")
        self.chk_select_all.stateChanged.connect(self._select_all)
        batch_row.addWidget(self.chk_select_all)

        self.btn_batch_read = QtWidgets.QPushButton("标记已读")
        self.btn_batch_read.setStyleSheet(_BTN_STYLE)
        self.btn_batch_read.clicked.connect(self._batch_mark_read)
        batch_row.addWidget(self.btn_batch_read)

        self.btn_batch_unread = QtWidgets.QPushButton("标记未读")
        self.btn_batch_unread.setStyleSheet(_BTN_STYLE)
        self.btn_batch_unread.clicked.connect(self._batch_mark_unread)
        batch_row.addWidget(self.btn_batch_unread)

        self.btn_batch_delete = QtWidgets.QPushButton("删除选中")
        self.btn_batch_delete.setStyleSheet(_BTN_STYLE)
        self.btn_batch_delete.clicked.connect(self._batch_delete)
        batch_row.addWidget(self.btn_batch_delete)

        self._update_batch_buttons()

        self.btn_mark_all_read = QtWidgets.QPushButton("全部已读")
        self.btn_mark_all_read.setStyleSheet(_BTN_PRIMARY_STYLE)
        self.btn_mark_all_read.clicked.connect(self._mark_all_read)
        batch_row.addWidget(self.btn_mark_all_read)

        self.btn_favorites = QtWidgets.QPushButton("仅收藏")
        self.btn_favorites.setCheckable(True)
        self.btn_favorites.setStyleSheet(_BTN_STYLE)
        self.btn_favorites.toggled.connect(self._load_items)
        batch_row.addWidget(self.btn_favorites)

        self.btn_unread = QtWidgets.QPushButton("仅未读")
        self.btn_unread.setCheckable(True)
        self.btn_unread.setStyleSheet(_BTN_STYLE)
        self.btn_unread.toggled.connect(self._load_items)
        batch_row.addWidget(self.btn_unread)

        batch_row.addStretch(1)
        section_items.addLayout(batch_row)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.setHandleWidth(3)

        self.item_list = QtWidgets.QListWidget()
        self.item_list.setAlternatingRowColors(True)
        self.item_list.itemDoubleClicked.connect(self._open_item)
        self.item_list.itemClicked.connect(self._on_item_clicked)
        self.item_list.itemChanged.connect(self._on_item_changed)
        self.item_list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.item_list.customContextMenuRequested.connect(self._show_context_menu)
        splitter.addWidget(self.item_list)

        self.preview_browser = QtWidgets.QTextBrowser()
        self.preview_browser.setOpenExternalLinks(True)
        self.preview_browser.setPlaceholderText("点击条目可在此预览内容...")
        splitter.addWidget(self.preview_browser)

        splitter.setSizes([500, 300])
        self._preview_splitter = splitter
        section_items.addWidget(splitter, 1)

        page_row = QtWidgets.QHBoxLayout()
        self.btn_prev = QtWidgets.QPushButton("上一页")
        self.btn_prev.setStyleSheet(_BTN_STYLE)
        self.btn_prev.clicked.connect(self._prev_page)
        page_row.addWidget(self.btn_prev)

        self.lb_page = QtWidgets.QLabel("第 1 页")
        page_row.addWidget(self.lb_page)

        self.btn_next = QtWidgets.QPushButton("下一页")
        self.btn_next.setStyleSheet(_BTN_STYLE)
        self.btn_next.clicked.connect(self._next_page)
        page_row.addWidget(self.btn_next)

        page_row.addStretch(1)

        self.lb_total = QtWidgets.QLabel("")
        page_row.addWidget(self.lb_total)

        self.btn_export = QtWidgets.QPushButton("导出OPML")
        self.btn_export.setStyleSheet(_BTN_STYLE)
        self.btn_export.clicked.connect(self._export_opml)
        page_row.addWidget(self.btn_export)

        self.btn_import = QtWidgets.QPushButton("导入OPML")
        self.btn_import.setStyleSheet(_BTN_STYLE)
        self.btn_import.clicked.connect(self._import_opml)
        page_row.addWidget(self.btn_import)

        section_items.addLayout(page_row)

        root.addLayout(section_items, 3)

        self.setTabOrder(self.search_input, self.item_list)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self._load_items()

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

    def _set_date_range(self, date_range):
        for btn in self._date_buttons:
            if btn.isChecked() and date_range:
                self._current_date_range = date_range
            elif not date_range:
                pass
        if not date_range:
            self._current_date_range = None
        self._load_items()

    def _update_thumbnail_btn_text(self):
        self.chk_thumbnail.setText("隐藏缩略图" if self._show_thumbnails else "显示缩略图")

    def _toggle_thumbnails(self, checked):
        self._show_thumbnails = checked
        self.owner.context.config.set("rss.show_thumbnails", checked)
        self._update_thumbnail_btn_text()
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

    def _build_settings_section(self):
        self.settings_section = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(self.settings_section)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        settings_group = QtWidgets.QGroupBox("代理设置")
        settings_lay = QtWidgets.QFormLayout(settings_group)
        self.in_proxy = QtWidgets.QLineEdit()
        self.in_proxy.setPlaceholderText("http://127.0.0.1:7890 或 socks5://127.0.0.1:1080")
        self.in_proxy.setText(self.owner.context.config.get("rss.proxy", ""))
        self.in_proxy.returnPressed.connect(self._save_proxy)
        settings_lay.addRow("代理地址", self.in_proxy)
        lay.addWidget(settings_group)

        cleanup_group = QtWidgets.QGroupBox("数据清理")
        cleanup_lay = QtWidgets.QHBoxLayout(cleanup_group)
        cleanup_lay.addWidget(QtWidgets.QLabel("清理"))
        self.spin_cleanup_days = QtWidgets.QSpinBox()
        self.spin_cleanup_days.setRange(7, 365)
        self.spin_cleanup_days.setValue(self.owner.context.config.get("rss.cleanup_days", 30))
        self.spin_cleanup_days.setSuffix(" 天前的数据")
        cleanup_lay.addWidget(self.spin_cleanup_days)
        btn_cleanup = QtWidgets.QPushButton("清理")
        btn_cleanup.setStyleSheet(_BTN_PRIMARY_STYLE)
        btn_cleanup.clicked.connect(self._cleanup_old)
        cleanup_lay.addWidget(btn_cleanup)
        lay.addWidget(cleanup_group)

        notify_group = QtWidgets.QGroupBox("通知设置")
        notify_lay = QtWidgets.QFormLayout(notify_group)
        self.chk_notify = QtWidgets.QCheckBox("启用桌面通知")
        self.chk_notify.setChecked(self.owner.context.config.get("rss.notification_enabled", True))
        self.chk_notify.stateChanged.connect(lambda s: self.owner.context.config.set("rss.notification_enabled", s == QtCore.Qt.Checked))
        notify_lay.addRow(self.chk_notify)
        lay.addWidget(notify_group)

        categories_group = QtWidgets.QGroupBox("分类管理")
        categories_lay = QtWidgets.QVBoxLayout(categories_group)
        self.category_list = QtWidgets.QListWidget()
        self.category_list.setMaximumHeight(80)
        categories_lay.addWidget(self.category_list)
        cat_btn_row = QtWidgets.QHBoxLayout()
        btn_add_cat = QtWidgets.QPushButton("添加分类")
        btn_add_cat.setStyleSheet(_BTN_STYLE)
        btn_add_cat.clicked.connect(self._show_category_dialog)
        btn_edit_cat = QtWidgets.QPushButton("编辑")
        btn_edit_cat.setStyleSheet(_BTN_STYLE)
        btn_edit_cat.clicked.connect(self._edit_category)
        btn_del_cat = QtWidgets.QPushButton("删除")
        btn_del_cat.setStyleSheet(_BTN_STYLE)
        btn_del_cat.clicked.connect(self._remove_category)
        cat_btn_row.addWidget(btn_add_cat)
        cat_btn_row.addWidget(btn_edit_cat)
        cat_btn_row.addWidget(btn_del_cat)
        cat_btn_row.addStretch(1)
        categories_lay.addLayout(cat_btn_row)
        lay.addWidget(categories_group)

        keywords_group = QtWidgets.QGroupBox("关键词提醒")
        keywords_lay = QtWidgets.QVBoxLayout(keywords_group)
        self.keyword_list = QtWidgets.QListWidget()
        self.keyword_list.setMaximumHeight(80)
        keywords_lay.addWidget(self.keyword_list)
        kw_btn_row = QtWidgets.QHBoxLayout()
        btn_add_kw = QtWidgets.QPushButton("添加关键词")
        btn_add_kw.setStyleSheet(_BTN_STYLE)
        btn_add_kw.clicked.connect(self._show_keyword_dialog)
        btn_del_kw = QtWidgets.QPushButton("删除选中")
        btn_del_kw.setStyleSheet(_BTN_STYLE)
        btn_del_kw.clicked.connect(self._remove_keyword)
        kw_btn_row.addWidget(btn_add_kw)
        kw_btn_row.addWidget(btn_del_kw)
        kw_btn_row.addStretch(1)
        keywords_lay.addLayout(kw_btn_row)
        lay.addWidget(keywords_group)

        rules_group = QtWidgets.QGroupBox("过滤规则")
        rules_lay = QtWidgets.QVBoxLayout(rules_group)
        self.rule_list = QtWidgets.QListWidget()
        self.rule_list.setMaximumHeight(80)
        rules_lay.addWidget(self.rule_list)
        rule_btn_row = QtWidgets.QHBoxLayout()
        btn_add_rule = QtWidgets.QPushButton("添加规则")
        btn_add_rule.setStyleSheet(_BTN_STYLE)
        btn_add_rule.clicked.connect(self._show_filter_dialog)
        btn_del_rule = QtWidgets.QPushButton("删除选中")
        btn_del_rule.setStyleSheet(_BTN_STYLE)
        btn_del_rule.clicked.connect(self._remove_rule)
        btn_toggle_rule = QtWidgets.QPushButton("启用/禁用")
        btn_toggle_rule.setStyleSheet(_BTN_STYLE)
        btn_toggle_rule.clicked.connect(self._toggle_rule)
        rule_btn_row.addWidget(btn_add_rule)
        rule_btn_row.addWidget(btn_del_rule)
        rule_btn_row.addWidget(btn_toggle_rule)
        rule_btn_row.addStretch(1)
        rules_lay.addLayout(rule_btn_row)
        lay.addWidget(rules_group)

        history_group = QtWidgets.QGroupBox("阅读历史")
        history_lay = QtWidgets.QVBoxLayout(history_group)
        self.history_list = QtWidgets.QListWidget()
        self.history_list.setMaximumHeight(100)
        history_lay.addWidget(self.history_list)
        btn_refresh_history = QtWidgets.QPushButton("刷新历史")
        btn_refresh_history.setStyleSheet(_BTN_STYLE)
        btn_refresh_history.clicked.connect(self._load_history)
        history_lay.addWidget(btn_refresh_history)
        lay.addWidget(history_group)

        stats_group = QtWidgets.QGroupBox("统计信息")
        stats_lay = QtWidgets.QVBoxLayout(stats_group)
        self.lb_stats = QtWidgets.QLabel("")
        stats_lay.addWidget(self.lb_stats)
        btn_refresh_stats = QtWidgets.QPushButton("刷新统计")
        btn_refresh_stats.setStyleSheet(_BTN_STYLE)
        btn_refresh_stats.clicked.connect(self._load_stats)
        stats_lay.addWidget(btn_refresh_stats)
        lay.addWidget(stats_group)

        lay.addStretch(1)

        self.settings_section.setVisible(False)
        root = self.layout()
        root.insertWidget(1, self.settings_section)
        self._load_keywords()
        self._load_rules()
        self._load_stats()
        self._load_categories()
        self._load_history()

    def _toggle_feed_section(self):
        dlg = _FeedManageDialog(self.owner, self)
        dlg.exec()
        self._load_tag_filter()
        self._load_items(preserve_scroll=True)

    def _toggle_settings_section(self):
        dlg = _SettingsDialog(self.owner, self)
        dlg.exec()
        self._load_items(preserve_scroll=True)

    def on_refreshed(self, counts):
        self._load_items(preserve_scroll=True)
        if counts:
            parts = ["{}: {}/{}".format(n, added, total) for n, tag, total, added in counts]
            self.lb_status.setText("刷新完成 — " + ", ".join(parts))
        else:
            self.lb_status.setText("刷新完成")

    def _load_feeds(self):
        self.feed_list.clear()
        for f in self.owner.store.list_feeds():
            status = "✓" if f["enabled"] else "✗"
            group = f" [{f['group_name']}]" if f.get("group_name") else ""
            error = f" ⚠{f['last_error'][:30]}" if f.get("last_error") else ""
            text = "{} {}{} — {}{}".format(status, f["name"], group, f["url"], error)
            if f["tag"] and f["tag"] != f["name"]:
                text += "  (标签: {})".format(f["tag"])
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

    def _load_tag_filter(self):
        current = self.combo_tag.currentData()
        self.combo_tag.blockSignals(True)
        self.combo_tag.clear()
        self.combo_tag.addItem("全部标签", None)
        self.combo_tag.addItem("磁链", "__磁链__")
        self.combo_tag.addItem("文章", "__文章__")
        for tag in self.owner.store.list_tags():
            self.combo_tag.addItem(tag, tag)
        if current:
            idx = self.combo_tag.findData(current)
            if idx >= 0:
                self.combo_tag.setCurrentIndex(idx)
        self.combo_tag.blockSignals(False)

    def _show_add_dialog(self):
        dlg = _AddFeedDialog(self.owner, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._load_feeds()
            self._load_tag_filter()

    def _remove_feed(self):
        item = self.feed_list.currentItem()
        if item is None:
            return
        fid = item.data(QtCore.Qt.UserRole)
        self.owner.store.remove_feed(fid)
        self._load_feeds()
        self._load_tag_filter()

    def _toggle_feed(self):
        item = self.feed_list.currentItem()
        if item is None:
            return
        fid = item.data(QtCore.Qt.UserRole)
        enabled = item.data(QtCore.Qt.UserRole + 1)
        self.owner.store.set_feed_enabled(fid, not enabled)
        self._load_feeds()

    def _load_items(self, preserve_scroll=False):
        scrollbar = self.item_list.verticalScrollBar()
        prev_value = None
        if preserve_scroll and scrollbar is not None:
            prev_value = scrollbar.value()

        query = self.search_input.text().strip()
        fav_only = self.btn_favorites.isChecked()
        unread_only = self.btn_unread.isChecked()

        field_map = {"全部": None, "标题": "title", "描述": "description", "链接": "link"}
        search_field = field_map.get(self.combo_search_field.currentText())

        if query:
            self._all_items = self.owner.store.search(query, 5000, field=search_field)
        else:
            tag_filter = self.combo_tag.currentData()
            self._all_items = self.owner.store.recent(
                5000, tag_filter=tag_filter, favorites_only=fav_only, unread_only=unread_only,
                date_range=self._current_date_range,
            )

        self._load_tag_filter()
        total = len(self._all_items)
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        self._current_page = min(self._current_page, total_pages - 1)
        start = self._current_page * PAGE_SIZE
        page_items = self._all_items[start : start + PAGE_SIZE]

        self.item_list.clear()
        self._item_title_btns = {}
        self._item_checkboxes = {}
        for it in page_items:
            is_checked = it["hash"] in self._selected_hashes
            row_widget, title_btn, chk = _make_item_row(self.item_list, it, None, self._show_thumbnails, checked=is_checked)
            title_btn.clicked.connect(lambda _, h=it["hash"], link=it["link"]: self._on_title_click(h, link))
            chk.toggled.connect(lambda checked, h=it["hash"]: self._on_check_toggled(h, checked))

            self._item_title_btns[it["hash"]] = title_btn
            self._item_checkboxes[it["hash"]] = chk

            item = QtWidgets.QListWidgetItem()
            item.setData(QtCore.Qt.UserRole, it["hash"])
            item.setData(QtCore.Qt.UserRole + 1, it["link"])
            item.setData(QtCore.Qt.UserRole + 2, it.get("description", ""))
            item.setData(QtCore.Qt.UserRole + 3, it.get("image_url", ""))
            self.item_list.addItem(item)
            self.item_list.setItemWidget(item, row_widget)

        self.lb_page.setText(f"第 {self._current_page + 1}/{total_pages} 页")
        self.lb_total.setText(f"共 {total} 条")
        self.btn_prev.setEnabled(self._current_page > 0)
        self.btn_next.setEnabled(self._current_page < total_pages - 1)

        if prev_value is not None:
            QtCore.QTimer.singleShot(
                0, lambda sb=scrollbar, v=prev_value, m=scrollbar.maximum(): sb.setValue(min(v, m))
            )

    def _prev_page(self):
        if self._current_page > 0:
            self._current_page -= 1
            self._load_items()

    def _next_page(self):
        total_pages = max(1, (len(self._all_items) + PAGE_SIZE - 1) // PAGE_SIZE)
        if self._current_page < total_pages - 1:
            self._current_page += 1
            self._load_items()

    def _on_title_click(self, item_hash, link):
        self.owner.store.mark_read(item_hash)
        self._update_read_appearance(item_hash, True)
        self._show_preview_by_hash(item_hash, link)

    def _on_check_toggled(self, item_hash, checked):
        if checked:
            self._selected_hashes.add(item_hash)
        else:
            self._selected_hashes.discard(item_hash)
        self._update_batch_buttons()

    def _on_item_changed(self, item):
        pass

    def _on_item_clicked(self, item):
        h = item.data(QtCore.Qt.UserRole)
        link = item.data(QtCore.Qt.UserRole + 1)
        if h:
            self.owner.store.mark_read(h)
            self._update_read_appearance(h, True)
        self._show_preview(item)
        self._last_clicked_row = self.item_list.row(item)

    def _update_read_appearance(self, item_hash, is_read):
        btn = self._item_title_btns.get(item_hash)
        if btn is not None:
            if is_read:
                btn.setStyleSheet(
                    "QPushButton { text-align: left; border: none; background: transparent; "
                    "color: #888; padding: 2px; }"
                    "QPushButton:hover { color: #555; }"
                )
            else:
                btn.setStyleSheet(
                    "QPushButton { text-align: left; border: none; background: transparent; color: palette(text); "
                    "text-decoration: underline; padding: 2px; }"
                    "QPushButton:hover { color: #1a73e8; }"
                )

    def _show_preview(self, item):
        h = item.data(QtCore.Qt.UserRole)
        link = item.data(QtCore.Qt.UserRole + 1)
        desc = item.data(QtCore.Qt.UserRole + 2)
        img_url = item.data(QtCore.Qt.UserRole + 3)
        if not h:
            return
        item_data = self.owner.store.get_item(h)
        if not item_data:
            return
        title = item_data.get("title", "")
        published = item_data.get("published", "")
        source = item_data.get("tags", "")
        html_parts = [f"<h3>{title}</h3>"]
        if published:
            html_parts.append(f"<p style='color:#888;font-size:12px;'>{published}</p>")
        if source:
            html_parts.append(f"<p style='color:#1a73e8;font-size:12px;'>标签: {source}</p>")
        if img_url and img_url.startswith("http"):
            html_parts.append(f"<p><img src='{img_url}' style='max-width:100%;max-height:200px;border-radius:4px;'></p>")
        if desc:
            html_parts.append(f"<hr><div>{desc}</div>")
        if link:
            html_parts.append(f"<hr><p><b>原文链接:</b> <a href='{link}'>{link}</a></p>")
        self.preview_browser.setHtml("\n".join(html_parts))
        self._preview_link = link
        if link and link.startswith("http"):
            self._load_page_content(link)

    def _show_preview_by_hash(self, item_hash, link):
        item_data = self.owner.store.get_item(item_hash)
        if not item_data:
            return
        title = item_data.get("title", "")
        published = item_data.get("published", "")
        source = item_data.get("tags", "")
        desc = item_data.get("description", "")
        img_url = item_data.get("image_url", "")
        html_parts = [f"<h3>{title}</h3>"]
        if published:
            html_parts.append(f"<p style='color:#888;font-size:12px;'>{published}</p>")
        if source:
            html_parts.append(f"<p style='color:#1a73e8;font-size:12px;'>标签: {source}</p>")
        if img_url and img_url.startswith("http"):
            html_parts.append(f"<p><img src='{img_url}' style='max-width:100%;max-height:200px;border-radius:4px;'></p>")
        if desc:
            html_parts.append(f"<hr><div>{desc}</div>")
        if link:
            html_parts.append(f"<hr><p><b>原文链接:</b> <a href='{link}'>{link}</a></p>")
        self.preview_browser.setHtml("\n".join(html_parts))
        self._preview_link = link
        if link and link.startswith("http"):
            self._load_page_content(link)

    def _load_page_content(self, url):
        from PySide6.QtNetwork import QNetworkRequest
        req = QNetworkRequest(QtCore.QUrl(url))
        req.setTransferTimeout(10000)
        reply = _get_network_mgr().get(req)

        def _on_reply():
            if reply.error() == reply.NetworkError.NoError:
                data = bytes(reply.readAll()).decode("utf-8", errors="replace")
                import re
                body_match = re.search(r"<body[^>]*>(.*?)</body>", data, re.DOTALL | re.IGNORECASE)
                if body_match:
                    content = body_match.group(1)
                else:
                    content = data
                content = re.sub(r"<script[^>]*>.*?</script>", "", content, flags=re.DOTALL | re.IGNORECASE)
                content = re.sub(r"<style[^>]*>.*?</style>", "", content, flags=re.DOTALL | re.IGNORECASE)
                content = re.sub(r"<nav[^>]*>.*?</nav>", "", content, flags=re.DOTALL | re.IGNORECASE)
                content = re.sub(r"<footer[^>]*>.*?</footer>", "", content, flags=re.DOTALL | re.IGNORECASE)
                existing = self.preview_browser.toHtml()
                self.preview_browser.setHtml(existing + f"<hr><h4>网页内容:</h4><div style='max-height:400px;overflow-y:auto;'>{content}</div>")
            else:
                existing = self.preview_browser.toHtml()
                self.preview_browser.setHtml(existing + f"<hr><p style='color:red;'>网页加载失败: {reply.errorString()}</p>")
            reply.deleteLater()

        reply.finished.connect(_on_reply)

    def _open_item(self, item):
        link = item.data(QtCore.Qt.UserRole + 1)
        desc = item.data(QtCore.Qt.UserRole + 2)
        if link:
            item_hash = item.data(QtCore.Qt.UserRole)
            item_data = self.owner.store.get_item(item_hash)
            if item_data and desc:
                dlg = _ItemPreviewDialog(item_data, self)
                dlg.exec()
            else:
                webbrowser.open(link)

    def _select_all(self, state):
        for item_hash, chk in self._item_checkboxes.items():
            chk.setChecked(state == QtCore.Qt.Checked)

    def _get_selected_hashes(self):
        return list(self._selected_hashes)

    def _update_batch_buttons(self):
        count = len(self._selected_hashes)
        self.btn_batch_read.setEnabled(count > 0)
        self.btn_batch_unread.setEnabled(count > 0)
        self.btn_batch_delete.setEnabled(count > 0)

    def _batch_mark_read(self):
        hashes = self._get_selected_hashes()
        if hashes:
            self.owner.store.batch_mark_read(hashes)
            for h in hashes:
                self._update_read_appearance(h, True)
            self._selected_hashes.clear()
            self._load_items()

    def _batch_mark_unread(self):
        hashes = self._get_selected_hashes()
        if hashes:
            self.owner.store.batch_mark_unread(hashes)
            for h in hashes:
                self._update_read_appearance(h, False)
            self._selected_hashes.clear()
            self._load_items()

    def _batch_delete(self):
        hashes = self._get_selected_hashes()
        if hashes:
            reply = QtWidgets.QMessageBox.question(
                self, "确认删除", f"确定删除 {len(hashes)} 条记录？",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            )
            if reply == QtWidgets.QMessageBox.Yes:
                self.owner.store.batch_delete(hashes)
                self._selected_hashes.clear()
                self._load_items()

    def _mark_all_read(self):
        tag_filter = self.combo_tag.currentData()
        self.owner.store.mark_all_read(tag_filter)
        self._load_items(preserve_scroll=True)

    def _show_context_menu(self, pos):
        item = self.item_list.itemAt(pos)
        if not item:
            return
        menu = QtWidgets.QMenu(self)

        act_open = menu.addAction("打开链接")
        act_preview = menu.addAction("预览详情")
        act_copy = menu.addAction("复制链接")
        act_share = menu.addAction("分享到剪贴板")
        menu.addSeparator()
        act_read = menu.addAction("标记已读")
        act_unread = menu.addAction("标记未读")
        menu.addSeparator()
        act_fav = menu.addAction("收藏/取消收藏")
        menu.addSeparator()

        categories = self.owner.store.get_categories()
        if categories:
            cat_menu = menu.addMenu("添加到分类")
            for cat in categories:
                act = cat_menu.addAction(f"{cat['name']}")
                act.setData(cat["id"])

        action = menu.exec_(self.item_list.mapToGlobal(pos))
        if not action:
            return

        h = item.data(QtCore.Qt.UserRole)
        link = item.data(QtCore.Qt.UserRole + 1)

        if action == act_open:
            if link:
                webbrowser.open(link)
        elif action == act_preview:
            item_data = self.owner.store.get_item(h)
            if item_data:
                dlg = _ItemPreviewDialog(item_data, self)
                dlg.exec()
        elif action == act_copy:
            if link:
                QtWidgets.QApplication.clipboard().setText(link)
        elif action == act_share:
            text = self.owner.store.share_item(h)
            if text:
                QtWidgets.QApplication.clipboard().setText(text)
                self.lb_status.setText("已复制到剪贴板")
        elif action == act_read:
            self.owner.store.mark_read(h)
            self._load_items()
        elif action == act_unread:
            self.owner.store.mark_unread(h)
            self._load_items()
        elif action == act_fav:
            self.owner.store.toggle_favorite(h)
            self._load_items()
        elif hasattr(action, "data") and action.data():
            cat_id = action.data()
            self.owner.store.set_item_category(h, cat_id)

    def _export_opml(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "导出 OPML", "subscriptions.opml", "OPML Files (*.opml)")
        if path:
            try:
                export_opml_file(self.owner.store, path)
                QtWidgets.QMessageBox.information(self, "成功", f"已导出到 {path}")
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "错误", f"导出失败: {e}")

    def _import_opml(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "导入 OPML", "", "OPML Files (*.opml);;All Files (*)")
        if path:
            try:
                count = import_opml_file(self.owner.store, path)
                QtWidgets.QMessageBox.information(self, "成功", f"已导入 {count} 个订阅源")
                self._load_feeds()
                self._load_tag_filter()
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "错误", f"导入失败: {e}")

    def _save_proxy(self):
        proxy = self.in_proxy.text().strip()
        self.owner.context.config.set("rss.proxy", proxy)
        self.owner._proxy = proxy

    def _cleanup_old(self):
        days = self.spin_cleanup_days.value()
        self.owner.context.config.set("rss.cleanup_days", days)
        self.owner.store.cleanup_old(days)
        self._load_items()
        QtWidgets.QMessageBox.information(self, "完成", f"已清理 {days} 天前的数据")

    def _load_keywords(self):
        self.keyword_list.clear()
        for kw in self.owner.store.get_keywords():
            item = QtWidgets.QListWidgetItem(f"{kw['keyword']} ({kw['color']})")
            item.setData(QtCore.Qt.UserRole, kw["id"])
            self.keyword_list.addItem(item)

    def _show_keyword_dialog(self):
        dlg = _KeywordDialog(self.owner, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._load_keywords()

    def _remove_keyword(self):
        item = self.keyword_list.currentItem()
        if item:
            kid = item.data(QtCore.Qt.UserRole)
            self.owner.store.remove_keyword(kid)
            self._load_keywords()

    def _load_rules(self):
        self.rule_list.clear()
        for rule in self.owner.store.get_filter_rules():
            status = "✓" if rule["enabled"] else "✗"
            text = f"{status} {rule['name']}: {rule['field']} {rule['operator']} '{rule['value']}' → {rule['action']}"
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, rule["id"])
            item.setData(QtCore.Qt.UserRole + 1, rule["enabled"])
            self.rule_list.addItem(item)

    def _show_filter_dialog(self):
        dlg = _FilterRuleDialog(self.owner, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._load_rules()

    def _remove_rule(self):
        item = self.rule_list.currentItem()
        if item:
            rid = item.data(QtCore.Qt.UserRole)
            self.owner.store.remove_filter_rule(rid)
            self._load_rules()

    def _toggle_rule(self):
        item = self.rule_list.currentItem()
        if item:
            rid = item.data(QtCore.Qt.UserRole)
            enabled = item.data(QtCore.Qt.UserRole + 1)
            self.owner.store.update_filter_rule(rid, enabled=not enabled)
            self._load_rules()

    def _load_categories(self):
        self.category_list.clear()
        for cat in self.owner.store.get_categories():
            item = QtWidgets.QListWidgetItem(f"{cat['name']} ({cat['color']})")
            item.setData(QtCore.Qt.UserRole, cat["id"])
            item.setData(QtCore.Qt.UserRole + 1, cat)
            self.category_list.addItem(item)

    def _show_category_dialog(self):
        dlg = _CategoryDialog(self.owner, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self._load_categories()

    def _edit_category(self):
        item = self.category_list.currentItem()
        if item:
            cat = item.data(QtCore.Qt.UserRole + 1)
            dlg = _CategoryDialog(self.owner, self, category=cat)
            if dlg.exec() == QtWidgets.QDialog.Accepted:
                self._load_categories()

    def _remove_category(self):
        item = self.category_list.currentItem()
        if item:
            cid = item.data(QtCore.Qt.UserRole)
            self.owner.store.remove_category(cid)
            self._load_categories()

    def _load_history(self):
        self.history_list.clear()
        for h in self.owner.store.get_read_history(20):
            text = f"[{h['read_at']}] {h['title']}"
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, h["hash"])
            self.history_list.addItem(item)

    def _load_stats(self):
        stats = self.owner.store.get_feed_stats()
        total_items = self.owner.store.get_item_count()
        total_unread = self.owner.store.get_unread_count()
        lines = [f"总条目: {total_items}", f"未读: {total_unread}", ""]
        for s in stats:
            lines.append(f"{s['name']}: {s['total']}条 (未读:{s['unread']})")
        self.lb_stats.setText("\n".join(lines))

    def _refresh(self):
        self.btn_refresh.setEnabled(False)
        self.lb_status.setText("正在刷新...")
        self.owner.refresh_now()
        self.btn_refresh.setEnabled(True)
