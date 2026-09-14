"""停用词编辑对话框：读写 rss.high_freq.stop_words（只存用户自定义部分）。"""

from core.qt_bootstrap import import_qt
from ui.widgets import make_button, make_line_edit, make_label

_, QtCore, QtGui, QtWidgets = import_qt()

from ..text_utils import _parse_keywords


class _StopWordsDialog(QtWidgets.QDialog):
    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner
        self.setWindowTitle("停用词管理")
        self.setMinimumWidth(420)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(make_label("输入停用词，用逗号或空格分隔（仅保存自定义部分）："))
        self.edit = make_line_edit()
        self.edit.setPlaceholderText("例如：下载, 在线, 高清")
        self.edit.setText(", ".join(self._load()))
        lay.addWidget(self.edit)
        row = QtWidgets.QHBoxLayout()
        btn_ok = make_button("保存")
        btn_ok.clicked.connect(self._save)
        btn_cancel = make_button("取消")
        btn_cancel.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(btn_ok)
        row.addWidget(btn_cancel)
        lay.addLayout(row)

    def _load(self):
        return list(
            self.owner.context.config.get("rss.high_freq.stop_words", []) or []
        )

    def _save(self):
        words = _parse_keywords(self.edit.text())
        self.owner.context.config.set("rss.high_freq.stop_words", words)
        self.accept()