"""translator 主页卡片：快捷翻译 + 语音识别入口。"""
from core.qt_bootstrap import import_qt
from qfluentwidgets import BodyLabel, ComboBox, PrimaryPushButton, PushButton, SubtitleLabel

_, QtCore, QtGui, QtWidgets = import_qt()

from .translator_core import translate_text, LANGUAGES


class _HomeWidget(QtWidgets.QWidget):
    """主页快捷翻译卡片：输入→翻译→结果 + 语音识别开关。"""

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self._owner = owner
        self._recognizer = None
        self.setMinimumSize(260, 250)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        title = SubtitleLabel("翻译工具", self)
        lay.addWidget(title)

        self._edit_src = QtWidgets.QPlainTextEdit(self)
        self._edit_src.setPlaceholderText("输入要翻译的文字...")
        self._edit_src.setMaximumHeight(64)
        lay.addWidget(self._edit_src)

        lang_bar = QtWidgets.QHBoxLayout()
        lang_bar.setSpacing(8)
        self._combo_src = ComboBox(self)
        self._combo_dst = ComboBox(self)
        for name, code in LANGUAGES:
            self._combo_src.addItem(name, userData=code)
            self._combo_dst.addItem(name, userData=code)
        self._combo_dst.setCurrentIndex(1)  # 默认目标：中文
        lang_bar.addWidget(self._combo_src, 1)
        lang_bar.addWidget(self._combo_dst, 1)
        lay.addLayout(lang_bar)

        btn_bar = QtWidgets.QHBoxLayout()
        btn_bar.setSpacing(8)
        self._btn_translate = PrimaryPushButton("翻译", self)
        self._btn_translate.clicked.connect(self._do_translate)
        btn_bar.addWidget(self._btn_translate)
        self._btn_speech = PushButton("开始语音识别", self)
        self._btn_speech.clicked.connect(self._toggle_speech)
        btn_bar.addWidget(self._btn_speech)
        btn_bar.addStretch(1)
        lay.addLayout(btn_bar)

        self._edit_result = QtWidgets.QPlainTextEdit(self)
        self._edit_result.setReadOnly(True)
        self._edit_result.setMaximumHeight(64)
        lay.addWidget(self._edit_result)

        self._label_speech = BodyLabel("", self)
        self._label_speech.setStyleSheet("color: #888;")
        lay.addWidget(self._label_speech)

        link = QtWidgets.QLabel(
            '<a href="#" style="color: #1a73e8;">打开完整页面</a>', self)
        link.setOpenExternalLinks(False)
        link.linkActivated.connect(self._open_page)
        lay.addWidget(link, 0, QtCore.Qt.AlignRight)

        self.destroyed.connect(self._cleanup)

    def _cleanup(self):
        if self._recognizer is not None:
            try:
                self._recognizer.stop()
            except Exception:
                pass

    def _do_translate(self):
        text = self._edit_src.toPlainText().strip()
        if not text:
            return
        src = self._combo_src.currentData() or "auto"
        dst = self._combo_dst.currentData() or "zh-CN"
        self._edit_result.setPlainText(
            translate_text(text, src_lang=src, dst_lang=dst))

    def _open_page(self):
        from ui.module_pages import open_module_page
        try:
            open_module_page(self._owner, self)
        except Exception:
            pass

    def _toggle_speech(self):
        if self._recognizer is not None and self._recognizer.is_listening:
            self._recognizer.stop()
            self._btn_speech.setText("开始语音识别")
            self._label_speech.setText("")
            return
        if self._recognizer is None:
            from .speech_core import SpeechRecognizer
            self._recognizer = SpeechRecognizer()
            self._recognizer.on_result.connect(self._on_speech)
        if self._recognizer.start():
            self._btn_speech.setText("停止语音识别")
            self._label_speech.setText("正在聆听...")
        else:
            self._label_speech.setText("语音识别不可用")

    def _on_speech(self, text):
        self._label_speech.setText(text)
        self._edit_src.setPlainText(text)


def _make_home_widget(owner, parent):
    return _HomeWidget(owner, parent)