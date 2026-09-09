"""页面选择器对话框：浏览器式元素点选，生成可被 rss_store 解析的选择器配置。"""
from core.qt_bootstrap import import_qt
from .webengine import _webengine_view

_, QtCore, QtGui, QtWidgets = import_qt()

class PageSelectorDialog(QtWidgets.QDialog):
    """浏览器式元素选择器对话框。"""

    def __init__(self, url, parent=None, initial_options=None):
        super().__init__(parent)
        self.setWindowTitle("页面元素选择器")
        self.resize(1100, 760)
        self._url = url or ""
        self._options = dict(initial_options or {})
        self._poll = None
        self._last_selector = self._options.get("selector", "")
        self._in_multi = False

        if _webengine_view() is None:  # pragma: no cover
            self._webengine_error = True
            root = QtWidgets.QVBoxLayout(self)
            lbl = QtWidgets.QLabel("QtWebEngine 组件不可用，无法打开页面选择器。\n"
                                   "请确认已安装 PySide6 的 WebEngine 支持。")
            lbl.setWordWrap(True)
            root.addWidget(lbl)
            btn = QtWidgets.QPushButton("关闭")
            btn.setMinimumSize(80, 30)
            btn.clicked.connect(self.reject)
            root.addWidget(btn, 0, QtCore.Qt.AlignRight)
            return
        self._webengine_error = False

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 工具栏（模式按钮）──────────────────────────
        toolbar = QtWidgets.QHBoxLayout()
        toolbar.setContentsMargins(8, 6, 8, 4)
        toolbar.setSpacing(6)

        self.btn_single = QtWidgets.QPushButton("选元素")
        self.btn_single.setMinimumSize(80, 30)
        self.btn_single.setCheckable(True)
        self.btn_single.clicked.connect(lambda: self._pick("single"))
        toolbar.addWidget(self.btn_single)

        self.btn_list = QtWidgets.QPushButton("列表容器")
        self.btn_list.setMinimumSize(80, 30)
        self.btn_list.setCheckable(True)
        self.btn_list.clicked.connect(lambda: self._pick("list"))
        toolbar.addWidget(self.btn_list)

        self.btn_multi = QtWidgets.QPushButton("多选")
        self.btn_multi.setMinimumSize(80, 30)
        self.btn_multi.setCheckable(True)
        self.btn_multi.clicked.connect(lambda: self._pick("multi"))
        toolbar.addWidget(self.btn_multi)

        self.lb_multi_count = QtWidgets.QLabel("")
        toolbar.addWidget(self.lb_multi_count)

        self.btn_multi_gen = QtWidgets.QPushButton("生成多选")
        self.btn_multi_gen.setMinimumSize(80, 30)
        self.btn_multi_gen.setStyleSheet("color:#2e7d32;")
        self.btn_multi_gen.clicked.connect(self._finalize_multi)
        self.btn_multi_gen.setVisible(False)
        toolbar.addWidget(self.btn_multi_gen)

        toolbar.addSpacing(8)
        self.kw_input = QtWidgets.QLineEdit()
        self.kw_input.setPlaceholderText("关键词：高亮包含文字的块，再点选一个")
        self.kw_input.setMaximumWidth(200)
        self.kw_input.returnPressed.connect(lambda: self._start_keyword())
        toolbar.addWidget(self.kw_input)
        self.btn_kw = QtWidgets.QPushButton("关键词高亮")
        self.btn_kw.setMinimumSize(80, 30)
        self.btn_kw.clicked.connect(self._start_keyword)
        toolbar.addWidget(self.btn_kw)

        toolbar.addStretch(1)

        self.btn_test = QtWidgets.QPushButton("测试匹配")
        self.btn_test.setMinimumSize(80, 30)
        self.btn_test.clicked.connect(self._test_match)
        toolbar.addWidget(self.btn_test)

        self.lb_count = QtWidgets.QLabel("")
        toolbar.addWidget(self.lb_count)

        self.btn_preview = QtWidgets.QPushButton("抓取预览")
        self.btn_preview.setMinimumSize(80, 30)
        self.btn_preview.clicked.connect(self._preview_extract)
        toolbar.addWidget(self.btn_preview)

        root.addLayout(toolbar)

        # ── 选择器输入行 ───────────────────────────────
        sel_row = QtWidgets.QHBoxLayout()
        sel_row.setContentsMargins(8, 2, 8, 4)
        sel_row.addWidget(QtWidgets.QLabel("选择器"))
        self.selector_input = QtWidgets.QLineEdit()
        self.selector_input.setPlaceholderText("CSS 选择器（可手输/编辑，支持逗号组合、tag、.class、#id、[attr]、>、:nth-child）")
        self.selector_input.setText(self._last_selector)
        sel_row.addWidget(self.selector_input, 1)
        btn_use_sel = QtWidgets.QPushButton("应用选择器")
        btn_use_sel.setMinimumSize(80, 30)
        btn_use_sel.clicked.connect(self._apply_manual_selector)
        sel_row.addWidget(btn_use_sel)
        root.addLayout(sel_row)

        # ── 状态行（可换行，不撑宽窗口）──────────────
        status_row = QtWidgets.QVBoxLayout()
        status_row.setContentsMargins(8, 0, 8, 2)
        self.mode_label = QtWidgets.QLabel("")
        self.mode_label.setWordWrap(True)
        self.mode_label.setStyleSheet("color:#666; background: rgba(0,0,0,0.03); padding:4px 6px;")
        self.mode_label.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        status_row.addWidget(self.mode_label)
        root.addLayout(status_row)

        # ── 导航行 ─────────────────────────────────────
        nav = QtWidgets.QHBoxLayout()
        nav.setContentsMargins(8, 2, 8, 2)
        self.in_url = QtWidgets.QLineEdit(self._url)
        self.in_url.returnPressed.connect(self._load)
        nav.addWidget(self.in_url, 1)
        btn_go = QtWidgets.QPushButton("打开")
        btn_go.setMinimumSize(80, 30)
        btn_go.clicked.connect(self._load)
        nav.addWidget(btn_go)
        root.addLayout(nav)

        view_cls = _webengine_view()
        self.web = view_cls(self) if view_cls is not None else QtWidgets.QWidget(self)
        root.addWidget(self.web, 1)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setContentsMargins(8, 6, 8, 6)
        btn_cancel = QtWidgets.QPushButton("取消")
        btn_cancel.setMinimumSize(80, 30)
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QtWidgets.QPushButton("完成")
        btn_ok.setMinimumSize(80, 30)
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._finish)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        root.addLayout(btn_row)

        self.web.loadFinished.connect(self._on_loaded)
        if self._url:
            self.web.load(QtCore.QUrl(self._url))
