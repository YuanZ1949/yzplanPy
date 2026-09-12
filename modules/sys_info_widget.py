"""sys_info 界面：qfluentwidgets 分组卡片布局（硬件/系统/网络/软件）。"""
from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from core.theme.tokens import sizing, theme_palette

from qfluentwidgets import (
    FluentIcon,
    GroupHeaderCardWidget,
    PlainTextEdit,
    PrimaryPushButton,
    PushButton,
)

from .sys_info import collect_info

# 类别 → 图标 → 键集合（未匹配的键归入「系统」）
_CATEGORY_KEYS = [
    ("硬件", FluentIcon.SPEED_HIGH,
     {"处理器", "物理核心", "逻辑核心", "内存总量", "内存使用", "GPU", "系统盘", "磁盘IO"}),
    ("系统", FluentIcon.SETTING,
     {"主机名", "系统", "版本", "机器", "系统启动时间"}),
    ("网络", FluentIcon.GLOBE, {"网络适配器"}),
    ("软件", FluentIcon.APPLICATION,
     {"Python版本", "PySide6版本", "qfluentwidgets版本"}),
]


def _sysinfo_palette():
    """sys_info 编辑区取色：全局令牌 + 编辑区专属背景（保原值）。"""
    p = theme_palette()
    return {
        "dark": p["dark"],
        "edit_bg": p["sysinfo_edit_bg"],
        "edit_border": p["border"],
        "text": p["text_primary"],
    }


def _make_edit(c):
    edit = PlainTextEdit()
    edit.setReadOnly(True)
    edit.setWordWrapMode(QtGui.QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    edit.setMinimumHeight(sizing()["sysinfo_edit_min_height"])
    edit.setStyleSheet(
        "QPlainTextEdit { background: %s; border: 1px solid %s;"
        " border-radius: %dpx; padding: %s; color: %s; }"
        % (c["edit_bg"], c["edit_border"], sizing()["radius_lg"],
           sizing()["sysinfo_edit_padding"], c["text"])
    )
    return edit


def _group_info(info):
    """把 collect_info 的键值对按类别分组，返回 [(类别名, [(键, 值), ...]), ...]。"""
    groups = []
    used = set()
    for cat_name, _icon, keys in _CATEGORY_KEYS:
        pairs = [(k, info[k]) for k in keys if k in info]
        used.update(k for k, _ in pairs)
        groups.append([cat_name, pairs])
    leftover = [(k, info[k]) for k in info if k not in used]
    if leftover:
        groups[1][1].extend(leftover)
    return groups


def _fill_cards(cards, info):
    groups = _group_info(info)
    for (_card, edit), (_cat_name, pairs) in zip(cards, groups):
        edit.setPlainText("\n".join(f"{k}: {v}" for k, v in pairs))


def _build_cards(parent):
    c = _sysinfo_palette()
    info = collect_info()
    cards = []
    for cat_name, icon, _keys in _CATEGORY_KEYS:
        card = GroupHeaderCardWidget(parent)
        card.setTitle(cat_name)
        edit = _make_edit(c)
        card.addGroup(icon, "", "", edit)
        cards.append((card, edit))
    _fill_cards(cards, info)
    return cards


def _refresh_cards(cards):
    _fill_cards(cards, collect_info())


def _copy_all():
    info = collect_info()
    text = "\n".join(f"{k}: {v}" for k, v in info.items())
    QtWidgets.QApplication.clipboard().setText(text)


def make_info_widget(parent):
    w = QtWidgets.QWidget(parent)
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(8, 8, 8, 8)
    lay.setSpacing(10)

    bar = QtWidgets.QHBoxLayout()
    btn_refresh = PrimaryPushButton("刷新")
    btn_copy = PushButton("复制全部")
    bar.addWidget(btn_refresh)
    bar.addWidget(btn_copy)
    bar.addStretch(1)
    lay.addLayout(bar)

    cards = _build_cards(w)
    for card, _edit in cards:
        lay.addWidget(card)
    lay.addStretch(1)

    btn_refresh.clicked.connect(lambda: _refresh_cards(cards))
    btn_copy.clicked.connect(lambda: _copy_all())
    return w