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


# ── 6. _extract_keywords: 中英混合 top_n 顺序与去重 ──────────

def test_extract_keywords_mixed_top_n_and_dedup():
    """中英混合标题 top_n 顺序与去重正确。"""
    from modules.rss_aggregator.text_utils import _extract_keywords
    texts = [
        "AI Trend 2026",
        "AI in Healthcare",
        "AI is transforming healthcare",
    ]
    result = _extract_keywords(texts, top_n=3)
    # ai 出现 3 次（最高频），healthcare 2 次，trend 1 次（首次出现最早）
    # "2026" 被 isdigit 过滤，"in" 被停用词过滤
    assert result == ["ai", "healthcare", "trend"], f"实际: {result}"


# ── 7. _extract_keywords: 全符号/停用词 → 空列表 ─────────────

def test_extract_keywords_all_stopwords_returns_empty():
    """全符号/停用词输入返回空列表。"""
    from modules.rss_aggregator.text_utils import _extract_keywords
    texts = ["!!!", "???", "，。、", "the a an of and"]
    result = _extract_keywords(texts)
    assert result == [], f"期望空列表, 实际: {result}"


# ── 8. _extract_keywords: top_n 截断生效 ─────────────────────

def test_extract_keywords_top_n_truncation():
    """top_n 截断生效。"""
    from modules.rss_aggregator.text_utils import _extract_keywords
    texts = [
        "Python Data Science",
        "Python Machine Learning",
        "Python Deep Learning",
    ]
    result = _extract_keywords(texts, top_n=2)
    assert len(result) == 2, f"期望长度 2, 实际: {result}"
    # python:3, learning:2, 其余均 1 次
    assert result == ["python", "learning"], f"实际: {result}"


# ── 9. refresh_aggs_for_feed 连带刷新子聚合 ─────────────────

class _StubStore:
    """替身 store：预置聚合列表，记录 refresh 调用。"""

    def __init__(self, aggs):
        self._aggs = aggs
        self.refreshed = []

    def list_aggregations(self):
        return list(self._aggs)

    def refresh_aggregation(self, agg_id):
        self.refreshed.append(agg_id)


class _StubModule:
    """最小 stub Module，仅暴露 store + refresh_aggs_for_feed。"""
    def __init__(self, store):
        self.store = store


def test_refresh_aggs_for_feed_propagates_to_children():
    """feed 完成后，父聚合及其子聚合均被 refresh。"""
    from modules.rss_aggregator.module import Module
    aggs = [
        {"id": 1, "feed_ids": "[10,20]", "parent_id": 0, "name": "ParentA"},
        {"id": 2, "feed_ids": "[]", "parent_id": 1, "name": "ChildA"},
        {"id": 3, "feed_ids": "[]", "parent_id": 0, "name": "Unrelated"},
    ]
    store = _StubStore(aggs)
    mod = _StubModule(store)
    # 调用 refresh_aggs_for_feed（绑定 Module 方法到 stub）
    Module.refresh_aggs_for_feed(mod, feed_id=10)
    # 父聚合(id=1) 含 feed_id=10 → 被 refresh；子聚合(id=2) parent_id=1 → 被 refresh
    assert 1 in store.refreshed, f"父聚合 id=1 应被 refresh, 实际: {store.refreshed}"
    assert 2 in store.refreshed, f"子聚合 id=2 应被 refresh, 实际: {store.refreshed}"
    # 无关联聚合(id=3) 不应被 refresh
    assert 3 not in store.refreshed, f"无关聚合 id=3 不应被 refresh, 实际: {store.refreshed}"


def test_refresh_aggs_for_feed_no_feed_id_returns_early():
    """feed_id 为空时不刷新任何聚合。"""
    from modules.rss_aggregator.module import Module
    store = _StubStore([{"id": 1, "feed_ids": "[10]", "parent_id": 0, "name": "A"}])
    mod = _StubModule(store)
    Module.refresh_aggs_for_feed(mod, feed_id=None)
    assert store.refreshed == []


# ── 10. MCP TOOLS inputSchema 含 parent_id / similarity_threshold ──

def _find_tool(tool_list, name):
    for t in tool_list:
        if t["name"] == name:
            return t
    return None


def test_rss_agg_add_tools_schema_has_parent_fields():
    """TOOLS 中 rss_agg_add 的 inputSchema 含 parent_id 和 similarity_threshold。"""
    import mcp_server
    tool = _find_tool(mcp_server.TOOLS, "rss_agg_add")
    assert tool is not None, "rss_agg_add 工具未注册"
    props = tool["inputSchema"]["properties"]
    assert "parent_id" in props, f"rss_agg_add inputSchema 缺 parent_id, keys={list(props)}"
    assert props["parent_id"]["type"] == "integer"
    assert "similarity_threshold" in props, f"rss_agg_add inputSchema 缺 similarity_threshold, keys={list(props)}"
    assert props["similarity_threshold"]["type"] == "number"


def test_rss_agg_update_tools_schema_has_parent_fields():
    """TOOLS 中 rss_agg_update 的 inputSchema 含 parent_id 和 similarity_threshold。"""
    import mcp_server
    tool = _find_tool(mcp_server.TOOLS, "rss_agg_update")
    assert tool is not None, "rss_agg_update 工具未注册"
    props = tool["inputSchema"]["properties"]
    assert "parent_id" in props, f"rss_agg_update inputSchema 缺 parent_id, keys={list(props)}"
    assert props["parent_id"]["type"] == "integer"
    assert "similarity_threshold" in props, f"rss_agg_update inputSchema 缺 similarity_threshold, keys={list(props)}"
    assert props["similarity_threshold"]["type"] == "number"


# ── 11. MCP rss_agg_add handler 透传 parent_id / similarity_threshold ──

def test_rss_agg_add_handler_passes_parent_fields(monkeypatch):
    """rss_agg_add handler 将 parent_id / similarity_threshold 透传到 store.add_aggregation。"""
    from mcp_server import tools_rss_agg as mod
    captured = {}

    class _FakeStore:
        @staticmethod
        def add_aggregation(name, agg_type="mixed", feed_ids=None, tags=None,
                            kw_required=None, kw_optional=None, kw_forbidden=None,
                            parent_id=0, similarity_threshold=0.55):
            captured["parent_id"] = parent_id
            captured["similarity_threshold"] = similarity_threshold
            return 999  # fake agg_id

        def get_aggregation(self, agg_id):
            return {"id": agg_id, "name": "x", "feed_ids": "[]", "tags": "[]",
                    "kw_required": "[]", "kw_optional": "[]", "kw_forbidden": "[]",
                    "parent_id": 0, "similarity_threshold": 0.55}

        def get_aggregation_item_count(self, agg_id):
            return 0

    monkeypatch.setattr("mcp_server.tools_rss_feeds._rss_store", lambda: _FakeStore(),
                        raising=False)
    # 直接调用函数签名
    mod.rss_agg_add("test", parent_id=42, similarity_threshold=0.8)
    assert captured["parent_id"] == 42, f"parent_id 未透传, captured={captured}"
    assert captured["similarity_threshold"] == 0.8, f"similarity_threshold 未透传, captured={captured}"
