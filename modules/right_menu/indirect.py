"""right_menu 间接字符串解析：`@shell32.dll,-51608` → 菜单里真实文字（Qt-free）。

Windows 把右键项的显示名写成**间接字符串**（`MUIVerb` 以 `@` 开头），真实文字存在
DLL 的资源表里，格式两种：`@module.dll,-id` 与 `@module.dll,section,-id`（可带
`%SystemRoot%` 环境变量）。解析用 `shlwapi.SHLoadIndirectString`——它同时吃这两种
形式，且对资源不存在返回失败（实测 E_FAIL），比手搓 LoadLibrary/LoadString 稳。

跨任务契约（`scan.py` 要求）：
  * **Qt-free**：只 import ctypes，绝不碰 PySide6。
  * **永不抛**：非 `@` 串直接原样返回（零 Win32 调用）；底层 ctypes 抛 OSError
    （非 Windows / API 缺失）一律回 `""`。调用方拿 `""` 表示「解析不出来」，
    按旧口径回退成 `@…（间接字符串）` 标注。
  * **缓存**：一次扫描里同一个 `@…` 常出现几十次（多作用域 × 多 hive），成功与
    失败都按原文进模块级 dict 缓存，只撞一次 API。
  * **线程纪律**：会调 Win32，只能在 worker 线程被调用（scan 本身就在扫描线程跑，
    见 `workers.py`；MCP 进程无线程约束）。
"""
__all__ = ["resolve"]

import ctypes
from ctypes import wintypes

#: 单次解析的输出缓冲（字符数）；真实菜单文字都很短，1K 足够
_BUF = 1024
#: 原文 → 解析结果（`""` 表示解析失败，同样缓存，避免反复撞 API）
_cache: dict = {}
_proc = None


def _load(text):
    """调一次 SHLoadIndirectString → 解析出的文字，失败返回 ""。

    与 `resolve` 分开：`resolve` 管缓存与非 `@` 短路，本函数是纯 Win32 边界，
    测试可整体 monkeypatch 掉它（钉住「非 @ 串零 API 调用」与异常兜底）。
    """
    global _proc
    if _proc is None:
        fn = ctypes.windll.shlwapi.SHLoadIndirectString
        fn.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR,
                       wintypes.UINT, ctypes.c_void_p]
        fn.restype = ctypes.c_long                    # HRESULT，勿用默认 int
        _proc = fn
    buf = ctypes.create_unicode_buffer(_BUF)
    hr = _proc(text, buf, _BUF, None)
    return buf.value if hr == 0 and buf.value else ""


def resolve(text):
    """间接串 → 真实文字；非 `@` 原样返回；任何失败回 ""（永不抛）。"""
    text = str(text or "")
    if not text.startswith("@"):
        return text
    if text in _cache:
        return _cache[text]
    try:
        value = _load(text)
    except Exception:                                 # ctypes 缺失/非 Windows
        value = ""
    _cache[text] = value
    return value
