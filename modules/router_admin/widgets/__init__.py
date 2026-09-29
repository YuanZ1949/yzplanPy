"""router_admin.widgets：模块内共享的令牌化控件工厂 + 确认/提示助手。

`ui/widgets.py` 只提供按钮/输入/下拉/卡片/胶囊/标签/复选框/工具按钮，缺表格、
密码框、进度条三样（AGENTS.md 已注明）。这里补齐，**严格令牌化**：颜色只取
`core.theme.tokens.theme_palette()`，尺寸/字号只取 `sizing()`，全文件不出现
任何颜色或像素字面量。表格工厂在同包 `tables.py`；各 Tab 在 `tabs_*.py`。

本文件不 import 同包兄弟模块（避免循环），也不在 import 期做任何副作用。
"""
from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing, theme_palette
from qfluentwidgets import InfoBar, InfoBarPosition, MessageBox, MessageBoxBase

from ui.widgets import make_label, make_line_edit, make_status_chip

_, QtCore, QtGui, QtWidgets = import_qt()

#: InfoBar 停留时长（ms）。比 qfluentwidgets 默认 1000 长，采集提示才看得清。
NOTIFY_MS = 4000


def _password_qss(p, sz):
    """口令框 QSS：与 make_line_edit 同规格，仅多一层 Password echoMode（由调用方设）。"""
    return (
        f"QLineEdit {{ background: {p['bg_control']}; color: {p['text_primary']};"
        f" border: 1px solid {p['border']}; border-radius: {sz['radius_md']}px;"
        f" padding: {sz['input_height'] // 5}px {sz['input_h_padding']}px;"
        f" font-size: {sz['font_size_sm']}px; }}"
        f"QLineEdit:focus {{ border: 1px solid {p['border_focus']}; }}"
    )


def make_password_edit(placeholder="口令", *, parent=None):
    """口令输入框。ui/widgets.py 无密码框工厂，此处按同一令牌规格自建。"""
    w = QtWidgets.QLineEdit(parent)
    w.setPlaceholderText(placeholder)
    w.setEchoMode(QtWidgets.QLineEdit.Password)
    w.setFixedHeight(sizing()["input_height"])
    w.setStyleSheet(_password_qss(theme_palette(), sizing()))
    return w


def _editor_qss(p, sz):
    return (
        f"QPlainTextEdit {{ background: {p['bg_control']};"
        f" color: {p['text_primary']}; border: 1px solid {p['border']};"
        f" border-radius: {sz['radius_md']}px;"
        f" padding: {sz['input_h_padding'] // 2}px {sz['input_h_padding']}px;"
        f" font-family: Consolas, monospace; font-size: {sz['font_size_sm']}px; }}"
        f"QPlainTextEdit:focus {{ border: 1px solid {p['border_focus']}; }}"
        f"QPlainTextEdit:disabled {{ color: {p['text_disabled']}; }}"
    )


def make_mono_editor(*, parent=None, read_only=False):
    """等宽多行编辑区（配置编辑 / 只读输出共用）。tab 宽度由令牌推导，无字面量。"""
    sz = sizing()
    w = QtWidgets.QPlainTextEdit(parent)
    w.setReadOnly(bool(read_only))
    w.setTabStopDistance(sz["input_h_padding"] * 4)
    w.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
    w.setStyleSheet(_editor_qss(theme_palette(), sz))
    return w


def _bar_qss(p, sz, color):
    return (
        f"QProgressBar {{ background: {p['bg_control']};"
        f" border: 1px solid {p['border']}; border-radius: {sz['radius_sm']}px;"
        f" text-align: center; font-size: {sz['font_size_xs']}px;"
        f" color: {p['text_secondary']}; }}"
        f"QProgressBar::chunk {{ background: {color};"
        f" border-radius: {sz['radius_sm']}px; }}"
    )


def make_usage_bar(*, parent=None):
    """使用率横条。返回 QProgressBar，调用 `bar.set_percent(pct, text)` 刷新。

    QProgressBar 没有 `setText`，显示文字走 `setFormat()`（不含 `%p%` 时按字面量
    渲染），所以文案与数值分开传。
    """
    bar = QtWidgets.QProgressBar(parent)
    bar.setRange(0, 100)
    bar.setTextVisible(True)
    bar.setFixedHeight(sizing()["btn_height_sm"])
    bar.set_percent = _bind_percent(bar)
    return bar


def _bind_percent(bar):
    """把 set_percent 绑到具体 bar 上（闭包代替子类，避免为一处分档配色多开一个类）。"""

    def set_percent(pct, text=None):
        try:
            value = float(pct)
        except (TypeError, ValueError):
            value = 0.0
        p = theme_palette()
        color = (p["accent"] if value < 70 else
                 p["status_warning"] if value < 90 else p["status_error"])
        bar.setValue(int(max(0, min(100, round(value)))))
        bar.setFormat(text if text is not None else f"{value:.0f}%")
        bar.setStyleSheet(_bar_qss(p, sizing(), color))

    set_percent(0, "—")
    return set_percent


def make_stat_card(title, *, parent=None):
    """总览/首页通用指标小卡。返回 (card, value_label)，value_label 可直接 setText。"""
    p, sz = theme_palette(), sizing()
    card = QtWidgets.QFrame(parent)
    card.setStyleSheet(
        f"QFrame {{ background: {p['bg_card']}; border: 1px solid {p['border']};"
        f" border-radius: {sz['radius_lg']}px; }}")
    pad = sz["dialog_margin"] // 2
    lay = QtWidgets.QVBoxLayout(card)
    lay.setContentsMargins(pad, pad, pad, pad)
    lay.setSpacing(sz["radius_xs"])
    lay.addWidget(make_label(title, role="caption", parent=card))
    value = make_label("—", role="subtitle", parent=card)
    lay.addWidget(value)
    return card, value


def make_card_block(title, *, parent=None):
    """令牌化分区卡：标题 + 竖排内容。返回 (card, layout)。

    三个 Tab 都要「一块带标题的分区」（内存 / 无线 / 备份），各自重写一遍
    边框 + 圆角 + 边距的 QSS 只会互相漂移，故收敛到这里。
    """
    p, sz = theme_palette(), sizing()
    card = QtWidgets.QFrame(parent)
    card.setStyleSheet(
        f"QFrame {{ background: {p['bg_card']}; border: 1px solid {p['border']};"
        f" border-radius: {sz['radius_lg']}px; }}")
    lay = QtWidgets.QVBoxLayout(card)
    lay.setContentsMargins(sz["dialog_margin"] // 2, sz["radius_md"],
                           sz["dialog_margin"] // 2, sz["radius_md"])
    lay.setSpacing(sz["radius_xs"])
    if title:
        lay.addWidget(make_label(title, role="caption", parent=card))
    return card, lay


def make_chip_row(title, *, parent=None):
    """「标题 + 一排状态胶囊」横条。返回 (row_layout, chips_widget, chips_layout)。

    调用方往 `chips_layout` 里 add_chip()（末尾已留 stretch），清空用 reset_chips()。
    """
    sz = sizing()
    row = QtWidgets.QHBoxLayout()
    row.setSpacing(sz["radius_sm"])
    row.addWidget(make_label(title, role="caption", parent=parent))
    holder = QtWidgets.QWidget(parent)
    lay = QtWidgets.QHBoxLayout(holder)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addStretch(1)
    row.addWidget(holder, 1)
    return row, holder, lay


def reset_chips(lay):
    """清空胶囊行（保留末尾 stretch），旧胶囊立即 deleteLater。"""
    while lay.count() > 1:
        item = lay.takeAt(0)
        if item.widget() is not None:
            item.widget().deleteLater()


def add_chip(lay, text, kind, *, parent=None):
    """往胶囊行末尾（stretch 之前）加一枚 make_status_chip。"""
    lay.insertWidget(lay.count() - 1, make_status_chip(text, kind=kind,
                                                       parent=parent))


def confirm(parent, title, text, *, ok_text="确定", cancel_text="取消"):
    """二次确认弹窗。parent 为 None（无宿主窗口）时视为拒绝，绝不默认放行。"""
    if parent is None:
        return False
    box = MessageBox(title, text, parent)
    box.yesButton.setText(ok_text)
    box.cancelButton.setText(cancel_text)
    return bool(box.exec() == QtWidgets.QDialog.Accepted)


class _PhraseBox(MessageBoxBase):
    """要求用户键入指定词才放行的确认框（重启路由器这类不可逆操作用）。"""

    def __init__(self, title, text, phrase, hint, parent):
        super().__init__(parent)
        self._phrase = phrase
        self.tip = make_label("", role="caption", parent=self.widget)
        for w in (make_label(title, role="subtitle", parent=self.widget),
                  make_label(text, role="body", parent=self.widget),
                  make_line_edit(hint, parent=self.widget),
                  self.tip):
            self.viewLayout.addWidget(w)
        self.edit = self.viewLayout.itemAt(2).widget()
        self.yesButton.setText("确定")
        self.cancelButton.setText("取消")
        self.tip.setText(f"请键入「{phrase}」后再点确定")

    def validate(self):
        if self.edit.text().strip() != self._phrase:
            self.tip.setText("键入内容不匹配，操作已被拒绝")
            return False
        return True


def confirm_phrase(parent, title, text, phrase, *, hint=None):
    """双重确认的第二道：必须键入 phrase 才返回 True。"""
    if parent is None:
        return False
    box = _PhraseBox(title, text, phrase, hint or f"键入 {phrase}", parent)
    return bool(box.exec() == QtWidgets.QDialog.Accepted)


def notify(parent, title, content, *, error=False, duration=NOTIFY_MS):
    """右上角非阻塞提示（成功/失败都用它，避免自动刷新时反复弹模态框）。"""
    if parent is None:
        return
    bar = (InfoBar.error if error else InfoBar.success)(
        title, content, parent=parent, position=InfoBarPosition.TOP_RIGHT,
        duration=duration)


def alert(parent, title, text):
    """模态错误提示：写操作失败时用，必须让用户明确点掉（隐藏取消键，只留确定）。"""
    if parent is None:
        return
    box = MessageBox(title, text, parent)
    box.cancelButton.hide()
    box.yesButton.setText("知道了")
    box.exec()
