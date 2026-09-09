"""todo_notes 主页卡片：_make_home_widget/_toggle_done/_home_context_menu。"""
from datetime import datetime
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()
from .constants import PRIORITY_COLORS, PRIORITY_LABELS
from ..todo_store import add_todo, delete_todo, get_todos, update_todo

_ROLE_PRIORITY = QtCore.Qt.UserRole + 1  # delegate reads priority for badge color


class _HomeItemDelegate(QtWidgets.QStyledItemDelegate):
    """Paint pending-item priority badge as a colored rounded pill + colored text,
    and done items as gray strikethrough text."""

    _PILL_RADIUS = 8
    _PILL_PAD_X = 7
    _PILL_PAD_Y = 2
    _PILL_GAP = 8
    _LEFT_MARGIN = 12

    def paint(self, painter, option, index):
        # Draw item background (hover / selection highlight)
        self.initStyleOption(option, index)
        option.text = ""
        style = option.widget.style() if option.widget else QtWidgets.QApplication.style()
        style.drawControl(QtWidgets.QStyle.CE_ItemViewItem, option, painter, option.widget)

        priority = index.data(_ROLE_PRIORITY)

        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        if priority is not None:
            # --- Pending: colored badge pill + colored title text ---
            color_hex = PRIORITY_COLORS.get(int(priority), "#888")
            label = PRIORITY_LABELS.get(int(priority), "待办")
            text = index.data(QtCore.Qt.DisplayRole) or ""

            bg = QtGui.QColor(color_hex)
            fm = option.fontMetrics
            tw = fm.horizontalAdvance(label)
            th = fm.height()
            badge_w = tw + self._PILL_PAD_X * 2
            badge_h = th + self._PILL_PAD_Y * 2
            badge_x = float(option.rect.left() + self._LEFT_MARGIN)
            badge_y = float(option.rect.top() + (option.rect.height() - badge_h) / 2)

            # Badge background pill
            painter.setBrush(QtGui.QBrush(bg))
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawRoundedRect(
                QtCore.QRectF(badge_x, badge_y, badge_w, badge_h),
                self._PILL_RADIUS, self._PILL_RADIUS,
            )
            # Badge label (white)
            painter.setPen(QtGui.QColor("white"))
            painter.setFont(option.font)
            painter.drawText(
                QtCore.QRectF(badge_x + self._PILL_PAD_X,
                              badge_y + self._PILL_PAD_Y, tw, th),
                int(QtCore.Qt.AlignCenter), label,
            )
            # Item title text (colored by priority)
            painter.setPen(QtGui.QColor(color_hex))
            tx = badge_x + badge_w + self._PILL_GAP
            painter.drawText(
                QtCore.QRectF(tx, option.rect.top(),
                              option.rect.right() - tx, option.rect.height()),
                int(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft), text,
            )
        else:
            # --- Done: gray strikethrough text ---
            painter.setPen(QtGui.QColor("#aaa"))
            font = QtGui.QFont(option.font)
            font.setStrikeOut(True)
            painter.setFont(font)
            rect = option.rect.adjusted(self._LEFT_MARGIN, 0, -4, 0)
            painter.drawText(
                rect, int(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft),
                index.data() or "",
            )

        painter.restore()

    def sizeHint(self, option, index):
        base = super().sizeHint(option, index)
        return QtCore.QSize(base.width(), max(base.height(), 32))


# ── 主页卡片 ──────────────────────────────────────────────────────────

def _make_home_widget(owner, parent):
    from core.qt_bootstrap import import_qt
    _, QtCore, QtGui, QtWidgets = import_qt()
    from qfluentwidgets import BodyLabel, PrimaryPushButton, StrongBodyLabel

    w = QtWidgets.QWidget(parent)
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(8, 4, 8, 6)
    lay.setSpacing(4)

    header = QtWidgets.QHBoxLayout()
    title = StrongBodyLabel("待办事项")
    header.addWidget(title)
    header.addStretch(1)
    count_lbl = BodyLabel("")
    count_lbl.setStyleSheet(
        "color: #888;"
        "background: rgba(128,128,128,0.10);"
        "border-radius: 9px;"
        "padding: 2px 10px;"
        "font-size: 12px;"
    )
    header.addWidget(count_lbl)
    lay.addLayout(header)

    list_widget = QtWidgets.QListWidget()
    list_widget.setStyleSheet(
        "QListWidget { border: none; background: transparent; outline: none; }"
        "QListWidget::item { padding: 8px 10px; margin: 2px 0; border-radius: 8px;"
        "  border-bottom: 1px solid rgba(128,128,128,0.08); }"
        "QListWidget::item:hover { background: rgba(128,128,128,0.08); border-radius: 8px; }"
        "QListWidget::item:selected { background: rgba(128,128,128,0.12); border-radius: 8px; }"
        "QListWidget::item:selected:hover { background: rgba(128,128,128,0.12); border-radius: 8px; }"
    )
    lay.addWidget(list_widget, 1)
    list_widget.setItemDelegate(_HomeItemDelegate(list_widget))

    add_row = QtWidgets.QHBoxLayout()
    add_input = QtWidgets.QLineEdit()
    add_input.setPlaceholderText("输入待办事项...")
    add_btn = PrimaryPushButton("添加")
    add_row.addWidget(add_input, 1)
    add_row.addWidget(add_btn)
    lay.addLayout(add_row)

    def refresh():
        list_widget.clear()
        todos = get_todos(done=0, order="due_date")
        overdue = get_todos(done=0, order="due_date")
        now = datetime.now().date()
        pending = [t for t in todos if not t["done"]]
        done_items = get_todos(done=1, order="created_at")[:5]
        count_lbl.setText(f"{len(pending)} 项待办")

        for t in pending:
            item = QtWidgets.QListWidgetItem()
            item.setData(QtCore.Qt.UserRole, t["id"])
            item.setData(_ROLE_PRIORITY, t["priority"])
            text = t["title"]
            if t["due_date"]:
                try:
                    due = datetime.strptime(t["due_date"], "%Y-%m-%d").date()
                    days = (due - now).days
                    if days < 0:
                        text += f"  [逾期{-days}天]"
                    elif days == 0:
                        text += "  [今天截止]"
                    elif days == 1:
                        text += "  [明天截止]"
                    else:
                        text += f"  [{days}天后]"
                except ValueError:
                    pass
            item.setText(text)
            list_widget.addItem(item)
        for t in done_items:
            item = QtWidgets.QListWidgetItem()
            item.setData(QtCore.Qt.UserRole, t["id"])
            item.setText(f"✓ {t['title']}")
            item.setForeground(QtGui.QColor("#aaa"))
            f = item.font()
            f.setStrikeOut(True)
            item.setFont(f)
            list_widget.addItem(item)

    def add_todo_from_input():
        text = add_input.text().strip()
        if not text:
            return
        add_todo(text)
        add_input.clear()
        refresh()

    add_btn.clicked.connect(add_todo_from_input)
    add_input.returnPressed.connect(add_todo_from_input)

    list_widget.itemDoubleClicked.connect(lambda item: _toggle_done(item, refresh))
    list_widget.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
    list_widget.customContextMenuRequested.connect(lambda pos: _home_context_menu(pos, list_widget, refresh))

    refresh()
    owner._home_refresh = refresh
    return w


def _toggle_done(item, refresh):
    todo_id = item.data(QtCore.Qt.UserRole)
    if todo_id is None:
        return
    todos = get_todos()
    for t in todos:
        if t["id"] == todo_id:
            update_todo(todo_id, done=0 if t["done"] else 1)
            break
    refresh()


def _home_context_menu(pos, list_widget, refresh):
    from core.qt_bootstrap import import_qt
    _, QtCore, _, QtWidgets = import_qt()

    item = list_widget.itemAt(pos)
    if not item:
        return
    todo_id = item.data(QtCore.Qt.UserRole)
    if todo_id is None:
        return

    menu = QtWidgets.QMenu()
    act_toggle = menu.addAction("切换完成状态")
    menu.addSeparator()
    act_high = menu.addAction("优先级: 紧急")
    act_hi = menu.addAction("优先级: 高")
    act_mid = menu.addAction("优先级: 中")
    act_low = menu.addAction("优先级: 低")
    menu.addSeparator()
    act_del = menu.addAction("删除")

    action = menu.exec_(list_widget.mapToGlobal(pos))
    if not action:
        return
    if action == act_toggle:
        _toggle_done(item, refresh)
    elif action == act_high:
        update_todo(todo_id, priority=3)
        refresh()
    elif action == act_hi:
        update_todo(todo_id, priority=2)
        refresh()
    elif action == act_mid:
        update_todo(todo_id, priority=1)
        refresh()
    elif action == act_low:
        update_todo(todo_id, priority=0)
        refresh()
    elif action == act_del:
        delete_todo(todo_id)
        refresh()
