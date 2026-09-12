"""translator LLM 配置：provider 选择条 + 配置对话框（独立文件控制行数）。"""
from core.config import AppConfig
from core.qt_bootstrap import import_qt
from core.theme.tokens import theme_palette
from qfluentwidgets import BodyLabel, ComboBox, PushButton

_, QtCore, QtGui, QtWidgets = import_qt()

from .translator_core import llm_configured, get_provider, set_provider

LLM_CFG = "modules.translator.llm"


def open_llm_config_dialog(parent=None):
    """弹出 LLM 配置对话框；保存成功返回 True。"""
    cfg = AppConfig()
    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle("LLM 大模型配置")
    form = QtWidgets.QFormLayout(dlg)
    ed_url = QtWidgets.QLineEdit(cfg.get(f"{LLM_CFG}.api_url", ""), dlg)
    ed_key = QtWidgets.QLineEdit(cfg.get(f"{LLM_CFG}.api_key", ""), dlg)
    ed_key.setEchoMode(QtWidgets.QLineEdit.Password)
    ed_model = QtWidgets.QLineEdit(cfg.get(f"{LLM_CFG}.model", ""), dlg)
    form.addRow("API URL", ed_url)
    form.addRow("API Key", ed_key)
    form.addRow("模型", ed_model)
    btns = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, dlg)
    btns.accepted.connect(dlg.accept)
    btns.rejected.connect(dlg.reject)
    form.addRow(btns)
    if dlg.exec() != QtWidgets.QDialog.Accepted:
        return False
    cfg.set(f"{LLM_CFG}.api_url", ed_url.text().strip())
    cfg.set(f"{LLM_CFG}.api_key", ed_key.text().strip())
    cfg.set(f"{LLM_CFG}.model", ed_model.text().strip())
    return True


class ProviderBar(QtWidgets.QWidget):
    """provider 选择条：Google/LLM 下拉 + LLM 配置按钮 + 未配置警告。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        p = theme_palette()
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(6)
        self._combo_provider = ComboBox(self)
        self._combo_provider.addItem("Google 翻译", userData="google")
        self._combo_provider.addItem("LLM 大模型", userData="llm")
        idx = self._combo_provider.findData(get_provider())
        self._combo_provider.setCurrentIndex(idx if idx >= 0 else 0)
        self._combo_provider.currentIndexChanged.connect(self._on_provider_changed)
        btn_llm_cfg = PushButton("⚙️ LLM配置", self)
        btn_llm_cfg.setToolTip("配置 OpenAI 兼容 LLM 接口（api_url / api_key / model）")
        btn_llm_cfg.clicked.connect(self._open_llm_config)
        bar.addWidget(self._combo_provider, 1)
        bar.addWidget(btn_llm_cfg)
        lay.addLayout(bar)
        self._label_llm_warn = BodyLabel("", self)
        self._label_llm_warn.setWordWrap(True)
        self._label_llm_warn.setStyleSheet(f"color: {p['status_error']};")
        lay.addWidget(self._label_llm_warn)
        self._update_llm_warning()

    def provider(self):
        return self._combo_provider.currentData() or "google"

    def _on_provider_changed(self):
        set_provider(self.provider())
        self._update_llm_warning()

    def _update_llm_warning(self):
        if self.provider() == "llm" and not llm_configured():
            self._label_llm_warn.setText(
                "⚠️ LLM 未配置：请点击「⚙️ LLM配置」填写 api_url / api_key / model")
        else:
            self._label_llm_warn.setText("")

    def _open_llm_config(self):
        if open_llm_config_dialog(self):
            self._update_llm_warning()