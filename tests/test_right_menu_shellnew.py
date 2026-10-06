"""ShellNew 新建菜单管理：扫描 / 隐藏 / 恢复 / 新增 / 删除。

四条被钉住的不变量（少任何一条，对应用例即红）：
  * **写前必备份**：任何一次写之前先 `backup_snapshot`，账本才可回滚。
  * **写后必回读**：`RegistryBackend` 是 never-raise 契约（无权限与成功在返回值上
    完全一样），直写不回读就会把「没发生的改动」记进账本并给用户报「已隐藏」。
  * **幂等判定看实时注册表**：重复点「隐藏」若再改一次名，后缀会叠成
    `NullFile__yzhidden__yzhidden`，还原再也对不上原名。
  * **HKLM 只隐藏、只走提权**：父进程绝不直写 HKLM（无权限的写入是静默的）。

失败侧的四个用例（`_NoDeleteRegistry` / `_NoSetRegistry` / `_NoTreeRegistry`）不是保险
起见：把对应那条回读校验删掉，它们就会各自转红——见 docs/task-8-report.md 的 mutation 记录。
"""
import os
from modules.right_menu import shellnew, store
from modules.right_menu.registry_backend import FakeRegistry

SN = r"Software\Classes\.xyz\ShellNew"


def test_scan_finds_hkcu_and_hklm():
    r = FakeRegistry()
    r.set("hkcu", SN, "NullFile", "")
    r.set("hklm", r"Software\Classes\.abc\ShellNew", "FileName", r"C:\tpl\abc.tpl")
    # 隐藏过的模板项：值名带后缀，kind / template 仍须报得出原类型与原路径
    r.set("hkcu", r"Software\Classes\.hid\ShellNew", "FileName__yzhidden", r"C:\tpl\hid.tpl")
    # 两个必须被过滤掉的：带 ShellNew 子键的**非扩展名**键（`Software\Classes` 下混着
    # * / Directory 等文件类键，只有「以 . 开头」这一条能拦住它）、以及没有 ShellNew
    # 子键的扩展名键（`.nop` 的值写在扩展名键本身上）
    r.set("hkcu", r"Software\Classes\Directory\ShellNew", "NullFile", "")
    r.set("hkcu", r"Software\Classes\.nop", "x", "")
    by = {i["ext"]: i for i in shellnew.scan_shellnew(r)}
    assert set(by) == {".xyz", ".abc", ".hid"}        # 两个过滤器都得拦住上面那两类
    assert by[".xyz"]["kind"] == "null" and by[".xyz"]["hive"] == "hkcu"
    assert by[".abc"]["kind"] == "template" and by[".abc"]["hive"] == "hklm"
    assert by[".abc"]["template"] == r"C:\tpl\abc.tpl"
    assert by[".hid"]["hidden"] is True and by[".hid"]["kind"] == "template"
    assert by[".hid"]["template"] == r"C:\tpl\hid.tpl"   # 带后缀也认得出模板路径


def test_hide_restore_roundtrip_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STATE_PATH", str(tmp_path / "state.json"))
    r = FakeRegistry(); r.set("hkcu", SN, "NullFile", "DATA")
    item = shellnew.scan_shellnew(r)[0]
    assert shellnew.hide_shellnew(r, item)["ok"]
    assert r.get("hkcu", SN, "NullFile__yzhidden") == "DATA"
    assert r.get("hkcu", SN, "NullFile") is None
    assert shellnew.hide_shellnew(r, item)["ok"]              # 幂等：不叠加后缀
    assert r.get("hkcu", SN, "NullFile__yzhidden") == "DATA"
    assert shellnew.restore_shellnew(r, item)["ok"]
    assert r.get("hkcu", SN, "NullFile") == "DATA"
    assert store.load()["shellnew_hidden"] == []
    # 恢复后再走一轮隐藏：值名不得叠加后缀
    assert shellnew.hide_shellnew(r, shellnew.scan_shellnew(r)[0])["ok"]
    names = [n for n, _ in r.list_values("hkcu", SN)]
    assert names == ["NullFile__yzhidden"]
    # 未隐藏时恢复是幂等的（ruling 7 前半段）：先恢复到未隐藏，再恢复一次仍 ok
    assert shellnew.restore_shellnew(r, shellnew.scan_shellnew(r)[0])["ok"]
    assert r.get("hkcu", SN, "NullFile") == "DATA"
    assert shellnew.restore_shellnew(r, shellnew.scan_shellnew(r)[0])["ok"]


def test_create_null_and_reject_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STATE_PATH", str(tmp_path / "state.json"))
    r = FakeRegistry()
    assert shellnew.create_shellnew(r, ".xyz", name="空文件", kind="null")["ok"]
    assert r.get("hkcu", SN, "NullFile") == ""
    assert not shellnew.create_shellnew(r, ".xyz", name="重复", kind="null")["ok"]   # 已存在拒绝


def test_create_template_copies_file(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(store, "TEMPLATES_DIR", str(tmp_path / "tpl"))
    src = tmp_path / "mytpl.txt"; src.write_text("x", encoding="utf-8")
    r = FakeRegistry()
    assert shellnew.create_shellnew(r, ".txt2", name="模板", kind="template",
                                    template_path=str(src))["ok"]
    fn = r.get("hkcu", r"Software\Classes\.txt2\ShellNew", "FileName")
    assert fn and os.path.isfile(fn) and os.path.basename(fn).endswith("mytpl.txt")


def test_invalid_ext_rejected():
    r = FakeRegistry()
    # `..` / `...` 曾经能过校验：写出的键是 `Software\Classes\..\ShellNew`（真注册表里
    # 等于 `Software\Classes` 自身），Explorer 里看不见却留下越界键——纯点体必须拒。
    for bad in ("xyz", r"..\evil", ".", "..", "...", "." + "x" * 40):
        assert not shellnew.create_shellnew(r, bad, name="x", kind="null")["ok"]


def test_hklm_hide_routes_elevation_and_delete_protection(monkeypatch):
    jobs = []
    monkeypatch.setattr(shellnew.elevate, "run_job",
                        lambda job, **k: (jobs.append(job), {"ok": True})[1])
    r = FakeRegistry(); r.set("hklm", SN, "NullFile", "D")
    item = [i for i in shellnew.scan_shellnew(r) if i["hive"] == "hklm"][0]
    assert shellnew.hide_shellnew(r, item)["ok"] and jobs
    assert r.get("hklm", SN, "NullFile") == "D"               # 未直写
    assert not shellnew.delete_shellnew(r, item)["ok"]        # HKLM 仅隐藏
    r.set("hkcu", SN, "NullFile", "D")
    item2 = [i for i in shellnew.scan_shellnew(r) if i["hive"] == "hkcu"][0]
    assert shellnew.delete_shellnew(r, item2)["ok"]
    assert r.get("hkcu", SN) is None


class _NoSetRegistry(FakeRegistry):
    """`set` 静默失败的注册表（模拟安全软件拦截写入：写进去的值回读不到）。"""

    def set(self, *a, **k):
        pass


class _NoDeleteRegistry(FakeRegistry):
    """`delete` 静默失败的注册表（值删不掉：改名的「旧名消失」那半永远为假）。"""

    def delete(self, *a, **k):
        pass


class _NoTreeRegistry(FakeRegistry):
    """`delete_tree` 静默失败的注册表（整棵 ShellNew 子树删不掉）。"""

    def delete_tree(self, *a, **k):
        pass


def test_hide_write_failure_reported(tmp_path, monkeypatch):
    """改名后旧值名还赖着 → 隐藏必须报失败，且**账本一个字都不能动**。

    与 `test_restore_write_failure_reported`（`_NoSetRegistry`，钉「新值名没落地」那半）
    配对：两个后端各让回读的一半为假，两半合起来才覆盖完整的改名回读。
    """
    monkeypatch.setattr(store, "STATE_PATH", str(tmp_path / "state.json"))
    r = _NoDeleteRegistry()
    FakeRegistry.set(r, "hkcu", SN, "NullFile", "DATA")   # 直调基类绕开 no-op 覆写
    item = shellnew.scan_shellnew(r)[0]
    out = shellnew.hide_shellnew(r, item)
    assert out["ok"] is False and "未生效" in out["detail"]
    assert store.load()["shellnew_hidden"] == []


def test_restore_write_failure_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STATE_PATH", str(tmp_path / "state.json"))
    r = _NoSetRegistry()
    FakeRegistry.set(r, "hkcu", SN, "NullFile__yzhidden", "DATA")
    item = shellnew.scan_shellnew(r)[0]
    out = shellnew.restore_shellnew(r, item)
    assert out["ok"] is False and "未生效" in out["detail"]


def test_create_write_failure_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STATE_PATH", str(tmp_path / "state.json"))
    r = _NoSetRegistry()
    out = shellnew.create_shellnew(r, ".xyz", name="x", kind="null")
    assert out["ok"] is False and "未生效" in out["detail"]


def test_delete_write_failure_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STATE_PATH", str(tmp_path / "state.json"))
    r = _NoTreeRegistry()
    FakeRegistry.set(r, "hkcu", SN, "NullFile", "")
    item = shellnew.scan_shellnew(r)[0]
    out = shellnew.delete_shellnew(r, item)
    assert out["ok"] is False and "未生效" in out["detail"]
