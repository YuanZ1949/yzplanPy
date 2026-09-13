"""AggregationService 后台聚合刷新测试。

验证：
- done 信号在后台批次完成后触发（含异常路径，绝不悬挂）
- 完成后主线程向 widgets 广播 on_feed_done({})
- 重入保护：busy 时新提交被忽略
- 相似性聚合的 auto_exclude 联动在后台刷新后仍生效
- 单个聚合失败不中断批次，done 仍触发
"""
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from modules.rss_aggregator.agg_service import AggregationService
from modules.rss_aggregator.auto_exclude import AUTO_EXCLUDE_SUFFIX
from modules.rss_store import RssStore


def _wait_for(spy, signal, timeout_ms=5000):
    """等待信号触发（超时保护）。

    本环境 PySide6 的 QSignalSpy.wait() 不处理跨线程排队事件（实测 count 恒为 0），
    改用标准 Qt 模式：QEventLoop + QTimer 超时 + 信号驱动退出。
    """
    loop = QEventLoop()
    QTimer.singleShot(timeout_ms, loop.quit)
    signal.connect(loop.quit)
    loop.exec()
    return spy.count() > 0


def _make_store(tmp_path):
    return RssStore(str(tmp_path / "t.db"))


def _seed_similar_items(store, feed_id=None, agg_id=None):
    """入库 4 条相似条目；feed_id 关联真实订阅源，agg_id 直接挂到聚合成员。"""
    entries = [
        {"title": "GPT-5 发布 性能全面提升", "link": "http://x/1", "description": "a"},
        {"title": "OpenAI 发布 GPT-5 新模型", "link": "http://x/2", "description": "b"},
        {"title": "Rust 入门教程 第一章", "link": "http://x/3", "description": "c"},
        {"title": "Rust 入门教程 第二章", "link": "http://x/4", "description": "d"},
    ]
    store.ingest("test", entries, feed_id=feed_id)
    if agg_id is not None:
        conn = store._conn()
        for e in entries:
            row = conn.execute("SELECT hash FROM items WHERE link=?", (e["link"],)).fetchone()
            if row:
                conn.execute(
                    "INSERT OR IGNORE INTO aggregation_items(agg_id,hash) VALUES(?,?)",
                    (agg_id, row["hash"]),
                )
        conn.commit()


class _FakeWidget:
    def __init__(self):
        self.calls = []

    def on_feed_done(self, info):
        self.calls.append(info)


def _make_module(tmp_path, monkeypatch):
    from modules.rss_aggregator.module import Module
    store = _make_store(tmp_path)
    monkeypatch.setattr("modules.rss_aggregator.module.RssStore", lambda path: store)
    context = type("_Ctx", (), {"config": {}})()
    mod = Module(context)
    return mod, store


# ── 1. done 信号触发 ────────────────────────────────────────

def test_refresh_all_done_signal_fires(tmp_path):
    store = _make_store(tmp_path)
    store.add_aggregation("A1", agg_type="mixed")
    store.add_aggregation("A2", agg_type="mixed")
    svc = AggregationService(store)
    spy = QSignalSpy(svc.done)
    assert svc.refresh_all() is True
    assert _wait_for(spy, svc.done), "done 信号应在超时内触发"
    assert spy.count() == 1


# ── 2. widgets 广播 ─────────────────────────────────────────

def test_widgets_receive_on_feed_done_broadcast(tmp_path, monkeypatch):
    mod, store = _make_module(tmp_path, monkeypatch)
    w = _FakeWidget()
    mod._widgets.append(w)
    svc = mod._get_agg_svc()
    spy = QSignalSpy(svc.done)
    svc.refresh_all()
    assert _wait_for(spy, svc.done), "done 信号应在超时内触发"
    assert w.calls == [{}], f"widget 应收到 on_feed_done({{}}), 实际: {w.calls}"


# ── 3. 重入保护 ─────────────────────────────────────────────

def test_reentry_busy_ignored(tmp_path):
    store = _make_store(tmp_path)
    svc = AggregationService(store)
    # 确定性：直接置 busy（不依赖真实线程时序）
    with svc._lock:
        svc._busy = True
    assert svc.refresh_all() is False, "busy 时新提交应被忽略"
    with svc._lock:
        svc._busy = False
    spy = QSignalSpy(svc.done)
    assert svc.refresh_all() is True, "空闲后提交应成功"
    assert _wait_for(spy, svc.done)


# ── 4. auto_exclude 联动 ────────────────────────────────────

def test_auto_exclude_linkage_via_refresh_one(tmp_path):
    store = _make_store(tmp_path)
    sim_id = store.add_aggregation("SimNews", agg_type="similarity", tags=["test"])
    child_id = store.add_aggregation("Sim子聚合", agg_type="keyword", parent_id=sim_id)
    _seed_similar_items(store, agg_id=child_id)
    svc = AggregationService(store)
    spy = QSignalSpy(svc.done)
    svc.refresh_one(sim_id)
    assert _wait_for(spy, svc.done), "done 信号应在超时内触发"
    children = [a for a in store.list_aggregations()
                if a.get("parent_id") == sim_id and a.get("name", "").endswith(AUTO_EXCLUDE_SUFFIX)]
    assert len(children) == 1, f"应创建 1 个未分类条目子聚合, 实际: {len(children)}"
    child = children[0]
    assert child["name"].endswith(AUTO_EXCLUDE_SUFFIX), f"子聚合名应以 {AUTO_EXCLUDE_SUFFIX} 结尾: {child['name']}"
    assert child["parent_id"] == sim_id
    forbidden = json.loads(child.get("kw_forbidden") or "[]")
    assert len(forbidden) > 0, "未分类条目子聚合应含 kw_forbidden 关键词"


def test_auto_exclude_linkage_via_refresh_for_feed(tmp_path):
    store = _make_store(tmp_path)
    store.add_feed("FeedA", "http://a/rss", "test")
    feed_id = store.list_feeds()[0]["id"]
    sim_id = store.add_aggregation("SimFeed", agg_type="similarity", feed_ids=[feed_id])
    child_id = store.add_aggregation("Sim子聚合", agg_type="keyword", parent_id=sim_id)
    _seed_similar_items(store, feed_id=feed_id, agg_id=child_id)
    svc = AggregationService(store)
    spy = QSignalSpy(svc.done)
    svc.refresh_for_feed(feed_id)
    assert _wait_for(spy, svc.done), "done 信号应在超时内触发"
    children = [a for a in store.list_aggregations()
                if a.get("parent_id") == sim_id and a.get("name", "").endswith(AUTO_EXCLUDE_SUFFIX)]
    assert len(children) == 1, f"应创建 1 个未分类条目子聚合, 实际: {len(children)}"
    child = children[0]
    assert child["name"].endswith(AUTO_EXCLUDE_SUFFIX), f"子聚合名应以 {AUTO_EXCLUDE_SUFFIX} 结尾: {child['name']}"
    assert child["parent_id"] == sim_id
    forbidden = json.loads(child.get("kw_forbidden") or "[]")
    assert len(forbidden) > 0, "未分类条目子聚合应含 kw_forbidden 关键词"


def test_auto_exclude_no_child_no_noise(tmp_path):
    """无直接子聚合 → 不创建噪音子聚合（保留无噪音语义）。"""
    store = _make_store(tmp_path)
    sim_id = store.add_aggregation("SimNews", agg_type="similarity", tags=["test"])
    _seed_similar_items(store)
    svc = AggregationService(store)
    spy = QSignalSpy(svc.done)
    svc.refresh_one(sim_id)
    assert _wait_for(spy, svc.done), "done 信号应在超时内触发"
    children = [a for a in store.list_aggregations()
                if a.get("parent_id") == sim_id and a.get("name", "").endswith(AUTO_EXCLUDE_SUFFIX)]
    assert len(children) == 0, f"无直接子聚合时不应创建子聚合, 实际: {len(children)}"


# ── 5. 失败隔离 ─────────────────────────────────────────────

class _FlakyStore:
    def __init__(self, real, fail_ids):
        self._real = real
        self._fail_ids = set(fail_ids)
        self.refreshed = []

    def list_aggregations(self):
        return self._real.list_aggregations()

    def refresh_aggregation(self, agg_id):
        self.refreshed.append(agg_id)
        if agg_id in self._fail_ids:
            raise RuntimeError("boom")
        return self._real.refresh_aggregation(agg_id)


def test_failure_isolation_batch_continues(tmp_path):
    real = _make_store(tmp_path)
    a1 = real.add_aggregation("A1", agg_type="mixed")
    a2 = real.add_aggregation("A2", agg_type="mixed")
    store = _FlakyStore(real, fail_ids={a1})
    svc = AggregationService(store)
    spy = QSignalSpy(svc.done)
    svc.refresh_all()
    assert _wait_for(spy, svc.done), "done 信号应在超时内触发"
    assert spy.count() == 1
    assert a1 in store.refreshed, "失败聚合也应被尝试刷新"
    assert a2 in store.refreshed, "批次应继续刷新后续聚合"


def test_done_fires_even_on_unexpected_batch_error(tmp_path):
    class _BoomStore:
        def list_aggregations(self):
            raise RuntimeError("boom")

    svc = AggregationService(_BoomStore())
    spy = QSignalSpy(svc.done)
    svc.refresh_all()
    assert _wait_for(spy, svc.done), "即使批次异常，done 信号也必须在超时内触发"
    assert spy.count() == 1
