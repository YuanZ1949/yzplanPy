"""MCP 工具切片：截图功能 (screenshot_*)。

提供窗口截图、HTML 截图、区域截图、模块截图等功能。
"""

import os
import time
import json
import uuid
from pathlib import Path


# ── 数据访问层 ─────────────────────────────────────────────────────────

def _get_screenshot_core():
    """获取截图核心实例。"""
    from modules.screenshot.screenshot_core import ScreenshotCore
    return ScreenshotCore()


def _mcp_inbox_command(command, payload):
    """发送 MCP inbox 命令并等待回复。"""
    from core.constants import DATA_DIR
    inbox = os.path.join(DATA_DIR, "mcp_inbox")
    os.makedirs(inbox, exist_ok=True)
    
    # 创建回复文件
    reply_file = os.path.join(inbox, f"reply_{uuid.uuid4().hex}.json")
    payload["reply_file"] = reply_file
    payload["command"] = command
    
    # 写入命令
    path = os.path.join(inbox, f"{payload['id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    
    # 等待回复（最多 10 秒）
    start_time = time.time()
    while time.time() - start_time < 10:
        if os.path.exists(reply_file):
            try:
                with open(reply_file, "r", encoding="utf-8") as f:
                    result = json.load(f)
                os.remove(reply_file)
                return result
            except Exception:
                pass
        time.sleep(0.1)
    
    # 超时
    if os.path.exists(reply_file):
        os.remove(reply_file)
    return {"success": False, "result": "超时：GUI 未响应"}


# ── 截图功能 ───────────────────────────────────────────────────────────

def screenshot_window_by_title(title: str, filename: str = None):
    """按标题截图窗口。"""
    core = _get_screenshot_core()
    result = core.capture_window_by_title(title, filename)
    if result:
        return {"success": True, "path": result, "message": f"窗口截图成功: {title}"}
    return {"success": False, "message": f"未找到标题包含 '{title}' 的窗口"}


def screenshot_yzplan(filename: str = None):
    """截图 YZplan 主窗口。"""
    core = _get_screenshot_core()
    result = core.capture_yzplan_window(filename)
    if result:
        return {"success": True, "path": result, "message": "YZplan 主窗口截图成功"}
    return {"success": False, "message": "未找到 YZplan 主窗口"}


def screenshot_fullscreen(filename: str = None):
    """全屏截图。"""
    core = _get_screenshot_core()
    result = core.capture_full_screen(filename)
    if result:
        return {"success": True, "path": result, "message": "全屏截图成功"}
    return {"success": False, "message": "全屏截图失败"}


def screenshot_region(x: int, y: int, width: int, height: int, filename: str = None):
    """截图指定区域。"""
    core = _get_screenshot_core()
    result = core.capture_region(x, y, width, height, filename)
    if result:
        return {"success": True, "path": result, "message": f"区域截图成功: ({x},{y}) {width}x{height}"}
    return {"success": False, "message": "区域截图失败"}


def screenshot_html(html_path: str, filename: str = None, width: int = 1920, height: int = 1080):
    """截图 HTML 文件。"""
    core = _get_screenshot_core()
    result = core.capture_html_file_sync(html_path, filename, width, height)
    if result:
        return {"success": True, "path": result, "message": f"HTML 截图成功: {html_path}"}
    return {"success": False, "message": f"HTML 截图失败: {html_path}"}


def screenshot_html_rss_preview(filename: str = None, width: int = 1920, height: int = 1080):
    """截图 RSS 样式预览页面。"""
    # 尝试查找 rss_style_preview.html
    project_root = Path(__file__).parent.parent.parent
    rss_preview_path = project_root / "rss_style_preview.html"
    
    if not rss_preview_path.exists():
        return {"success": False, "message": f"未找到 RSS 样式预览文件: {rss_preview_path}"}
    
    core = _get_screenshot_core()
    result = core.capture_html_file_sync(str(rss_preview_path), filename, width, height)
    if result:
        return {"success": True, "path": result, "message": "RSS 样式预览截图成功"}
    return {"success": False, "message": "RSS 样式预览截图失败"}


def screenshot_list_windows():
    """列出所有可见窗口。"""
    core = _get_screenshot_core()
    windows = core.list_windows()
    window_list = []
    for hwnd, title, class_name in windows:
        window_list.append({
            "hwnd": hwnd,
            "title": title,
            "class_name": class_name
        })
    return {"windows": window_list, "count": len(window_list)}


def screenshot_module(module_id: str, filename: str = None, widget_type: str = None):
    """截图指定模块的 widget（需要 YZplan GUI 运行）。
    
    Args:
        module_id: 模块 ID（如 rss_aggregator）
        filename: 输出文件名（不含扩展名）
        widget_type: widget 类型，可选值：
            - None: 捕获第一个可见的 widget（默认）
            - "home": 捕获主页 widget
            - "page": 捕获页面 widget（完整界面）
    """
    from core.constants import DATA_DIR
    
    # 构建输出路径
    if filename:
        output_path = os.path.join(DATA_DIR, "screenshots", f"{filename}.png")
    else:
        output_path = None  # 由 GUI 端自动生成
    
    # 发送命令到 GUI
    payload = {
        "id": uuid.uuid4().hex,
        "module_id": module_id,
        "output_path": output_path,
        "widget_type": widget_type,
        "title": "截图",
        "message": f"正在截图模块: {module_id}",
        "silent": True,
    }
    
    result = _mcp_inbox_command("capture_module", payload)
    
    if result.get("success"):
        saved_path = result.get("result")
        return {"success": True, "path": saved_path, "message": f"模块截图成功: {module_id}"}
    else:
        return {"success": False, "message": result.get("result", "截图失败")}


def screenshot_module_geometry(module_id: str):
    """获取指定模块 widget 的几何信息（位置和大小）。"""
    payload = {
        "id": uuid.uuid4().hex,
        "module_id": module_id,
        "title": "获取模块信息",
        "message": f"正在获取模块 {module_id} 的几何信息",
        "silent": True,
    }
    
    result = _mcp_inbox_command("get_module_geometry", payload)
    
    if result.get("success"):
        geometry = result.get("result")
        return {"success": True, "geometry": geometry, "message": f"获取模块几何信息成功: {module_id}"}
    else:
        return {"success": False, "message": result.get("result", "获取几何信息失败")}


# ── MCP 工具定义 ──────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "screenshot_window_by_title",
        "description": "按标题截图指定窗口（支持部分匹配）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "必填，窗口标题（支持部分匹配）"},
                "filename": {"type": "string", "description": "输出文件名（不含扩展名），不填则自动生成"},
            },
            "required": ["title"],
        },
        "handler": lambda a: screenshot_window_by_title(a["title"], filename=a.get("filename")),
    },
    {
        "name": "screenshot_yzplan",
        "description": "截图 YZplan 主窗口。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "输出文件名（不含扩展名），不填则自动生成"},
            },
        },
        "handler": lambda a: screenshot_yzplan(filename=a.get("filename")),
    },
    {
        "name": "screenshot_fullscreen",
        "description": "全屏截图。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "输出文件名（不含扩展名），不填则自动生成"},
            },
        },
        "handler": lambda a: screenshot_fullscreen(filename=a.get("filename")),
    },
    {
        "name": "screenshot_region",
        "description": "截图指定屏幕区域。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "必填，X 坐标"},
                "y": {"type": "integer", "description": "必填，Y 坐标"},
                "width": {"type": "integer", "description": "必填，宽度"},
                "height": {"type": "integer", "description": "必填，高度"},
                "filename": {"type": "string", "description": "输出文件名（不含扩展名），不填则自动生成"},
            },
            "required": ["x", "y", "width", "height"],
        },
        "handler": lambda a: screenshot_region(a["x"], a["y"], a["width"], a["height"], 
                                               filename=a.get("filename")),
    },
    {
        "name": "screenshot_html",
        "description": "截图 HTML 文件（使用 WebEngine 渲染）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "html_path": {"type": "string", "description": "必填，HTML 文件路径"},
                "filename": {"type": "string", "description": "输出文件名（不含扩展名），不填则自动生成"},
                "width": {"type": "integer", "description": "渲染宽度，默认 1920"},
                "height": {"type": "integer", "description": "渲染高度，默认 1080"},
            },
            "required": ["html_path"],
        },
        "handler": lambda a: screenshot_html(a["html_path"], filename=a.get("filename"),
                                            width=a.get("width", 1920), height=a.get("height", 1080)),
    },
    {
        "name": "screenshot_html_rss_preview",
        "description": "截图 RSS 样式预览页面（rss_style_preview.html）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "输出文件名（不含扩展名），不填则自动生成"},
                "width": {"type": "integer", "description": "渲染宽度，默认 1920"},
                "height": {"type": "integer", "description": "渲染高度，默认 1080"},
            },
        },
        "handler": lambda a: screenshot_html_rss_preview(filename=a.get("filename"),
                                                        width=a.get("width", 1920), 
                                                        height=a.get("height", 1080)),
    },
    {
        "name": "screenshot_list_windows",
        "description": "列出所有可见窗口。",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda a: screenshot_list_windows(),
    },
    {
        "name": "screenshot_module",
        "description": "截图指定模块的 widget（需要 YZplan GUI 运行）。通过 MCP inbox 命令让 GUI 捕获模块的 widget。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "module_id": {"type": "string", "description": "必填，模块 ID（如 rss_aggregator）"},
                "filename": {"type": "string", "description": "输出文件名（不含扩展名），不填则自动生成"},
                "widget_type": {"type": "string", "description": "widget 类型：home（主页）、page（完整页面），不填则捕获第一个可见 widget"},
            },
            "required": ["module_id"],
        },
        "handler": lambda a: screenshot_module(a["module_id"], filename=a.get("filename"), widget_type=a.get("widget_type")),
    },
    {
        "name": "screenshot_module_geometry",
        "description": "获取指定模块 widget 的几何信息（位置和大小），可用于区域截图。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "module_id": {"type": "string", "description": "必填，模块 ID（如 rss_aggregator）"},
            },
            "required": ["module_id"],
        },
        "handler": lambda a: screenshot_module_geometry(a["module_id"]),
    },
]
