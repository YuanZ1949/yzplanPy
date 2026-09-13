"""截图模块设置面板（独立可复用 widget）。

从 screenshot_ui.py 抽出，供模块页 Tab5 与模块管理页 create_settings_widget
共用同一实现。控件沿用截图模块既有风格，不强制 ui/widgets.py 工厂。
"""
from pathlib import Path
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QSpinBox, QFileDialog, QGroupBox,
    QCheckBox, QRadioButton, QButtonGroup, QKeySequenceEdit,
)


class _SettingsTab(QWidget):
    """截图设置面板。context/status_callback/hotkey_callback 均可为 None。"""

    def __init__(self, parent=None, context=None, core=None,
                 status_callback=None, hotkey_callback=None):
        super().__init__(parent)
        self.context = context
        self.core = core
        self._status_callback = status_callback
        self._hotkey_callback = hotkey_callback
        self._hotkey_enabled = False
        self._build_ui()
        self._load_settings()

    def _status(self, msg: str):
        """状态文本输出：有回调则转发，否则静默。"""
        if self._status_callback is not None:
            self._status_callback(msg)

    def _build_ui(self):
        """构建设置面板 UI（内部自接线控件信号）。"""
        layout = QVBoxLayout(self)
        # 保存目录
        dir_group = QGroupBox("保存目录")
        dir_layout = QVBoxLayout(dir_group)

        dir_input_layout = QHBoxLayout()
        self.save_dir_input = QLineEdit()
        self.save_dir_input.setPlaceholderText("截图保存目录...")
        dir_input_layout.addWidget(self.save_dir_input)

        self.browse_dir_btn = QPushButton("浏览")
        self.browse_dir_btn.setMinimumSize(80, 30)
        self.browse_dir_btn.clicked.connect(self.browse_save_dir)
        dir_input_layout.addWidget(self.browse_dir_btn)

        dir_layout.addLayout(dir_input_layout)
        layout.addWidget(dir_group)

        # 图片格式
        fmt_group = QGroupBox("图片格式")
        fmt_layout = QVBoxLayout(fmt_group)

        self.format_combo = QComboBox()
        self.format_combo.addItems(["PNG", "JPG"])
        fmt_layout.addWidget(self.format_combo)

        layout.addWidget(fmt_group)

        # 文件名模板
        tpl_group = QGroupBox("文件名模板")
        tpl_layout = QVBoxLayout(tpl_group)

        self.template_input = QLineEdit()
        self.template_input.setPlaceholderText("screenshot_%Y%m%d_%H%M%S")
        tpl_layout.addWidget(self.template_input)

        layout.addWidget(tpl_group)

        # 全局快捷键
        hotkey_group = QGroupBox("全局快捷键")
        hotkey_layout = QVBoxLayout(hotkey_group)

        self.hotkey_enable_cb = QCheckBox("启用全局快捷键")
        self.hotkey_enable_cb.toggled.connect(self._on_hotkey_enable_toggled)
        hotkey_layout.addWidget(self.hotkey_enable_cb)

        hotkey_seq_layout = QHBoxLayout()
        hotkey_seq_layout.addWidget(QLabel("快捷键:"))
        self.hotkey_seq_edit = QKeySequenceEdit()
        self.hotkey_seq_edit.setKeySequence(QKeySequence("Ctrl+Shift+S"))
        self.hotkey_seq_edit.setEnabled(False)
        hotkey_seq_layout.addWidget(self.hotkey_seq_edit)
        hotkey_seq_layout.addStretch()
        hotkey_layout.addLayout(hotkey_seq_layout)

        # 启动方式：立即 / 延时
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("启动方式:"))
        self.hotkey_mode_group = QButtonGroup(self)
        self.hotkey_immediate_rb = QRadioButton("立即截图")
        self.hotkey_immediate_rb.setChecked(True)
        self.hotkey_delayed_rb = QRadioButton("延时截图")
        self.hotkey_mode_group.addButton(self.hotkey_immediate_rb)
        self.hotkey_mode_group.addButton(self.hotkey_delayed_rb)
        mode_layout.addWidget(self.hotkey_immediate_rb)
        mode_layout.addWidget(self.hotkey_delayed_rb)
        mode_layout.addStretch()
        hotkey_layout.addLayout(mode_layout)

        delay_layout = QHBoxLayout()
        delay_layout.addWidget(QLabel("延时秒数:"))
        self.hotkey_delay_spin = QSpinBox()
        self.hotkey_delay_spin.setRange(1, 60)
        self.hotkey_delay_spin.setValue(3)
        self.hotkey_delay_spin.setSuffix(" 秒")
        self.hotkey_delay_spin.setEnabled(False)
        delay_layout.addWidget(self.hotkey_delay_spin)
        delay_layout.addStretch()
        hotkey_layout.addLayout(delay_layout)

        self.hotkey_delayed_rb.toggled.connect(
            lambda checked: self.hotkey_delay_spin.setEnabled(checked))

        layout.addWidget(hotkey_group)

        # 保存按钮
        self.save_settings_btn = QPushButton("保存设置")
        self.save_settings_btn.setMinimumSize(80, 30)
        self.save_settings_btn.clicked.connect(self.save_settings)
        layout.addWidget(self.save_settings_btn)

        layout.addStretch()

    def browse_save_dir(self):
        """浏览并选择保存目录。"""
        directory = QFileDialog.getExistingDirectory(
            self, "选择保存目录", self.save_dir_input.text().strip()
        )
        if directory:
            self.save_dir_input.setText(directory)

    def _load_settings(self):
        """从配置加载设置到控件。context 为 None 时直接返回。"""
        if self.context is None:
            return
        cfg = self.context.config
        save_dir = cfg.module_setting("screenshot", "save_dir")
        if save_dir:
            self.save_dir_input.setText(save_dir)
        fmt = cfg.module_setting("screenshot", "format", "PNG")
        idx = self.format_combo.findText(fmt)
        if idx >= 0:
            self.format_combo.setCurrentIndex(idx)
        tpl = cfg.module_setting("screenshot", "filename_template")
        if tpl:
            self.template_input.setText(tpl)

        # 快捷键设置
        hotkey_enabled = cfg.module_setting("screenshot", "hotkey_enabled", False)
        self.hotkey_enable_cb.setChecked(bool(hotkey_enabled))
        hotkey_seq = cfg.module_setting("screenshot", "hotkey_sequence", "Ctrl+Shift+S")
        try:
            self.hotkey_seq_edit.setKeySequence(QKeySequence(hotkey_seq))
        except Exception:
            self.hotkey_seq_edit.setKeySequence(QKeySequence("Ctrl+Shift+S"))
        hotkey_mode = cfg.module_setting("screenshot", "hotkey_mode", "immediate")
        if hotkey_mode == "delayed":
            self.hotkey_delayed_rb.setChecked(True)
        else:
            self.hotkey_immediate_rb.setChecked(True)
        delay = cfg.module_setting("screenshot", "hotkey_delay", 3)
        self.hotkey_delay_spin.setValue(int(delay))

    def save_settings(self):
        """保存设置到配置并应用到 core。"""
        if self.context is None:
            self._status("设置未保存：缺少应用配置")
            return

        save_dir = self.save_dir_input.text().strip()
        fmt = self.format_combo.currentText()
        tpl = self.template_input.text().strip() or "screenshot_%Y%m%d_%H%M%S"

        # 快捷键设置
        hotkey_enabled = self.hotkey_enable_cb.isChecked()
        hotkey_seq = self.hotkey_seq_edit.keySequence().toString()
        hotkey_mode = "delayed" if self.hotkey_delayed_rb.isChecked() else "immediate"
        hotkey_delay = self.hotkey_delay_spin.value()

        cfg = {
            "save_dir": save_dir,
            "format": fmt,
            "filename_template": tpl,
            "hotkey_enabled": hotkey_enabled,
            "hotkey_sequence": hotkey_seq,
            "hotkey_mode": hotkey_mode,
            "hotkey_delay": hotkey_delay,
        }
        self.context.config.set_module_config("screenshot", cfg)

        # Apply to core
        if self.core is not None:
            if save_dir:
                self.core.output_dir = Path(save_dir)
                self.core.output_dir.mkdir(parents=True, exist_ok=True)
            self.core._format = fmt
            self.core._filename_template = tpl

        # 应用快捷键
        self._apply_hotkey()

        self._status(f"设置已保存：{save_dir or '默认目录'} / {fmt}")

    # ── 快捷键 ──────────────────────────────────────────────────────────
    def _on_hotkey_enable_toggled(self, checked: bool):
        """启用/禁用复选框切换时，同步启用快捷键输入控件。"""
        self.hotkey_seq_edit.setEnabled(checked)
        self.hotkey_immediate_rb.setEnabled(checked)
        self.hotkey_delayed_rb.setEnabled(checked)
        if checked and self.hotkey_delayed_rb.isChecked():
            self.hotkey_delay_spin.setEnabled(True)
        else:
            self.hotkey_delay_spin.setEnabled(False)

    def _apply_hotkey(self):
        """注册/注销全局快捷键；无 hotkey_callback 或 core 时直接返回。"""
        if self._hotkey_callback is None or self.core is None:
            return

        if self._hotkey_enabled:
            self.core.unregister_hotkey()
            self._hotkey_enabled = False

        if not self.hotkey_enable_cb.isChecked():
            return

        seq = self.hotkey_seq_edit.keySequence()
        if seq.isEmpty():
            self._status("快捷键为空，未注册")
            return

        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            self._status("快捷键注册失败：无 QApplication")
            return

        ok = self.core.register_hotkey(seq, self._hotkey_callback, app=app)
        if ok:
            self._hotkey_enabled = True
            self._status(f"全局快捷键已注册: {seq.toString()}")
        else:
            self._status(f"快捷键注册失败: {seq.toString()}")