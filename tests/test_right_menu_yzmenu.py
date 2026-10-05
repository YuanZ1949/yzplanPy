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
    cmd = r.get("hkcu", r"Software\Classes\*\shell\YZplan\shell\open_manager")
    assert "--menu-action open_manager" in cmd
    st = store.load()["yzmenu"]
    assert st["installed"] is True and st["actions"] == ["open_manager", "toggle_classic"]


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
    assert yzmenu.ACTION_LABELS["open_manager"] == "打开管理器"


def test_action_command_mentions_action():
    cmd = yzmenu.action_command("restore_all")
    assert "--menu-action" in cmd and "restore_all" in cmd
