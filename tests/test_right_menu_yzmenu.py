"""yzmenu 系统右键子菜单：三个根的键形状、账本一致性与动作校验。

零真实注册表：全部注入 `FakeRegistry`，只验本包自建的键值形状与账本写入。
"""
from modules.right_menu import store, yzmenu
from modules.right_menu.registry_backend import FakeRegistry


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "STATE_PATH", str(tmp_path / "state.json"))


def test_install_creates_three_roots_and_actions(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    r = FakeRegistry()
    assert yzmenu.install_yzmenu(r, ["open_manager", "toggle_classic"])["ok"]
    for root in ("*", "Directory", r"Directory\Background"):
        p = rf"Software\Classes\{root}\shell\YZplan"
        assert r.get("hkcu", p, "MUIVerb") == "YZplan"
        assert r.get("hkcu", p, "SubCommands") == ""
        assert r.get("hkcu", p, "Position") == "Top"
        assert r.get("hkcu", p, "Icon")           # 图标不能是空串（右键里会显示白块）
    cmd = r.get("hkcu", r"Software\Classes\*\shell\YZplan\shell\open_manager")
    assert "--menu-action open_manager" in cmd
    st = store.load()["yzmenu"]
    assert st["installed"] is True and st["actions"] == ["open_manager", "toggle_classic"]
    for act in ("open_manager", "toggle_classic"):     # 动作子键的显示名映射
        sub = rf"Software\Classes\*\shell\YZplan\shell\{act}"
        assert r.get("hkcu", sub, "MUIVerb") == yzmenu.ACTION_LABELS[act]
    # 幂等清理：改装动作清单重装后，上一次的动作子键不能留在菜单里（否则多一行死动作）。
    yzmenu.install_yzmenu(r, ["open_manager"])
    assert r.get("hkcu", r"Software\Classes\*\shell\YZplan\shell\toggle_classic") is None
    assert r.get("hkcu", r"Software\Classes\*\shell\YZplan\shell\open_manager") is not None
    assert yzmenu.get_yzmenu_state(r)["actions"] == ["open_manager"]


def test_state_and_uninstall(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    r = FakeRegistry()
    assert yzmenu.get_yzmenu_state(r) == {"installed": False, "actions": []}
    yzmenu.install_yzmenu(r, ["show_window"])
    state = yzmenu.get_yzmenu_state(r)
    assert state["installed"] is True and state["actions"] == ["show_window"]
    assert yzmenu.uninstall_yzmenu(r)["ok"]
    assert yzmenu.get_yzmenu_state(r)["installed"] is False
    assert r.get("hkcu", r"Software\Classes\Directory\shell\YZplan") is None
    assert store.load()["yzmenu"] == {"installed": False, "actions": []}


def test_unknown_action_rejected():
    assert not yzmenu.install_yzmenu(FakeRegistry(), ["nope"])["ok"]
    # 空清单（/ None / 标量）也拒：SubCommands 指向一条没有子命令的菜单 = 点了是空的。
    assert not yzmenu.install_yzmenu(FakeRegistry(), [])["ok"]
    assert not yzmenu.install_yzmenu(FakeRegistry(), None)["ok"]
    assert yzmenu.ACTION_LABELS["open_manager"] == "打开管理器"


def test_action_command_mentions_action():
    cmd = yzmenu.action_command("restore_all")
    assert "--menu-action" in cmd and "restore_all" in cmd
