"""聚合对话框的构建辅助：把成员/标签/关键词分组构建逻辑从 f.py 拆出。

这些函数接收对话框实例，构建对应 QGroupBox 并把控件挂到实例属性上，
不改变控件层级、信号连接或默认值。
"""
from typing import Any
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()
from ..styles import _btn_style, _rss_head_style
from ..text_utils import _parse_keywords
from core.theme.tokens import sizing
from ui.widgets import make_button, make_label, make_line_edit


class _FlowLayout(QtWidgets.QLayout):
    """经典 Qt FlowLayout：子项按可用宽度自动换行（高频词 chips 容器用）。"""

    def __init__(self, parent=None, margin=0, h_spacing=6, v_spacing=6):
        super().__init__(parent)
        self._items = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def clear(self):
        """移除并销毁全部子项。"""
        while self.count():
            item = self.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def expandingDirections(self):
        return QtCore.Qt.Orientations(QtCore.Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QtCore.QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QtCore.QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QtCore.QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        effective = QtCore.QRect(
            rect.x() + m.left(), rect.y() + m.top(),
            rect.width() - m.left() - m.right(),
            rect.height() - m.top() - m.bottom())
        x, y = effective.x(), effective.y()
        line_height = 0
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self._h_spacing
            if next_x - self._h_spacing > effective.right() and line_height > 0:
                x = effective.x()
                y += line_height + self._v_spacing
                next_x = x + hint.width() + self._h_spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + m.bottom()


class _HighFreqMixin:
    """高频词交互方法混入：追加/点击（供 _AddAggregationDialog 使用）。"""

    _parent_agg: dict | None
    store: Any
    combo_type: Any
    tag_list: Any
    in_required: Any
    in_forbidden: Any

    def _append_keyword(self, word, to_forbidden=False):
        """把 word 追加到必须/禁止关键词桶（去重，空词或已存在则 no-op）。"""
        if not word:
            return
        target = self.in_forbidden if to_forbidden else self.in_required
        words = _parse_keywords(target.text())
        if word in words:
            return
        words.append(word)
        target.setText(" ".join(words))

    def _on_chip_clicked(self, word):
        """chip 单击加入必须桶，Shift+单击加入禁止桶。"""
        mods = QtGui.QGuiApplication.keyboardModifiers()
        to_forbidden = bool(mods & QtCore.Qt.ShiftModifier)
        self._append_keyword(word, to_forbidden)


def _chips_pool(results, buckets):
    """chips 池 = 分析结果全集 − 三桶已解析词。"""
    used = set()
    for key in ("required", "optional", "forbidden"):
        used |= set(buckets.get(key) or [])
    return [(w, c) for w, c in results if w not in used]


def _chip_text(word, count):
    return f"{word} · {count}"


def build_high_freq_group(dialog, parent):
    """高频词面板：搜索框 + chips 滚动区 + 按钮行。

    设置 dialog._hf_results / _hf_selected / _hf_chips_layout / _hf_scroll /
    _hf_search / _hf_spin_top_n / _hf_spin_granularity / _hf_group / btn_high_freq。
    """
    from modules.rss_store.store_conn import MAX_SIMILARITY_GRANULARITY
    from .f import _granularity_hint  # lazy: f.py 模块级 import 本模块，避免循环

    group = QtWidgets.QWidget(parent)
    vb = QtWidgets.QVBoxLayout(group)
    vb.setContentsMargins(0, 0, 0, 0)

    # 搜索框
    search = make_line_edit()
    search.setPlaceholderText("搜索关键词…")
    vb.addWidget(search)

    # spin_top_n + 粒度
    spin_row = QtWidgets.QHBoxLayout()
    spin_row.addWidget(make_label("Top N:"))
    spin_top_n = QtWidgets.QSpinBox()
    spin_top_n.setRange(10, 200)
    spin_top_n.setValue(50)
    spin_row.addWidget(spin_top_n)
    spin_row.addWidget(make_label("粒度:"))
    spin_granularity = QtWidgets.QSpinBox()
    spin_granularity.setRange(1, MAX_SIMILARITY_GRANULARITY)
    spin_granularity.setValue(1)
    spin_row.addWidget(spin_granularity)
    granularity_hint = make_label(_granularity_hint(1))
    spin_row.addWidget(granularity_hint)
    spin_row.addStretch(1)
    vb.addLayout(spin_row)

    # chips 滚动区
    scroll = QtWidgets.QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFixedHeight(sizing()["rss_hf_scroll_height"])
    chips_container = QtWidgets.QWidget()
    chips_layout = _FlowLayout(chips_container, h_spacing=6, v_spacing=6)
    scroll.setWidget(chips_container)
    vb.addWidget(scroll)

    # 按钮行
    btn_row = QtWidgets.QHBoxLayout()
    btn_analyze = make_button("分析高频词")
    btn_add_all = make_button("全部加入必须")
    btn_clear = make_button("清空关键词")
    btn_stop = make_button("停用词…")
    btn_row.addWidget(btn_analyze)
    btn_row.addWidget(btn_add_all)
    btn_row.addWidget(btn_clear)
    btn_row.addWidget(btn_stop)
    btn_row.addStretch(1)
    vb.addLayout(btn_row)

    # 状态
    dialog._hf_results = []
    dialog._hf_worker = None
    dialog._hf_selected = set()
    dialog._hf_chips_layout = chips_layout
    dialog._hf_scroll = scroll
    dialog._hf_search = search
    dialog._hf_spin_top_n = spin_top_n
    dialog._hf_spin_granularity = spin_granularity
    dialog._hf_group = group
    dialog.btn_high_freq = btn_analyze

    def _render_chips():
        """根据 _hf_results + 搜索过滤 + 桶状态渲染 chips。"""
        while chips_layout.count():
            child = chips_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        text = search.text().strip().lower()
        buckets = {
            "required": _parse_keywords(dialog.in_required.text()) if hasattr(dialog, "in_required") else [],
            "optional": _parse_keywords(dialog.in_optional.text()) if hasattr(dialog, "in_optional") else [],
            "forbidden": _parse_keywords(dialog.in_forbidden.text()) if hasattr(dialog, "in_forbidden") else [],
        }
        pool = _chips_pool(dialog._hf_results, buckets)
        if text:
            pool = [(w, c) for w, c in pool if text in w.lower()]
        for word, count in pool:
            btn = make_button(_chip_text(word, count))
            btn.setCheckable(True)
            btn.setChecked(word in dialog._hf_selected)
            btn.clicked.connect(lambda checked, w=word: _on_chip_click(w, checked))
            chips_layout.addWidget(btn)

    def _on_chip_click(word, checked):
        if checked:
            dialog._hf_selected.add(word)
        else:
            dialog._hf_selected.discard(word)

    def _on_analyze():
        """分析高频词：从聚合标题经 jieba 分词统计频次。"""
        store = dialog.owner.store if hasattr(dialog.owner, "store") else None
        target_id = dialog.agg_id if hasattr(dialog, "agg_id") else 0
        if not target_id and dialog._parent_agg:
            target_id = dialog._parent_agg["id"]
        target_id = int(target_id or 0)
        if store and hasattr(store, "aggregation_titles"):
            titles = store.aggregation_titles(target_id, limit=None)
        else:
            titles = []
        from modules.rss_aggregator.text_segment import segment_titles
        top_n = spin_top_n.value()
        dialog._hf_results = segment_titles(
            titles, top_n=top_n, granularity=spin_granularity.value())
        dialog._hf_selected.clear()
        _render_chips()

    btn_analyze.clicked.connect(_on_analyze)
    search.textChanged.connect(lambda: _render_chips())

    def _on_granularity_changed(v):
        """粒度变化：写回 config 默认 + 更新说明 + 已有结果时立即重跑。"""
        config = getattr(getattr(dialog.owner, "context", None), "config", None)
        if config is not None:
            config.set("rss.similarity_granularity", v)
        granularity_hint.setText(_granularity_hint(v))
        if dialog._hf_results:
            _on_analyze()

    spin_granularity.valueChanged.connect(_on_granularity_changed)

    def _on_add_all():
        """把选中 chips 加入【必须】桶。"""
        if not hasattr(dialog, "in_required"):
            return
        words = _parse_keywords(dialog.in_required.text())
        for w in dialog._hf_selected:
            if w not in words:
                words.append(w)
        dialog.in_required.setText(" ".join(words))
        dialog._hf_selected.clear()
        _render_chips()

    btn_add_all.clicked.connect(_on_add_all)

    def _on_clear():
        """清空三桶。"""
        for attr in ("in_required", "in_optional", "in_forbidden"):
            if hasattr(dialog, attr):
                getattr(dialog, attr).setText("")
        _render_chips()

    btn_clear.clicked.connect(_on_clear)

    def _on_stop_words():
        from .stop_words import _StopWordsDialog
        _StopWordsDialog(dialog.owner, parent=dialog).exec()

    btn_stop.clicked.connect(_on_stop_words)

    return group


def build_members_group(dialog):
    """构建成员勾选组（非 parent 模式）。

    设置 dialog.member_list / dialog._members_group，并调用 dialog._load_members()。
    """
    group = QtWidgets.QGroupBox("成员")
    group.setStyleSheet(_rss_head_style())
    mg = QtWidgets.QVBoxLayout(group)
    dialog.member_list = QtWidgets.QListWidget()
    dialog.member_list.setMaximumHeight(160)
    dialog._load_members()
    mg.addWidget(dialog.member_list)
    dialog._members_group = group
    return group


def build_tag_group(dialog):
    """构建标签多选组（相似性类型专用）。

    设置 dialog.tag_list / dialog._tag_group。
    """
    group = QtWidgets.QGroupBox("标签（相似性类型专用）")
    group.setStyleSheet(_rss_head_style())
    tg = QtWidgets.QVBoxLayout(group)
    dialog.tag_list = QtWidgets.QListWidget()
    dialog.tag_list.setMaximumHeight(120)
    dialog.tag_list.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
    for tag in dialog.store.list_tags():
        dialog.tag_list.addItem(QtWidgets.QListWidgetItem(tag))
    tg.addWidget(dialog.tag_list)
    dialog._tag_group = group
    return group


def build_keyword_group(dialog):
    """构建关键词三桶组 + 自动提取按钮。

    设置 dialog.btn_auto_extract / in_required / in_optional / in_forbidden。
    """
    group = QtWidgets.QGroupBox("关键词三桶（仅关键词类型）")
    group.setStyleSheet(_rss_head_style())
    kg = QtWidgets.QVBoxLayout(group)
    kw_row = QtWidgets.QHBoxLayout()
    kw_row.addWidget(QtWidgets.QLabel(group.title()))
    kw_row.addStretch(1)
    dialog.btn_auto_extract = QtWidgets.QPushButton("自动提取关键词")
    dialog.btn_auto_extract.setStyleSheet(_btn_style(min_width=80))
    dialog.btn_auto_extract.clicked.connect(dialog._on_auto_extract)
    kw_row.addWidget(dialog.btn_auto_extract)
    kg.addLayout(kw_row)
    fk = QtWidgets.QFormLayout()
    dialog.in_required = QtWidgets.QLineEdit()
    dialog.in_required.setPlaceholderText("必须命中（逗号/空格分隔）")
    dialog.in_optional = QtWidgets.QLineEdit()
    dialog.in_optional.setPlaceholderText("可选命中（空=不限）")
    dialog.in_forbidden = QtWidgets.QLineEdit()
    dialog.in_forbidden.setPlaceholderText("禁止命中")
    fk.addRow("必须", dialog.in_required)
    fk.addRow("可选", dialog.in_optional)
    fk.addRow("禁止", dialog.in_forbidden)
    kg.addLayout(fk)
    return group
