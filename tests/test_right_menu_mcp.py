import os

from mcp_server import tools_right_menu as t


def test_tool_names_registered():
    from mcp_server import _TOOL_BY_NAME
    names = {x["name"] for x in t.TOOLS}
    assert names == {"right_menu_scan", "right_menu_set_disabled", "right_menu_classic_state",
                     "right_menu_classic_set", "right_menu_custom_list", "right_menu_custom_save",
                     "right_menu_custom_delete", "right_menu_shellnew_scan", "right_menu_shellnew_hide",
                     "right_menu_shellnew_restore", "right_menu_restore_all", "right_menu_open_manager"}
    assert all(n in _TOOL_BY_NAME for n in names)


def test_scan_handler_uses_fake(monkeypatch):
    from modules.right_menu.registry_backend import FakeRegistry
    r = FakeRegistry()
    r.set("hkcu", r"Software\Classes\*\shell\Alpha", "", "Alpha")
    r.set("hkcu", r"Software\Classes\Directory\shell\Beta", "", "Beta")
    monkeypatch.setattr(t, "_backend", lambda: r)
    out = t.right_menu_scan({"scope": "file"})
    assert out["ok"] and out["items"][0]["display_name"] == "Alpha"
    assert all(i["display_name"] != "Beta" for i in out["items"])   # scope 真的生效了
    out_all = t.right_menu_scan({"scope": "all"})
    assert len(out_all["items"]) == 2 and out_all["shellnew"] == []


def test_hklm_write_returns_gui_hint(monkeypatch):
    from modules.right_menu import ops
    called = []
    monkeypatch.setattr(ops, "apply_op",
                        lambda *a, **k: called.append(1) or {"ok": True, "detail": ""})
    out = t.right_menu_set_disabled({"action": "disable", "hive": "hklm",
                                     "key_path": r"Software\Classes\*\shell\X"})
    assert out["ok"] is False and "GUI" in out["error"]
    assert called == []          # 守卫必须早于任何操作层调用（零 UAC 风险）


def test_restore_all_with_hklm_ledger_returns_gui_hint(monkeypatch):
    from modules.right_menu import store
    store.add_disabled("hklm", r"Software\Classes\*\shell\Y", None)
    called = []
    monkeypatch.setattr(store, "restore_all",
                        lambda *a, **k: called.append(1) or {"ok": True, "report": []})
    out = t.right_menu_restore_all({})
    assert out["ok"] is False and "GUI" in out["error"]
    assert called == []


def test_restore_all_hklm_in_other_buckets_returns_gui_hint(monkeypatch):
    """除 disabled 外，另两桶的 HKLM 条目同样必须被守卫拦住。

    `store.restore_all` 对 `shellnew_hidden` / `custom_items` 的 HKLM 条目同样落到
    `elevate.run_job`（真 UAC + 最长 60s 阻塞），守卫只查 disabled 桶就会漏过去。
    """
    from modules.right_menu import store
    store.add_shellnew_hidden("hklm", r"Software\Classes\.zz\ShellNew", "NullFile")
    store.set_custom_items([{"id": "z1", "title": "Z", "hive": "hklm", "scope": "file",
                             "action": {"kind": "command", "target": "z.exe", "args": ""}}])
    called = []
    monkeypatch.setattr(store, "restore_all",
                        lambda *a, **k: called.append(1) or {"ok": True, "report": []})
    out = t.right_menu_restore_all({})
    assert out["ok"] is False and "GUI" in out["error"]
    assert called == []


def test_custom_save_hklm_guard(monkeypatch):
    from modules.right_menu import custom, store
    called = []
    monkeypatch.setattr(custom, "save_item",
                        lambda *a, **k: called.append(1) or {"ok": True, "detail": ""})
    action = {"kind": "command", "target": r"C:\tools\z.exe", "args": "%1"}
    out = t.right_menu_custom_save({"item": {"id": "n1", "title": "New", "scope": "file",
                                             "hive": "hklm", "action": action}})
    assert out["ok"] is False and "GUI" in out["error"]
    # 旧投影在 HKLM、新项写 HKCU 同样要拒：_sync_item 按**旧** hive 分组删旧投影，那组走提权
    store.set_custom_items([{"id": "old1", "title": "Old", "scope": "file",
                             "hive": "hklm", "action": action}])
    out = t.right_menu_custom_save({"item": {"id": "old1", "title": "Updated", "scope": "file",
                                             "hive": "hkcu", "action": action}})
    assert out["ok"] is False and "GUI" in out["error"]
    assert called == []


def test_custom_delete_hklm_guard(monkeypatch):
    from modules.right_menu import custom, store
    store.set_custom_items([{"id": "z1", "title": "Z", "hive": "hklm", "scope": "file",
                             "action": {"kind": "command", "target": "z.exe", "args": ""}}])
    called = []
    monkeypatch.setattr(custom, "delete_item",
                        lambda *a, **k: called.append(1) or {"ok": True, "detail": ""})
    out = t.right_menu_custom_delete({"item_id": "z1"})
    assert out["ok"] is False and "GUI" in out["error"]
    assert called == []


def test_shellnew_hide_hklm_guard(monkeypatch):
    from modules.right_menu import shellnew
    from modules.right_menu.registry_backend import FakeRegistry
    r = FakeRegistry()
    r.set("hklm", r"Software\Classes\.zz\ShellNew", "NullFile", "")
    monkeypatch.setattr(t, "_backend", lambda: r)
    called = []
    monkeypatch.setattr(shellnew, "hide_shellnew",
                        lambda *a, **k: called.append(1) or {"ok": True, "detail": ""})
    out = t.right_menu_shellnew_hide({"hive": "hklm", "ext": ".zz"})
    assert out["ok"] is False and "GUI" in out["error"]
    assert called == []


def test_open_manager_queues_inbox(monkeypatch, tmp_path):
    monkeypatch.setattr(t, "DATA_DIR", str(tmp_path))
    out = t.right_menu_open_manager({})
    assert out["queued"] is True
    assert os.path.isfile(out["inbox_file"])
    assert str(out["inbox_file"]).startswith(str(tmp_path))
    import json as _json
    with open(out["inbox_file"], encoding="utf-8") as handle:
        payload = _json.load(handle)
    assert payload["command"] == "menu_action" and payload["action"] == "open_manager"
