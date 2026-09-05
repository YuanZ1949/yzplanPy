"""RSS 对话框 B：新增订阅源。"""

import logging
import re

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from .styles import _btn_primary_style
from .text_utils import _parse_keywords, _rss_colors
from .utils import _bind_geometry

logger = logging.getLogger("rss_aggregator")

class _AddFeedDialog(QtWidgets.QDialog):
    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加订阅源")
        self.setMinimumWidth(480)
        _bind_geometry(self, "rss_add_feed")
        self.owner = owner
        self._scrape_options = None

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        type_row = QtWidgets.QHBoxLayout()
        type_row.addWidget(QtWidgets.QLabel("类型"))
        self.combo_type = QtWidgets.QComboBox()
        self.combo_type.addItem("标准 RSS / Atom", "normal")
        self.combo_type.addItem("页面监控（网页元素）", "scrape")
        self.combo_type.currentIndexChanged.connect(self._toggle_type)
        type_row.addWidget(self.combo_type, 1)
        lay.addLayout(type_row)

        form = QtWidgets.QFormLayout()
        self.in_name = QtWidgets.QLineEdit()
        self.in_name.setPlaceholderText("例如：阮一峰博客 / 某页面价格监控")
        self.in_url = QtWidgets.QLineEdit()
        self.in_url.setPlaceholderText("RSS/Atom feed 地址，或要监控的网页 URL")
        self.in_tag = QtWidgets.QLineEdit()
        self.in_tag.setPlaceholderText("多个标签用逗号分隔，例如：科技, 资讯（可选，默认同名称）")
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

        # 标准 RSS：自动发现
        self.btn_discover = QtWidgets.QPushButton("自动发现RSS")
        self.btn_discover.clicked.connect(self._discover)
        lay.addWidget(self.btn_discover)

        # 页面监控：选择器
        self.scrape_box = QtWidgets.QWidget()
        scrape_lay = QtWidgets.QVBoxLayout(self.scrape_box)
        scrape_lay.setContentsMargins(0, 0, 0, 0)
        scrape_lay.setSpacing(8)
        row_sel = QtWidgets.QHBoxLayout()
        self.btn_selector = QtWidgets.QPushButton("打开页面选择器")
        self.btn_selector.setStyleSheet(_btn_primary_style())
        self.btn_selector.clicked.connect(self._open_selector)
        row_sel.addWidget(self.btn_selector)
        self.lb_scrape = QtWidgets.QLabel("点击按钮打开页面，用鼠标点选要监控的元素。")
        self.lb_scrape.setWordWrap(True)
        self.lb_scrape.setStyleSheet(f"color:{_rss_colors()['text_secondary']};")
        row_sel.addWidget(self.lb_scrape, 1)
        scrape_lay.addLayout(row_sel)

        self.chk_rendered = QtWidgets.QCheckBox("需要 JS 渲染时才抓取（动态网页较慢）")
        scrape_lay.addWidget(self.chk_rendered)

        kw_row = QtWidgets.QHBoxLayout()
        kw_row.addWidget(QtWidgets.QLabel("关键词过滤"))
        self.in_keywords = QtWidgets.QLineEdit()
        self.in_keywords.setPlaceholderText("逗号/空格分隔，命中任一即保留；留空=接受全部")
        self.in_keywords.setClearButtonEnabled(True)
        kw_row.addWidget(self.in_keywords, 1)
        scrape_lay.addLayout(kw_row)

        self.scrape_box.setVisible(False)
        lay.addWidget(self.scrape_box)

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

    def _toggle_type(self):
        is_scrape = self.combo_type.currentData() == "scrape"
        self.btn_discover.setVisible(not is_scrape)
        self.scrape_box.setVisible(is_scrape)

    def _open_selector(self):
        url = self.in_url.text().strip()
        if not url:
            QtWidgets.QMessageBox.information(self, "提示", "请先填写要监控的网页 URL")
            return
        from ..page_selector import PageSelectorDialog
        dlg = PageSelectorDialog(url, self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            opts = dlg.options()
            self._scrape_options = opts
            sel = opts.get("selector", "")
            mode = "列表" if opts.get("mode") == "list" else "单元素"
            self.lb_scrape.setText(f"已锁定: [{mode}] {sel}")

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
        feed_tags = [t.strip() for t in self.in_tag.text().replace("，", ",").split(",") if t.strip()] or [name]
        tag = feed_tags[0]
        group = self.in_group.text().strip()
        interval = self.in_interval.value()
        if not name or not url:
            return
        if self.combo_type.currentData() == "scrape":
            if not self._scrape_options or not self._scrape_options.get("selector"):
                QtWidgets.QMessageBox.warning(self, "提示", "请先用页面选择器锁定要监控的元素")
                return
            opts = dict(self._scrape_options)
            opts["keywords"] = _parse_keywords(self.in_keywords.text())
            self.owner.store.add_feed(
                name, url, tag, group, interval,
                feed_type="scrape",
                scrape_options=opts,
                rendered=1 if self.chk_rendered.isChecked() else 0,
                tags=feed_tags,
            )
        else:
            self.owner.store.add_feed(name, url, tag, group, interval, tags=feed_tags)
        self.accept()
