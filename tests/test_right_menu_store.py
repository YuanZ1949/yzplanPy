"""right_menu 账本 store 单测：原子写、损坏降级、变更助手、备份快照与剪枝。

每个用例自己 monkeypatch STATE_PATH/BACKUP_DIR/MAX_BACKUPS，绝不碰生产
data/right_menu/（conftest 的 _isolate_db 也做了同一层隔离）。
"""
import json, os
from modules.right_menu import store


def test_load_empty_and_corrupted_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STATE_PATH", str(tmp_path / "state.json"))
    assert store.load()["disabled"] == []
    with open(store.STATE_PATH, "w", encoding="utf-8") as f:
        f.write("{broken json")
    assert store.load()["schema"] == 1 and store.load()["disabled"] == []


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
    assert store.add_shellnew_hidden("hkcu", r"Software\Classes\.xyz\ShellNew", "NullFile")
    assert store.set_custom_items([{"id": "1", "title": "T"}])
    assert store.set_yzmenu(True, ["open_manager"])
    assert store.load()["disabled"][0]["key_path"].endswith("X")
    assert store.remove_disabled("hkcu", r"Software\Classes\*\shell\X")
    assert store.load()["disabled"] == []
    # 账本形状必须与 spec design.md:269-270 一致（下游 T10/T11 按此形状读写）
    assert store.load()["yzmenu"] == {"installed": True, "actions": ["open_manager"]}
    assert store.add_restore_point("demo", ["a"])
    point = store.load()["restore_points"][-1]
    assert point["reason"] == "demo"
    assert isinstance(point["id"], str) and point["id"] != ""
    assert point["changes"] == ["a"]


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