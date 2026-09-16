"""
Screenshot UI Module for YZplan
Provides a user-friendly interface for capturing windows, HTML files, and screen regions.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFileDialog, QMessageBox,
    QListWidgetItem, QTabWidget, QProgressBar,
)
from PySide6.QtCore import Qt, QTimer
from pathlib import Path

from .screenshot_core import ScreenshotCore
from .screenshot_settings import _SettingsTab
from .screenshot_tabs import (
    _make_window_tab, _make_html_tab, _make_region_tab, _make_window_list_tab,
    _on_hotkey_triggered, _on_delayed_hotkey, _on_html_path_changed,
)
from .screenshot_worker import ScreenshotWorker  # noqa: F401 (re-export)
from core.theme.tokens import sizing, theme_palette


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

    def closeEvent(self, event):
        """关闭窗口时注销全局热键并安全停止截图线程。

        - 注销全局热键：installNativeEventFilter 登记对象若随 GC 销毁会留下
          悬垂指针，下一次原生事件触发崩溃；RegisterHotKey 也会残留。
        - 若截图线程仍在运行：请求中断并等待其退出，避免
          "QThread: Destroyed while thread is still running" 崩溃。
        """
        self.core.unregister_hotkey()
        self._hotkey_enabled = False
        if self.worker is not None and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait(2000)
        super().closeEvent(event)

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
        sz = sizing()
        title_label.setStyleSheet(
            f"font-size: {sz['shot_title_font_size']}px; font-weight: bold; margin-bottom: {sz['shot_title_margin_bottom']}px;"
        )
        main_layout.addWidget(title_label)

        # Status label（提前创建，供设置 tab 接线 status_callback；仍置于底部）
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet(
            f"color: {theme_palette()['text_secondary']}; font-size: {sz['shot_status_font_size']}px;")

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
        self._settings_tab = _SettingsTab(
            tab_widget, self.context, self.core,
            self.status_label.setText, self._on_hotkey_triggered)
        tab_widget.addTab(self._settings_tab, "设置")

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)

        # Status label（加入布局，置于底部）
        main_layout.addWidget(self.status_label)

    def create_window_tab(self) -> QWidget:
        return _make_window_tab(self)

    def create_html_tab(self) -> QWidget:
        return _make_html_tab(self)

    def create_region_tab(self) -> QWidget:
        return _make_region_tab(self)

    def create_window_list_tab(self) -> QWidget:
        return _make_window_list_tab(self)

    def _on_hotkey_triggered(self):
        return _on_hotkey_triggered(self)

    def _on_delayed_hotkey(self):
        return _on_delayed_hotkey(self)

    def _on_html_path_changed(self, text: str):
        return _on_html_path_changed(self, text)

    def browse_html_file(self):
        """Browse for an HTML file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择 HTML 文件", "", "HTML 文件 (*.html *.htm);;所有文件 (*)")
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

    def capture_by_class(self):
        """Capture window by class name."""
        class_name = self.window_class_input.text().strip()
        if not class_name:
            QMessageBox.warning(self, "错误", "请输入窗口类名")
            return
        self.start_operation("window_class", class_name=class_name)

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
        self.start_operation("html_file", html_path=html_path, width=width, height=height)

    def capture_rss_preview(self):
        """Capture the RSS style preview HTML file."""
        project_root = Path(__file__).parent.parent.parent
        rss_preview_path = project_root / "rss_style_preview.html"
        if not rss_preview_path.exists():
            QMessageBox.warning(self, "错误",
                                f"未找到 RSS 样式预览文件:\n{rss_preview_path}")
            return
        width = self.html_width_spin.value()
        height = self.html_height_spin.value()
        self.start_operation("html_file", html_path=str(rss_preview_path),
                             width=width, height=height)

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
        self._apply_post_capture(output_path)
        if Path(output_path).exists():
            self.status_label.setText(f"截图成功: {output_path}")
            QMessageBox.information(self, "成功", f"截图已保存到:\n{output_path}")
        else:
            self.status_label.setText("截图成功（未保存到磁盘）")
            QMessageBox.information(self, "成功", "截图已完成")

    def _apply_post_capture(self, output_path: str):
        """按设置执行截图后处理（自动复制到剪贴板 / 自动保存）。"""
        apply_post_capture(self.context.config if self.context else None,
                           output_path)

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


def apply_post_capture(config, output_path: str) -> None:
    """按配置执行截图后处理：自动复制到剪贴板 / 自动保存。

    Args:
        config: AppConfig 实例（读取 screenshot.auto_copy / screenshot.auto_save）。
        output_path: 截图保存路径。
    """
    if config is None:
        return
    if config.module_setting("screenshot", "auto_copy", False):
        _copy_image_to_clipboard(output_path)
    if not config.module_setting("screenshot", "auto_save", True):
        try:
            Path(output_path).unlink(missing_ok=True)
        except OSError:
            pass


def _copy_image_to_clipboard(output_path: str) -> None:
    """将截图文件复制到系统剪贴板。"""
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is None:
        return
    image = QImage(output_path)
    if not image.isNull():
        QApplication.clipboard().setImage(image)