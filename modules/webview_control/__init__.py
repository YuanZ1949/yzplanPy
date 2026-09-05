"""webview_control 模块：msedgewebview2.exe 网络管控，通过 Windows 防火墙规则拦截 + 进程监控。"""
import ctypes
import logging
import os
import subprocess
import threading
import time

from ..base import ModuleBase

logger = logging.getLogger("webview_control")

from .constants import RULE_PREFIX, WEBVIEW2_SEARCH_PATHS
from .firewall import (
    _is_admin,
    _run_netsh,
    find_webview2_paths,
    get_firewall_rules,
    block_all,
    unblock_all,
    toggle_rule,
)
from .remote import block_remote_ip, unblock_rule, list_yzplan_rules
from .processes import scan_processes
from .info import MODULE_INFO
from .hosts import (
    _is_webview_pid,
    _proc_exe_path,
    _host_signature_for_webview,
    scan_hosts,
    _host_pid,
    kill_host_webview,
)
from .config import load_blocked_exes, save_blocked_exes
from .module import Module
from .home import _make_home_widget, blocked_host, _quick_block_all, _quick_unblock_all
from .page import _make_page_widget

__all__ = [
    "RULE_PREFIX",
    "WEBVIEW2_SEARCH_PATHS",
    "_is_admin",
    "_run_netsh",
    "find_webview2_paths",
    "get_firewall_rules",
    "block_all",
    "unblock_all",
    "toggle_rule",
    "block_remote_ip",
    "unblock_rule",
    "list_yzplan_rules",
    "scan_processes",
    "MODULE_INFO",
    "_is_webview_pid",
    "_proc_exe_path",
    "_host_signature_for_webview",
    "scan_hosts",
    "_host_pid",
    "kill_host_webview",
    "load_blocked_exes",
    "save_blocked_exes",
    "Module",
    "_make_home_widget",
    "blocked_host",
    "_quick_block_all",
    "_quick_unblock_all",
    "_make_page_widget",
]