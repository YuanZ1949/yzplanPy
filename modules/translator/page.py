"""translator 模块页：三栏布局（翻译 / 语音 / 字幕）。"""
import collections

from core.qt_bootstrap import import_qt
from qfluentwidgets import (
    BodyLabel, CheckBox, ComboBox, PrimaryPushButton, PushButton,
    SubtitleLabel,
)

_, QtCore, QtGui, QtWidgets = import_qt()

from .translator_core import translate_text, LANGUAGES
from .llm_config import ProviderBar
from .speech_core import SpeechRecognizer
from .subtitle_panel import _SubtitlePanel

_HISTORY_MAX = 20


class _TranslatorPage(QtWidgets.QWidget):
    """翻译模块完整页面：左翻译 / 右语音 / 第三栏字幕。"""

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self._owner = owner
        self._recognizer = None
        self._history = collections.deque(maxlen=_HISTORY_MAX)
        self._build_ui()
        self.destroyed.connect(self._cleanup)

    def _cleanup(self):
        try:
            self._subtitle_panel.close_subtitle()
        except Exception:
            pass
        if self._recognizer is not None:
            try:
                self._recognizer.stop()
            except Exception:
                pass

    def _build_ui(self):
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)
        cols = QtWidgets.QHBoxLayout()
        cols.setSpacing(10)
        self._subtitle_panel = _SubtitlePanel(self)
        cols.addWidget(self._build_translate_col(), 3)
        cols.addWidget(self._build_speech_col(), 2)
        cols.addWidget(self._subtitle_panel, 2)
        lay.addLayout(cols, 1)

    # ── 左栏：翻译区 ──────────────────────────────────────────
    def _build_translate_col(self):
        card = QtWidgets.QFrame(self)
        card.setFrameShape(QtWidgets.QFrame.StyledPanel)
        v = QtWidgets.QVBoxLayout(card)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(8)

        v.addWidget(SubtitleLabel("翻译", card))

        lang_bar = QtWidgets.QHBoxLayout()
        lang_bar.setSpacing(6)
        self._combo_src = ComboBox(card)
        self._combo_dst = ComboBox(card)
        for name, code in LANGUAGES:
            self._combo_src.addItem(name, userData=code)
            self._combo_dst.addItem(name, userData=code)
        self._combo_dst.setCurrentIndex(1)  # 默认目标：中文
        btn_swap = PushButton("⇄", card)
        btn_swap.setToolTip("交换语言")
        btn_swap.clicked.connect(self._swap_langs)
        lang_bar.addWidget(self._combo_src, 1)
        lang_bar.addWidget(btn_swap)
        lang_bar.addWidget(self._combo_dst, 1)
        v.addLayout(lang_bar)

        self._provider_bar = ProviderBar(card)
        v.addWidget(self._provider_bar)

        self._edit_src = QtWidgets.QPlainTextEdit(card)
        self._edit_src.setPlaceholderText("输入要翻译的文字...")
        v.addWidget(self._edit_src, 1)

        btn_translate = PrimaryPushButton("翻译", card)
        btn_translate.clicked.connect(self._do_translate)
        v.addWidget(btn_translate)

        self._edit_target = QtWidgets.QPlainTextEdit(card)
        self._edit_target.setReadOnly(True)
        v.addWidget(self._edit_target, 1)

        btn_copy = PushButton("复制结果", card)
        btn_copy.clicked.connect(self._copy_target)
        v.addWidget(btn_copy)

        self._label_history = BodyLabel("", card)
        self._label_history.setWordWrap(True)
        self._label_history.setStyleSheet("color: #888;")
        v.addWidget(self._label_history)
        return card

    # ── 右栏：语音区 ──────────────────────────────────────────
    def _build_speech_col(self):
        card = QtWidgets.QFrame(self)
        card.setFrameShape(QtWidgets.QFrame.StyledPanel)
        v = QtWidgets.QVBoxLayout(card)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(8)

        v.addWidget(SubtitleLabel("语音识别", card))

        status_bar = QtWidgets.QHBoxLayout()
        status_bar.setSpacing(6)
        self._dot = QtWidgets.QLabel("●", card)
        self._dot.setStyleSheet("color: #888; font-size: 16px;")
        self._label_status = BodyLabel("未开始", card)
        status_bar.addWidget(self._dot)
        status_bar.addWidget(self._label_status)
        status_bar.addStretch(1)
        v.addLayout(status_bar)

        btn_bar = QtWidgets.QHBoxLayout()
        btn_bar.setSpacing(6)
        self._btn_start = PrimaryPushButton("开始", card)
        self._btn_start.clicked.connect(self._start_speech)
        self._btn_stop = PushButton("停止", card)
        self._btn_stop.clicked.connect(self._stop_speech)
        self._btn_stop.setEnabled(False)
        btn_bar.addWidget(self._btn_start)
        btn_bar.addWidget(self._btn_stop)
        v.addLayout(btn_bar)

        self._edit_recog = QtWidgets.QPlainTextEdit(card)
        self._edit_recog.setReadOnly(True)
        self._edit_recog.setPlaceholderText("识别到的文字显示在这里...")
        v.addWidget(self._edit_recog, 1)

        self._check_auto = CheckBox("自动翻译", card)
        v.addWidget(self._check_auto)

        self._label_auto = BodyLabel("", card)
        self._label_auto.setWordWrap(True)
        self._label_auto.setStyleSheet("color: #888;")
        v.addWidget(self._label_auto)
        return card

    # ── 翻译交互 ──────────────────────────────────────────────
    def _index_of(self, code):
        for i in range(self._combo_src.count()):
            if self._combo_src.itemData(i) == code:
                return i
        return 0

    def _swap_langs(self):
        src = self._combo_src.currentData()
        dst = self._combo_dst.currentData()
        new_src = dst if dst != "auto" else "zh"
        new_dst = src if src != "auto" else "zh"
        self._combo_src.setCurrentIndex(self._index_of(new_src))
        self._combo_dst.setCurrentIndex(self._index_of(new_dst))

    def _do_translate(self):
        text = self._edit_src.toPlainText().strip()
        if not text:
            return
        src = self._combo_src.currentData() or "auto"
        dst = self._combo_dst.currentData() or "zh-CN"
        result = translate_text(
            text, src_lang=src, dst_lang=dst, provider=self._provider_bar.provider())
        self._edit_target.setPlainText(result)
        self._history.append((text, result))
        self._update_history()

    def _copy_target(self):
        text = self._edit_target.toPlainText()
        if text:
            QtWidgets.QApplication.clipboard().setText(text)

    def _update_history(self):
        lines = [f"{s[:20]} → {t[:20]}" for s, t in self._history]
        self._label_history.setText("历史:\n" + "\n".join(lines))

    # ── 语音交互 ──────────────────────────────────────────────
    def _start_speech(self):
        if self._recognizer is None:
            self._recognizer = SpeechRecognizer()
            self._recognizer.on_result.connect(self._on_speech)
        if self._recognizer.start():
            self._dot.setStyleSheet("color: #34a853; font-size: 16px;")
            self._label_status.setText("正在聆听")
            self._btn_start.setEnabled(False)
            self._btn_stop.setEnabled(True)
        else:
            self._label_status.setText("语音识别不可用")

    def _stop_speech(self):
        if self._recognizer is not None:
            self._recognizer.stop()
        self._dot.setStyleSheet("color: #888; font-size: 16px;")
        self._label_status.setText("已停止")
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)

    def _on_speech(self, text):
        self._edit_recog.appendPlainText(text)
        result = ""
        if self._check_auto.isChecked():
            dst = self._combo_dst.currentData() or "zh-CN"
            result = translate_text(
                text, src_lang="auto", dst_lang=dst,
                provider=self._provider_bar.provider())
            self._label_auto.setText(result)
            self._history.append((text, result))
            self._update_history()
        self._subtitle_panel.feed(text, result)


def _make_page_widget(owner, parent):
    return _TranslatorPage(owner, parent)