"""ScreenshotWorker thread (extracted to meet file-size budget)."""
from PySide6.QtCore import QThread, Signal
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
