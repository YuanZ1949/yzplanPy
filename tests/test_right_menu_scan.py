"""right_menu scan 四作用域扫描契约（Qt-free 只读扫描器）。

全部用例注入 `registry_backend.FakeRegistry`（内存树）→ **零真实注册表读写**；
后端契约本身（Fake/Win32 语义对齐）的用例见 `test_right_menu_registry_backend.py`
（原与本文件同处，因超 250 行硬上限拆出，内容未改）。

覆盖 brief Step 3 的规则：四作用域根路径、shellex 跳过（含大小写变体）、
显示名/命令/图标的取值优先级、`extended`/`disabled` 判据、排序、级联子菜单，
以及「后端不保证文本化」时 scan 自身的兜底（见 `_HostileBackend`）。
"""
from modules.right_menu import scan
from modules.right_menu.registry_backend import FakeRegistry


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
    # 写入侧兜底：FakeRegistry.set 走 `_text`，非字符串取回来已是 str
    # （故这条**验不了** scan 自身的兜底，见 _HostileBackend 那条）。
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


# ── brief Step 3 明写、此前无测试的元数据分支 ──────────────────────────
def test_scan_command_delegate_execute():
    """无 `command` 子键时回落 DelegateExecute 值，并标注来源（非内建伪项）。"""
    r = FakeRegistry()
    r.set("HKCU", r"Software\Classes\*\shell\Del", "", "委托项")
    r.set("HKCU", r"Software\Classes\*\shell\Del", "DelegateExecute", "{4F1E2A0B-0000-11AA-AA11-003072DE489B}")
    it = scan.scan_scope(r, "file")[0]
    assert it["command"] == "(DelegateExecute) {4F1E2A0B-0000-11AA-AA11-003072DE489B}"
    assert it["builtin"] is False


def test_scan_command_key_wins_over_delegate_execute():
    """`key\\command` 默认值优先于 DelegateExecute（brief 的 `>` 优先级）。"""
    r = FakeRegistry()
    r.set("HKCU", r"Software\Classes\*\shell\Both", "", "两者都有")
    r.set("HKCU", r"Software\Classes\*\shell\Both", "DelegateExecute", "{GUID}")
    r.set("HKCU", r"Software\Classes\*\shell\Both\command", "", "run.exe")
    assert scan.scan_scope(r, "file")[0]["command"] == "run.exe"


def test_scan_icon_priority_defaulticon_and_none():
    """`Icon` 值 > `key\\DefaultIcon` 默认值 > None（brief 表格第三行）。"""
    r = FakeRegistry()
    r.set("HKCU", r"Software\Classes\*\shell\Both", "", "图标优先")
    r.set("HKCU", r"Software\Classes\*\shell\Both", "Icon", r"C:\a.exe,0")
    r.set("HKCU", r"Software\Classes\*\shell\Both\DefaultIcon", "", r"C:\b.exe,1")
    r.set("HKCU", r"Software\Classes\*\shell\OnlyDefault", "", "仅默认图标")
    r.set("HKCU", r"Software\Classes\*\shell\OnlyDefault\DefaultIcon", "", r"C:\c.exe,2")
    r.set("HKCU", r"Software\Classes\*\shell\NoIcon", "", "无图标")
    by = {i["display_name"]: i for i in scan.scan_scope(r, "file")}
    assert by["图标优先"]["icon"] == r"C:\a.exe,0"     # Icon 压过 DefaultIcon
    assert by["仅默认图标"]["icon"] == r"C:\c.exe,2"   # 无 Icon 时取 DefaultIcon 默认值
    assert by["无图标"]["icon"] is None                # 两者皆无 → None


def test_scan_skips_shellex_keys_case_insensitive():
    """`shellex` / `ShellEx` 是 COM 扩展处理器，不是右键项——大小写变体都跳过。

    为什么必须用**两棵独立的树**：`FakeRegistry` 按 casefold 后的路径建索引，
    且 `_ensure` 只在节点不存在时写入 display（`registry_backend.py:246-248`），
    所以在同一棵树里先后写 `shellex` 与 `ShellEx` 会塌成**一个**节点并保留首次
    拼写（`list_keys` 也只吐那个拼写）。若沿用单树写法，即使 scan 的
    `name.casefold() not in _SKIP_KEYS`（`scan.py:110`）退化成精确匹配，
    本用例也照样绿（恰好命中的是小写 `shellex`）——即覆盖是假的。
    分成两棵树后，`ShellEx` 那半段的驼峰拼写**真的**流到 scan，退化即刻变红。
    """
    lower = FakeRegistry()
    lower.set("HKCU", r"Software\Classes\*\shell\shellex", "", "小写变体")
    lower.set("HKCU", r"Software\Classes\*\shell\Real", "", "真项")
    assert sorted(lower.list_keys("HKCU", r"Software\Classes\*\shell")) == ["Real", "shellex"]
    assert [i["display_name"] for i in scan.scan_scope(lower, "file")] == ["真项"]

    camel = FakeRegistry()
    camel.set("HKCU", r"Software\Classes\*\shell\ShellEx", "", "驼峰变体")
    camel.set("HKCU", r"Software\Classes\*\shell\Real", "", "真项")
    # 前提自证：树里保留的是驼峰拼写（而非塌成小写），跳过它才是 casefold 的功劳
    assert sorted(camel.list_keys("HKCU", r"Software\Classes\*\shell")) == ["Real", "ShellEx"]
    assert [i["display_name"] for i in scan.scan_scope(camel, "file")] == ["真项"]


def test_scan_muiverb_indirect_string_suffix():
    """解析器不可用时 `MUIVerb` 间接串 = 原样显示 + 「（间接字符串）」标注（回退口径）。

    真实解析路径见 `test_right_menu_indirect.py`；这里注入恒失败的 resolver 钉住
    回退行为，不依赖机器上是否装了对应资源。
    """
    r = FakeRegistry()
    r.set("HKCU", r"Software\Classes\*\shell\Indirect", "MUIVerb", "@shell32.dll,-151")
    it = scan.scan_scope(r, "file", resolver=lambda _s: "")[0]
    assert it["display_name"] == "@shell32.dll,-151（间接字符串）"


# ── 敌意后端：scan 自身必须兜住退化值（FakeRegistry 写时已强转，验不了）──
class _HostileBackend:
    """只满足 registry_backend 协议形状的桩：`get` 对任意 (hive, path, name)
    轮转返回 `None / 0 / 5 / b"by" / ["l"] / object()`。

    为什么需要它：`FakeRegistry.set` 走 `_text`，写进去的非字符串取出来已是 str，
    所以「后端不保证文本化」这一前提用它**根本构造不出来**——把 scan 的 `_text`
    删掉，那些测试照样绿。这里让 get 无视键与值名一律吐退化值，scan 必须在不依赖
    后端文本化的前提下跑完全程（review 1 的绑定点）。

    `list_keys` 只在浅层给一个子键名：真实注册表是有限树，深层恒空——否则桩会自己
    造出「无限级联子菜单」的伪影（RecursionError 与 scan 的契约无关，brief 只要求
    跳过 shellex）。其余五个方法按协议最小 no-op 返回。
    """

    _VALUES = (None, 0, 5, b"by", ["l"], object())

    def __init__(self):
        self._next = 0

    def get(self, hive, path, name=None):
        value = self._VALUES[self._next % len(self._VALUES)]
        self._next += 1
        return value

    def list_keys(self, hive, path):
        return ["Only"] if str(path or "").count("\\") <= 3 else []

    def list_values(self, hive, path):
        return []

    def set(self, hive, path, name, value):
        return None

    def delete(self, hive, path, name=None):
        return None

    def delete_tree(self, hive, path):
        return None


def test_scan_survives_hostile_degenerate_values():
    """退化值不得炸 scan（不抛），且输出的显示名/命令/图标保持 str 或 None。"""
    items = scan.scan_scope(_HostileBackend(), "file")      # 不抛即第一道断言
    assert items                                           # 桩的子键确实被枚举到
    for item in items:
        assert isinstance(item["display_name"], str)
        assert item["command"] is None or isinstance(item["command"], str)
        assert item["icon"] is None or isinstance(item["icon"], str)
    # 至少一项的显示名来自「值」而不是键名兜底 → 确实发生过文本化，而非全程 None
    assert any(i["display_name"] != "Only" for i in items)
