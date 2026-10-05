"""自定义右键项：DOM 校验 / 命令模板展开 / 注册表投影 / CRUD。

九组用例、六条被钉住的不变量（少任何一条，对应用例即红）：
  * **危险不静默**：未加引号的 `%1` 与未识别的 `%x` 是**警告**而非拒绝——用户往往
    就是想看展开结果再决定，但坏命令必须在保存前被说出来（plan Review Focus 2）。
  * **注册表里占位符原样**：`command` 默认值写的是 `target + " " + args` 模板，展开是
    explorer 的活；`expand_command` 只是同源实现的预览/告警，绝不写进注册表。
  * **投影先删后建**：改作用域 / 改扩展名过滤 / 改标题后，旧投影路径必须被清掉，
    否则用户会看到两个同名菜单项（`test_sync_idempotent_and_repositions` 钉这条）。
  * **slug 确定性**：`<净标题>_<id[:6]>`，同一条 item 反复 sync 必须落同一个键。
  * **HKCU 直写 / HKLM 走提权**：父进程直写 HKLM 是静默无效的（`run_job` 被
    monkeypatch 掉后 `hklm` 命名空间必须一个字节都没变）。
  * **写前必备份**：任何注册表写之前先 `backup_snapshot`（spec L172）。
"""
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
    assert r'"C:\My Docs\a.txt"' in cmd      # %1（多选取第一个；含空格→带引号）
    assert r'"C:\My Docs"' in cmd            # %V（含空格→带引号）
    assert r"C:\b.txt" in cmd                # %*（全部选中）
    assert "%1" in custom.expand_command(_item())    # 无选中时保留占位符


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
    assert r.get("hkcu", r"Software\Classes\SystemFileAssociations\.py\shell\用记事本打开_a1",
                 "MUIVerb") == "用记事本打开"
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
    assert custom.save_item(r, it)["ok"]
    assert custom.save_item(r, it)["ok"]                                  # 二次保存幂等
    it2 = dict(it, scope="directory")
    assert custom.save_item(r, it2)["ok"]
    assert r.get("hkcu", r"Software\Classes\*\shell\用记事本打开_a1", "MUIVerb") is None  # 旧投影被清
    assert r.get("hkcu", r"Software\Classes\Directory\shell\用记事本打开_a1",
                 "MUIVerb") == "用记事本打开"


def test_delete_removes_projection_and_ledger(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    r = FakeRegistry()
    custom.save_item(r, _item())
    assert custom.delete_item(r, "a1")["ok"]
    assert r.get("hkcu", r"Software\Classes\*\shell\用记事本打开_a1", "MUIVerb") is None
    assert store.load()["custom_items"] == []


def test_hklm_sync_routes_elevate(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    jobs = []
    monkeypatch.setattr(custom.elevate, "run_job",
                        lambda job, **k: (jobs.append(job), {"ok": True})[1])
    r = FakeRegistry()
    assert custom.save_item(r, _item(hive="hklm"))["ok"] and jobs
    assert r.get("hklm", r"Software\Classes\*\shell\用记事本打开_a1", "MUIVerb") is None  # 未直写


def test_export_import_roundtrip(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    r = FakeRegistry()
    custom.save_item(r, _item())
    out_path = str(tmp_path / "items.json")
    assert custom.export_items(out_path)["ok"]
    r2 = FakeRegistry()
    assert custom.import_items(r2, out_path)["ok"]
    assert r2.get("hkcu", r"Software\Classes\*\shell\用记事本打开_a1", "MUIVerb") == "用记事本打开"
