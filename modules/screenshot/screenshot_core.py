"""
Screenshot Core Module for YZplan
Provides window capture, HTML rendering, and region screenshot capabilities.
"""

import os
import sys
import time
import ctypes
import ctypes.wintypes as wintypes
from pathlib import Path
from typing import Optional, Tuple, List, Callable
from datetime import datetime

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import Qt, QRect, QTimer, QUrl, QAbstractNativeEventFilter
from PySide6.QtGui import QPixmap, QScreen, QPainter, QColor, QKeySequence
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings

import win32gui
import win32ui
import win32con
import win32api

# ── 全局快捷键（Win32 RegisterHotKey + WM_HOTKEY 原生事件过滤器）──────────
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312

_user32 = ctypes.WinDLL("user32", use_last_error=True)


# Qt 特殊键 → Win32 虚拟键码（仅常用可作快捷键的键）
_QT_SPECIAL_TO_VK = {
    Qt.Key_Escape: 0x1B,       # VK_ESCAPE  # type: ignore[reportAttributeAccessIssue]
    Qt.Key_Tab: 0x09,          # VK_TAB  # type: ignore[reportAttributeAccessIssue]
    Qt.Key_Backspace: 0x08,    # VK_BACK  # type: ignore[reportAttributeAccessIssue]
    Qt.Key_Return: 0x0D,       # VK_RETURN  # type: ignore[reportAttributeAccessIssue]
    Qt.Key_Enter: 0x0D,        # VK_RETURN  # type: ignore[reportAttributeAccessIssue]
    Qt.Key_Insert: 0x2D,       # VK_INSERT  # type: ignore[reportAttributeAccessIssue]
    Qt.Key_Delete: 0x2E,       # VK_DELETE  # type: ignore[reportAttributeAccessIssue]
    Qt.Key_Home: 0x24,         # VK_HOME  # type: ignore[reportAttributeAccessIssue]
    Qt.Key_End: 0x23,          # VK_END  # type: ignore[reportAttributeAccessIssue]
    Qt.Key_PageUp: 0x21,       # VK_PRIOR  # type: ignore[reportAttributeAccessIssue]
    Qt.Key_PageDown: 0x22,     # VK_NEXT  # type: ignore[reportAttributeAccessIssue]
    Qt.Key_Left: 0x25,         # VK_LEFT  # type: ignore[reportAttributeAccessIssue]
    Qt.Key_Up: 0x26,           # VK_UP  # type: ignore[reportAttributeAccessIssue]
    Qt.Key_Right: 0x27,        # VK_RIGHT  # type: ignore[reportAttributeAccessIssue]
    Qt.Key_Down: 0x28,         # VK_DOWN  # type: ignore[reportAttributeAccessIssue]
    Qt.Key_Print: 0x2C,        # VK_SNAPSHOT  # type: ignore[reportAttributeAccessIssue]
    Qt.Key_Pause: 0x13,        # VK_PAUSE  # type: ignore[reportAttributeAccessIssue]
}

_QT_KEY_SPECIAL_FLAG = 0x01000000


def _key_sequence_to_hotkey(seq: QKeySequence):
    """将 QKeySequence 解析为 (modifiers, vk)。返回 (None, None) 表示无效。"""
    if seq.isEmpty():
        return None, None
    comb = seq[0]  # type: ignore[reportIndexIssue]
    modifiers = 0
    mods = comb.keyboardModifiers()
    if mods & Qt.KeyboardModifier.ControlModifier:
        modifiers |= MOD_CONTROL
    if mods & Qt.KeyboardModifier.AltModifier:
        modifiers |= MOD_ALT
    if mods & Qt.KeyboardModifier.ShiftModifier:
        modifiers |= MOD_SHIFT
    if mods & Qt.KeyboardModifier.MetaModifier:
        modifiers |= MOD_WIN

    qt_key = int(comb.key())
    if qt_key == 0:
        return None, None

    # 特殊键（带 0x01000000 标志）
    if qt_key & _QT_KEY_SPECIAL_FLAG:
        vk = _QT_SPECIAL_TO_VK.get(qt_key)
        if vk is None:
            # F1-F35: Qt 0x01000030+n → Win32 0x70+n
            f_base = Qt.Key_F1  # type: ignore[reportAttributeAccessIssue]
            if f_base <= qt_key <= Qt.Key_F35:  # type: ignore[reportAttributeAccessIssue]
                vk = 0x70 + (qt_key - f_base)
        if vk is None:
            return None, None
        return modifiers, vk

    # 普通键（字母/数字/符号）：Qt 码 == Win32 VK 码
    return modifiers, qt_key


class ScreenshotHotKeyFilter(QAbstractNativeEventFilter):
    """全局快捷键原生事件过滤器：支持可配置修饰键与虚拟键。"""

    def __init__(self, app, modifiers: int, vk: int, hotkey_id: int = 0xBB02):
        super().__init__()
        self.app = app
        self.hotkey_id = hotkey_id
        self.callbacks = []
        self._registered = False
        self._register(modifiers, vk)

    def _register(self, modifiers: Optional[int], vk: Optional[int]):
        if self._registered:
            _user32.UnregisterHotKey(None, self.hotkey_id)
            self._registered = False
        if modifiers is None or vk is None:
            return
        ok = _user32.RegisterHotKey(None, self.hotkey_id, modifiers, vk)
        if ok:
            self._registered = True
            self.app.installNativeEventFilter(self)

    def re_register(self, modifiers: Optional[int], vk: Optional[int]):
        """重新注册（用于快捷键变更）。"""
        if self._registered:
            self.app.removeNativeEventFilter(self)
        self._register(modifiers, vk)

    def nativeEventFilter(self, event_type, message, result=None):
        msg = wintypes.MSG.from_address(int(message))
        if msg.message == WM_HOTKEY and msg.wParam == self.hotkey_id:
            for cb in self.callbacks:
                try:
                    cb()
                except Exception:
                    pass
            return True, 0
        return False, 0

    def add_callback(self, callback: Callable):
        self.callbacks.append(callback)

    def release(self):
        if self._registered:
            self.app.removeNativeEventFilter(self)
            _user32.UnregisterHotKey(None, self.hotkey_id)
            self._registered = False
        self.callbacks.clear()


class ScreenshotCore:
    """Core screenshot functionality for capturing windows, regions, and HTML content."""
    
    def __init__(self, output_dir: Optional[str] = None, config=None):
        """
        Initialize the screenshot core.
        
        Args:
            output_dir: Directory to save screenshots. Defaults to data/screenshots/
            config: AppConfig 实例；非空时应用 modules.screenshot.config 的
                save_dir / format / filename_template 设置。
        """
        if output_dir is None:
            # Default to data/screenshots/ in the project root
            project_root = Path(__file__).parent.parent.parent
            output_dir = str(project_root / "data" / "screenshots")

        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 图片格式与文件名模板（可被模块设置覆盖）
        self._format = "PNG"
        self._filename_template = "screenshot_%Y%m%d_%H%M%S"

        if config is not None:
            save_dir = config.module_setting("screenshot", "save_dir")
            if save_dir:
                self.output_dir = Path(save_dir)
                self.output_dir.mkdir(parents=True, exist_ok=True)
            fmt = config.module_setting("screenshot", "format", "PNG")
            if fmt in ("PNG", "JPG"):
                self._format = fmt
            tpl = config.module_setting("screenshot", "filename_template")
            if tpl:
                self._filename_template = tpl

        # Store QWebEngineView instance for HTML screenshots
        self._web_view = None

        # 全局快捷键
        self._hotkey_filter = None

    # ── 全局快捷键 ──────────────────────────────────────────────────────
    def register_hotkey(self, key_sequence: QKeySequence, callback: Callable,
                        app=None) -> bool:
        """注册全局快捷键。

        Args:
            key_sequence: QKeySequence 快捷键（如 Ctrl+Shift+S）
            callback: 触发回调
            app: QApplication 实例；为 None 时使用 QApplication.instance()

        Returns:
            是否注册成功
        """
        modifiers, vk = _key_sequence_to_hotkey(key_sequence)
        if modifiers is None or vk is None:
            return False
        if app is None:
            app = QApplication.instance()
        if app is None:
            return False
        if self._hotkey_filter is None:
            self._hotkey_filter = ScreenshotHotKeyFilter(app, modifiers, vk)
        else:
            self._hotkey_filter.re_register(modifiers, vk)
        self._hotkey_filter.add_callback(callback)
        return self._hotkey_filter._registered

    def unregister_hotkey(self):
        """注销全局快捷键。"""
        if self._hotkey_filter is not None:
            self._hotkey_filter.release()
            self._hotkey_filter = None

    def is_hotkey_registered(self) -> bool:
        """是否已注册全局快捷键。"""
        return self._hotkey_filter is not None and self._hotkey_filter._registered

    def capture_window_by_title(self, window_title: str, output_filename: Optional[str] = None) -> Optional[str]:
        """
        Capture a window by its title.
        
        Args:
            window_title: Title of the window to capture (partial match)
            output_filename: Output filename (without extension). Auto-generated if None.
            
        Returns:
            Path to the saved screenshot, or None if failed.
        """
        try:
            # Find window by title
            hwnd = self._find_window_by_title(window_title)
            if hwnd is None:
                print(f"Window not found: {window_title}")
                return None
            
            return self.capture_window(hwnd, output_filename)
            
        except Exception as e:
            print(f"Error capturing window by title: {e}")
            return None
    
    def capture_window_by_class(self, window_class: str, output_filename: Optional[str] = None) -> Optional[str]:
        """
        Capture a window by its class name.
        
        Args:
            window_class: Class name of the window to capture
            output_filename: Output filename (without extension). Auto-generated if None.
            
        Returns:
            Path to the saved screenshot, or None if failed.
        """
        try:
            # Find window by class
            hwnd = win32gui.FindWindow(window_class, None)
            if hwnd is None:
                print(f"Window not found by class: {window_class}")
                return None
            
            return self.capture_window(hwnd, output_filename)
            
        except Exception as e:
            print(f"Error capturing window by class: {e}")
            return None
    
    def capture_window(self, hwnd: int, output_filename: Optional[str] = None) -> Optional[str]:
        """
        Capture a specific window handle.
        
        Args:
            hwnd: Window handle (HWND)
            output_filename: Output filename (without extension). Auto-generated if None.
            
        Returns:
            Path to the saved screenshot, or None if failed.
        """
        try:
            # Get window rect
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            width = right - left
            height = bottom - top
            
            if width <= 0 or height <= 0:
                print(f"Invalid window dimensions: {width}x{height}")
                return None
            
            # Create device contexts
            hwnd_dc = win32gui.GetWindowDC(hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()
            
            # Create bitmap
            save_bit_map = win32ui.CreateBitmap()
            save_bit_map.CreateCompatibleBitmap(mfc_dc, width, height)
            save_dc.SelectObject(save_bit_map)
            
            # Copy window content
            save_dc.BitBlt((0, 0), (width, height), mfc_dc, (0, 0), win32con.SRCCOPY)
            
            # Convert to QPixmap
            bmpinfo = save_bit_map.GetInfo()
            bmpstr = save_bit_map.GetBitmapBits(True)
            
            # Create QImage from bitmap data
            from PySide6.QtGui import QImage
            image = QImage(bmpstr, bmpinfo['bmWidth'], bmpinfo['bmHeight'], 
                          QImage.Format_RGB32)  # type: ignore[reportAttributeAccessIssue]
            
            # Generate filename if not provided
            if output_filename is None:
                timestamp = datetime.now().strftime(self._filename_template)
                window_title = win32gui.GetWindowText(hwnd)
                safe_title = "".join(c for c in window_title if c.isalnum() or c in (' ', '-', '_')).strip()
                if not safe_title:
                    safe_title = f"window_{hwnd}"
                output_filename = f"{safe_title}_{timestamp}"
            
            # Save the screenshot
            ext = self._format.lower()
            output_path = self.output_dir / f"{output_filename}.{ext}"
            image.save(str(output_path), self._format)  # type: ignore[reportArgumentType, reportCallIssue]
            
            # Cleanup
            win32gui.DeleteObject(save_bit_map.GetHandle())
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwnd_dc)
            
            print(f"Window captured successfully: {output_path}")
            return str(output_path)
            
        except Exception as e:
            print(f"Error capturing window: {e}")
            return None
    
    def capture_yzplan_window(self, output_filename: Optional[str] = None) -> Optional[str]:
        """
        Capture the YZplan main window.
        
        Args:
            output_filename: Output filename (without extension). Auto-generated if None.
            
        Returns:
            Path to the saved screenshot, or None if failed.
        """
        # Try to find YZplan window by class or title
        try:
            # First try by window class (common for PySide6 apps)
            hwnd = win32gui.FindWindow("PySide6Window", None)
            if hwnd is None:
                # Try by title
                hwnd = self._find_window_by_title("YZplan")
            
            if hwnd is None:
                print("YZplan window not found")
                return None
            
            return self.capture_window(hwnd, output_filename)
            
        except Exception as e:
            print(f"Error capturing YZplan window: {e}")
            return None
    
    def capture_region(self, x: int, y: int, width: int, height: int, 
                      output_filename: Optional[str] = None) -> Optional[str]:
        """
        Capture a specific region of the screen.
        
        Args:
            x: X coordinate of the top-left corner
            y: Y coordinate of the top-left corner
            width: Width of the region
            height: Height of the region
            output_filename: Output filename (without extension). Auto-generated if None.
            
        Returns:
            Path to the saved screenshot, or None if failed.
        """
        try:
            # Get screen size
            screen = QApplication.primaryScreen()
            if screen is None:
                print("No screen available")
                return None
            
            # Capture the region
            pixmap = screen.grabWindow(0, x, y, width, height)
            
            if pixmap.isNull():
                print("Failed to capture region")
                return None
            
            # Generate filename if not provided
            if output_filename is None:
                timestamp = datetime.now().strftime(self._filename_template)
                output_filename = f"region_{x}_{y}_{width}x{height}_{timestamp}"
            
            # Save the screenshot
            ext = self._format.lower()
            output_path = self.output_dir / f"{output_filename}.{ext}"
            pixmap.save(str(output_path), self._format)
            
            print(f"Region captured successfully: {output_path}")
            return str(output_path)
            
        except Exception as e:
            print(f"Error capturing region: {e}")
            return None
    
    def capture_full_screen(self, output_filename: Optional[str] = None) -> Optional[str]:
        """
        Capture the entire screen.
        
        Args:
            output_filename: Output filename (without extension). Auto-generated if None.
            
        Returns:
            Path to the saved screenshot, or None if failed.
        """
        try:
            # Get screen
            screen = QApplication.primaryScreen()
            if screen is None:
                print("No screen available")
                return None
            
            # Capture full screen
            pixmap = screen.grabWindow(0)
            
            if pixmap.isNull():
                print("Failed to capture screen")
                return None
            
            # Generate filename if not provided
            if output_filename is None:
                timestamp = datetime.now().strftime(self._filename_template)
                output_filename = f"{timestamp}"
            
            # Save the screenshot
            ext = self._format.lower()
            output_path = self.output_dir / f"{output_filename}.{ext}"
            pixmap.save(str(output_path), self._format)
            
            print(f"Screen captured successfully: {output_path}")
            return str(output_path)
            
        except Exception as e:
            print(f"Error capturing screen: {e}")
            return None
    
    def capture_html_file(self, html_file_path: str, output_filename: Optional[str] = None,
                          width: int = 1920, height: int = 1080, 
                          wait_time: int = 2000) -> Optional[str]:
        """
        Capture an HTML file by rendering it in a web engine.
        
        Args:
            html_file_path: Path to the HTML file
            output_filename: Output filename (without extension). Auto-generated if None.
            width: Width of the render window
            height: Height of the render window
            wait_time: Time to wait for rendering (milliseconds)
            
        Returns:
            Path to the saved screenshot, or None if failed.
        """
        try:
            html_path = Path(html_file_path)
            if not html_path.exists():
                print(f"HTML file not found: {html_file_path}")
                return None
            
            # Create web view if not exists
            if self._web_view is None:
                self._web_view = QWebEngineView()
                # Configure web engine settings
                settings = self._web_view.settings()
                settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)  # type: ignore[reportAttributeAccessIssue]
                settings.setAttribute(QWebEngineSettings.PluginsEnabled, True)  # type: ignore[reportAttributeAccessIssue]
                settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)  # type: ignore[reportAttributeAccessIssue]
            
            # Set window size
            self._web_view.resize(width, height)
            
            # Load the HTML file
            file_url = QUrl.fromLocalFile(str(html_path.absolute()))
            self._web_view.setUrl(file_url)
            
            # Wait for rendering
            QTimer.singleShot(wait_time, lambda: self._capture_web_view(html_path, output_filename))
            
            print(f"HTML file loading: {html_path}")
            return None  # Async operation
            
        except Exception as e:
            print(f"Error capturing HTML file: {e}")
            return None
    
    def capture_html_file_sync(self, html_file_path: str, output_filename: Optional[str] = None,
                              width: int = 1920, height: int = 1080,
                              wait_time: int = 3000) -> Optional[str]:
        """
        Capture an HTML file synchronously with proper page load waiting.
        
        Args:
            html_file_path: Path to the HTML file
            output_filename: Output filename (without extension). Auto-generated if None.
            width: Width of the render window
            height: Height of the render window
            wait_time: Time to wait for rendering (milliseconds)
            
        Returns:
            Path to the saved screenshot, or None if failed.
        """
        try:
            html_path = Path(html_file_path)
            if not html_path.exists():
                print(f"HTML file not found: {html_file_path}")
                return None
            
            # Create web view
            web_view = QWebEngineView()
            
            # Configure web engine settings
            settings = web_view.settings()
            settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)  # type: ignore[reportAttributeAccessIssue]
            settings.setAttribute(QWebEngineSettings.PluginsEnabled, True)  # type: ignore[reportAttributeAccessIssue]
            settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)  # type: ignore[reportAttributeAccessIssue]
            settings.setAttribute(QWebEngineSettings.LocalStorageEnabled, True)  # type: ignore[reportAttributeAccessIssue]
            
            # Set window size
            web_view.resize(width, height)
            
            # Track page load status
            page_loaded = [False]
            
            def on_load_finished(ok):
                page_loaded[0] = True
                print(f"Page load finished: {ok}")
            
            web_view.loadFinished.connect(on_load_finished)
            
            # Load the HTML file
            file_url = QUrl.fromLocalFile(str(html_path.absolute()))
            print(f"Loading HTML: {file_url.toString()}")
            web_view.setUrl(file_url)
            
            # Show the web view
            web_view.show()
            
            # Process events and wait for page load
            start_time = time.time()
            max_wait = wait_time / 1000.0  # Convert to seconds
            
            while not page_loaded[0] and (time.time() - start_time) < max_wait:
                QApplication.processEvents()
                time.sleep(0.1)
            
            # Additional wait for rendering
            remaining = max(0, (wait_time / 1000.0) - (time.time() - start_time))
            if remaining > 0:
                end_time = time.time() + remaining
                while time.time() < end_time:
                    QApplication.processEvents()
                    time.sleep(0.1)
            
            # Grab the page content
            pixmap = web_view.grab()
            
            # Generate filename if not provided
            if output_filename is None:
                timestamp = datetime.now().strftime(self._filename_template)
                output_filename = f"html_{html_path.stem}_{timestamp}"
            
            # Save the screenshot
            ext = self._format.lower()
            output_path = self.output_dir / f"{output_filename}.{ext}"
            pixmap.save(str(output_path), self._format)
            
            # Cleanup
            web_view.close()
            web_view.deleteLater()
            
            print(f"HTML file captured successfully: {output_path}")
            return str(output_path)
            
        except Exception as e:
            print(f"Error capturing HTML file: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _capture_web_view(self, html_path: Path, output_filename: str | None):
        """Internal method to capture web view after rendering."""
        try:
            if self._web_view is None:
                return
            
            # Capture the web view
            pixmap = self._web_view.grab()
            
            # Generate filename if not provided
            if output_filename is None:
                timestamp = datetime.now().strftime(self._filename_template)
                output_filename = f"html_{html_path.stem}_{timestamp}"
            
            # Save the screenshot
            ext = self._format.lower()
            output_path = self.output_dir / f"{output_filename}.{ext}"
            pixmap.save(str(output_path), self._format)
            
            print(f"HTML file captured successfully: {output_path}")
            
        except Exception as e:
            print(f"Error capturing web view: {e}")
    
    def _find_window_by_title(self, title: str) -> Optional[int]:
        """Find a window handle by its title (partial match)."""
        result = None
        
        def callback(hwnd, _):
            nonlocal result
            if win32gui.IsWindowVisible(hwnd):
                window_title = win32gui.GetWindowText(hwnd)
                if title.lower() in window_title.lower():
                    result = hwnd
            return True
        
        win32gui.EnumWindows(callback, None)
        return result
    
    def list_windows(self) -> List[Tuple[int, str, str]]:
        """
        List all visible windows.
        
        Returns:
            List of tuples: (hwnd, title, class_name)
        """
        windows = []
        
        def callback(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title:  # Only include windows with titles
                    class_name = win32gui.GetClassName(hwnd)
                    windows.append((hwnd, title, class_name))
            return True
        
        win32gui.EnumWindows(callback, None)
        return windows
    
    def capture_window_by_hwnd(self, hwnd: int, output_filename: Optional[str] = None) -> Optional[str]:
        """
        Capture a window by its handle.
        
        Args:
            hwnd: Window handle
            output_filename: Output filename (without extension). Auto-generated if None.
            
        Returns:
            Path to the saved screenshot, or None if failed.
        """
        return self.capture_window(hwnd, output_filename)


# Convenience function for quick HTML screenshot
def screenshot_html(html_path: str, output_path: Optional[str] = None, 
                   width: int = 1920, height: int = 1080) -> Optional[str]:
    """
    Quick function to screenshot an HTML file.
    
    Args:
        html_path: Path to the HTML file
        output_path: Output path (without extension). Auto-generated if None.
        width: Width of the render window
        height: Height of the render window
        
    Returns:
        Path to the saved screenshot, or None if failed.
    """
    core = ScreenshotCore()
    return core.capture_html_file_sync(html_path, output_path, width, height)
