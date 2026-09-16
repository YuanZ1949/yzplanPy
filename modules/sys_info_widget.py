"""sys_info 界面：两列表单布局（项目名 | 值），分组小标题，无卡片外框。"""
from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from core.theme.tokens import sizing, theme_palette

from qfluentwidgets import FluentIcon

from .sys_info import collect_info, validate_info
from ui.widgets import make_button, make_label, make_status_chip

# 类别 → 图标 → 键集合（未匹配的键归入「系统」）
_CATEGORY_KEYS = [
    ("硬件", FluentIcon.SPEED_HIGH,
     {"处理器", "物理核心", "逻辑核心", "内存总量", "内存使用", "GPU", "系统盘", "磁盘IO"}),
    ("系统", FluentIcon.SETTING,
     {"主机名", "系统", "版本", "机器", "系统启动时间",
      "开机自启", "主题", "窗口尺寸", "截图热键"}),
    ("网络", FluentIcon.GLOBE, {"网络适配器"}),
    ("软件", FluentIcon.APPLICATION,
     {"Python版本", "PySide6版本", "qfluentwidgets版本"}),
]


def _sysinfo_palette():
    """sys_info 表单取色：全局令牌（无私有色板）。"""
    p = theme_palette()
    return {
        "dark": p["dark"],
        "label_fg": p["sysinfo_label_fg"],
        "row_border": p["sysinfo_row_border"],
        "value_bg": p["sysinfo_value_bg"],
        "text": p["text_primary"],
    }


def _make_value_label(c):
    """值单元格：只读、可选中复制、自动换行、行高自适应（最小高来自令牌）。"""
    sz = sizing()
    label = QtWidgets.QLabel()
    label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(
        QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        | QtCore.Qt.TextInteractionFlag.TextSelectableByKeyboard)
    label.setMinimumHeight(sz["sysinfo_row_height"])
    label.setStyleSheet(
        "QLabel { background: %s; border: 1px solid %s;"
        " border-radius: %dpx; padding: %s; color: %s; }"
        % (c["value_bg"], c["row_border"], sz["radius_md"],
           sz["sysinfo_edit_padding"], c["text"])
    )
    return label


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


def _build_form(parent, config=None):
    """构建两列表单：表头（项目名|值）+ 分组小标题 + 项目名|值 行（无卡片外框）。"""
    c = _sysinfo_palette()
    sz = sizing()
    info = collect_info(config)
    groups = _group_info(info)
    container = QtWidgets.QWidget(parent)
    grid = QtWidgets.QGridLayout(container)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(sz["radius_md"])
    grid.setVerticalSpacing(sz["radius_sm"])

    row = 0
    head_name = make_label("项目名", role="caption")
    head_name.setMinimumWidth(sz["sysinfo_label_width"])
    grid.addWidget(head_name, row, 0)
    grid.addWidget(make_label("值", role="caption"), row, 1)
    row += 1

    for cat_name, pairs in groups:
        grid.addWidget(make_label(cat_name, role="subtitle"), row, 0, 1, 2)
        row += 1
        for key, value in pairs:
            name = make_label(key, role="body")
            name.setMinimumWidth(sz["sysinfo_label_width"])
            name.setStyleSheet(
                "QLabel { color: %s; background: transparent; }" % c["label_fg"])
            value_label = _make_value_label(c)
            value_label.setProperty("sysinfo_key", key)
            value_label.setText(str(value) if value not in (None, "") else "—")
            grid.addWidget(name, row, 0)
            grid.addWidget(value_label, row, 1)
            row += 1
    return container


def _refresh_form(form, config=None):
    """重新采集并更新表单值单元格。"""
    info = collect_info(config)
    for label in form.findChildren(QtWidgets.QLabel):
        key = label.property("sysinfo_key")
        if key:
            value = info.get(key)
            label.setText(str(value) if value not in (None, "") else "—")


def _copy_all(config=None):
    info = collect_info(config)
    text = "\n".join(f"{k}: {v}" for k, v in info.items())
    QtWidgets.QApplication.clipboard().setText(text)


def _update_validation(row, config):
    """重建校验结果区：正常 → 1 个 success chip；有问题 → warning chips（最多 6 条，
    超出追加 error chip「等 N 项」）。"""
    problems = validate_info(collect_info(config))
    for i in reversed(range(row.count())):
        it = row.itemAt(i)
        w = it.widget()
        row.removeItem(it)
        if w is not None:
            w.deleteLater()
    if not problems:
        row.addWidget(make_status_chip("正常", kind="success"))
    else:
        for msg in problems[:6]:
            row.addWidget(make_status_chip(msg, kind="warning"))
        if len(problems) > 6:
            row.addWidget(make_status_chip(f"等 {len(problems) - 6} 项", kind="error"))
    row.addStretch(1)


def make_info_widget(parent, config=None):
    w = QtWidgets.QWidget(parent)
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(8, 8, 8, 8)
    lay.setSpacing(10)

    bar = QtWidgets.QHBoxLayout()
    btn_refresh = make_button("刷新", kind="primary")
    btn_copy = make_button("复制全部")
    bar.addWidget(btn_refresh)
    bar.addWidget(btn_copy)
    bar.addStretch(1)
    lay.addLayout(bar)

    validation_row = QtWidgets.QHBoxLayout()
    validation_row.setSpacing(6)
    lay.addLayout(validation_row)

    scroll = QtWidgets.QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
    form = _build_form(scroll, config)
    scroll.setWidget(form)
    lay.addWidget(scroll, 1)

    _update_validation(validation_row, config)
    btn_refresh.clicked.connect(lambda: _refresh_form(form, config))
    btn_refresh.clicked.connect(lambda: _update_validation(validation_row, config))
    btn_copy.clicked.connect(lambda: _copy_all(config))
    return w