"""翻译模块页字幕栏：悬浮字幕开关 + 字号/透明度设置。"""
from core.qt_bootstrap import import_qt
from core.theme.tokens import theme_palette
from qfluentwidgets import BodyLabel, PushButton, Slider, SpinBox, SubtitleLabel

_, QtCore, QtGui, QtWidgets = import_qt()


class _SubtitlePanel(QtWidgets.QFrame):
    """字幕区卡片：显示悬浮字幕按钮 + 字号/透明度设置。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._subtitle = None
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self._build_ui()

    def _build_ui(self):
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(8)

        v.addWidget(SubtitleLabel("悬浮字幕", self))

        self._btn_subtitle = PushButton("显示悬浮字幕", self)
        self._btn_subtitle.clicked.connect(self._toggle_subtitle)
        v.addWidget(self._btn_subtitle)

        size_bar = QtWidgets.QHBoxLayout()
        size_bar.setSpacing(6)
        size_bar.addWidget(BodyLabel("字号", self))
        self._spin_size = SpinBox(self)
        self._spin_size.setRange(12, 48)
        self._spin_size.setValue(24)
        size_bar.addWidget(self._spin_size)
        v.addLayout(size_bar)

        op_bar = QtWidgets.QHBoxLayout()
        op_bar.setSpacing(6)
        op_bar.addWidget(BodyLabel("透明度", self))
        self._slider_op = Slider(QtCore.Qt.Horizontal, self)
        self._slider_op.setRange(50, 100)
        self._slider_op.setValue(90)
        op_bar.addWidget(self._slider_op)
        v.addLayout(op_bar)

        self._label_sub = BodyLabel("", self)
        self._label_sub.setWordWrap(True)
        p = theme_palette()
        self._label_sub.setStyleSheet(f"color: {p['text_secondary']};")
        v.addWidget(self._label_sub)
        v.addStretch(1)

        self._spin_size.valueChanged.connect(self._apply_settings)
        self._slider_op.valueChanged.connect(self._apply_settings)

    # ── 悬浮字幕开关 ──────────────────────────────────────────
    def _toggle_subtitle(self):
        if self._subtitle is not None:
            self._close_subtitle()
            return
        from .subtitle_widget import SubtitleWidget
        self._subtitle = SubtitleWidget()
        self._subtitle.set_opacity(self._slider_op.value() / 100.0)
        self._subtitle.set_font_size(self._spin_size.value())
        self._subtitle.show()
        self._btn_subtitle.setText("关闭悬浮字幕")
        self._label_sub.setText("字幕窗口已显示")

    def _close_subtitle(self):
        if self._subtitle is not None:
            try:
                self._subtitle.close()
            except RuntimeError:
                pass
            self._subtitle = None
        try:
            self._btn_subtitle.setText("显示悬浮字幕")
            self._label_sub.setText("")
        except RuntimeError:
            pass

    def _apply_settings(self):
        if self._subtitle is not None:
            try:
                self._subtitle.set_font_size(self._spin_size.value())
                self._subtitle.set_opacity(self._slider_op.value() / 100.0)
            except RuntimeError:
                pass

    def feed(self, original, translation):
        """语音识别结果 → 字幕显示。"""
        if self._subtitle is not None:
            try:
                self._subtitle.set_content(original, translation)
            except RuntimeError:
                pass

    def close_subtitle(self):
        self._close_subtitle()