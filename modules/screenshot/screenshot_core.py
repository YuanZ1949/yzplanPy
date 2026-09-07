"""
Screenshot Core Module for YZplan
Provides window capture, HTML rendering, and region screenshot capabilities.
"""

import os
import sys
import time
from pathlib import Path
from typing import Optional, Tuple, List
from datetime import datetime

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import Qt, QRect, QTimer, QUrl
from PySide6.QtGui import QPixmap, QScreen, QPainter, QColor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings

import win32gui
import win32ui
import win32con
import win32api


class ScreenshotCore:
    """Core screenshot functionality for capturing windows, regions, and HTML content."""
    
    def __init__(self, output_dir: str = None):
        """
        Initialize the screenshot core.
        
        Args:
            output_dir: Directory to save screenshots. Defaults to data/screenshots/
        """
        if output_dir is None:
            # Default to data/screenshots/ in the project root
            project_root = Path(__file__).parent.parent.parent
            output_dir = project_root / "data" / "screenshots"
        
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Store QWebEngineView instance for HTML screenshots
        self._web_view = None
        
    def capture_window_by_title(self, window_title: str, output_filename: str = None) -> Optional[str]:
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
    
    def capture_window_by_class(self, window_class: str, output_filename: str = None) -> Optional[str]:
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
    
    def capture_window(self, hwnd: int, output_filename: str = None) -> Optional[str]:
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
                          QImage.Format_RGB32)
            
            # Generate filename if not provided
            if output_filename is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                window_title = win32gui.GetWindowText(hwnd)
                safe_title = "".join(c for c in window_title if c.isalnum() or c in (' ', '-', '_')).strip()
                if not safe_title:
                    safe_title = f"window_{hwnd}"
                output_filename = f"{safe_title}_{timestamp}"
            
            # Save the screenshot
            output_path = self.output_dir / f"{output_filename}.png"
            image.save(str(output_path), "PNG")
            
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
    
    def capture_yzplan_window(self, output_filename: str = None) -> Optional[str]:
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
                      output_filename: str = None) -> Optional[str]:
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
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_filename = f"region_{x}_{y}_{width}x{height}_{timestamp}"
            
            # Save the screenshot
            output_path = self.output_dir / f"{output_filename}.png"
            pixmap.save(str(output_path), "PNG")
            
            print(f"Region captured successfully: {output_path}")
            return str(output_path)
            
        except Exception as e:
            print(f"Error capturing region: {e}")
            return None
    
    def capture_full_screen(self, output_filename: str = None) -> Optional[str]:
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
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_filename = f"screenshot_{timestamp}"
            
            # Save the screenshot
            output_path = self.output_dir / f"{output_filename}.png"
            pixmap.save(str(output_path), "PNG")
            
            print(f"Screen captured successfully: {output_path}")
            return str(output_path)
            
        except Exception as e:
            print(f"Error capturing screen: {e}")
            return None
    
    def capture_html_file(self, html_file_path: str, output_filename: str = None,
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
                settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
                settings.setAttribute(QWebEngineSettings.PluginsEnabled, True)
                settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
            
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
    
    def capture_html_file_sync(self, html_file_path: str, output_filename: str = None,
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
            settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
            settings.setAttribute(QWebEngineSettings.PluginsEnabled, True)
            settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
            settings.setAttribute(QWebEngineSettings.LocalStorageEnabled, True)
            
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
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_filename = f"html_{html_path.stem}_{timestamp}"
            
            # Save the screenshot
            output_path = self.output_dir / f"{output_filename}.png"
            pixmap.save(str(output_path), "PNG")
            
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
    
    def _capture_web_view(self, html_path: Path, output_filename: str):
        """Internal method to capture web view after rendering."""
        try:
            if self._web_view is None:
                return
            
            # Capture the web view
            pixmap = self._web_view.grab()
            
            # Generate filename if not provided
            if output_filename is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_filename = f"html_{html_path.stem}_{timestamp}"
            
            # Save the screenshot
            output_path = self.output_dir / f"{output_filename}.png"
            pixmap.save(str(output_path), "PNG")
            
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
    
    def capture_window_by_hwnd(self, hwnd: int, output_filename: str = None) -> Optional[str]:
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
def screenshot_html(html_path: str, output_path: str = None, 
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
