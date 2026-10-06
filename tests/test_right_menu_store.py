"""right_menu 账本 store 单测：原子写、损坏降级、变更助手、备份快照与剪枝。

每个用例自己 monkeypatch STATE_PATH/BACKUP_DIR/MAX_BACKUPS，绝不碰生产
data/right_menu/（conftest 的 _isolate_db 也做了同一层隔离）。
"""
import json, os
from modules.right_menu import store


def test_load_empty_and_corrupted_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(store, "BACKUP_DIR", str(tmp_path / "backups"))
    assert store.load()["disabled"] == []
    with open(store.STATE_PATH, "w", encoding="utf-8") as f:
        f.write("{broken json")
    assert store.load()["schema"] == 1 and store.load()["disabled"] == []
    # 账本存在却读不出时不得写快照：空账本快照「看起来合法」却无内容可还原
    assert store.backup_snapshot("x") is None
    assert not os.path.exists(store.BACKUP_DIR)   # 一个文件都没写


def test_save_is_atomic_and_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STATE_PATH", str(tmp_path / "state.json"))
    st = store._empty_state()
    st["disabled"].append({"hive": "hkcu", "key_path": "k", "name": "LegacyDisable", "original": None, "ts": "t"})
    assert store.save(st) is True
    assert store.load()["disabled"][0]["key_path"] == "k"
    assert not os.path.exists(store.STATE_PATH + ".tmp")   # 原子写不留半文件


def test_mutators_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STATE_PATH", str(tmp_path / "state.json"))
    assert store.add_disabled("hkcu", r"Software\Classes\*\shell\X", None)
    assert "original" in store.load()["disabled"][0]   # spec:266：disabled 账带 original
    assert store.add_shellnew_hidden("hkcu", r"Software\Classes\.xyz\ShellNew", "NullFile")
    # spec design.md:267 的 shellnew 形状是 path/orig_name（无 original 键）
    assert set(store.load()["shellnew_hidden"][-1]) == {"hive", "path", "orig_name", "ts"}
    assert store.set_custom_items([{"id": "1", "title": "T"}])
    assert store.set_yzmenu(True, ["open_manager"])
    assert store.load()["disabled"][0]["key_path"].endswith("X")
    assert store.remove_disabled("hkcu", r"Software\Classes\*\shell\X")
    assert store.load()["disabled"] == []
    assert store.remove_shellnew_hidden("hkcu", r"Software\Classes\.xyz\ShellNew", "NullFile")
    assert store.load()["shellnew_hidden"] == []
    # 账本形状必须与 spec design.md:269-270 一致（下游 T10/T11 按此形状读写）
    assert store.load()["yzmenu"] == {"installed": True, "actions": ["open_manager"]}
    assert store.add_restore_point("demo", ["a"])
    point = store.load()["restore_points"][-1]
    assert point["reason"] == "demo"
    assert isinstance(point["id"], str) and point["id"] != ""
    assert point["changes"] == ["a"]
    # F1：非可迭代标量入参不得抛（永不抛不变量），生成器等可迭代输入仍可用
    assert store.set_custom_items(7) and store.load()["custom_items"] == []
    assert store.set_yzmenu(True, 7) and store.load()["yzmenu"]["actions"] == []
    assert store.set_yzmenu(True, (a for a in ["open_manager"]))
    assert store.load()["yzmenu"]["actions"] == ["open_manager"]
    # F4：未登记的账桶（编程错误）拒绝写入并返回 False，不抛 KeyError
    assert store._upsert("nosuchbucket", "hkcu", "k", None) is False
    assert store._drop("nosuchbucket", "hkcu", "k") is False
    assert "nosuchbucket" not in store.load()


def test_backup_snapshot_writes_file_and_prunes(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(store, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(store, "MAX_BACKUPS", 3)
    for i in range(5):
        assert store.backup_snapshot(f"op{i}") is not None
    files = os.listdir(store.BACKUP_DIR)
    assert len(files) == 3   # 剪枝到上限
    data = json.load(open(os.path.join(store.BACKUP_DIR, sorted(files)[-1]), encoding="utf-8"))
    assert data["schema"] == 1

    # 同一 reason 连拍：序号必须数值感知。字典序会把 _op_9 排到 _op_11 之前，
    # 于是最旧的 9/10/11 反而被当成「最新」留下。冻结时钟 + 人为 mtime 平局，
    # 否则真实 mtime 递增会掩盖排序键的错误（只拍 5 次也分不出个位数序号）。
    monkeypatch.setattr(store.time, "strftime", lambda fmt: "20261005_141530")
    monkeypatch.setattr(store, "MAX_BACKUPS", 99)
    monkeypatch.setattr(store, "BACKUP_DIR", str(tmp_path / "burst"))
    for _ in range(12):
        assert store.backup_snapshot("op") is not None
    for name in os.listdir(store.BACKUP_DIR):
        os.utime(os.path.join(store.BACKUP_DIR, name), (1757000000, 1757000000))
    monkeypatch.setattr(store, "MAX_BACKUPS", 3)
    assert store._prune_backups() == 9
    left = sorted(int(n[:-len(".json")].rsplit("_", 1)[-1] or 0)
                  for n in os.listdir(store.BACKUP_DIR))
    assert left == [9, 10, 11]   # 序号最大的 3 个存活


def test_restore_all_reverts_and_clears_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(store, "BACKUP_DIR", str(tmp_path / "backups"))
    from modules.right_menu import classic, custom, yzmenu
    from modules.right_menu.registry_backend import FakeRegistry

    r = FakeRegistry()
    # 1) 被隐藏项
    r.set("hkcu", r"Software\Classes\*\shell\Demo", "", "Demo")
    store.add_disabled("hkcu", r"Software\Classes\*\shell\Demo", None)
    r.set("hkcu", r"Software\Classes\*\shell\Demo", "LegacyDisable", "")
    # 2) ShellNew 隐藏
    r.set("hkcu", r"Software\Classes\.xyz\ShellNew", "NullFile__yzhidden", "D")
    store.add_shellnew_hidden("hkcu", r"Software\Classes\.xyz\ShellNew", "NullFile")
    # 3) 自定义项（写投影 + 账本）
    custom.save_item(r, {"id": "a1", "title": "T", "icon": "", "scope": "file",
                         "ext_filter": [], "hive": "hkcu", "extended": False,
                         "position": "bottom",
                         "action": {"kind": "open", "target": r"C:\t.txt",
                                    "args": "", "workdir": ""},
                         "children": []})
    # 4) YZplan 子菜单 + 经典菜单
    yzmenu.install_yzmenu(r, ["open_manager"])
    classic.enable_classic(r)

    out = store.restore_all(r)
    assert out["ok"] and out["report"]
    assert r.get("hkcu", r"Software\Classes\*\shell\Demo", "LegacyDisable") is None
    assert r.get("hkcu", r"Software\Classes\.xyz\ShellNew", "NullFile") == "D"
    assert r.get("hkcu", r"Software\Classes\*\shell\T_a1", "MUIVerb") is None
    assert yzmenu.get_yzmenu_state(r)["installed"] is False
    assert classic.get_classic_state(r) == "disabled"
    st = store.load()
    assert st["disabled"] == [] and st["shellnew_hidden"] == [] and st["custom_items"] == []
    assert st["restore_points"] and st["restore_points"][-1]["reason"] == "restore_all"
