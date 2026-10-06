"""right_menu 间接字符串解析（`@dll,-id` → 菜单里真实文字）契约。

分两层：

  * ``indirect.resolve`` 本体：ctypes 调 ``SHLoadIndirectString``（Qt-free，满足
    scan 的 Qt-free 契约）。非 ``@`` 开头**不碰 Win32**；解析失败/异常返回 ``""``
    （永不抛）；结果按原文缓存（同一 ``@shell32.dll,-…`` 在一次扫描里常出现几十次）。
  * scan 集成：``scan_scope(resolver=…)`` —— 解析成功 → ``display_name`` 就是真实
    文字（不带标注）；解析失败或解析器抛出 → 维持旧口径 ``@…（间接字符串）``。

真实成功路径依赖机器自带资源（shell32「打开方式...」），环境缺失时 skip 而非
硬失败——Win32 资源号不是跨版本稳定契约。
"""
import pytest

from modules.right_menu import indirect, scan
from modules.right_menu.registry_backend import FakeRegistry


# ── indirect.resolve 本体 ──────────────────────────────────────────────
def test_resolve_non_at_passthrough_never_touches_win32(monkeypatch):
    """非 `@` 串原样返回，且一次 Win32 调用都不许发生。"""
    monkeypatch.setattr(indirect, "_load",
                        lambda _s: pytest.fail("非 @ 串不应调用 Win32"))
    assert indirect.resolve("打开") == "打开"
    assert indirect.resolve("") == ""


def test_resolve_failure_returns_empty_string():
    """不存在的模块/资源 → 空串（调用方据此回退到标注），绝不抛。"""
    assert indirect.resolve("@oceanus_no_such_module_xyz.dll,-1") == ""
    assert indirect.resolve("@") == ""


def test_resolve_real_indirect_string():
    """真实资源解析出非空、非 `@` 原文的本地化文本；本机没有该资源则 skip。"""
    text = indirect.resolve(r"@%SystemRoot%\system32\shell32.dll,-9016")
    if not text:
        pytest.skip("本机 shell32 无该资源（跨 Windows 版本不保证）")
    assert not text.startswith("@")


def test_resolve_caches_both_success_and_failure(monkeypatch):
    """成功与失败都进缓存：同串只调一次 Win32（失败也别反复撞 API）。"""
    monkeypatch.setattr(indirect, "_cache", {})
    calls = []

    def fake_load(s):
        calls.append(s)
        return "X" if s == "@ok.dll,-1" else ""

    monkeypatch.setattr(indirect, "_load", fake_load)
    assert indirect.resolve("@ok.dll,-1") == "X"
    assert indirect.resolve("@ok.dll,-1") == "X"
    assert indirect.resolve("@bad.dll,-1") == ""
    assert indirect.resolve("@bad.dll,-1") == ""
    assert calls == ["@ok.dll,-1", "@bad.dll,-1"]


def test_resolve_swallows_loader_exception(monkeypatch):
    """底层 ctypes 抛 OSError（非 Windows / API 缺失）也必须回  "" 不抛。"""
    def boom(_s):
        raise OSError("WinError 100")

    monkeypatch.setattr(indirect, "_load", boom)
    assert indirect.resolve("@a.dll,-1") == ""


# ── scan 集成：resolver 注入 ───────────────────────────────────────────
def _seed(r):
    r.set("HKCU", r"Software\Classes\*\shell\Indirect", "MUIVerb", "@shell32.dll,-151")
    r.set("HKCU", r"Software\Classes\*\shell\Indirect\command", "", "x.exe")


def test_scan_resolver_success_shows_real_text():
    """解析成功 → display_name 直接是真实文字，不带「（间接字符串）」标注。"""
    r = FakeRegistry(); _seed(r)
    it = scan.scan_scope(r, "file", resolver=lambda _s: "打开")[0]
    assert it["display_name"] == "打开"


def test_scan_resolver_empty_falls_back_to_annotation():
    """解析失败（回 ""）→ 维持旧口径：原文 + 「（间接字符串）」标注。"""
    r = FakeRegistry(); _seed(r)
    it = scan.scan_scope(r, "file", resolver=lambda _s: "")[0]
    assert it["display_name"] == "@shell32.dll,-151（间接字符串）"


def test_scan_resolver_exception_falls_back_to_annotation():
    """解析器抛异常也不许炸扫描（scan 绝不抛契约）→ 同样回退标注。"""
    r = FakeRegistry(); _seed(r)

    def boom(_s):
        raise RuntimeError("boom")

    it = scan.scan_scope(r, "file", resolver=boom)[0]
    assert it["display_name"] == "@shell32.dll,-151（间接字符串）"


def test_scan_non_indirect_muiverb_bypasses_resolver():
    """非 `@` 的 MUIVerb 一次都不进解析器（不为已知可显示的文字付 API 代价）。"""
    r = FakeRegistry()
    r.set("HKCU", r"Software\Classes\*\shell\Plain", "MUIVerb", "直接文本")
    scan.scan_scope(r, "file",
                    resolver=lambda _s: pytest.fail("非 @ MUIVerb 不应进解析器"))
    assert True


def test_scan_submenu_child_indirect_resolved():
    """级联子菜单的子项同样过 resolver（_build 递归也要带解析器）。"""
    r = FakeRegistry()
    base = r"Software\Classes\*\shell\Parent"
    r.set("HKCU", base, "SubCommands", "")
    r.set("HKCU", base + r"\shell\Child", "MUIVerb", "@x.dll,-1")
    parent = scan.scan_scope(r, "file", resolver=lambda _s: "子真实名")[0]
    assert parent["children"][0]["display_name"] == "子真实名"


def test_scan_default_resolver_does_not_raise():
    """默认 resolver = 真解析器：真机上要么解析出文字，要么回退标注，都不抛。"""
    r = FakeRegistry(); _seed(r)
    name = scan.scan_scope(r, "file")[0]["display_name"]
    assert isinstance(name, str) and name
    assert (not name.startswith("@")) or name.endswith("（间接字符串）")
