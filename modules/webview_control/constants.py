"""webview_control - constants: rule prefix and WebView2 search paths."""
import os

from core.theme.tokens import theme_palette

RULE_PREFIX = "YZplan_BlockWebView2"

WEBVIEW2_SEARCH_PATHS = [
    os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\EdgeWebView2"),
    os.path.expandvars(r"%ProgramFiles%\Microsoft\EdgeWebView2"),
    os.path.expandvars(r"%LocalAppData%\Microsoft\EdgeWebView2"),
]

HOST_STATUS_LABELS = {
    "pending": "待处置",
    "allowed": "已放行",
    "blocked": "已拦截",
}

def host_status_colors():
    """链接状态色（主题感知，值来自全局令牌）。"""
    p = theme_palette()
    return {
        "pending": p["webview_pending"],
        "allowed": p["webview_allowed"],
        "blocked": p["webview_blocked"],
    }
