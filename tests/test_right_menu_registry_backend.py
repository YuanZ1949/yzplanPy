"""right_menu 注册表后端契约（Task 2 交付，从 test_right_menu_scan.py 拆出）。

本文件固定 `registry_backend.FakeRegistry` 的语义，因为后续所有操作层
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

（原先这些用例与 scan 用例同处 tests/test_right_menu_scan.py；因文件超过
250 行硬上限（AGENTS.md 通用规范）拆出，用例内容一字未改。）
"""
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


def test_fake_resolves_dot_segments_like_windows():
    """`.` / `..` 必须按 Windows 键路径语义折叠，否则路径穿越在测试里完全隐形。

    真注册表里 `a\\..\\b` 指的就是 `b`：本模块把用户数据拼进键路径（custom 的 slug、
    shellnew 的扩展名），FakeRegistry 若照单全收成另一棵树，那么「坏数据删掉了兄弟键」
    这类缺陷在任何用例里都测不出来——缺陷本身却是真的（Customize/scan 的实测对象是注册表，
    不是这个 fake）。
    """
    r = FakeRegistry()
    r.set("HKCU", r"k\a\b", "v", "1")
    r.set("HKCU", r"k\keep", "v", "2")
    assert r.get("HKCU", r"k\x\..\a\b", "v") == "1"          # `..` 回退一级
    assert r.get("HKCU", r"..\k\keep", "v") == "2"           # 顶层之上回退 = 停在顶层
    assert r.get("HKCU", r"k\.\a\.\b", "v") == "1"           # `.` 段丢弃
    assert r.list_keys("HKCU", r"k\a\..\a") == ["b"]        # 列子键也走折叠
    assert r.list_values("HKCU", r"k\a\.\b") == [("v", "1")]
    # delete_tree 同样走折叠：`k\keep\..\keep` 折叠回 `k\keep` 自身（不会另造一棵
    # 叫 `k\keep\..\keep` 的树），兄弟键 `k\a\b` 不受牵连。
    r.delete_tree("HKCU", r"k\keep\..\keep")
    assert r.get("HKCU", r"k\keep", "v") is None
    assert r.get("HKCU", r"k\a\b", "v") == "1"
    assert r.list_keys("HKCU", "k") == ["a"]