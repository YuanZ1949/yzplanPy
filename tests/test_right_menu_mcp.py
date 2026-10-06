from mcp_server import tools_right_menu as t


def test_tool_names_registered():
    from mcp_server import _TOOL_BY_NAME
    names = {x["name"] for x in t.TOOLS}
    assert {"right_menu_scan", "right_menu_set_disabled", "right_menu_classic_state",
            "right_menu_classic_set", "right_menu_custom_list", "right_menu_restore_all",
            "right_menu_open_manager"} <= names
    assert all(n in _TOOL_BY_NAME for n in names)


def test_scan_handler_uses_fake(monkeypatch):
    from modules.right_menu.registry_backend import FakeRegistry
    r = FakeRegistry()
    r.set("hkcu", r"Software\Classes\*\shell\Alpha", "", "Alpha")
    monkeypatch.setattr(t, "_backend", lambda: r)
    out = t.right_menu_scan({"scope": "file"})
    assert out["ok"] and out["items"][0]["display_name"] == "Alpha"


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


def test_open_manager_queues_inbox(monkeypatch, tmp_path):
    monkeypatch.setattr(t, "DATA_DIR", str(tmp_path))
    out = t.right_menu_open_manager({})
    assert out["queued"] is True
