"""proxy_ctrl.widgets：模块内共享的令牌化控件工厂 + 确认/提示助手。

`ui/widgets.py` 只提供按钮/输入/下拉/卡片/胶囊/标签/复选框/工具按钮，缺**进度条**
与**表格**两样（AGENTS.md 已注明）。这里补齐进度条，表格工厂在同包 `tables.py`，
各 Tab 在 `tab_*.py`。

**严格令牌化**：颜色只取 `core.theme.tokens.theme_palette()`，尺寸/字号只取
`sizing()`，全文件不出现任何颜色或像素字面量（AGENTS.md 规则 2/3）。
样式函数一律把 palette dict 作参数传入，本文件不定义任何 `_xxx_colors()`
（AGENTS.md 规则 4）。

本文件不 import 同包兄弟模块（避免循环），import 期不做任何副作用。
"""
from core.qt_bootstrap import import_qt
from core.theme.tokens import sizing, theme_palette
from qfluentwidgets import InfoBar, InfoBarPosition, MessageBox

from ui.widgets import make_label, make_status_chip

_, QtCore, QtGui, QtWidgets = import_qt()

#: InfoBar 停留时长（ms）。比 qfluentwidgets 默认 1000 长，批量设置的提示才看得清。
NOTIFY_MS = 4000


def card_qss(p, sz, radius_key="radius_lg"):
    """分区卡的统一 QSS（边框 + 圆角），各 Tab 共用一处。"""
    return (f"QFrame {{ background: {p['bg_card']}; border: 1px solid {p['border']};"
            f" border-radius: {sz[radius_key]}px; }}")


def make_card_block(title, *, parent=None):
    """令牌化分区卡：标题 + 竖排内容。返回 (card, layout)。

    三个 Tab 都要「一块带标题的分区」（目标 / 扫描参数 / 测速），各自重写一遍
    边框 + 圆角 + 边距的 QSS 只会互相漂移，故收敛到这里。
    """
    p, sz = theme_palette(), sizing()
    card = QtWidgets.QFrame(parent)
    card.setStyleSheet(card_qss(p, sz))
    lay = QtWidgets.QVBoxLayout(card)
    lay.setContentsMargins(sz["dialog_margin"] // 2, sz["radius_md"],
                           sz["dialog_margin"] // 2, sz["radius_md"])
    lay.setSpacing(sz["radius_xs"])
    if title:
        lay.addWidget(make_label(title, role="caption", parent=card))
    return card, lay


def _bar_qss(p, sz, color):
    return (f"QProgressBar {{ background: {p['bg_control']};"
            f" border: 1px solid {p['border']}; border-radius: {sz['radius_sm']}px;"
            f" text-align: center; font-size: {sz['font_size_xs']}px;"
            f" color: {p['text_secondary']}; }}"
            f"QProgressBar::chunk {{ background: {color};"
            f" border-radius: {sz['radius_sm']}px; }}")


def make_usage_bar(*, parent=None):
    """进度条。返回 QProgressBar，调用 `bar.set_percent(pct, text)` 刷新。

    QProgressBar 没有 `setText`，显示文字必须走 `setFormat()`（不含 `%p%` 时按
    字面量渲染），所以文案与数值分开传。
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


def add_chip(lay, text, kind, *, parent=None):
    """往胶囊行末尾（stretch 之前）加一枚 make_status_chip。"""
    lay.insertWidget(lay.count() - 1, make_status_chip(text, kind=kind,
                                                       parent=parent))


def reset_chips(lay):
    """清空胶囊行（保留末尾 stretch），旧胶囊立即 deleteLater。"""
    while lay.count() > 1:
        item = lay.takeAt(0)
        if item.widget() is not None:
            item.widget().deleteLater()



def confirm(parent, title, text, *, ok_text="确定", cancel_text="取消"):
    """二次确认弹窗。parent 为 None（无宿主窗口）时视为拒绝，绝不默认放行。"""
    if parent is None:
        return False
    box = MessageBox(title, text, parent)
    box.yesButton.setText(ok_text)
    box.cancelButton.setText(cancel_text)
    return bool(box.exec() == QtWidgets.QDialog.Accepted)


def notify(parent, title, content, *, error=False, duration=NOTIFY_MS):
    """右上角非阻塞提示（成功/失败都用它，避免自动刷新时反复弹模态框）。"""
    if parent is None:
        return
    (InfoBar.error if error else InfoBar.success)(
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


def summarize(results):
    """批量操作结果 → 「n/m 项成功」的汇总文案。results: [TargetResult, ...]"""
    total = len(results or [])
    ok = sum(1 for r in results if r is not None and r.ok)
    if total == 0:
        return "没有可操作的目标", True
    if ok == total:
        return f"全部 {total} 项已生效", True
    failed = [f"{getattr(r, 'name', '?')}"
              for r in (results or []) if r is not None and not r.ok]
    return f"{ok}/{total} 项成功，失败：{'、'.join(failed)}", False
