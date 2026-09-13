"""Win11 DWM 兼容：彻底关闭系统 Mica backdrop，消除 WebEngine 预览的 DWM 闪烁源。

qfluentwidgets FramelessWindow（Win11）默认 setMicaEffect → 写
DWMWA_SYSTEMBACKDROP_TYPE=2（系统 DWM backdrop）；其 removeBackgroundEffect
只把 WCA_ACCENT_POLICY 置 DISABLED，不重置该 DWM 属性 → “半白”Mica 常驻，
与 WebEngine 双合成器叠加（历史黑屏/闪烁源）。本模块把系统 backdrop 归零
并保底保留 Win11 圆角：初始即纯色，预览前后视觉一致（“半白变透明”消失）。
非 Win11 / hWnd 无效 / 调用失败一律静默返回 False。
"""

import ctypes
import sys

_DWMWA_SYSTEMBACKDROP_TYPE = 38
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWCP_ROUND = 1  # DWMWCP_ROUND：圆角


def disable_mica_backdrop(hwnd):
    """关闭窗口的系统 DWM backdrop（Mica），保底保留 Win11 圆角。

    成功返回 True；非 win32、hWnd 无效或 DWM 调用失败静默返回 False。
    """
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        dwmapi = ctypes.windll.dwmapi
        fn = dwmapi.DwmSetWindowAttribute
        fn.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
        fn.restype = ctypes.c_long
        # 系统 backdrop 归零：关闭 Mica（Win11 build>=22000 才支持，旧系统失败静默）
        fn(ctypes.c_void_p(hwnd), _DWMWA_SYSTEMBACKDROP_TYPE,
           ctypes.byref(ctypes.c_int(0)), 4)
        # 关闭 backdrop 后 DWM 可能回落为无圆角，显式保留 Win11 圆角
        fn(ctypes.c_void_p(hwnd), _DWMWA_WINDOW_CORNER_PREFERENCE,
           ctypes.byref(ctypes.c_int(_DWMWCP_ROUND)), 4)
        return True
    except Exception:
        return False