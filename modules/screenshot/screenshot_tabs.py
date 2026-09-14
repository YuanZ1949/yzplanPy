# -*- coding: utf-8 -*-
"""截图标签页构建器与热键回调（从 screenshot_ui.py 拆出，迁移至工厂与主题令牌）。

ctx 即 ScreenshotWidget 实例：构建器把控件引用写入 ctx 属性、信号经 ctx 回调
连接，行为与迁移前完全一致。
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QSpinBox, QListWidget,
)
from PySide6.QtCore import Qt
from ui.widgets import make_button, make_line_edit, make_label
from core.theme.tokens import sizing


def _make_window_tab(ctx) -> QWidget:
    """Create the window capture tab."""
    sz = sizing()
    widget = QWidget()
    layout = QVBoxLayout(widget)

    # Window title input
    title_group = QGroupBox("按标题查找窗口")
    title_layout = QVBoxLayout(title_group)

    title_input_layout = QHBoxLayout()
    ctx.window_title_input = make_line_edit("输入窗口标题（支持部分匹配）...")
    title_input_layout.addWidget(ctx.window_title_input)

    ctx.capture_title_btn = make_button("截图")
    ctx.capture_title_btn.setMinimumWidth(sz["btn_min_width"])
    ctx.capture_title_btn.clicked.connect(ctx.capture_by_title)
    title_input_layout.addWidget(ctx.capture_title_btn)

    title_layout.addLayout(title_input_layout)
    layout.addWidget(title_group)

    # YZplan window capture
    yzplan_group = QGroupBox("YZplan 主窗口")
    yzplan_layout = QVBoxLayout(yzplan_group)

    ctx.capture_yzplan_btn = make_button("截图 YZplan 主窗口")
    ctx.capture_yzplan_btn.setMinimumWidth(sz["btn_min_width"])
    ctx.capture_yzplan_btn.clicked.connect(ctx.capture_yzplan)
    yzplan_layout.addWidget(ctx.capture_yzplan_btn)

    layout.addWidget(yzplan_group)

    # Full screen capture
    screen_group = QGroupBox("全屏截图")
    screen_layout = QVBoxLayout(screen_group)

    ctx.capture_screen_btn = make_button("截图整个屏幕")
    ctx.capture_screen_btn.setMinimumWidth(sz["btn_min_width"])
    ctx.capture_screen_btn.clicked.connect(ctx.capture_fullscreen)
    screen_layout.addWidget(ctx.capture_screen_btn)

    layout.addWidget(screen_group)

    layout.addStretch()
    return widget


def _make_html_tab(ctx) -> QWidget:
    """Create the HTML capture tab."""
    sz = sizing()
    widget = QWidget()
    layout = QVBoxLayout(widget)

    # HTML file selection
    file_group = QGroupBox("HTML 文件")
    file_layout = QVBoxLayout(file_group)

    file_input_layout = QHBoxLayout()
    ctx.html_path_input = make_line_edit("输入或选择 HTML 文件路径...")
    ctx.html_path_input.textChanged.connect(ctx._on_html_path_changed)
    file_input_layout.addWidget(ctx.html_path_input)

    ctx.browse_html_btn = make_button("浏览")
    ctx.browse_html_btn.setMinimumWidth(sz["btn_min_width"])
    ctx.browse_html_btn.clicked.connect(ctx.browse_html_file)
    file_input_layout.addWidget(ctx.browse_html_btn)

    file_layout.addLayout(file_input_layout)

    # Render settings
    settings_layout = QHBoxLayout()

    settings_layout.addWidget(make_label("宽度:"))
    ctx.html_width_spin = QSpinBox()
    ctx.html_width_spin.setRange(320, 7680)
    ctx.html_width_spin.setValue(1920)
    settings_layout.addWidget(ctx.html_width_spin)

    settings_layout.addWidget(make_label("高度:"))
    ctx.html_height_spin = QSpinBox()
    ctx.html_height_spin.setRange(240, 4320)
    ctx.html_height_spin.setValue(1080)
    settings_layout.addWidget(ctx.html_height_spin)

    settings_layout.addStretch()
    file_layout.addLayout(settings_layout)

    # Capture button
    ctx.capture_html_btn = make_button("截图 HTML 文件")
    ctx.capture_html_btn.setMinimumWidth(sz["btn_min_width"])
    ctx.capture_html_btn.clicked.connect(ctx.capture_html_file)
    ctx.capture_html_btn.setEnabled(False)
    file_layout.addWidget(ctx.capture_html_btn)

    layout.addWidget(file_group)

    # Quick access to rss_style_preview.html
    quick_group = QGroupBox("快速访问")
    quick_layout = QVBoxLayout(quick_group)

    ctx.capture_rss_preview_btn = make_button("截图 RSS 样式预览")
    ctx.capture_rss_preview_btn.setMinimumWidth(sz["btn_min_width"])
    ctx.capture_rss_preview_btn.clicked.connect(ctx.capture_rss_preview)
    quick_layout.addWidget(ctx.capture_rss_preview_btn)

    layout.addWidget(quick_group)

    layout.addStretch()
    return widget


def _make_region_tab(ctx) -> QWidget:
    """Create the region capture tab."""
    sz = sizing()
    widget = QWidget()
    layout = QVBoxLayout(widget)

    # Region settings
    region_group = QGroupBox("区域设置")
    region_layout = QVBoxLayout(region_group)

    # X, Y coordinates
    coord_layout = QHBoxLayout()

    coord_layout.addWidget(make_label("X:"))
    ctx.region_x_spin = QSpinBox()
    ctx.region_x_spin.setRange(0, 10000)
    ctx.region_x_spin.setValue(0)
    coord_layout.addWidget(ctx.region_x_spin)

    coord_layout.addWidget(make_label("Y:"))
    ctx.region_y_spin = QSpinBox()
    ctx.region_y_spin.setRange(0, 10000)
    ctx.region_y_spin.setValue(0)
    coord_layout.addWidget(ctx.region_y_spin)

    coord_layout.addStretch()
    region_layout.addLayout(coord_layout)

    # Width, Height
    size_layout = QHBoxLayout()

    size_layout.addWidget(make_label("宽度:"))
    ctx.region_width_spin = QSpinBox()
    ctx.region_width_spin.setRange(1, 10000)
    ctx.region_width_spin.setValue(800)
    size_layout.addWidget(ctx.region_width_spin)

    size_layout.addWidget(make_label("高度:"))
    ctx.region_height_spin = QSpinBox()
    ctx.region_height_spin.setRange(1, 10000)
    ctx.region_height_spin.setValue(600)
    size_layout.addWidget(ctx.region_height_spin)

    size_layout.addStretch()
    region_layout.addLayout(size_layout)

    # Capture button
    ctx.capture_region_btn = make_button("截图指定区域")
    ctx.capture_region_btn.setMinimumWidth(sz["btn_min_width"])
    ctx.capture_region_btn.clicked.connect(ctx.capture_region)
    region_layout.addWidget(ctx.capture_region_btn)

    layout.addWidget(region_group)

    layout.addStretch()
    return widget


def _make_window_list_tab(ctx) -> QWidget:
    """Create the window list tab."""
    sz = sizing()
    widget = QWidget()
    layout = QVBoxLayout(widget)

    # Refresh button
    refresh_layout = QHBoxLayout()
    ctx.refresh_windows_btn = make_button("刷新窗口列表")
    ctx.refresh_windows_btn.setMinimumWidth(sz["btn_min_width"])
    ctx.refresh_windows_btn.clicked.connect(ctx.refresh_window_list)
    refresh_layout.addWidget(ctx.refresh_windows_btn)
    refresh_layout.addStretch()
    layout.addLayout(refresh_layout)

    # Window list
    ctx.window_list = QListWidget()
    ctx.window_list.itemDoubleClicked.connect(ctx.capture_selected_window)
    layout.addWidget(ctx.window_list)

    # Capture selected window
    capture_layout = QHBoxLayout()
    ctx.capture_selected_btn = make_button("截图选中窗口")
    ctx.capture_selected_btn.setMinimumWidth(sz["btn_min_width"])
    ctx.capture_selected_btn.clicked.connect(ctx.capture_selected_window)
    ctx.capture_selected_btn.setEnabled(False)
    capture_layout.addWidget(ctx.capture_selected_btn)
    capture_layout.addStretch()
    layout.addLayout(capture_layout)

    # Connect list selection change
    ctx.window_list.itemSelectionChanged.connect(ctx.on_window_selected)

    # Load windows initially
    ctx.refresh_window_list()

    return widget


def _on_hotkey_triggered(self):
    """全局快捷键触发：立即或延时启动截图。"""
    if self._settings_tab.hotkey_delayed_rb.isChecked():
        delay_ms = self._settings_tab.hotkey_delay_spin.value() * 1000
        self._delay_timer.start(delay_ms)
        self.status_label.setText(
            f"将在 {self._settings_tab.hotkey_delay_spin.value()} 秒后截图...")
    else:
        self.capture_fullscreen()


def _on_delayed_hotkey(self):
    """延时结束后执行截图。"""
    self.capture_fullscreen()


def _on_html_path_changed(self, text: str):
    """HTML 路径输入变化时，启用/禁用截图按钮。"""
    self.capture_html_btn.setEnabled(bool(text.strip()))