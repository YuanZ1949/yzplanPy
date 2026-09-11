"""悬浮字幕窗口：置顶无边框半透明，实时显示原文+译文。"""
from core.qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

_MAX_PAIRS = 4


class SubtitleWidget(QtWidgets.QWidget):
    """实时翻译悬浮字幕：原文（灰小字）+ 译文（白大字），可拖动/右键菜单。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setWindowTitle("悬浮字幕")
        self._pairs = []
        self._font_size = 24
        self._opacity = 0.9
        self._drag_pos = None
        self._build_ui()
        self.resize(420, 140)

    def _build_ui(self):
        self._label_orig = QtWidgets.QLabel(self)
        self._label_orig.setWordWrap(True)
        self._label_orig.setStyleSheet("color: rgba(200, 200, 200, 220);")
        self._label_trans = QtWidgets.QLabel(self)
        self._label_trans.setWordWrap(True)
        self._label_trans.setStyleSheet("color: white;")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(4)
        lay.addWidget(self._label_orig)
        lay.addWidget(self._label_trans)
        self._apply_font()

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 60), 1))
        p.setBrush(QtGui.QColor(20, 20, 20, int(255 * self._opacity)))
        p.drawRoundedRect(rect, 10, 10)

    def set_content(self, original, translation):
        """更新字幕内容：新内容显示在底部，旧内容上移（保留最近 N 对）。"""
        self._pairs.append((original, translation))
        if len(self._pairs) > _MAX_PAIRS:
            self._pairs = self._pairs[-_MAX_PAIRS:]
        self._label_orig.setText(original)
        self._label_trans.setText(translation)

    def set_font_size(self, size):
        self._font_size = max(12, min(48, int(size)))
        self._apply_font()

    def _apply_font(self):
        f_orig = QtGui.QFont(self.font())
        f_orig.setPointSize(max(9, self._font_size - 8))
        self._label_orig.setFont(f_orig)
        f_trans = QtGui.QFont(self.font())
        f_trans.setPointSize(self._font_size)
        f_trans.setBold(True)
        self._label_trans.setFont(f_trans)

    def set_opacity(self, value):
        self._opacity = max(0.5, min(1.0, float(value)))
        self.update()

    # ── 拖动与右键菜单 ─────────────────────────────────────────
    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._drag_pos = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft())
            event.accept()
        elif event.button() == QtCore.Qt.RightButton:
            self._show_menu(event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & QtCore.Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def _show_menu(self, pos):
        menu = QtWidgets.QMenu(self)
        menu.addAction("关闭", self.close)
        menu.addAction("字号 +", lambda: self.set_font_size(self._font_size + 2))
        menu.addAction("字号 -", lambda: self.set_font_size(self._font_size - 2))
        sub = menu.addMenu("透明度")
        sub.addAction("更透明", lambda: self.set_opacity(self._opacity - 0.1))
        sub.addAction("更不透明", lambda: self.set_opacity(self._opacity + 0.1))
        menu.exec(pos)