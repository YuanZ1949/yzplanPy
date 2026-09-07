"""webview_control - constants: rule prefix and WebView2 search paths."""
import os

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

HOST_STATUS_COLORS = {
    "pending": "#e67e22",
    "allowed": "#27ae60",
    "blocked": "#e74c3c",
}
