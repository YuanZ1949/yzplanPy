"""webview_control - constants: rule prefix and WebView2 search paths."""
import os

RULE_PREFIX = "YZplan_BlockWebView2"

WEBVIEW2_SEARCH_PATHS = [
    os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\EdgeWebView2"),
    os.path.expandvars(r"%ProgramFiles%\Microsoft\EdgeWebView2"),
    os.path.expandvars(r"%LocalAppData%\Microsoft\EdgeWebView2"),
]
