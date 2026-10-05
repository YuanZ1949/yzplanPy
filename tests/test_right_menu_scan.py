"""right_menu 注册表后端契约 + scan（Task 4 追加本文件的 scan 测试）。

本文件先固定 `registry_backend.FakeRegistry` 的语义，因为后续所有操作层
（scan / ops / shellnew / classic / custom / yzmenu / elevate）都靠注入它做
**零真实注册表读写**的测试：FakeRegistry 的行为必须与 Win32Backend 对齐，
否则这些测试保护不了真实路径。

对齐的关键语义：
  * hive 大小写不敏感（HKCU/hkcu 等价）——T2 测试用大写，账本条目与 scan
    输出用小写，逐任务各自为政会在跨任务集成时炸；
  * 键路径与值名都大小写不敏感（真实注册表如此），但 list_keys/list_values
    返回**写入时的原始大小写**；
  * name=None（get/delete）指向默认值（winreg 的 ""）；
  * 键或值不存在时一律静默成功（get 返 None，delete/delete_tree 不抛）；
  * set 自动创建缺失的中间层级（真实 CreateKeyEx 就是这个语义）。

Win32Backend 的唯一契约是**永不抛异常**：任何失败降级为 None/[]/静默。
"""
from modules.right_menu import scan
from modules.right_menu.registry_backend import FakeRegistry


def test_fake_set_get_roundtrip():
    r = FakeRegistry()
    r.set("HKCU", r"Software\Classes\*\shell\Demo", "", "Demo")
    r.set("HKCU", r"Software\Classes\*\shell\Demo", "MUIVerb", "演示")
    assert r.get("HKCU", r"Software\Classes\*\shell\Demo") == "Demo"      # 默认值
    assert r.get("HKCU", r"Software\Classes\*\shell\Demo", "MUIVerb") == "演示"


def test_fake_missing_returns_none_and_silent_delete():
    r = FakeRegistry()
    assert r.get("HKCU", r"Software\Nope") is None
    assert r.get("HKCU", r"Software\Nope", "x") is None
    r.delete("HKCU", r"Software\Nope", "x")   # 静默成功
    r.delete_tree("HKCU", r"Software\Nope")   # 静默成功


def test_fake_list_keys_and_values():
    r = FakeRegistry()
    r.set("HKCU", r"Software\Classes\*\shell\A", "", "A")
    r.set("HKCU", r"Software\Classes\*\shell\B", "", "B")
    assert sorted(r.list_keys("HKCU", r"Software\Classes\*\shell")) == ["A", "B"]
    r.set("HKCU", r"Software\Classes\*\shell\A", "Extended", "")
    assert set(r.list_values("HKCU", r"Software\Classes\*\shell\A")) == {("", "A"), ("Extended", "")}


def test_fake_delete_tree_removes_descendants():
    r = FakeRegistry()
    r.set("HKCU", r"k\a\b", "v", "1")
    r.delete_tree("HKCU", r"k")
    assert r.get("HKCU", r"k\a\b", "v") is None
    assert r.list_keys("HKCU", r"k") == []


def test_win32_backend_never_raises(monkeypatch):
    import sys
    from modules.right_menu import registry_backend as rb
    monkeypatch.setitem(sys.modules, "winreg", None)   # import winreg 抛 ImportError
    b = rb.Win32Backend()
    assert b.get("HKCU", r"Software\Nope") is None
    assert b.list_keys("HKCU", r"Software\Nope") == []
    assert b.list_values("HKCU", r"Software\Nope") == []
    # 写/删路径同样不得把 ImportError 漏给调用方（T6/T8 会直接调这三个方法）
    assert b.set("HKCU", r"Software\Nope", "", "v") is None
    assert b.delete("HKCU", r"Software\Nope", "v") is None
    assert b.delete_tree("HKCU", r"Software\Nope") is None
    # 未知 hive：winreg 可用时也不得抛——不解析根键，因此完全不碰注册表
    monkeypatch.undo()          # 恢复真 winreg，否则下面这半段仍在 winreg 缺失下跑
    b = rb.Win32Backend()
    assert b.get("HKBOGUS", r"Software\Nope") is None
    assert b.set("HKBOGUS", r"Software\Nope", "", "v") is None
    assert b.delete("HKBOGUS", r"Software\Nope") is None
    assert b.delete_tree("HKBOGUS", r"Software\Nope") is None
    assert b.list_keys("HKBOGUS", r"Software\Nope") == []
    assert b.list_values("HKBOGUS", r"Software\Nope") == []


def test_fake_hive_case_insensitive():
    """hive 大小写不敏感：账本/scan 用小写、别处用大写，必须命中同一棵树。"""
    r = FakeRegistry()
    r.set("HKCU", r"k", "v", "1")
    assert r.get("hkcu", r"k", "v") == "1"
    r.set("hklm", r"k2", "v", "2")
    assert r.get("HKLM", r"k2", "v") == "2"
    assert r.list_keys("hkcu", "") == ["k"]      # 大写写入、小写枚举仍是同一 hive
    assert r.list_keys("HKLM", "") == ["k2"]


# ── scan 四作用域扫描 ──────────────────────────────────────────────────
def _seed(r):
    r.set("HKCU", r"Software\Classes\*\shell\SevenZip", "", "7-Zip")
    r.set("HKCU", r"Software\Classes\*\shell\SevenZip", "MUIVerb", "7-Zip 菜单")
    r.set("HKCU", r"Software\Classes\*\shell\SevenZip\command", "", r'"C:\7z.exe" "%1"')
    r.set("HKCU", r"Software\Classes\*\shell\ExtOnly", "MUIVerb", "Shift 项")
    r.set("HKCU", r"Software\Classes\*\shell\ExtOnly", "Extended", "")
    r.set("HKCU", r"Software\Classes\*\shell\Hidden", "", "隐藏项")
    r.set("HKCU", r"Software\Classes\*\shell\Hidden", "LegacyDisable", "")
    r.set("HKLM", r"Software\Classes\*\shell\SysWide", "", "系统项")
    r.set("HKLM", r"Software\Classes\*\shell\SysWide\command", "", "sys.exe")


def test_scan_file_scope_fields():
    r = FakeRegistry(); _seed(r)
    items = scan.scan_scope(r, "file")
    by_name = {i["display_name"]: i for i in items}
    it = by_name["7-Zip 菜单"]            # MUIVerb 优先
    assert it["hive"] == "hkcu" and it["key_path"].endswith(r"shell\SevenZip")
    assert it["command"] == r'"C:\7z.exe" "%1"' and it["extended"] is False
    assert by_name["Shift 项"]["extended"] is True
    assert by_name["隐藏项"]["disabled"] is True
    assert by_name["系统项"]["hive"] == "hklm"


def test_scan_skip_hklm_when_disabled():
    r = FakeRegistry(); _seed(r)
    assert all(i["hive"] == "hkcu" for i in scan.scan_scope(r, "file", include_hklm=False))


def test_scan_default_value_fallback_and_keyname_fallback():
    r = FakeRegistry()
    r.set("HKCU", r"Software\Classes\*\shell\WithDefault", "", "默认名")
    r.set("HKCU", r"Software\Classes\*\shell\Bare", "", "")
    items = scan.scan_scope(r, "file")
    by = {i["key_path"].rsplit("\\", 1)[-1]: i for i in items}
    assert by["WithDefault"]["display_name"] == "默认名"
    assert by["Bare"]["display_name"] == "Bare"      # 空默认值回退键名


def test_scan_submenu_children():
    r = FakeRegistry()
    r.set("HKCU", r"Software\Classes\*\shell\Parent", "MUIVerb", "父菜单")
    r.set("HKCU", r"Software\Classes\*\shell\Parent", "SubCommands", "")
    r.set("HKCU", r"Software\Classes\*\shell\Parent\shell\Child", "", "子项")
    r.set("HKCU", r"Software\Classes\*\shell\Parent\shell\Child\command", "", "child.exe")
    parent = [i for i in scan.scan_scope(r, "file") if i["display_name"] == "父菜单"][0]
    assert parent["children"][0]["display_name"] == "子项"
    assert parent["children"][0]["command"] == "child.exe"


def test_scan_nonstring_values_coerced():
    r = FakeRegistry()
    r.set("HKCU", r"Software\Classes\*\shell\Num", "MUIVerb", 5)   # 模拟非字符串值
    items = scan.scan_scope(r, "file")
    assert items[0]["display_name"] == "5"


def test_scan_order_disabled_last():
    r = FakeRegistry(); _seed(r)
    items = scan.scan_scope(r, "file")
    flags = [i["disabled"] for i in items]
    assert flags == sorted(flags)      # 禁用项排在最后


def test_scan_scopes_paths():
    r = FakeRegistry()
    r.set("HKCU", r"Software\Classes\Directory\shell\DT", "", "文件夹项")
    r.set("HKCU", r"Software\Classes\Directory\Background\shell\BG", "", "背景项")
    r.set("HKCU", r"Software\Classes\Drive\shell\DR", "", "驱动器项")
    assert scan.scan_scope(r, "directory")[0]["display_name"] == "文件夹项"
    assert scan.scan_scope(r, "background")[0]["display_name"] == "背景项"
    assert scan.scan_scope(r, "drive")[0]["display_name"] == "驱动器项"