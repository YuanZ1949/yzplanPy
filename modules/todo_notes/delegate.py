"""todo_notes 表格内联编辑器：_TodoItemDelegate。"""
from typing import Callable
from core.qt_bootstrap import import_qt
_, QtCore, QtGui, QtWidgets = import_qt()
from core.theme.tokens import rgba_to_qcolor, sizing, theme_palette
from .constants import (CUSTOM_OPTION_DATA, CUSTOM_OPTION_LABEL,
                        COL_CATEGORY, COL_CHECK, COL_CONTENT, COL_PRIORITY,
                        COL_STATUS, CONTENT_SAFE_MAX_LINES, content_editor_font,
                        content_row_height,
                        category_color, editor_qss, PRIORITY_LABELS,
                        priority_color, status_color)
from ..todo_store import get_categories, get_or_create_status, get_statuses


# 选项列（类别/优先级/状态）：失焦时由 delegate 画「贴文字的彩色胶囊」（旧观感），
# 聚焦时才让位给常驻 combo 自己的编辑器外观（保留手输新值能力）。
_BADGE_COLS = (COL_CATEGORY, COL_PRIORITY, COL_STATUS)


def _widget_focused(w):
    """常驻控件（或其内嵌 QLineEdit）是否持有焦点。控件已销毁时安全返回 False。"""
    try:
        if w.hasFocus():
            return True
        le = w.lineEdit() if hasattr(w, "lineEdit") else None
        return bool(le is not None and le.hasFocus())
    except RuntimeError:
        return False


class _TodoItemDelegate(QtWidgets.QStyledItemDelegate):
    """便签表格列内联编辑器：类别/优先级/状态用下拉框，标题/内容用不全选的多行/单行框。"""

    def __init__(self, table):
        super().__init__(table)
        self.table = table
        # 复选框列增强点击处理回调：signature:
        #   handler(row, ctrl, shift)
        self.check_click_handler: Callable[[int, bool, bool], bool] | None = None
        # 行内编辑结束回调（destroyEditor 末尾调用）：page_widget 用它复位 _editing 守卫
        self.on_editing_finished: Callable[[], None] | None = None
        # 状态 id -> status dict 缓存（paint 每格调用，避免每次查库）
        self._status_cache: dict | None = None
        # 类别名 -> 颜色缓存（paint 每格调用，避免每次查库/查色板）
        self._category_color_cache: dict | None = None

    def _status_map(self):
        """状态 id -> status dict（缓存，页面刷新时失效）。"""
        if self._status_cache is None:
            self._status_cache = {s["id"]: s for s in get_statuses()}
        return self._status_cache

    def _category_color_of(self, category):
        """类别色（缓存）：存储色优先，回落 todo_option_palette 按序号取色。"""
        if not category:
            return None
        if self._category_color_cache is None:
            cats = get_categories()
            self._category_color_cache = {
                c: category_color(c, index=i) for i, c in enumerate(cats)
            }
        return self._category_color_cache.get(category)

    def invalidate_status_cache(self):
        """状态/类别颜色缓存失效（页面 refresh 后调用，反映新增/改色状态）。"""
        self._status_cache = None
        self._category_color_cache = None

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
        return content_row_height(text, width)

    def sizeHint(self, option, index):
        base = super().sizeHint(option, index)
        if index.column() == COL_CONTENT:
            h = self._content_height(option, index)
            return QtCore.QSize(max(base.width(), 40), h)
        return base

    def updateEditorGeometry(self, editor, option, index):
        """让内容列编辑器覆盖（已展开的）单元格/行高矩形，避免编辑器过小。"""
        if index.column() == COL_CONTENT:
            editor.setGeometry(option.rect)
        else:
            super().updateEditorGeometry(editor, option, index)

    def paint(self, painter, option, index):
        # 已完成行：整行特别浅的浅绿色背景（选中行由后续 CE_ItemViewItem
        # 正常覆盖高亮，selected 优先，浅绿不盖过 selection）
        done = False
        sid = index.sibling(index.row(), COL_STATUS).data(QtCore.Qt.UserRole)
        if sid is not None:
            st = self._status_map().get(sid)
            done = bool(st and st["is_done_like"])
        if done:
            _p = theme_palette()
            painter.fillRect(option.rect, rgba_to_qcolor(_p["todo_done_bg"]))
        # 整行统一 hover 反馈（取代 QSS 单格 ::item:hover 边框）：鼠标所在行的
        # 所有单元格画同一块柔色背景；selected 行由选中背景覆盖，不叠加。
        if getattr(self.table, "_hover_row", -1) == index.row() \
                and not (option.state & QtWidgets.QStyle.State_Selected):
            painter.fillRect(option.rect,
                             rgba_to_qcolor(theme_palette()["todo_item_hover_bg"]))
        # 该格有常驻编辑器覆盖：只画背景（done/hover/selected），内容由控件自身绘制。
        # 控件背景已透明，若此处再画徽章/文本会从编辑器后面透出形成重影。
        # 例外：类别/优先级/状态三列在控件失焦时保持「旧观感」——控件完全隐形，
        # 由下面的徽章分支画贴文字的彩色胶囊；聚焦时才让位给控件自己的编辑器外观。
        w = self.table.cellWidget(index.row(), index.column())
        if w is not None and not (
                index.column() in _BADGE_COLS and not _widget_focused(w)):
            self.initStyleOption(option, index)
            option.text = ""
            style = option.widget.style() if option.widget else QtWidgets.QApplication.style()
            style.drawControl(QtWidgets.QStyle.CE_ItemViewItem, option, painter, option.widget)
            return
        # 复选框列：自绘居中圆角复选框（去掉默认指示器右侧的空框）。
        # 先按 CE_ItemViewItem 画背景（保持 hover/selected），再居中画 14px 复选框。
        if index.column() == COL_CHECK:
            self.initStyleOption(option, index)
            option.text = ""
            # 关键：否则 Qt 仍按 CheckStateRole 画默认指示器
            option.features &= ~QtWidgets.QStyleOptionViewItem.HasCheckIndicator
            style = option.widget.style() if option.widget else QtWidgets.QApplication.style()
            style.drawControl(QtWidgets.QStyle.CE_ItemViewItem, option, painter, option.widget)
            _p = theme_palette()
            _sz = sizing()
            size = _sz["todo_check_size"]          # 14 (scaled)
            radius = _sz["todo_check_radius"]      # 3 (scaled)
            center = option.rect.center()
            rect = QtCore.QRectF(center.x() - size / 2, center.y() - size / 2, size, size)
            checked = index.data(QtCore.Qt.CheckStateRole) == QtCore.Qt.Checked.value
            painter.save()
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            if checked:
                painter.setBrush(QtGui.QBrush(QtGui.QColor(_p["accent"])))
                painter.setPen(QtCore.Qt.NoPen)
                painter.drawRoundedRect(rect, radius, radius)
                # 白色 2px 对勾 polyline（相对坐标）
                pen = QtGui.QPen(QtGui.QColor("white"), 2)
                pen.setCapStyle(QtCore.Qt.RoundCap)
                pen.setJoinStyle(QtCore.Qt.RoundJoin)
                painter.setPen(pen)
                pts = [rect.topLeft() + QtCore.QPointF(rect.width() * fx, rect.height() * fy)
                       for fx, fy in ((0.22, 0.55), (0.45, 0.75), (0.78, 0.35))]
                painter.drawPolyline(QtGui.QPolygonF(pts))
            else:
                painter.setBrush(QtCore.Qt.NoBrush)
                painter.setPen(QtGui.QPen(QtGui.QColor(_p["border_strong"]), 1))
                painter.drawRoundedRect(rect, radius, radius)
            painter.restore()
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
            _p = theme_palette()
            if index.column() == COL_PRIORITY:
                val = index.data(QtCore.Qt.UserRole)
                bg = QtGui.QColor(priority_color(val))
            elif index.column() == COL_STATUS:
                sid = index.data(QtCore.Qt.UserRole)
                st = self._status_map().get(sid)
                bg = QtGui.QColor(status_color(st))
            else:  # COL_CATEGORY
                bg = QtGui.QColor(self._category_color_of(text) or _p["todo_category"])
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

    def _make_content_editor(self, parent, row):
        """创建内容列编辑器（常驻/行内共用）：多行、无滚动条、自动换行、无边框。"""
        editor = QtWidgets.QPlainTextEdit(parent)
        editor.setFrameStyle(QtWidgets.QFrame.NoFrame)
        # 无内部滚动条：编辑器随内容自适应扩大（grow-not-scroll）
        editor.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        editor.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        # 自动换行（单词边界或任意处）：与显示态一致，避免横向滚动
        editor.setWordWrapMode(QtGui.QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        # 与行高公式同源字体：QSS 会把编辑器字体固定下来，用 table.font() 会
        # 在 polish 后与公式字体漂移（UI 变体行距 15 vs 应用字体 16）。
        editor.setFont(content_editor_font())
        editor.setStyleSheet(editor_qss())
        # 文档边距与行高公式同源（令牌驱动），避免公式假设与真实渲染漂移
        editor.document().setDocumentMargin(sizing()["todo_editor_doc_margin"])
        # 编辑期间行高随换行实时自适应：统一公式 lines×lineSpacing+18（与显示态一致）
        # 不用 lambda 捕获 editor —— refresh() 可能在 textChanged 信号排队时销毁 editor，
        # 导致 lambda 调用已释放的 C++ 对象 → 0xC0000005 崩溃。
        # 改用 _on_text_changed 通过 self.sender() 安全获取 editor。
        editor._editing_row = row
        editor.textChanged.connect(self._on_text_changed)
        return editor

    def createEditor(self, parent, option, index):
        # 行内编辑期间暂停函数采样器：sys.setprofile 钩子会对每次按键/重绘
        # 都产生采样开销，编辑结束（destroyEditor）时恢复。
        try:
            from core.perf import profile_pause
            profile_pause()
        except Exception:
            pass
        col = index.column()
        if col == COL_CHECK:  # 复选框列：不创建编辑器（无多余可编辑区域）
            return None
        if col == COL_CONTENT:  # 内容：多行编辑
            return self._make_content_editor(parent, index.row())
        if col == COL_CATEGORY:  # 类别
            editor = QtWidgets.QComboBox(parent)
            editor.setEditable(True)
            editor.addItem("")
            for c in get_categories():
                editor.addItem(c)
            editor.addItem(CUSTOM_OPTION_LABEL, CUSTOM_OPTION_DATA)
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
            editor = QtWidgets.QComboBox(parent)
            editor.setEditable(True)
            for s in get_statuses():
                editor.addItem(s["name"], s["id"])
            editor.addItem(CUSTOM_OPTION_LABEL, CUSTOM_OPTION_DATA)
            editor.lineEdit().setFrame(False)
            self._adapt_combo_popup(editor)
            editor.activated.connect(lambda *_: self._commit_current())
            return editor
        return super().createEditor(parent, option, index)

    def setEditorData(self, editor, index):
        col = index.column()
        if col == COL_CONTENT:
            editor.setPlainText(index.data() or "")
            # 编辑器打开即按真实文本展开行高并垂直居中（createEditor 阶段文本为空，
            # 仅靠 textChanged 不够；setEditorData 才拿到真实文本）
            self._update_editing_row_height(editor, index.row())
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
            sid = index.data(QtCore.Qt.UserRole)
            for i in range(editor.count()):
                if editor.itemData(i) == sid:
                    editor.setCurrentIndex(i)
                    break
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
            if editor.currentData() == CUSTOM_OPTION_DATA:
                # 「自定义…」哨兵：未填新名则不落库（编辑态输入了新名则走文本提交）
                if text == CUSTOM_OPTION_LABEL or not text:
                    return
            if item is not None:
                item.setText(text)
            else:
                model.setData(index, text)
        elif col == COL_PRIORITY:
            val = editor.currentData()
            if item is not None:
                item.setData(QtCore.Qt.UserRole, val)
                item.setText(PRIORITY_LABELS.get(val, "?"))
                item.setForeground(QtGui.QColor(priority_color(val)))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
        elif col == COL_STATUS:
            sid = editor.currentData()
            text = (editor.currentText() or "").strip()
            if sid == CUSTOM_OPTION_DATA or not sid:
                # 「自定义…」哨兵：未填新名则不落库；输入了新名则按文本新建状态
                if text == CUSTOM_OPTION_LABEL or not text:
                    return
                statuses = {s["name"]: s for s in get_statuses()}
                st = statuses.get(text)
                if st is None:
                    sid = get_or_create_status(text)
                    st = {"id": sid, "name": text, "color": None}
            else:
                st = self._status_map().get(sid)
            if item is not None:
                item.setData(QtCore.Qt.UserRole, sid)
                item.setText(st["name"] if st else "待办")
                item.setForeground(QtGui.QColor(status_color(st)))
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
            self._update_editing_row_height(editor, row)
        except Exception:
            pass

    def _update_editing_row_height(self, editor, row):
        """编辑内容时行高随换行实时自适应：与显示态共用 content_row_height 公式
        （含 CONTENT_FIT_SLACK，见 constants），编辑器填满单元格
        （viewportMargins 全 0），滚动条恒关。"""
        try:
            text = editor.toPlainText()
            try:
                col_w = self.table.columnWidth(COL_CONTENT)
            except Exception:
                col_w = 200
            ideal_h = content_row_height(text, col_w)
            # 严格贴合内容所需高度：不得用 defaultSectionSize() 兜底，
            # 否则当内容高度小于默认行高时行会被抬高，底部多出一整行空白。
            self.table.setRowHeight(row, ideal_h)
            # 编辑器内滚动条恒为关（grow-not-scroll）
            editor.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            # 编辑器填满单元格：无内边距（行高已含 chrome 高度）
            editor.setViewportMargins(0, 0, 0, 0)
        except Exception:
            pass

    def _restore_content_row_height(self, index):
        """编辑结束后把内容行恢复为正常折行显示高度（最多 CONTENT_SAFE_MAX_LINES 行），而非默认单行。"""
        try:
            text = index.data() or ""
            try:
                col_w = self.table.columnWidth(COL_CONTENT)
            except Exception:
                col_w = 200
            self.table.setRowHeight(
                index.row(), content_row_height(text, col_w))
        except Exception:
            pass

    def destroyEditor(self, editor, index):
        # 内容多行编辑结束后，把行高恢复为内容折行的正常显示高度（≤ CONTENT_SAFE_MAX_LINES 行），
        # 而不是恢复为默认单行，避免“选择后行高瞬间回到单行”。
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
