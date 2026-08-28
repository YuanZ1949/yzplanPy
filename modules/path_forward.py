"""path_forward 模块：Ctrl+G 将最近资源管理器的地址注入当前聚焦的文件对话框。仅 Windows。"""
import ctypes
import ctypes.wintypes as wintypes
import time

from .base import ModuleBase

user32 = ctypes.WinDLL("user32", use_last_error=True)

VK_CONTROL = 0x11
VK_V = 0x56
VK_RETURN = 0x0D
KEYEVENTF_KEYUP = 0x0002


def get_last_explorer_path():
    """通过 Shell.Application 枚举资源管理器窗口，返回最近活跃窗口的本地路径。"""
    import win32com.client
    import pythoncom

    pythoncom.CoInitialize()
    try:
        shell = win32com.client.Dispatch("Shell.Application")
        fg = user32.GetForegroundWindow()
        candidates = []
        for win in shell.Windows():
            try:
                url = win.LocationURL or ""
                if not url.lower().startswith("file://"):
                    continue
                hwnd = int(win.HWND)
                candidates.append((url, hwnd))
            except Exception:
                continue
        # 优先：当前前台窗口本身是资源管理器；否则取枚举中最前面（通常为最近激活）
        for url, hwnd in candidates:
            if hwnd == fg:
                return _url_to_path(url)
        if candidates:
            return _url_to_path(candidates[0][0])
        return None
    finally:
        pythoncom.CoUninitialize()


def _url_to_path(url):
    from urllib.parse import unquote, urlsplit
    parts = urlsplit(url)
    host = parts.netloc or ""
    path = parts.path or ""

    if host:
        if len(host) == 2 and host[1] == ":" and host[0].isalpha():
            # file://C:/foo -> 盘符路径（host 已含冒号）
            p = host + path
        elif host.lower() in ("localhost", ""):
            p = path
        else:
            # UNC：\\server\share\path
            return unquote("\\\\" + host + path).replace("/", "\\")
        return unquote(p).replace("/", "\\")

    # file:///C:/... 或 file:///path
    p = unquote(path)
    if len(p) > 2 and p[0] == "/" and p[2] == ":":
        p = p[1:]
    return p.replace("/", "\\")


def inject_path(path):
    """将路径粘贴到当前聚焦窗口（文件对话框的“文件名”输入框），并回车。"""
    if not path:
        return False
    _set_clipboard(path)
    fg = user32.GetForegroundWindow()
    user32.SetForegroundWindow(fg)
    time.sleep(0.05)
    _key(VK_CONTROL, press=True)
    _key(VK_V, press=True)
    time.sleep(0.05)
    _key(VK_V, press=False)
    _key(VK_CONTROL, press=False)
    time.sleep(0.03)
    _key(VK_RETURN, press=True)
    _key(VK_RETURN, press=False)
    return True


def _set_clipboard(text):
    import win32clipboard
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


def _key(vk, press=True):
    flags = 0 if press else KEYEVENTF_KEYUP
    user32.keybd_event(vk, 0, flags, 0)


MODULE_INFO = {
    "id": "path_forward",
    "name": "路径传递",
    "description": "Ctrl+G：将最近资源管理器地址填入当前聚焦的文件对话框",
}


class Module(ModuleBase):
    MODULE_ID = "path_forward"
    MODULE_NAME = "路径传递"
    MODULE_DESCRIPTION = "Ctrl+G：将最近资源管理器地址填入当前聚焦的文件对话框"

    def __init__(self, context):
        super().__init__(context)
        self._last_path = None

    def start(self):
        super().start()
        try:
            from core.hotkey import HotKeyFilter
            self.hotkey = HotKeyFilter(self.context.app)
            self.hotkey.register("path_forward", self._on_hotkey)
        except Exception:
            self.hotkey = None

    def stop(self):
        if self.hotkey is not None:
            self.hotkey.release()
            self.hotkey = None
        super().stop()

    def _on_hotkey(self):
        try:
            path = get_last_explorer_path()
            if not path:
                return
            self._last_path = path
            inject_path(path)
        except Exception:
            pass

    def create_home_widget(self, parent):
        return _make_home_widget(self, parent)


def _make_home_widget(owner, parent):
    from core.qt_bootstrap import import_qt
    _, QtCore, QtGui, QtWidgets = import_qt()
    w = QtWidgets.QWidget(parent)
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(8, 8, 8, 8)
    title = QtWidgets.QLabel("路径传递")
    title.setStyleSheet("font-weight: bold;")
    lbl = QtWidgets.QLabel("最近资源管理器地址：<空白>")
    lbl.setWordWrap(True)
    btn = QtWidgets.QPushButton("捕获当前窗口地址并注入")
    btn.clicked.connect(owner._on_hotkey)
    lay.addWidget(title)
    lay.addWidget(lbl)
    lay.addWidget(btn)
    lbl.setProperty("yzplan_lbl", True)
    return w