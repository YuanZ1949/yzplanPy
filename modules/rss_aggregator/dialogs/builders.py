"""聚合对话框的构建辅助：把成员/标签/关键词分组构建逻辑从 f.py 拆出。

这些函数接收对话框实例，构建对应 QGroupBox 并把控件挂到实例属性上，
不改变控件层级、信号连接或默认值。
"""
from typing import Any
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()
from ..styles import _btn_style, _rss_head_style
from ..text_utils import _parse_keywords, analyze_high_freq_titles, rss_palette
from core.theme.tokens import sizing


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
    """高频词交互方法混入：分析/追加/点击（供 _AddAggregationDialog 使用）。"""

    _parent_agg: dict | None
    store: Any
    combo_type: Any
    tag_list: Any
    hf_flow: Any
    hf_flow_layout: Any
    in_required: Any
    in_forbidden: Any

    def _on_analyze_high_freq(self):
        """分析高频词：从成员标题提取高频词渲染为可点击 chips。"""
        titles = []
        if self._parent_agg:
            titles = self.store.aggregation_titles(self._parent_agg["id"])
        elif hasattr(self, "tag_list") and self.combo_type.currentData() == "similarity":
            selected = [item.text() for item in self.tag_list.selectedItems()]
            recent_fn: Any = getattr(self.store, "recent", None)
            if selected and recent_fn is not None:
                titles = [it.get("title") or "" for it in recent_fn(limit=200, tags=selected)]
        self.hf_flow_layout.clear()
        if not titles:
            return
        for word in analyze_high_freq_titles(titles, top_n=12):
            chip = QtWidgets.QPushButton(word)
            chip.setStyleSheet(_chip_style())
            chip.clicked.connect(lambda _=False, w=word: self._on_chip_clicked(w))
            self.hf_flow_layout.addWidget(chip)

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


def _chip_style():
    """高频词 chip 药丸样式：复用 rss_pill_tag 令牌 + hover 变体。"""
    c = rss_palette()
    s = sizing()
    return (
        f"QPushButton {{ background: {c['rss_pill_tag_bg']}; color: {c['rss_pill_tag_fg']}; border: none; "
        f"border-radius: {s['rss_radius_md']}px; padding: {s['rss_thumb_padding']}; "
        f"font-size: {s['rss_font_xs']}px; }}"
        f"QPushButton:hover {{ background: {c['rss_control_bg_hover']}; }}"
    )


def build_high_freq_group(dialog):
    """构建标题高频词组（相似性类型专用）：分析按钮 + 提示 + chips 流式布局。

    设置 dialog.btn_high_freq / dialog.hf_flow / dialog._hf_group。
    """
    group = QtWidgets.QGroupBox("标题高频词")
    group.setStyleSheet(_rss_head_style())
    hg = QtWidgets.QVBoxLayout(group)
    top_row = QtWidgets.QHBoxLayout()
    dialog.btn_high_freq = QtWidgets.QPushButton("分析高频词")
    dialog.btn_high_freq.setStyleSheet(_btn_style(min_width=80))
    dialog.btn_high_freq.clicked.connect(dialog._on_analyze_high_freq)
    top_row.addWidget(dialog.btn_high_freq)
    top_row.addStretch(1)
    hg.addLayout(top_row)
    hint = QtWidgets.QLabel("单击=加入【必须】· Shift+单击=加入【禁止】")
    hint.setStyleSheet(
        f"QLabel {{ color:{rss_palette()['rss_text_faint']}; font-size:{sizing()['rss_font_md']}px; }}")
    hg.addWidget(hint)
    dialog.hf_flow = QtWidgets.QWidget()
    dialog.hf_flow_layout = _FlowLayout()
    dialog.hf_flow.setLayout(dialog.hf_flow_layout)
    hg.addWidget(dialog.hf_flow)
    dialog._hf_group = group
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
