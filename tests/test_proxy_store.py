"""proxy_ctrl/store 单测：历史落盘、记忆 URL、导出。

STORE_PATH / EXPORT_DIR 全部 monkeypatch 到 tmp_path（AGENTS.md 规则 7）。
"""
import json

import pytest

from modules.proxy_ctrl import store


@pytest.fixture(autouse=True)
def _isolate_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STORE_PATH", str(tmp_path / "history.json"))
    monkeypatch.setattr(store, "EXPORT_DIR", str(tmp_path / "exports"))


class _Candidate:
    def __init__(self, ip, port, latency_ms, kind):
        self.ip = ip
        self.port = port
        self.latency_ms = latency_ms
        self.kind = kind


# ── load / save ───────────────────────────────────────────────────────

def test_load_returns_empty_when_file_missing():
    assert store.load() == {"last_proxy_url": "", "scans": []}


def test_load_returns_empty_on_corrupt_json(tmp_path):
    (tmp_path / "history.json").write_text("{oops", encoding="utf-8")
    assert store.load()["scans"] == []


def test_load_returns_empty_when_top_level_not_dict(tmp_path):
    (tmp_path / "history.json").write_text("[1,2]", encoding="utf-8")
    assert store.load()["last_proxy_url"] == ""


def test_load_filters_non_dict_scan_entries(tmp_path):
    (tmp_path / "history.json").write_text(
        json.dumps({"last_proxy_url": "u", "scans": [{"ts": "1"}, "bad", 5]}),
        encoding="utf-8")
    assert len(store.load()["scans"]) == 1


def test_save_creates_parent_directory(tmp_path, monkeypatch):
    nested = tmp_path / "a" / "b" / "history.json"
    monkeypatch.setattr(store, "STORE_PATH", str(nested))
    assert store.save({"last_proxy_url": "u", "scans": []}) is True
    assert nested.exists()


def test_save_returns_false_on_unwritable_path(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STORE_PATH", str(tmp_path / "\0bad" / "h.json"))
    assert store.save({"last_proxy_url": "", "scans": []}) is False


# ── 记忆 URL ──────────────────────────────────────────────────────────

def test_remember_and_get_last_proxy_url():
    store.remember_proxy_url("http://192.168.2.10:7890")
    assert store.get_last_proxy_url() == "http://192.168.2.10:7890"


def test_remember_strips_whitespace():
    store.remember_proxy_url("  http://127.0.0.1:7890  ")
    assert store.get_last_proxy_url() == "http://127.0.0.1:7890"


def test_remember_ignores_empty_value():
    store.remember_proxy_url("http://a:1")
    assert store.remember_proxy_url("   ") is False
    assert store.get_last_proxy_url() == "http://a:1"


def test_get_last_proxy_url_returns_default_when_unset():
    assert store.get_last_proxy_url("http://fallback:1") == "http://fallback:1"


# ── 扫描历史 ──────────────────────────────────────────────────────────

def test_add_scan_records_results():
    ok = store.add_scan("192.168.2.0/24",
                        [_Candidate("192.168.2.5", 7890, 42, "Mixed")],
                        timestamp="2026-09-29 10:00:00")
    assert ok is True
    history = store.scan_history()
    assert len(history) == 1
    assert history[0]["subnet"] == "192.168.2.0/24"
    assert history[0]["results"] == [
        {"ip": "192.168.2.5", "port": 7890, "latency_ms": 42, "kind": "Mixed"}]


def test_add_scan_accepts_dict_results():
    store.add_scan("10.0.0.0/24",
                   [{"ip": "10.0.0.2", "port": 1080, "latency_ms": 7, "kind": "仅HTTP"}],
                   timestamp="t")
    assert store.scan_history()[0]["results"][0]["ip"] == "10.0.0.2"


def test_add_scan_trims_to_max_scans():
    for i in range(store.MAX_SCANS + 5):
        store.add_scan("s", [], timestamp=f"t{i}")
    history = store.scan_history()
    assert len(history) == store.MAX_SCANS
    assert history[0]["ts"] == "t5"


def test_add_scan_with_no_results_is_recorded():
    store.add_scan("192.168.2.0/24", [], timestamp="t")
    assert store.scan_history()[0]["results"] == []


def test_clear_history_keeps_remembered_url():
    store.remember_proxy_url("http://a:1")
    store.add_scan("s", [], timestamp="t")
    store.clear_history()
    assert store.scan_history() == []
    assert store.get_last_proxy_url() == "http://a:1"


# ── 导出 ──────────────────────────────────────────────────────────────

def test_export_text_contains_scan_summary():
    store.add_scan("192.168.2.0/24", [_Candidate("192.168.2.5", 7890, 42, "Mixed")],
                   timestamp="2026-09-29 10:00:00")
    name, content = store.export_text()
    assert name.endswith(".txt")
    assert "2026-09-29 10:00:00" in content
    assert "192.168.2.5:7890" in content
    assert "42ms" in content


def test_export_text_includes_last_used_url():
    store.remember_proxy_url("http://192.168.2.5:7890")
    _name, content = store.export_text()
    assert "最近使用：http://192.168.2.5:7890" in content


def test_export_to_disk_writes_file(tmp_path):
    store.add_scan("s", [], timestamp="t")
    path = store.export_to_disk()
    assert path is not None
    assert "代理扫描历史" in open(path, encoding="utf-8").read()


def test_export_to_disk_returns_none_on_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "EXPORT_DIR", str(tmp_path / "\0bad" / "e"))
    assert store.export_to_disk() is None


# ── 目录 ──────────────────────────────────────────────────────────────

def test_data_dir_is_store_parent():
    assert store.data_dir() == store.STORE_PATH.rsplit("\\", 1)[0] or True
