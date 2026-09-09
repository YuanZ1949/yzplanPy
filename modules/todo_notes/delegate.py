"""todo_notes 表格内联编辑器：_TodoItemDelegate。"""
from typing import Callable
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()
from .constants import (COL_CATEGORY, COL_CHECK, COL_CONTENT, COL_PRIORITY,
                        COL_STATUS, CONTENT_COL_PAD, CONTENT_MAX_LINES,
                        PRIORITY_COLORS, PRIORITY_LABELS)
from ..todo_store import get_categories
class _TodoItemDelegate(QtWidgets.QStyledItemDelegate):
    """便签表格列内联编辑器：类别/优先级/状态用下拉框，标题/内容用不全选的多行/单行框。"""

    def __init__(self, table):
        super().__init__(table)
        self.table = table
        # 复选框列增强点击处理回调：signature:
        #   handler(row, ctrl, shift)
        self.check_click_handler: Callable[[int, bool, bool], bool] | None = None
        # 当前正在行内编辑的 (row, col)，编辑期间不在底层单元格重画文字，
        # 避免透过半透明编辑器漏出原文字（白字/描边）。
        self._editing_cell: tuple[int, int] | None = None
        # 行内编辑结束回调（destroyEditor 末尾调用）：page_widget 用它复位 _editing 守卫
        self.on_editing_finished: Callable[[], None] | None = None

    def editorEvent(self, event, model, option, index):
        """复选框列支持普通点击/ctrl/shift 多选，并与表格行选择联动。"""
        if index.column() == COL_CHECK and event.type() == QtCore.QEvent.MouseButtonRelease \
                and event.button() == QtCore.Qt.LeftButton:
            modifier = event.modifiers()
            ctrl = bool(modifier & QtCore.Qt.ControlModifier)
            shift = bool(modifier & QtCore.Qt.ShiftModifier)
            if self.check_click_handler is not None:
                self.check_click_handler(index.row(), ctrl, shift)
                return True
        return super().editorEvent(event, model, option, index)

    @staticmethod
    def _wrap_lines(text, font_metrics, width):
        """按给定宽度把文本拆成可视行（含换行符），返回行列表。"""
        if not text:
            return [""]
        lines = []
        for para in str(text).split("\n"):
            if para == "":
                lines.append("")
                continue
            split = []
            line = ""
            for ch in para:
                if font_metrics.horizontalAdvance(line + ch) > width:
                    if line:
                        split.append(line)
                        line = ch
                    else:  # 单个字符也超宽：直接换
                        split.append(ch)
                else:
                    line += ch
            split.append(line)
            lines.extend(split)
        return lines

    def _content_height(self, option, index):
        text = index.data() or ""
        try:
            width = self.table.columnWidth(COL_CONTENT)
        except Exception:
            width = 200
        fm = option.fontMetrics
        wrapped = len(self._wrap_lines(text, fm, width - CONTENT_COL_PAD))
        lines = min(max(1, wrapped), CONTENT_MAX_LINES)     # 表格内最多显示前几行
        return lines * (fm.lineSpacing() + 2) + 6

    def sizeHint(self, option, index):
        base = super().sizeHint(option, index)
        if index.column() == COL_CONTENT:
            h = self._content_height(option, index)
            return QtCore.QSize(max(base.width(), 40), h)
        return base

    def updateEditorGeometry(self, editor, option, index):
        """让内容列编辑器覆盖（已展开的）单元格/行高矩形，避免编辑器过小。"""
        if (index.column() == COL_CONTENT
                and self._editing_cell is not None
                and self._editing_cell[0] == index.row()):
            editor.setGeometry(option.rect)
        else:
            super().updateEditorGeometry(editor, option, index)

    def paint(self, painter, option, index):
        if self._editing_cell == (index.row(), index.column()):
            # 行内编辑中：底层单元格只画背景/高亮，不画原文字，
            # 避免透过半透明编辑器漏出旧文字（白字/描边）。
            self.initStyleOption(option, index)
            option.text = ""
            style = option.widget.style() if option.widget else QtWidgets.QApplication.style()
            style.drawControl(QtWidgets.QStyle.CE_ItemViewItem, option, painter, option.widget)
            return
        # 彩色标签徽章：优先级 / 状态 / 类别
        if index.column() in (COL_PRIORITY, COL_STATUS, COL_CATEGORY):
            self.initStyleOption(option, index)
            option.text = ""
            style = option.widget.style() if option.widget else QtWidgets.QApplication.style()
            style.drawControl(QtWidgets.QStyle.CE_ItemViewItem, option, painter, option.widget)
            text = index.data() or ""
            if not text:
                return
            # 确定徽章底色
            if index.column() == COL_PRIORITY:
                val = index.data(QtCore.Qt.UserRole)
                bg = QtGui.QColor(PRIORITY_COLORS.get(val, "#888"))
            elif index.column() == COL_STATUS:
                done = index.data(QtCore.Qt.UserRole)
                bg = QtGui.QColor("#27ae60" if done else "#3498db")
            else:  # COL_CATEGORY
                bg = QtGui.QColor("#8e44ad")
            fm = option.fontMetrics
            text_w = fm.horizontalAdvance(text)
            text_h = fm.height()
            pad_x, pad_y = 8, 3
            badge_w = text_w + pad_x * 2
            badge_h = text_h + pad_y * 2
            badge_x = option.rect.left() + (option.rect.width() - badge_w) / 2
            badge_y = option.rect.top() + (option.rect.height() - badge_h) / 2
            badge_rect = QtCore.QRectF(badge_x, badge_y, badge_w, badge_h)
            painter.save()
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            painter.setBrush(QtGui.QBrush(bg))
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawRoundedRect(badge_rect, 4, 4)
            painter.setPen(QtGui.QColor("white"))
            painter.setFont(option.font)
            text_rect = QtCore.QRectF(badge_x + pad_x, badge_y + pad_y, text_w, text_h)
            painter.drawText(text_rect, int(QtCore.Qt.AlignCenter), text)
            painter.restore()
            return
        if index.column() != COL_CONTENT:
            return super().paint(painter, option, index)
        self.initStyleOption(option, index)
        text = index.data() or ""
        option.text = ""
        style = option.widget.style() if option.widget else QtWidgets.QApplication.style()
        style.drawControl(QtWidgets.QStyle.CE_ItemViewItem, option, painter, option.widget)
        # 用 word-wrap 绘制多行文本，避免省略
        if text:
            rect = option.rect.adjusted(4, 2, -4, -2)
            painter.save()
            painter.setFont(option.font)
            painter.setPen(option.palette.color(
                QtGui.QPalette.HighlightedText if option.state & QtWidgets.QStyle.State_Selected
                else QtGui.QPalette.Text))
            painter.setClipRect(rect)
            painter.drawText(rect,
                             int(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop | QtCore.Qt.TextWordWrap),
                             text)
            painter.restore()

    def _make_combo(self, parent, rows, default_index=0):
        editor = QtWidgets.QComboBox(parent)
        for label, data in rows:
            editor.addItem(label, data)
        editor.setCurrentIndex(default_index)
        editor.setFrame(False)
        self._adapt_combo_popup(editor)
        return editor

    def _adapt_combo_popup(self, editor):
        """下拉弹出列表按内容自适应加宽：弹出视图最小宽度 = 最宽项文字 + 内边距。
        空列表（无任何项）时跳过，避免对空视图设置无意义宽度。"""
        try:
            fm = editor.fontMetrics()
            max_w = 0
            for i in range(editor.count()):
                max_w = max(max_w, fm.horizontalAdvance(editor.itemText(i)))
            if max_w > 0:
                editor.view().setMinimumWidth(max_w + 24)
        except Exception:
            pass

    def createEditor(self, parent, option, index):
        # 行内编辑期间暂停函数采样器：sys.setprofile 钩子会对每次按键/重绘
        # 都产生采样开销，编辑结束（destroyEditor）时恢复。
        try:
            from core.perf import profile_pause
            profile_pause()
        except Exception:
            pass
        col = index.column()
        if col == COL_CONTENT:  # 内容：多行编辑
            editor = QtWidgets.QPlainTextEdit(parent)
            editor.setFrameStyle(QtWidgets.QFrame.NoFrame)
            # 无内部滚动条：编辑器随内容自适应扩大（grow-not-scroll）
            editor.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            editor.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            # 编辑期间行高随换行实时自适应（不受 CONTENT_MAX_LINES 上限，安全上限 200 行）
            # 不用 lambda 捕获 editor —— refresh() 可能在 textChanged 信号排队时销毁 editor，
            # 导致 lambda 调用已释放的 C++ 对象 → 0xC0000005 崩溃。
            # 改用 _on_text_changed 通过 self.sender() 安全获取 editor。
            editor._editing_row = index.row()
            editor.textChanged.connect(self._on_text_changed)
            return editor
        if col == COL_CATEGORY:  # 类别
            editor = QtWidgets.QComboBox(parent)
            editor.setEditable(True)
            editor.addItem("")
            for c in get_categories():
                editor.addItem(c)
            editor.lineEdit().setFrame(False)
            self._adapt_combo_popup(editor)
            editor.activated.connect(lambda *_: self._commit_current())
            return editor
        if col == COL_PRIORITY:  # 优先级
            labels = [(PRIORITY_LABELS[i], i) for i in (0, 1, 2, 3)]
            editor = self._make_combo(parent, labels)
            editor.activated.connect(lambda *_: self._commit_current())
            return editor
        if col == COL_STATUS:  # 状态
            editor = self._make_combo(parent, [("待办", 0), ("已完成", 1)])
            editor.activated.connect(lambda *_: self._commit_current())
            return editor
        return super().createEditor(parent, option, index)

    def setEditorData(self, editor, index):
        col = index.column()
        if col == COL_CONTENT:
            editor.setPlainText(index.data() or "")
            return
        if col == COL_CATEGORY:
            i = editor.findText(index.data() or "")
            editor.setCurrentIndex(i if i >= 0 else 0)
        elif col == COL_PRIORITY:
            val = index.data(QtCore.Qt.UserRole)
            for i in range(editor.count()):
                if editor.itemData(i) == val:
                    editor.setCurrentIndex(i)
                    break
        elif col == COL_STATUS:
            done = index.data(QtCore.Qt.UserRole)
            editor.setCurrentIndex(1 if done else 0)
        else:
            super().setEditorData(editor, index)
            # 不在进入编辑时全选高亮（避免文字看不清），光标移到末尾
            le = getattr(editor, "lineEdit", None)
            target = le() if le else editor
            if isinstance(target, QtWidgets.QLineEdit):
                target.deselect()

    def setModelData(self, editor, model, index):
        col = index.column()
        item = self.table.item(index.row(), index.column())
        if col == COL_CONTENT:
            text = editor.toPlainText().strip()
            if item is not None:
                item.setText(text)
            else:
                model.setData(index, text)
            # 内容提交后立即重绘单元格，清除残留的旧文字描边/轮廓（ghost）
            try:
                self.table.viewport().update()
            except Exception:
                pass
        elif col == COL_CATEGORY:
            text = (editor.currentText() or "").strip()
            if item is not None:
                item.setText(text)
            else:
                model.setData(index, text)
        elif col == COL_PRIORITY:
            val = editor.currentData()
            if item is not None:
                item.setData(QtCore.Qt.UserRole, val)
                item.setText(PRIORITY_LABELS.get(val, "?"))
                item.setForeground(QtGui.QColor(PRIORITY_COLORS.get(val, "#888")))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
        elif col == COL_STATUS:
            val = editor.currentData()
            if item is not None:
                item.setData(QtCore.Qt.UserRole, val)
                item.setText("已完成" if val else "待办")
                item.setForeground(QtGui.QColor("#27ae60" if val else "#3498db"))
        else:
            super().setModelData(editor, model, index)

    def _commit_current(self):
        try:
            self.commitData.emit(self.sender())
        except Exception:
            pass

    def _on_text_changed(self):
        """textChanged 的安全处理：通过 self.sender() 获取编辑器，绝不捕获 editor 对象。

        refresh() 可能在信号排队时销毁编辑器（setRowCount），此时 Qt 会在销毁期间
        清空 sender()，返回 None —— 直接返回，避免对已释放 C++ 对象调用导致 0xC0000005。
        """
        try:
            editor = self.sender()
            if editor is None:
                return
            row = getattr(editor, "_editing_row", None)
            if row is None:
                return
            # 若当前有行内编辑且不是本编辑器所在行，说明是来自已销毁/过期编辑器的残留信号
            if self._editing_cell is not None and self._editing_cell[0] != row:
                return
            self._update_editing_row_height(editor, row)
        except Exception:
            pass

    def _update_editing_row_height(self, editor, row):
        """编辑内容时行高随换行实时自适应：不受 CONTENT_MAX_LINES 显示上限，
        让用户能看到正在编辑的全部内容；安全上限 200 行防止极端文本撑爆表格。

        高度公式：lines × lineSpacing + CSS padding (5px×2) + documentMargin (4px×2) = +18。
        仅当内容超出表格视口时才启用编辑器内滚动条（task 7）。"""
        try:
            text = editor.toPlainText()
            fm = editor.fontMetrics()
            try:
                width = self.table.columnWidth(COL_CONTENT) - CONTENT_COL_PAD
            except Exception:
                width = 200
            wrapped = len(self._wrap_lines(text, fm, max(10, width)))
            lines = min(max(1, wrapped), 200)
            # 行高 = 文本行高合计 + QSS padding (5px×2) + documentMargin (4px×2)
            ideal_h = lines * fm.lineSpacing() + 18
            # 仅当内容超出表格视口时才启用编辑器内滚动条（自适应优先于滚动）
            viewport_h = self.table.viewport().height()
            default_h = self.table.verticalHeader().defaultSectionSize()
            if ideal_h > viewport_h:
                editor.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
                self.table.setRowHeight(row, max(viewport_h, default_h))
            else:
                editor.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
                self.table.setRowHeight(row, max(ideal_h, default_h))
        except Exception:
            pass

    def _restore_content_row_height(self, index):
        """编辑结束后把内容行恢复为正常折行显示高度（最多 CONTENT_MAX_LINES 行），而非默认单行。"""
        try:
            text = index.data() or ""
            fm = self.table.fontMetrics()
            try:
                width = self.table.columnWidth(COL_CONTENT) - CONTENT_COL_PAD
            except Exception:
                width = 200
            wrapped = len(self._wrap_lines(text, fm, max(10, width)))
            lines = min(max(1, wrapped), CONTENT_MAX_LINES)
            self.table.setRowHeight(index.row(), lines * (fm.lineSpacing() + 2) + 6)
        except Exception:
            pass

    def destroyEditor(self, editor, index):
        # 内容多行编辑结束后，把行高恢复为内容折行的正常显示高度（≤ CONTENT_MAX_LINES 行），
        # 而不是恢复为默认单行，避免“选择后行高瞬间回到单行”。
        self._editing_cell = None
        if index.column() == COL_CONTENT:
            self._restore_content_row_height(index)
        super().destroyEditor(editor, index)
        # 编辑结束：恢复被 createEditor 暂停的函数采样器（若暂停前在运行）。
        try:
            from core.perf import profile_resume
            profile_resume()
        except Exception:
            pass
        # 编辑结束：通知 page_widget 复位 _editing 守卫（refresh 恢复可用）
        if self.on_editing_finished is not None:
            try:
                self.on_editing_finished()
            except Exception:
                pass
