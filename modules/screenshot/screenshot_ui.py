"""
Screenshot UI Module for YZplan
Provides a user-friendly interface for capturing windows, HTML files, and screen regions.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QComboBox, QLineEdit, QSpinBox, QFileDialog, QMessageBox,
    QListWidget, QListWidgetItem, QTabWidget, QGroupBox,
    QProgressBar, QFrame, QCheckBox, QRadioButton, QButtonGroup,
    QKeySequenceEdit, QApplication
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QIcon, QPixmap, QKeySequence
from pathlib import Path
from typing import Optional

from .screenshot_core import ScreenshotCore


class ScreenshotWorker(QThread):
    """Worker thread for screenshot operations."""
    finished = Signal(str)  # Output path
    error = Signal(str)  # Error message
    progress = Signal(int)  # Progress percentage
    
    def __init__(self, core: ScreenshotCore, operation: str, **kwargs):
        super().__init__()
        self.core = core
        self.operation = operation
        self.kwargs = kwargs
    
    def run(self):
        try:
            self.progress.emit(10)
            
            if self.operation == "window_title":
                result = self.core.capture_window_by_title(
                    self.kwargs.get("title", ""),
                    self.kwargs.get("filename")
                )
            elif self.operation == "window_hwnd":
                result = self.core.capture_window(
                    self.kwargs.get("hwnd", 0),
                    self.kwargs.get("filename")
                )
            elif self.operation == "yzplan":
                result = self.core.capture_yzplan_window(
                    self.kwargs.get("filename")
                )
            elif self.operation == "region":
                result = self.core.capture_region(
                    self.kwargs.get("x", 0),
                    self.kwargs.get("y", 0),
                    self.kwargs.get("width", 800),
                    self.kwargs.get("height", 600),
                    self.kwargs.get("filename")
                )
            elif self.operation == "fullscreen":
                result = self.core.capture_full_screen(
                    self.kwargs.get("filename")
                )
            elif self.operation == "html_file":
                result = self.core.capture_html_file_sync(
                    self.kwargs.get("html_path", ""),
                    self.kwargs.get("filename"),
                    self.kwargs.get("width", 1920),
                    self.kwargs.get("height", 1080)
                )
            else:
                result = None
                self.error.emit(f"Unknown operation: {self.operation}")
            
            self.progress.emit(100)
            
            if result:
                self.finished.emit(result)
            else:
                self.error.emit("Screenshot operation failed")
                
        except Exception as e:
            self.error.emit(str(e))


class ScreenshotWidget(QWidget):
    """Main screenshot widget for YZplan."""
    
    def __init__(self, parent=None, context=None):
        super().__init__(parent)
        self.context = context
        self.core = ScreenshotCore(config=context.config if context is not None else None)
        self.worker = None
        self._hotkey_enabled = False
        self._delay_timer = QTimer(self)
        self._delay_timer.setSingleShot(True)
        self._delay_timer.timeout.connect(self._on_delayed_hotkey)
        self.setup_ui()
        self._load_settings()
        self._apply_hotkey()
        
    def setup_ui(self):
        """Setup the user interface."""
        self.setWindowTitle("YZplan 截图工具")
        self.setMinimumSize(600, 500)
        
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        # Title
        title_label = QLabel("截图工具")
        title_label.setStyleSheet("font-size: 18px; font-weight: bold; margin-bottom: 10px;")
        main_layout.addWidget(title_label)
        
        # Tab widget for different screenshot modes
        tab_widget = QTabWidget()
        main_layout.addWidget(tab_widget)
        
        # Tab 1: Window capture
        tab_widget.addTab(self.create_window_tab(), "窗口截图")
        
        # Tab 2: HTML capture
        tab_widget.addTab(self.create_html_tab(), "HTML 截图")
        
        # Tab 3: Region capture
        tab_widget.addTab(self.create_region_tab(), "区域截图")
        
        # Tab 4: Window list
        tab_widget.addTab(self.create_window_list_tab(), "窗口列表")
        
        # Tab 5: Settings
        tab_widget.addTab(self.create_settings_tab(), "设置")
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)
        
        # Status label
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color: #666; font-size: 12px;")
        main_layout.addWidget(self.status_label)
        
    def create_window_tab(self) -> QWidget:
        """Create the window capture tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Window title input
        title_group = QGroupBox("按标题查找窗口")
        title_layout = QVBoxLayout(title_group)
        
        title_input_layout = QHBoxLayout()
        self.window_title_input = QLineEdit()
        self.window_title_input.setPlaceholderText("输入窗口标题（支持部分匹配）...")
        title_input_layout.addWidget(self.window_title_input)
        
        self.capture_title_btn = QPushButton("截图")
        self.capture_title_btn.setMinimumSize(80, 30)
        self.capture_title_btn.clicked.connect(self.capture_by_title)
        title_input_layout.addWidget(self.capture_title_btn)
        
        title_layout.addLayout(title_input_layout)
        layout.addWidget(title_group)
        
        # YZplan window capture
        yzplan_group = QGroupBox("YZplan 主窗口")
        yzplan_layout = QVBoxLayout(yzplan_group)
        
        self.capture_yzplan_btn = QPushButton("截图 YZplan 主窗口")
        self.capture_yzplan_btn.setMinimumSize(80, 30)
        self.capture_yzplan_btn.clicked.connect(self.capture_yzplan)
        yzplan_layout.addWidget(self.capture_yzplan_btn)
        
        layout.addWidget(yzplan_group)
        
        # Full screen capture
        screen_group = QGroupBox("全屏截图")
        screen_layout = QVBoxLayout(screen_group)
        
        self.capture_screen_btn = QPushButton("截图整个屏幕")
        self.capture_screen_btn.setMinimumSize(80, 30)
        self.capture_screen_btn.clicked.connect(self.capture_fullscreen)
        screen_layout.addWidget(self.capture_screen_btn)
        
        layout.addWidget(screen_group)
        
        layout.addStretch()
        return widget
    
    def create_html_tab(self) -> QWidget:
        """Create the HTML capture tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # HTML file selection
        file_group = QGroupBox("HTML 文件")
        file_layout = QVBoxLayout(file_group)
        
        file_input_layout = QHBoxLayout()
        self.html_path_input = QLineEdit()
        self.html_path_input.setPlaceholderText("输入或选择 HTML 文件路径...")
        self.html_path_input.textChanged.connect(self._on_html_path_changed)
        file_input_layout.addWidget(self.html_path_input)
        
        self.browse_html_btn = QPushButton("浏览")
        self.browse_html_btn.setMinimumSize(80, 30)
        self.browse_html_btn.clicked.connect(self.browse_html_file)
        file_input_layout.addWidget(self.browse_html_btn)
        
        file_layout.addLayout(file_input_layout)
        
        # Render settings
        settings_layout = QHBoxLayout()
        
        settings_layout.addWidget(QLabel("宽度:"))
        self.html_width_spin = QSpinBox()
        self.html_width_spin.setRange(320, 7680)
        self.html_width_spin.setValue(1920)
        settings_layout.addWidget(self.html_width_spin)
        
        settings_layout.addWidget(QLabel("高度:"))
        self.html_height_spin = QSpinBox()
        self.html_height_spin.setRange(240, 4320)
        self.html_height_spin.setValue(1080)
        settings_layout.addWidget(self.html_height_spin)
        
        settings_layout.addStretch()
        file_layout.addLayout(settings_layout)
        
        # Capture button
        self.capture_html_btn = QPushButton("截图 HTML 文件")
        self.capture_html_btn.setMinimumSize(80, 30)
        self.capture_html_btn.clicked.connect(self.capture_html_file)
        self.capture_html_btn.setEnabled(False)
        file_layout.addWidget(self.capture_html_btn)
        
        layout.addWidget(file_group)
        
        # Quick access to rss_style_preview.html
        quick_group = QGroupBox("快速访问")
        quick_layout = QVBoxLayout(quick_group)
        
        self.capture_rss_preview_btn = QPushButton("截图 RSS 样式预览")
        self.capture_rss_preview_btn.setMinimumSize(80, 30)
        self.capture_rss_preview_btn.clicked.connect(self.capture_rss_preview)
        quick_layout.addWidget(self.capture_rss_preview_btn)
        
        layout.addWidget(quick_group)
        
        layout.addStretch()
        return widget
    
    def create_region_tab(self) -> QWidget:
        """Create the region capture tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Region settings
        region_group = QGroupBox("区域设置")
        region_layout = QVBoxLayout(region_group)
        
        # X, Y coordinates
        coord_layout = QHBoxLayout()
        
        coord_layout.addWidget(QLabel("X:"))
        self.region_x_spin = QSpinBox()
        self.region_x_spin.setRange(0, 10000)
        self.region_x_spin.setValue(0)
        coord_layout.addWidget(self.region_x_spin)
        
        coord_layout.addWidget(QLabel("Y:"))
        self.region_y_spin = QSpinBox()
        self.region_y_spin.setRange(0, 10000)
        self.region_y_spin.setValue(0)
        coord_layout.addWidget(self.region_y_spin)
        
        coord_layout.addStretch()
        region_layout.addLayout(coord_layout)
        
        # Width, Height
        size_layout = QHBoxLayout()
        
        size_layout.addWidget(QLabel("宽度:"))
        self.region_width_spin = QSpinBox()
        self.region_width_spin.setRange(1, 10000)
        self.region_width_spin.setValue(800)
        size_layout.addWidget(self.region_width_spin)
        
        size_layout.addWidget(QLabel("高度:"))
        self.region_height_spin = QSpinBox()
        self.region_height_spin.setRange(1, 10000)
        self.region_height_spin.setValue(600)
        size_layout.addWidget(self.region_height_spin)
        
        size_layout.addStretch()
        region_layout.addLayout(size_layout)
        
        # Capture button
        self.capture_region_btn = QPushButton("截图指定区域")
        self.capture_region_btn.setMinimumSize(80, 30)
        self.capture_region_btn.clicked.connect(self.capture_region)
        region_layout.addWidget(self.capture_region_btn)
        
        layout.addWidget(region_group)
        
        layout.addStretch()
        return widget
    
    def create_window_list_tab(self) -> QWidget:
        """Create the window list tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Refresh button
        refresh_layout = QHBoxLayout()
        self.refresh_windows_btn = QPushButton("刷新窗口列表")
        self.refresh_windows_btn.setMinimumSize(80, 30)
        self.refresh_windows_btn.clicked.connect(self.refresh_window_list)
        refresh_layout.addWidget(self.refresh_windows_btn)
        refresh_layout.addStretch()
        layout.addLayout(refresh_layout)
        
        # Window list
        self.window_list = QListWidget()
        self.window_list.itemDoubleClicked.connect(self.capture_selected_window)
        layout.addWidget(self.window_list)
        
        # Capture selected window
        capture_layout = QHBoxLayout()
        self.capture_selected_btn = QPushButton("截图选中窗口")
        self.capture_selected_btn.setMinimumSize(80, 30)
        self.capture_selected_btn.clicked.connect(self.capture_selected_window)
        self.capture_selected_btn.setEnabled(False)
        capture_layout.addWidget(self.capture_selected_btn)
        capture_layout.addStretch()
        layout.addLayout(capture_layout)
        
        # Connect list selection change
        self.window_list.itemSelectionChanged.connect(self.on_window_selected)
        
        # Load windows initially
        self.refresh_window_list()
        
        return widget
    
    def create_settings_tab(self) -> QWidget:
        """Create the settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Save directory
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
        
        # Image format
        fmt_group = QGroupBox("图片格式")
        fmt_layout = QVBoxLayout(fmt_group)
        
        self.format_combo = QComboBox()
        self.format_combo.addItems(["PNG", "JPG"])
        fmt_layout.addWidget(self.format_combo)
        
        layout.addWidget(fmt_group)
        
        # Filename template
        tpl_group = QGroupBox("文件名模板")
        tpl_layout = QVBoxLayout(tpl_group)
        
        self.template_input = QLineEdit()
        self.template_input.setPlaceholderText("screenshot_%Y%m%d_%H%M%S")
        tpl_layout.addWidget(self.template_input)
        
        layout.addWidget(tpl_group)
        
        # Hotkey settings
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
        
        # Save button
        self.save_settings_btn = QPushButton("保存设置")
        self.save_settings_btn.setMinimumSize(80, 30)
        self.save_settings_btn.clicked.connect(self.save_settings)
        layout.addWidget(self.save_settings_btn)
        
        layout.addStretch()
        return widget
    
    def browse_save_dir(self):
        """Browse for a save directory."""
        directory = QFileDialog.getExistingDirectory(
            self, "选择保存目录", self.save_dir_input.text().strip()
        )
        if directory:
            self.save_dir_input.setText(directory)
    
    def _load_settings(self):
        """Load settings from config into the settings tab widgets."""
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
        """Save settings from the settings tab into config and apply to core."""
        if self.context is None:
            self.status_label.setText("设置未保存：缺少应用配置")
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
        if save_dir:
            self.core.output_dir = Path(save_dir)
            self.core.output_dir.mkdir(parents=True, exist_ok=True)
        self.core._format = fmt
        self.core._filename_template = tpl
        
        # 应用快捷键
        self._apply_hotkey()
        
        self.status_label.setText(f"设置已保存：{save_dir or '默认目录'} / {fmt}")
    
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
        """根据当前设置注册/注销全局快捷键。"""
        if self._hotkey_enabled:
            self.core.unregister_hotkey()
            self._hotkey_enabled = False
        
        if not self.hotkey_enable_cb.isChecked():
            return
        
        seq = self.hotkey_seq_edit.keySequence()
        if seq.isEmpty():
            self.status_label.setText("快捷键为空，未注册")
            return
        
        app = QApplication.instance()
        if app is None:
            self.status_label.setText("快捷键注册失败：无 QApplication")
            return
        
        ok = self.core.register_hotkey(seq, self._on_hotkey_triggered, app=app)
        if ok:
            self._hotkey_enabled = True
            self.status_label.setText(f"全局快捷键已注册: {seq.toString()}")
        else:
            self.status_label.setText(f"快捷键注册失败: {seq.toString()}")
    
    def _on_hotkey_triggered(self):
        """全局快捷键触发：立即或延时启动截图。"""
        if self.hotkey_delayed_rb.isChecked():
            delay_ms = self.hotkey_delay_spin.value() * 1000
            self._delay_timer.start(delay_ms)
            self.status_label.setText(f"将在 {self.hotkey_delay_spin.value()} 秒后截图...")
        else:
            self.capture_fullscreen()
    
    def _on_delayed_hotkey(self):
        """延时结束后执行截图。"""
        self.capture_fullscreen()
    
    def _on_html_path_changed(self, text: str):
        """HTML 路径输入变化时，启用/禁用截图按钮。"""
        self.capture_html_btn.setEnabled(bool(text.strip()))
    
    def browse_html_file(self):
        """Browse for an HTML file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 HTML 文件",
            "",
            "HTML 文件 (*.html *.htm);;所有文件 (*)"
        )
        
        if file_path:
            self.html_path_input.setText(file_path)
            self.capture_html_btn.setEnabled(True)
    
    def refresh_window_list(self):
        """Refresh the list of windows."""
        self.window_list.clear()
        
        windows = self.core.list_windows()
        for hwnd, title, class_name in windows:
            item = QListWidgetItem(f"{title} [{class_name}] (hwnd: {hwnd})")
            item.setData(Qt.UserRole, hwnd)  # type: ignore[reportAttributeAccessIssue]
            self.window_list.addItem(item)
    
    def on_window_selected(self):
        """Handle window selection change."""
        selected = self.window_list.selectedItems()
        self.capture_selected_btn.setEnabled(len(selected) > 0)
    
    def capture_by_title(self):
        """Capture window by title."""
        title = self.window_title_input.text().strip()
        if not title:
            QMessageBox.warning(self, "错误", "请输入窗口标题")
            return
        
        self.start_operation("window_title", title=title)
    
    def capture_yzplan(self):
        """Capture YZplan main window."""
        self.start_operation("yzplan")
    
    def capture_fullscreen(self):
        """Capture full screen."""
        self.start_operation("fullscreen")
    
    def capture_html_file(self):
        """Capture HTML file."""
        html_path = self.html_path_input.text().strip()
        if not html_path:
            QMessageBox.warning(self, "错误", "请选择 HTML 文件")
            return
        
        if not Path(html_path).exists():
            QMessageBox.warning(self, "错误", "HTML 文件不存在")
            return
        
        width = self.html_width_spin.value()
        height = self.html_height_spin.value()
        
        self.start_operation("html_file", 
                           html_path=html_path, 
                           width=width, 
                           height=height)
    
    def capture_rss_preview(self):
        """Capture the RSS style preview HTML file."""
        # Try to find rss_style_preview.html in the project root
        project_root = Path(__file__).parent.parent.parent
        rss_preview_path = project_root / "rss_style_preview.html"
        
        if not rss_preview_path.exists():
            QMessageBox.warning(self, "错误", 
                              f"未找到 RSS 样式预览文件:\n{rss_preview_path}")
            return
        
        width = self.html_width_spin.value()
        height = self.html_height_spin.value()
        
        self.start_operation("html_file", 
                           html_path=str(rss_preview_path), 
                           width=width, 
                           height=height)
    
    def capture_region(self):
        """Capture screen region."""
        x = self.region_x_spin.value()
        y = self.region_y_spin.value()
        width = self.region_width_spin.value()
        height = self.region_height_spin.value()
        
        self.start_operation("region", x=x, y=y, width=width, height=height)
    
    def capture_selected_window(self):
        """Capture the selected window from the list."""
        selected = self.window_list.selectedItems()
        if not selected:
            return
        
        hwnd = selected[0].data(Qt.UserRole)  # type: ignore[reportAttributeAccessIssue]
        self.start_operation("window_hwnd", hwnd=hwnd)
    
    def start_operation(self, operation: str, **kwargs):
        """Start a screenshot operation."""
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "错误", "已有截图操作正在进行")
            return
        
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setText("正在截图...")
        
        self.worker = ScreenshotWorker(self.core, operation, **kwargs)
        self.worker.finished.connect(self.on_operation_finished)
        self.worker.error.connect(self.on_operation_error)
        self.worker.progress.connect(self.on_progress_update)
        self.worker.start()
    
    def on_operation_finished(self, output_path: str):
        """Handle successful screenshot operation."""
        self.progress_bar.setVisible(False)
        self.status_label.setText(f"截图成功: {output_path}")
        
        QMessageBox.information(self, "成功", 
                              f"截图已保存到:\n{output_path}")
    
    def on_operation_error(self, error_msg: str):
        """Handle failed screenshot operation."""
        self.progress_bar.setVisible(False)
        self.status_label.setText(f"截图失败: {error_msg}")
        
        QMessageBox.critical(self, "错误", f"截图失败:\n{error_msg}")
    
    def on_progress_update(self, progress: int):
        """Handle progress update."""
        self.progress_bar.setValue(progress)


def create_screenshot_widget(parent=None) -> ScreenshotWidget:
    """Factory function to create screenshot widget."""
    return ScreenshotWidget(parent)
