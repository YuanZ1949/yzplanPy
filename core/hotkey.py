"""全局快捷键：Win32 RegisterHotKey + WM_HOTKEY 原生事件过滤器。仅 Windows。"""
import ctypes
import ctypes.wintypes as wintypes

from .qt_bootstrap import import_qt

_, QtCore, QtGui, QtWidgets = import_qt()

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312

user32 = ctypes.WinDLL("user32", use_last_error=True)


class HotKeyFilter(QtCore.QAbstractNativeEventFilter):
    def __init__(self, app, hotkey_id=0xBB01, modifiers=MOD_CONTROL, vk=ord("G")):
        super().__init__()
        self.app = app
        self.hotkey_id = hotkey_id
        self.callbacks = {}
        user32.RegisterHotKey(None, hotkey_id, modifiers, vk)
        app.installNativeEventFilter(self)

    def nativeEventFilter(self, event_type, message, result=None):
        msg = ctypes.wintypes.MSG.from_address(int(message))
        if msg.message == WM_HOTKEY and msg.wParam == self.hotkey_id:
            for cb in self.callbacks.values():
                cb()
            return True, 0
        return False, 0

    def register(self, callback_id, callback):
        self.callbacks[callback_id] = callback

    def unregister(self, callback_id):
        self.callbacks.pop(callback_id, None)

    def release(self):
        self.app.removeNativeEventFilter(self)
        user32.UnregisterHotKey(None, self.hotkey_id)