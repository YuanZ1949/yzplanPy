"""classic 经典右键菜单总开关：状态三态判定 / 开关往返 / explorer 重启。

经典菜单的机制是往 `HKCU\\Software\\Classes\\CLSID\\{86ca1aa0-...}\\InprocServer32`
的**默认值**写空串——Windows 11 见到空值就用旧版 shell 右键菜单实现，删除整棵 CLSID
子树即还原。因此这里钉住三件事：

  * **状态三态**：`disabled`（键不存在 = 新版菜单）/ `enabled`（默认值为空）/ `unknown`
    （值非空或键存在但无默认值 = 这个 CLSID 被别的 COM 注册占了，不能当经典处理）。
    少一条，UI 就可能在别人的 COM 注册上误判并写坏它。
  * **往返对称**：enable 后能读回 enabled，disable 后整棵子树消失。
  * **重启注入**：explorer 重启必须经 `runner` 注入，测试不得真的 taskkill 用户的
    资源管理器；失败路径降级为 `{"ok": False}` 而非抛出。
"""
from modules.right_menu import classic
from modules.right_menu.registry_backend import FakeRegistry


def test_state_three_values():
    r = FakeRegistry()
    assert classic.get_classic_state(r) == "disabled"           # 键不存在 = 新版菜单
    r.set("hkcu", classic.INPROC_KEY, "", "")
    assert classic.get_classic_state(r) == "enabled"            # 空默认值 = 经典
    r.set("hkcu", classic.INPROC_KEY, "", r"C:\other.dll")
    assert classic.get_classic_state(r) == "unknown"            # 非本机制的 COM 注册


def test_state_unknown_when_key_without_default():
    r = FakeRegistry()
    r.set("hkcu", classic.INPROC_KEY, "Other", "x")   # 键存在但没有默认值
    assert classic.get_classic_state(r) == "unknown"


def test_toggle_roundtrip():
    r = FakeRegistry()
    assert classic.enable_classic(r)["ok"]
    assert classic.get_classic_state(r) == "enabled"
    assert classic.disable_classic(r)["ok"]
    # 断言子树真的没了——查 CLSID_KEY 的**子键**，而不是它的默认值：默认值永远是 None
    #（没有任何代码往 CLSID_KEY 上写值），拿它断言就是恒真，disable 变成空操作也测不出来。
    # 这条排在 state 断言**前面**：它是承重的第一条（delete_tree 被掏空时先红在这里，
    # 而不是被派生的 state 断言顺带盖过去）。
    assert r.list_keys("hkcu", classic.CLSID_KEY) == []
    assert classic.get_classic_state(r) == "disabled"


def test_restart_explorer_command():
    calls = []
    out = classic.restart_explorer(runner=lambda cmd: calls.append(cmd))
    assert out["ok"] is True
    joined = " ".join(calls[0])
    assert "taskkill" in joined and "explorer.exe" in joined and "start" in joined


def test_restart_explorer_failure():
    def boom(cmd): raise OSError("denied")
    out = classic.restart_explorer(runner=boom)
    assert out["ok"] is False


def test_restart_explorer_uses_popen_when_runner_absent(monkeypatch):
    calls = []
    monkeypatch.setattr(classic.subprocess, "Popen", lambda cmd: calls.append(cmd))
    out = classic.restart_explorer()
    assert out["ok"] is True
    assert calls and "explorer.exe" in " ".join(calls[0])
