"""自定义右键项：DOM 校验 / 命令模板展开 / 注册表投影 / CRUD。

十三组用例、八条被钉住的不变量（少任何一条，对应用例即红）：
  * **备份早于改动**：`save_item` 的快照必须拍在**账本被改之前**——否则快照里已经是新值，
    还原不出任何东西（`test_save_item_snapshots_before_ledger_change`）。
  * **ops 按 hive 分组**：HKLM→HKCU 切换时，旧 HKLM 投影的删除也必须走提权通道
    （`test_sync_hive_switch_routes_both_channels`）。
  * **写失败不留在半路**：账本回滚 + 尽力重建旧投影（`test_save_failure_restores_old_projection`）。
  * **危险不静默**：未加引号的 `%1` 与未识别的 `%x` 是**警告**而非拒绝——用户往往就是想看
    展开结果再决定，但坏命令必须在保存前说出来（plan Review Focus 2）。
  * **注册表里占位符原样**：`command` 默认值写的是 `target + " " + args` 模板，展开是
    explorer 的活；`expand_command` 只是同源实现的预览/告警，绝不写进注册表。
  * **投影先删后建**：改作用域 / 改扩展名过滤 / 改标题后，旧投影路径必须被清掉，否则用户会
    看到两个同名菜单项（`test_sync_idempotent_and_repositions`）。
  * **slug 确定性**：`<净标题>_<id[:6]>`，同一条 item 反复 sync 必须落同一个键。
  * **HKCU 直写 / HKLM 走提权**：父进程直写 HKLM 是静默无效的（`run_job` 被 monkeypatch 掉后
    `hklm` 命名空间必须一个字节都没变）。

所有 HKLM 用例都先 monkeypatch `custom.elevate.run_job`——真跑一次就是用户桌面上的一个 UAC
弹窗。测试只用 FakeRegistry，零真实注册表读写。
"""
import json

from modules.right_menu import custom, store
from modules.right_menu.registry_backend import FakeRegistry


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "STATE_PATH", str(tmp_path / "state.json"))


def _item(**kw):
    base = {"id": "a1", "title": "用记事本打开", "icon": "", "scope": "file",
            "ext_filter": [], "hive": "hkcu", "extended": False,
            "position": "bottom",
            "action": {"kind": "program", "target": r"C:\Windows\notepad.exe",
                       "args": '"%1"', "workdir": ""},
            "children": []}
    base.update(kw)
    return base


def test_validate_rejects_and_warns():
    out = custom.validate_item(_item(action={"kind": "program", "target": "", "args": ""}))
    assert not out["ok"] and out["errors"]
    out = custom.validate_item(_item(action={"kind": "program", "target": "x", "args": "%1"}))
    assert out["ok"] and any("引号" in w for w in out["warnings"])       # 未引号占位符→警告
    out = custom.validate_item(_item(action={"kind": "program", "target": "x", "args": "%q"}))
    assert any("占位" in w for w in out["warnings"])                     # 未识别占位符→警告


def test_expand_command_placeholders():
    it = _item(action={"kind": "program", "target": r"C:\Windows\notepad.exe",
                       "args": '"%1" %V %*', "workdir": ""})
    cmd = custom.expand_command(it, selected=[r"C:\My Docs\a.txt", r"C:\b.txt"],
                                current_dir=r"C:\My Docs")
    # 全串比对：%1 取多选第一个（模板里已带引号 → 裸路径）、%V 补引号、%* 两条全上
    assert cmd == (r'C:\Windows\notepad.exe "C:\My Docs\a.txt" "C:\My Docs" '
                   r'"C:\My Docs\a.txt" C:\b.txt')
    assert "%1" in custom.expand_command(_item())    # 无选中时保留占位符
    cmd2 = custom.expand_command(_item(action={"kind": "program", "target": "x", "args": "%1"}),
                                 selected=[r"C:\My Docs\a.txt"])
    assert cmd2 == r'x "C:\My Docs\a.txt"'           # 未加引号但含空格 → 自动补引号


def test_sync_creates_projection_and_values(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    r = FakeRegistry()
    assert custom.save_item(r, _item())["ok"]
    p = r"Software\Classes\*\shell\用记事本打开_a1"
    assert r.get("hkcu", p, "MUIVerb") == "用记事本打开"
    assert r.get("hkcu", p + r"\command") == r"C:\Windows\notepad.exe " + '"%1"'
    assert store.load()["custom_items"][0]["id"] == "a1"


def test_sync_ext_filter_uses_system_file_associations(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    r = FakeRegistry()
    assert custom.save_item(r, _item(ext_filter=[".py", ".txt"]))["ok"]
    for ext in (".py", ".txt"):          # 过滤里的**每个**扩展名都要投影（漏一条 = 功能缺陷）
        key = rf"Software\Classes\SystemFileAssociations\{ext}\shell\用记事本打开_a1"
        assert r.get("hkcu", key, "MUIVerb") == "用记事本打开"
    assert r.get("hkcu", r"Software\Classes\*\shell\用记事本打开_a1", "MUIVerb") is None


def test_sync_submenu_structure(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    r = FakeRegistry()
    child = _item(id="c1", title="子项",
                  action={"kind": "open", "target": r"C:\tmp\a.txt", "args": "", "workdir": ""})
    it = _item(id="p1", title="父菜单", children=[child])
    assert custom.save_item(r, it)["ok"]
    parent = r"Software\Classes\*\shell\父菜单_p1"
    assert r.get("hkcu", parent, "SubCommands") == ""
    assert r.get("hkcu", parent + r"\shell\子项_c1", "MUIVerb") == "子项"


def test_sync_idempotent_and_repositions(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    r = FakeRegistry()
    it = _item()
    base, p = r"Software\Classes\*\shell", r"Software\Classes\*\shell\用记事本打开_a1"

    def snap():
        """投影的完整指纹：键集合 + 四个关键值——二次 save 不得有任何一处漂移。"""
        return (r.list_keys("hkcu", base), r.get("hkcu", p, "MUIVerb"),
                r.get("hkcu", p, "Position"), r.get("hkcu", p + r"\command"))

    assert custom.save_item(r, it)["ok"]
    first = snap()
    assert first[0] == ["用记事本打开_a1"] and first[2] == "Bottom"
    assert custom.save_item(r, it)["ok"]                                  # 二次保存幂等
    assert snap() == first
    it2 = dict(it, scope="directory")
    assert custom.save_item(r, it2)["ok"]
    assert r.get("hkcu", p, "MUIVerb") is None                            # 旧投影被清
    assert r.get("hkcu", r"Software\Classes\Directory\shell\用记事本打开_a1",
                 "MUIVerb") == "用记事本打开"
    # 改标题 → slug 变 → 旧键必须消失（否则菜单里留下一个再也点不到的第二份）
    assert custom.save_item(r, dict(it, title="改名"))["ok"]
    assert r.get("hkcu", p, "MUIVerb") is None
    assert r.get("hkcu", base + r"\改名_a1", "MUIVerb") == "改名"


def test_sync_scope_bases_background_and_drive(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    for scope, seg in (("background", r"Directory\Background"), ("drive", "Drive")):
        r = FakeRegistry()
        assert custom.save_item(r, _item(scope=scope))["ok"]
        key = rf"Software\Classes\{seg}\shell\用记事本打开_a1"
        assert r.get("hkcu", key, "MUIVerb") == "用记事本打开"


def test_delete_removes_projection_and_ledger(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    r = FakeRegistry()
    custom.save_item(r, _item())
    assert custom.delete_item(r, "a1")["ok"]
    assert r.get("hkcu", r"Software\Classes\*\shell\用记事本打开_a1", "MUIVerb") is None
    assert store.load()["custom_items"] == []


def test_save_item_snapshots_before_ledger_change(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    r = FakeRegistry()
    assert custom.save_item(r, _item())["ok"]              # 先建立“用记事本打开”
    seen, real = [], store.backup_snapshot

    def rec(reason):
        seen.append([str(i.get("title")) for i in store.get_custom_items()])
        return real(reason)

    monkeypatch.setattr(store, "backup_snapshot", rec)
    assert custom.save_item(r, _item(title="T2"))["ok"]
    assert seen == [["用记事本打开"]]                       # 备份时账本仍是改前状态


class _BlockNewPathRegistry(FakeRegistry):
    """`set` 在命中 `block` 子串的键上抛异常（模拟安全软件拦截新投影的写入）。"""

    block = ""

    def set(self, hive, path, name, value):
        if self.block and self.block in path:
            raise RuntimeError("blocked")
        return super().set(hive, path, name, value)


def test_save_failure_restores_old_projection(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    r = _BlockNewPathRegistry()
    old_p = r"Software\Classes\*\shell\用记事本打开_a1"
    assert custom.save_item(r, _item())["ok"]
    r.block = "T2"                                          # 新投影（标题 T2）的 set 全部被拦
    out = custom.save_item(r, _item(title="T2"))
    assert out["ok"] is False
    assert r.get("hkcu", old_p, "MUIVerb") == "用记事本打开"    # 旧投影被尽力重建
    assert store.load()["custom_items"][0]["title"] == "用记事本打开"  # 账本已回滚


def test_hklm_sync_routes_elevate(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    jobs = []
    monkeypatch.setattr(custom.elevate, "run_job",
                        lambda job, **k: (jobs.append(job), {"ok": True})[1])
    r = FakeRegistry()
    assert custom.save_item(r, _item(hive="hklm"))["ok"] and jobs
    assert all(op["hive"] == "hklm" for op in jobs[0]["ops"])      # 作业里不得混入 hkcu
    assert r.get("hklm", r"Software\Classes\*\shell\用记事本打开_a1", "MUIVerb") is None  # 未直写


def test_sync_hive_switch_routes_both_channels(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    jobs = []
    monkeypatch.setattr(custom.elevate, "run_job",
                        lambda job, **k: (jobs.append(job), {"ok": True})[1])
    r = FakeRegistry()
    assert custom.save_item(r, _item(hive="hklm"))["ok"]   # 建立 HKLM 投影（走作业）
    jobs.clear()
    assert custom.save_item(r, _item(hive="hkcu"))["ok"]   # 切回 HKCU
    assert jobs and all(op["action"] == "delete_tree" and op["hive"] == "hklm"
                        for op in jobs[0]["ops"])          # 旧 HKLM 投影经提权通道删除
    assert r.get("hkcu", r"Software\Classes\*\shell\用记事本打开_a1", "MUIVerb") == "用记事本打开"
    assert r.get("hklm", r"Software\Classes\*\shell\用记事本打开_a1", "MUIVerb") is None


def test_export_import_roundtrip(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    r = FakeRegistry()
    custom.save_item(r, _item())
    out_path = str(tmp_path / "items.json")
    assert custom.export_items(out_path)["ok"]
    r2 = FakeRegistry()
    assert custom.import_items(r2, out_path)["ok"]
    assert r2.get("hkcu", r"Software\Classes\*\shell\用记事本打开_a1", "MUIVerb") == "用记事本打开"


def test_traversal_id_rejected_and_sibling_key_survives(tmp_path, monkeypatch):
    r"""C1：未校验的 `id` 曾直接流进 `_sync_item` 的 delete_tree/set 路径。

    带反斜杠与 `..` 的 id 拼出的投影路径，在真注册表里会被解析成**键路径的父级**
    （FakeRegistry 现已按 Windows 语义折叠 `..`，见 `registry_backend._clean`），
    于是 `_sync_item` 那句「先删全部旧投影再重写」会把 `shell` 下的兄弟键整棵删掉——
    一条坏数据就能连带清掉用户所有同类右键项。故 id 必须在**写任何东西之前**被拒。

    断言三件事：① `validate_item` 对坏 id 返回 ok=False；② `import_items` 逐条跳过它
    （既有契约：跳过而非整份拒绝）且账本不被污染；③ 兄弟键 `shell\Good` 仍在，
    `save_item`（= MCP `right_menu_custom_save` 那条路）同样拒收。
    """
    _isolate(monkeypatch, tmp_path)
    r = FakeRegistry()
    sibling = r"Software\Classes\*\shell\Good"
    r.set("hkcu", sibling, "", "x")            # 与被导入项同级的既有键
    bad = _item(id="..\\..\\", title="坏项")

    assert custom.validate_item(bad)["ok"] is False
    path = str(tmp_path / "items.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump([_item(), bad], fh, ensure_ascii=False)
    out = custom.import_items(r, path)
    assert "跳过" in out["detail"]             # 坏条目被跳过，不进账本
    assert [i["id"] for i in store.load()["custom_items"]] == ["a1"]
    assert r.get("hkcu", sibling, "") == "x"    # 兄弟键存活

    assert custom.save_item(r, bad)["ok"] is False
    assert r.get("hkcu", sibling, "") == "x"
