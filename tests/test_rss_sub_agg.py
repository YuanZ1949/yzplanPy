"""二级聚合（sub-aggregation）数据层测试。
TDD: 本文件先写（红），再改 store.py（绿）。
"""
import sqlite3
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from modules.rss_store import RssStore


# ── helpers ──────────────────────────────────────────────────

def _make_store(tmp_path):
    """创建临时库 RssStore，返回 (store, db_path)。"""
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    return store, db


def _seed_items(store, feed_name="A", feed_tag="TagA", items=None):
    """创建 feed 并写入条目（含 feed_id 关联），返回 store。"""
    store.add_feed(feed_name, f"http://{feed_name}/rss", feed_tag)
    feed_id = store.list_feeds()[0]["id"]
    store.ingest(feed_tag, items or [
        {"title": "AI Trend 2026", "link": "http://x/1", "description": "Latest AI trends"},
        {"title": "Python Tips", "link": "http://x/2", "description": "Python tricks"},
        {"title": "AI in Healthcare", "link": "http://x/3", "description": "AI is transforming healthcare"},
        {"title": "Rust Guide", "link": "http://x/4", "description": "Learn Rust programming"},
    ], feed_id=feed_id)
    return store


# ── 1. Schema: parent_id & similarity_threshold columns ─────

def test_sub_agg_schema_columns(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store, db = _make_store(tmp_path)

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        cols = {r["name"]: r for r in conn.execute("PRAGMA table_info(aggregations)").fetchall()}

    assert "parent_id" in cols, "aggregations 表缺少 parent_id 列"
    assert cols["parent_id"]["type"] == "INTEGER", f"parent_id 类型应为 INTEGER, 实际: {cols['parent_id']['type']}"
    # DEFAULT 0 校验：插入时未指定 parent_id 应为 0
    assert cols["parent_id"]["dflt_value"] == "0", f"parent_id 默认值应为 0, 实际: {cols['parent_id']['dflt_value']}"

    assert "similarity_threshold" in cols, "aggregations 表缺少 similarity_threshold 列"
    assert cols["similarity_threshold"]["type"] == "REAL", (
        f"similarity_threshold 类型应为 REAL, 实际: {cols['similarity_threshold']['type']}"
    )
    assert cols["similarity_threshold"]["dflt_value"] == "0.55", (
        f"similarity_threshold 默认值应为 0.55, 实际: {cols['similarity_threshold']['dflt_value']}"
    )


# ── 2. 父子聚合 refresh：子快照 ⊆ 父快照 & 每条 title 含 "AI" ──

def test_sub_agg_parent_child_refresh(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store, _ = _make_store(tmp_path)
    _seed_items(store)

    # 创建父聚合（mixed，覆盖全部 feed）
    feed_id = store.list_feeds()[0]["id"]
    parent_id = store.add_aggregation(
        "ParentAll", agg_type="mixed",
        feed_ids=[feed_id],
    )
    assert parent_id is not None

    # 创建子聚合（keyword, parent_id=父, kw_required=["AI"]）
    child_id = store.add_aggregation(
        "ChildAI", agg_type="keyword",
        parent_id=parent_id,
        kw_required=["AI"],
    )

    # 先刷新父聚合，再刷新子聚合
    parent_count = store.refresh_aggregation(parent_id)
    child_count = store.refresh_aggregation(child_id)

    assert parent_count >= 2, f"父聚合应包含至少 2 条含 AI 的条目, 实际: {parent_count}"
    assert child_count >= 2, f"子聚合应包含至少 2 条含 AI 的条目, 实际: {child_count}"

    # 子快照 ⊆ 父快照（通过 hash 集合比较）
    parent_hashes = set(
        r["hash"] for r in store._conn().execute(
            "SELECT hash FROM aggregation_items WHERE agg_id=?", (parent_id,)
        ).fetchall()
    )
    child_hashes = set(
        r["hash"] for r in store._conn().execute(
            "SELECT hash FROM aggregation_items WHERE agg_id=?", (child_id,)
        ).fetchall()
    )
    assert child_hashes.issubset(parent_hashes), (
        f"子快照应为父快照的子集; 子有 {len(child_hashes)} 条, 父有 {len(parent_hashes)} 条, "
        f"差集: {child_hashes - parent_hashes}"
    )

    # 子聚合每条 title 含 "AI"
    child_titles = store.aggregation_titles(child_id)
    for t in child_titles:
        assert "AI" in t, f"子聚合标题应含 'AI': {t}"


# ── 3. similarity_threshold roundtrip ───────────────────────

def test_sub_agg_similarity_threshold_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store, _ = _make_store(tmp_path)

    agg_id = store.add_aggregation("ThrTest", agg_type="mixed", similarity_threshold=0.65)
    agg = store.get_aggregation(agg_id)

    assert agg is not None, "get_aggregation 应返回记录"
    assert agg["similarity_threshold"] == 0.65, (
        f"similarity_threshold roundtrip 期望 0.65, 实际: {agg['similarity_threshold']}"
    )


# ── 4. 删除父聚合 → 子聚合行 + 子快照均消失 ─────────────────

def test_sub_agg_cascade_delete(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store, _ = _make_store(tmp_path)
    _seed_items(store)

    feed_id = store.list_feeds()[0]["id"]
    parent_id = store.add_aggregation("ParentDel", agg_type="mixed", feed_ids=[feed_id])
    assert parent_id is not None
    child_id = store.add_aggregation(
        "ChildDel", agg_type="keyword",
        parent_id=parent_id, kw_required=["AI"],
    )

    store.refresh_aggregation(parent_id)
    store.refresh_aggregation(child_id)

    # 确认子聚合存在
    assert store.get_aggregation(child_id) is not None
    child_snap = store._conn().execute(
        "SELECT COUNT(*) AS c FROM aggregation_items WHERE agg_id=?", (child_id,)
    ).fetchone()["c"]
    assert child_snap > 0, "子聚合快照应非空"

    # 删除父聚合
    store.remove_aggregation(parent_id)

    # 子聚合行消失
    assert store.get_aggregation(child_id) is None, "子聚合行应在父删除后消失"

    # 子聚合快照消失
    child_snap_after = store._conn().execute(
        "SELECT COUNT(*) AS c FROM aggregation_items WHERE agg_id=?", (child_id,)
    ).fetchone()["c"]
    assert child_snap_after == 0, f"子聚合快照应在父删除后清空, 实际剩余: {child_snap_after}"


# ── 5. aggregation_titles 返回父快照标题列表 ────────────────

def test_sub_agg_aggregation_titles(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store, _ = _make_store(tmp_path)
    _seed_items(store)

    feed_id = store.list_feeds()[0]["id"]
    parent_id = store.add_aggregation("ParentTitles", agg_type="mixed", feed_ids=[feed_id])
    store.refresh_aggregation(parent_id)

    titles = store.aggregation_titles(parent_id)
    assert len(titles) > 0, "aggregation_titles 应返回非空列表"
    # 每个元素是字符串
    for t in titles:
        assert isinstance(t, str), f"标题应为字符串: {t}"
    # 应包含至少一个已知条目
    assert any("AI" in t or "Python" in t or "Rust" in t for t in titles), (
        f"应包含已知条目标题, 实际: {titles}"
    )
