"""todo_notes 表格内联编辑器：_TodoItemDelegate。"""
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
        self.check_click_handler = None
        # 当前正在行内编辑的 (row, col)，编辑期间不在底层单元格重画文字，
        # 避免透过半透明编辑器漏出原文字（白字/描边）。
        self._editing_cell = None

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

    def paint(self, painter, option, index):
        if self._editing_cell == (index.row(), index.column()):
            # 行内编辑中：底层单元格只画背景/高亮，不画原文字，
            # 避免透过半透明编辑器漏出旧文字（白字/描边）。
            self.initStyleOption(option, index)
            option.text = ""
            style = option.widget.style() if option.widget else QtWidgets.QApplication.style()
            style.drawControl(QtWidgets.QStyle.CE_ItemViewItem, option, painter, option.widget)
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
        return editor

    def createEditor(self, parent, option, index):
        col = index.column()
        if col == COL_CONTENT:  # 内容：多行编辑
            editor = QtWidgets.QPlainTextEdit(parent)
            editor.setFrameStyle(QtWidgets.QFrame.NoFrame)
            return editor
        if col == COL_CATEGORY:  # 类别
            editor = QtWidgets.QComboBox(parent)
            editor.setEditable(True)
            editor.addItem("")
            for c in get_categories():
                editor.addItem(c)
            editor.lineEdit().setFrame(False)
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
