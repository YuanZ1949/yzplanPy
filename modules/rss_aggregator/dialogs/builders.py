"""聚合对话框的构建辅助：把成员/标签/关键词分组构建逻辑从 f.py 拆出。

这些函数接收对话框实例，构建对应 QGroupBox 并把控件挂到实例属性上，
不改变控件层级、信号连接或默认值。
"""
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()
from ..styles import _btn_style, _rss_head_style


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
