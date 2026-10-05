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


def test_disable_restore_name_marker_roundtrip(tmp_path, monkeypatch):
    """op 里的 `name` 是「隐藏标记的值名」，隐藏与还原必须两侧同源（`_marker`）。

    隐藏侧写死 `LegacyDisable`、还原侧却按 `name` 删的话，这个隐藏项就再也还原不掉
    （删了一个从没写过的值名），而账本里那条记录还留着假装可还原；账本记 `name` 的
    意义也正在于此——还原时才知道当初写的是哪个标记值名。
    """
    _isolate(monkeypatch, tmp_path)
    r = FakeRegistry()
    op = {"action": "disable", "hive": "hkcu", "key_path": KEY,
          "name": "ProgrammaticAccessOnly"}
    assert ops.apply_op(r, op)["ok"] is True
    assert r.get("hkcu", KEY, "ProgrammaticAccessOnly") == ""      # 写在 name 上
    assert r.get("hkcu", KEY, "LegacyDisable") is None             # 不是默认标记
    assert store.load()["disabled"][0]["name"] == "ProgrammaticAccessOnly"
    assert ops.apply_op(r, dict(op, action="restore"))["ok"] is True
    assert r.get("hkcu", KEY, "ProgrammaticAccessOnly") is None
    assert store.load()["disabled"] == []


def test_restore_with_original_roundtrip_hkcu(tmp_path, monkeypatch):
    """`original` 的回填顺序：先删标记、再写回原值（ops.py restore 分支）。

    顺序反了（先 set 再 delete）会把刚写回去的原值又删掉，还原等于没做；干脆不写回
    也一样——隐藏前的原值就永久丢了。因此这里断言的是**最终落地的值**，而不只是 ok。
    """
    _isolate(monkeypatch, tmp_path)
    r = FakeRegistry()
    FakeRegistry.set(r, "hkcu", KEY, "LegacyDisable", "")    # 直调基类：键与标记确实存在
    out = ops.apply_op(r, {"action": "restore", "hive": "hkcu", "key_path": KEY,
                           "original": "KeepMe"})
    assert out["ok"] is True
    assert r.get("hkcu", KEY, "LegacyDisable") == "KeepMe"


def test_hklm_restore_with_original_orders_delete_then_set(monkeypatch):
    """提权作业的原语顺序同一条不变量：先 delete 标记再 set 回原值（`_job_ops`）。

    子进程按列表顺序逐条执行且每条都回读，顺序反了的话第二条 set 会被随后的 delete
    抹掉，子进程报 ok 、父进程照记成功——用户在 HKLM 上得到一个还原不了的隐藏项。
    """
    jobs = []
    monkeypatch.setattr(ops.elevate, "run_job",
                        lambda job, **k: (jobs.append(job), {"ok": True})[1])
    out = ops.apply_op(FakeRegistry(), {"action": "restore", "hive": "hklm",
                                        "key_path": KEY, "original": "KeepMe"})
    assert out["ok"] is True
    assert [item["action"] for item in jobs[0]["ops"]] == ["delete", "set"]


class _NoDeleteRegistry(FakeRegistry):
    """`delete` 静默失败的注册表（值删不掉，键还在）。"""

    def delete(self, hive, path, name=None):
        pass


def test_restore_readback_failure_reported(tmp_path, monkeypatch):
    """还原没落地必须报失败（restore 分支的回读校验：隐藏侧有闸、还原侧也必须有）。

    标记没被删掉时若照报「已完成」，用户会以为项已恢复而它还在右键菜单里隐藏着，
    再点一次「还原」也只会得到同样一句谎话。
    """
    _isolate(monkeypatch, tmp_path)
    r = _NoDeleteRegistry()
    FakeRegistry.set(r, "hkcu", KEY, "LegacyDisable", "")    # 标记确实在，删它删不动
    out = ops.apply_op(r, {"action": "restore", "hive": "hkcu", "key_path": KEY})
    assert out["ok"] is False and "写入" in out["detail"]
    assert store.load()["disabled"] == []


class _NoTreeRegistry(FakeRegistry):
    """`delete_tree` 静默失败的注册表（键连同子树都留着）。"""

    def delete_tree(self, hive, path):
        pass


def test_delete_readback_failure_reported(tmp_path, monkeypatch):
    """删除没落地必须报失败（delete 分支的回读校验）。

    键删不掉却报「已删除」，用户会以为右键项已经清理干净，实际上它下次开机又出现；
    而且此刻账本若已销账，「一键还原」就再也无从追溯它曾经被本模块动过。
    """
    _isolate(monkeypatch, tmp_path)
    r = _NoTreeRegistry()
    FakeRegistry.set(r, "hkcu", KEY + r"\command", "", "x")   # 有子键 → list_keys 非空
    out = ops.apply_op(r, {"action": "delete", "hive": "hkcu", "key_path": KEY,
                           "builtin": False})
    assert out["ok"] is False and "写入" in out["detail"]
    assert r.list_keys("hkcu", KEY) != []                      # 子树确实还在
