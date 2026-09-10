"""RSS 行部件：_WrapRow/_HeadRow/_AutoRow 与 pill 样式。"""

import logging
import re

from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

from .text_utils import _rss_colors

logger = logging.getLogger("rss_aggregator")

_TITLE_FONT_PX = 10


class _WrapRow(QtWidgets.QWidget):
    """可换行的标题行：内部用 word-wrap QLabel，自适应行高，可点击。"""

    clicked = QtCore.Signal()

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(1, 1, 1, 1)
        lay.setSpacing(0)
        self.label = QtWidgets.QLabel(text)
        self.label.setObjectName("rssTitleLabel")
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(QtCore.Qt.NoTextInteraction)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        f = self.label.font()
        f.setPointSizeF(_TITLE_FONT_PX)
        self.label.setFont(f)
        lay.addWidget(self.label)
        self.label.installEventFilter(self)

    def eventFilter(self, obj, event):
        if (
            obj is self.label
            and event.type() == QtCore.QEvent.MouseButtonRelease
            and event.button() == QtCore.Qt.LeftButton
        ):
            self.clicked.emit()
        return super().eventFilter(obj, event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def text(self):
        return self.label.text()

    def setText(self, text):
        self.label.setText(text)

    def setStyleSheet(self, ss):
        self.label.setStyleSheet(ss.replace("QPushButton", "QLabel"))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        m = self.layout().contentsMargins()
        avail = max(width - m.left() - m.right() - 4, 40)
        return self.label.heightForWidth(avail) + m.top() + m.bottom() + 2


class _ElideLabel(QtWidgets.QLabel):
    """单行省略号标签：按控件宽度横向省略显示，text() 恒返回完整文本（供逻辑/tooltip 使用）。"""

    clicked = QtCore.Signal()

    def __init__(self, text="", parent=None):
        self._full = text or ""
        super().__init__("", parent)
        self.setWordWrap(False)
        self.setTextInteractionFlags(QtCore.Qt.NoTextInteraction)
        # Ignored：横向宽度交给布局 stretch 分配，sizeHint 不参与宽度计算
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        # 兼容垫片：与 _WrapRow.label 对齐，供消费者（如 home.py 双击打开链接）以
        # title_btn.label 访问本标签自身。
        self.label = self

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def setText(self, text):
        self._full = text or ""
        self._refresh()

    def text(self):
        return self._full

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self):
        w = self.width()
        if w > 0:
            super().setText(self.fontMetrics().elidedText(self._full, QtCore.Qt.ElideRight, w))
        else:
            super().setText(self._full)


class _HeadRow(QtWidgets.QWidget):
    """磁链聚合分组头：左侧单行省略标题(▸ 前缀)，右侧固定"来源计数"徽标(不换行、样式参考标签)。"""

    titleClicked = QtCore.Signal()
    badgeClicked = QtCore.Signal()
    headDoubleClicked = QtCore.Signal()
    checkboxToggled = QtCore.Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("rssHeadRow")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setAttribute(QtCore.Qt.WA_Hover, True)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(1, 1, 1, 1)
        lay.setSpacing(4)
        self.checkbox = QtWidgets.QCheckBox()
        lay.addWidget(self.checkbox)
        self.checkbox.toggled.connect(self.checkboxToggled)
        self._full_title = ""
        self.title_label = _ElideLabel("")
        self.title_label.setObjectName("rssHeadTitle")
        f = self.title_label.font()
        f.setPointSizeF(_TITLE_FONT_PX)
        self.title_label.setFont(f)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.count_label = QtWidgets.QLabel("")
        self.count_label.setObjectName("rssHeadCount")
        self.count_label.setWordWrap(False)
        self.count_label.setAlignment(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight)
        self.count_label.setSizePolicy(
            QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Preferred)
        lay.addWidget(self.title_label, 1)
        lay.addWidget(self.count_label, 0)
        self.title_label.installEventFilter(self)
        self.count_label.installEventFilter(self)

    def set_check_state(self, state):
        self.checkbox.blockSignals(True)
        self.checkbox.setCheckState(state)
        self.checkbox.blockSignals(False)

    def check_state(self):
        return self.checkbox.checkState()

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.MouseButtonDblClick and event.button() == QtCore.Qt.LeftButton:
            if obj in (self.title_label, self.count_label):
                self.headDoubleClicked.emit()
                return True
        if event.type() == QtCore.QEvent.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton:
            if obj is self.count_label:
                self.badgeClicked.emit()
                return True
            if obj is self.title_label:
                self.titleClicked.emit()
                return True
        return super().eventFilter(obj, event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.headDoubleClicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def setText(self, text):
        self._full_title = text or ""
        self.title_label.setText(self._full_title)
        # 完整标题并入 tooltip，避免展开前缀污染完整标题展示
        tip = self.toolTip()
        if self._full_title and ("\n" + self._full_title) not in tip and not tip.endswith(self._full_title):
            self.setToolTip((tip + "\n" if tip else "") + self._full_title)

    def text(self):
        return self._full_title

    def set_expanded(self, expanded):
        """切换展开/折叠前缀（▾/▸），不影响 _full_title 与 text()/tooltip。"""
        prefix = "▾ " if expanded else "▸ "
        self.title_label.setText(prefix + self._full_title)

    def set_count(self, text):
        self.count_label.setText(text)

    def setStyleSheet(self, ss):
        """ss 用 QPushButton#id 书写；转换为 QLabel 选择器后按 objectName 分派，合并同一标签的基础与 :hover 规则。
        #rssHeadRow 容器级规则直接应用 QSS（作用于分组头整行背景）。"""
        rules = {"#rssHeadTitle": [], "#rssHeadCount": [], "#rssHeadRow": []}
        for block in ss.split("}"):
            if "{" not in block:
                continue
            head, body = block.split("{", 1)
            sel = head.strip()
            if "#rssHeadTitle" in sel:
                rules["#rssHeadTitle"].append(sel.replace("QPushButton", "QLabel") + "{" + body + "}")
            elif "#rssHeadCount" in sel:
                rules["#rssHeadCount"].append(sel.replace("QPushButton", "QLabel") + "{" + body + "}")
            elif "#rssHeadRow" in sel:
                rules["#rssHeadRow"].append(sel + "{" + body + "}")
        if rules["#rssHeadTitle"]:
            self.title_label.setStyleSheet("".join(rules["#rssHeadTitle"]))
        if rules["#rssHeadCount"]:
            self.count_label.setStyleSheet("".join(rules["#rssHeadCount"]))
        if rules["#rssHeadRow"]:
            super().setStyleSheet("".join(rules["#rssHeadRow"]))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        m = self.layout().contentsMargins()
        spawn = (self.checkbox.sizeHint().width() + self.layout().spacing()
                 + self.count_label.sizeHint().width() + self.layout().spacing())
        avail = max(width - m.left() - m.right() - spawn, 40)
        return self.title_label.heightForWidth(avail) + m.top() + m.bottom() + 2


class _AutoRow(QtWidgets.QWidget):
    """列表条目行容器：把行高交给内部标题自适应（按可用宽度换行）。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._title = None
        self._thumb = None
        self.setObjectName("rssItemRow")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setAttribute(QtCore.Qt.WA_Hover, True)

    def bind_title(self, title_widget):
        self._title = title_widget

    def bind_thumb(self, thumb_widget):
        self._thumb = thumb_widget

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        if self._title is None:
            return max(self.sizeHint().height(), 24)
        m = self.layout().contentsMargins()
        spacer = 4
        for i in range(self.layout().count()):
            w = self.layout().itemAt(i).widget()
            if w is not None and w is not self._title:
                spacer += w.sizeHint().width() + self.layout().spacing()
        # 可用宽度必须扣除自身布局左右边距，否则按过宽宽度计算换行，
        # 行数偏少导致最后一行被截断（内容比框大）。
        avail = max(width - m.left() - m.right() - spacer, 40)
        h = self._title.heightForWidth(avail)
        if self._thumb is not None:
            h = max(h, self._thumb.sizeHint().height() + 4)
        # 返回高度必须加上自身布局上下边距，否则行 widget 比所需矮，
        # 多行内容上下被截断。
        return h + m.top() + m.bottom()


def _pill_style(bg, fg):
    """标签/类型药丸样式：圆角胶囊 + 对比色前景。"""
    return (
        f"QLabel {{ background: {bg}; color: {fg}; padding: 1px 8px; "
        "border-radius: 8px; font-size: 10px; font-weight: 600; }"
    )
