"""ops 统一操作层：参数校验 / 写前备份 / 账本一致性 / hkcu 直写回读 / hklm 提权映射。

三条被钉住的不变量（少任何一条，对应用例即红）：
  * **写前必备份**：任何一次写之前先 `store.backup_snapshot`，账本才可回滚。
  * **写后必回读**：`RegistryBackend` 是 never-raise 契约（无权限与成功在返回值上无法
    区分），直写路径不校验就会把「没发生的改动」记进账本（controller 裁定，承 T2 评审）。
  * **提权只经作业**：HKLM 一律走 `elevate.run_job`，父进程绝不直写 HKLM。
"""
from modules.right_menu import ops, store
from modules.right_menu.registry_backend import FakeRegistry

KEY = r"Software\Classes\*\shell\Demo"


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "STATE_PATH", str(tmp_path / "state.json"))


class _NoSetRegistry(FakeRegistry):
    """`set` 静默失败的注册表（模拟安全软件拦截写入）。"""

    def set(self, hive, path, name, value):
        return None


def test_disable_hkcu_writes_legacy_and_ledger(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    r = FakeRegistry(); r.set("hkcu", KEY, "", "Demo")
    backups = []
    monkeypatch.setattr(ops.store, "backup_snapshot", lambda reason: backups.append(reason))
    assert ops.apply_op(r, {"action": "disable", "hive": "hkcu", "key_path": KEY})["ok"]
    assert r.get("hkcu", KEY, "LegacyDisable") == ""
    assert store.load()["disabled"][0]["key_path"] == KEY
    assert backups      # 写前必须备份


def test_restore_roundtrip_clears_ledger(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    r = FakeRegistry(); r.set("hkcu", KEY, "", "Demo")
    ops.apply_op(r, {"action": "disable", "hive": "hkcu", "key_path": KEY})
    assert ops.apply_op(r, {"action": "restore", "hive": "hkcu", "key_path": KEY})["ok"]
    assert r.get("hkcu", KEY, "LegacyDisable") is None
    assert store.load()["disabled"] == []


def test_hklm_disable_goes_through_elevate(monkeypatch):
    jobs = []
    monkeypatch.setattr(ops.elevate, "run_job",
                        lambda job, **k: (jobs.append(job), {"ok": True})[1])
    r = FakeRegistry()
    out = ops.apply_op(r, {"action": "disable", "hive": "hklm", "key_path": KEY})
    assert out["ok"] and jobs[0]["ops"][0]["action"] == "set"
    assert r.get("hklm", KEY, "LegacyDisable") is None   # 不得直写


def test_hklm_cancelled_reports_friendly(monkeypatch):
    monkeypatch.setattr(ops.elevate, "run_job", lambda job, **k: {"ok": False, "error": "cancelled"})
    out = ops.apply_op(FakeRegistry(), {"action": "disable", "hive": "hklm", "key_path": KEY})
    assert out["ok"] is False and "取消" in out["detail"]


def test_delete_protections():
    r = FakeRegistry()
    assert not ops.apply_op(r, {"action": "delete", "hive": "hklm", "key_path": KEY})["ok"]
    assert not ops.apply_op(r, {"action": "delete", "hive": "hkcu", "key_path": KEY, "builtin": True})["ok"]
    r.set("hkcu", KEY, "", "Demo")
    assert ops.apply_op(r, {"action": "delete", "hive": "hkcu", "key_path": KEY})["ok"]
    assert r.get("hkcu", KEY) is None


def test_restore_missing_key_is_silent_ok():
    assert ops.apply_op(FakeRegistry(), {"action": "restore", "hive": "hkcu", "key_path": KEY})["ok"]


def test_unknown_action_rejected():
    assert not ops.apply_op(FakeRegistry(), {"action": "rename", "hive": "hkcu", "key_path": KEY})["ok"]


def test_disable_write_failed_reported(tmp_path, monkeypatch):
    """直写没落地必须报失败，且**账本一个字都不能动**。

    never-raise 后端让「被拦截」和「成功」在返回值上完全一样，只有回读能区分；不回读
    就会给用户报「已隐藏」，账本里还留下一条从未发生的改动（后续「还原」会去删一个
    不存在的值）。
    """
    _isolate(monkeypatch, tmp_path)
    r = _NoSetRegistry()
    FakeRegistry.set(r, "hkcu", KEY, "", "Demo")     # 直调基类绕开 no-op 覆写，键确实存在
    out = ops.apply_op(r, {"action": "disable", "hive": "hkcu", "key_path": KEY})
    assert out["ok"] is False and "写入" in out["detail"]
    assert store.load()["disabled"] == []