"""n-gram 粒度分词器 + 每聚合粒度列（Task 3）TDD 测试。

覆盖：
- _norm_text(text, granularity=1) 与旧 _WORD_RE.findall 行为字节一致（parametrized）
- granularity=n 生成连续 n 个基础 token 的 n-gram（滑动窗口）
- granularity=10 不抛异常；越界粒度（0/11/负）被钳制到 [1, 10]
- _cluster_by_similarity_gen 接受 granularity 且影响聚类结果
- aggregations 表 similarity_granularity 列：schema / roundtrip / 默认值 / 钳制
"""
import sqlite3
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from modules.rss_store import RssStore


# ── _norm_text：granularity=1 与旧行为字节一致 ────────────────

@pytest.mark.parametrize("text", [
    "三体 第一季 01",
    "AI Trend 2026",
    "海贼王第1000话高清下载",
    "Python Tips & Tricks",
    "!!! 纯符号 ???",
    "Mixed 中文 English 123",
    "",
    None,
    "a" * 50,
])
def test_norm_text_granularity1_identical_to_baseline(text):
    """granularity=1 时 _norm_text 与旧 _WORD_RE.findall 行为字节一致。"""
    from modules.rss_aggregator.text_utils import _norm_text, _WORD_RE
    assert _norm_text(text, 1) == _WORD_RE.findall((text or "").lower())


# ── _norm_text：n-gram 生成 ───────────────────────────────────

def test_norm_text_granularity3_ngram_combos():
    """granularity=3 在「三体 第一季 01」上生成 3-gram 组合。"""
    from modules.rss_aggregator.text_utils import _norm_text
    tokens = _norm_text("三体 第一季 01", 3)
    assert tokens == ["三体 第一季 01"]


def test_norm_text_granularity2_ngram_combos():
    """granularity=2 生成连续 2 个基础 token 的滑动窗口。"""
    from modules.rss_aggregator.text_utils import _norm_text
    tokens = _norm_text("三体 第一季 01", 2)
    assert tokens == ["三体 第一季", "第一季 01"]


def test_norm_text_granularity10_no_throw():
    """granularity=10 不抛异常：短文本返回空列表，长文本生成 10-gram。"""
    from modules.rss_aggregator.text_utils import _norm_text
    assert _norm_text("三体 第一季 01", 10) == []
    long_text = " ".join(f"词{i}" for i in range(15))
    tokens = _norm_text(long_text, 10)
    assert len(tokens) == 6  # 15 - 10 + 1
    assert tokens[0] == "词0 词1 词2 词3 词4 词5 词6 词7 词8 词9"


def test_norm_text_granularity_out_of_range_clamped():
    """越界粒度（0/负/11）被钳制到 [1, 10]。"""
    from modules.rss_aggregator.text_utils import _norm_text
    base = ["三体", "第一季", "01"]
    assert _norm_text("三体 第一季 01", 0) == base
    assert _norm_text("三体 第一季 01", -3) == base
    assert _norm_text("三体 第一季 01", 11) == _norm_text("三体 第一季 01", 10)


# ── _cluster_by_similarity_gen：granularity 生效 ──────────────

def _drain(gen):
    """消费生成器，返回最终簇列表。"""
    try:
        while True:
            next(gen)
    except StopIteration as e:
        return e.value


def test_cluster_by_similarity_gen_granularity_affects_clusters():
    """granularity=1 时共享 token 聚成 1 簇；granularity=3 时 3-gram 全异 → 3 簇。"""
    from modules.rss_aggregator.text_utils import _cluster_by_similarity_gen
    items = [
        {"title": "三体 第一季 01", "link": "http://x/1", "published": "2026-01-01"},
        {"title": "三体 第一季 02", "link": "http://x/2", "published": "2026-01-02"},
        {"title": "三体 第二季 01", "link": "http://x/3", "published": "2026-01-03"},
    ]
    clusters1 = _drain(_cluster_by_similarity_gen(items, 0.55, 1))
    clusters3 = _drain(_cluster_by_similarity_gen(items, 0.55, 3))
    assert len(clusters1) == 1, f"granularity=1 应聚成 1 簇, 实际: {len(clusters1)}"
    assert len(clusters3) == 3, f"granularity=3 应聚成 3 簇, 实际: {len(clusters3)}"


def test_cluster_by_similarity_gen_default_granularity_is_1():
    """默认 granularity=1：与显式传 1 结果一致。"""
    from modules.rss_aggregator.text_utils import _cluster_by_similarity_gen
    items = [
        {"title": "三体 第一季 01", "link": "http://x/1", "published": "2026-01-01"},
        {"title": "三体 第一季 02", "link": "http://x/2", "published": "2026-01-02"},
    ]
    default = _drain(_cluster_by_similarity_gen(items, 0.55))
    explicit = _drain(_cluster_by_similarity_gen(items, 0.55, 1))
    assert len(default) == len(explicit) == 1


# ── Todo 24: 输出端改为独立标题 + 频次（非 n-gram 合并 token）────────

def test_cluster_by_similarity_gen_granularity9_individual_titles_with_counts():
    """granularity=9：结果含独立原始标题 + 整数频次，频次和 == 源条目数。

    回归 todo 24：聚合结果必须是独立标题（非 9-token 拼接串）各配频次。
    """
    from modules.rss_aggregator.text_utils import _cluster_by_similarity_gen
    items = [
        {"title": "三体 第一季 01 高清 中字 1080p 完整版 国语 全集",
         "link": "http://x/1", "published": "2026-01-01"},
        {"title": "三体 第一季 01 高清 中字 1080p 完整版 国语 全集",
         "link": "http://x/2", "published": "2026-01-02"},
        {"title": "海贼王 第1000话 高清 中字 1080p 完整版 国语 全集 剧场版",
         "link": "http://x/3", "published": "2026-01-03"},
    ]
    clusters = _drain(_cluster_by_similarity_gen(items, 0.55, 9))
    assert clusters, "granularity=9 应产生结果"
    titles = {it["title"] for it in items}
    for cl in clusters:
        assert "title" in cl and "count" in cl, f"簇应含 title/count: {cl}"
        assert isinstance(cl["count"], int) and cl["count"] >= 1, (
            f"count 应为 >=1 的整数, 实际: {cl.get('count')!r}"
        )
        assert cl["title"] in titles, f"标题应为独立原始标题, 实际: {cl['title']!r}"
    assert sum(cl["count"] for cl in clusters) == len(items), (
        f"频次和应等于源条目数 {len(items)}, 实际: {sum(cl['count'] for cl in clusters)}"
    )


def test_cluster_by_similarity_sync_output_shape():
    """同步包装 _cluster_by_similarity 输出 {title, count} 形状（todo 24）。"""
    from modules.rss_aggregator.text_utils import _cluster_by_similarity
    items = [
        {"title": "三体 第一季 01 高清 中字 1080p 完整版 国语 全集",
         "link": "http://x/1", "published": "2026-01-01"},
        {"title": "三体 第一季 01 高清 中字 1080p 完整版 国语 全集",
         "link": "http://x/2", "published": "2026-01-02"},
    ]
    clusters = _cluster_by_similarity(items, 0.55, 9)
    assert len(clusters) == 1
    assert clusters[0]["title"] == items[0]["title"]
    assert clusters[0]["count"] == 2


# ── DB：schema + roundtrip + 钳制 ─────────────────────────────

def _make_store(tmp_path):
    return RssStore(str(tmp_path / "t.db"))


def test_aggregations_schema_has_similarity_granularity(tmp_path, monkeypatch):
    """aggregations 表含 similarity_granularity INTEGER DEFAULT 1。"""
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    _make_store(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        cols = {r["name"]: r for r in conn.execute("PRAGMA table_info(aggregations)").fetchall()}
    assert "similarity_granularity" in cols, "aggregations 表缺少 similarity_granularity 列"
    assert cols["similarity_granularity"]["type"] == "INTEGER", (
        f"similarity_granularity 类型应为 INTEGER, 实际: {cols['similarity_granularity']['type']}"
    )
    assert cols["similarity_granularity"]["dflt_value"] == "1", (
        f"similarity_granularity 默认值应为 1, 实际: {cols['similarity_granularity']['dflt_value']}"
    )


def test_add_aggregation_similarity_granularity_roundtrip(tmp_path, monkeypatch):
    """add_aggregation(similarity_granularity=5) 读回 5。"""
    monkeypatch.chdir(tmp_path)
    store = _make_store(tmp_path)
    agg_id = store.add_aggregation("GranTest", agg_type="mixed", similarity_granularity=5)
    agg = store.get_aggregation(agg_id)
    assert agg is not None
    assert agg["similarity_granularity"] == 5


def test_add_aggregation_default_granularity_is_1(tmp_path, monkeypatch):
    """未指定 similarity_granularity 时默认 1。"""
    monkeypatch.chdir(tmp_path)
    store = _make_store(tmp_path)
    agg_id = store.add_aggregation("GranDefault", agg_type="mixed")
    assert store.get_aggregation(agg_id)["similarity_granularity"] == 1


def test_update_aggregation_similarity_granularity(tmp_path, monkeypatch):
    """update_aggregation(agg_id, similarity_granularity=8) 生效。"""
    monkeypatch.chdir(tmp_path)
    store = _make_store(tmp_path)
    agg_id = store.add_aggregation("GranUpd", agg_type="mixed")
    store.update_aggregation(agg_id, similarity_granularity=8)
    assert store.get_aggregation(agg_id)["similarity_granularity"] == 8


def test_add_aggregation_granularity_out_of_range_clamped(tmp_path, monkeypatch):
    """越界粒度（0/11/负）被钳制到 [1, 10]。"""
    monkeypatch.chdir(tmp_path)
    store = _make_store(tmp_path)
    a0 = store.add_aggregation("Gran0", agg_type="mixed", similarity_granularity=0)
    a11 = store.add_aggregation("Gran11", agg_type="mixed", similarity_granularity=11)
    aneg = store.add_aggregation("GranNeg", agg_type="mixed", similarity_granularity=-5)
    assert store.get_aggregation(a0)["similarity_granularity"] == 1
    assert store.get_aggregation(a11)["similarity_granularity"] == 10
    assert store.get_aggregation(aneg)["similarity_granularity"] == 1


def test_update_aggregation_granularity_out_of_range_clamped(tmp_path, monkeypatch):
    """update 越界粒度同样被钳制。"""
    monkeypatch.chdir(tmp_path)
    store = _make_store(tmp_path)
    agg_id = store.add_aggregation("GranUpdClamp", agg_type="mixed")
    store.update_aggregation(agg_id, similarity_granularity=99)
    assert store.get_aggregation(agg_id)["similarity_granularity"] == 10
    store.update_aggregation(agg_id, similarity_granularity=-1)
    assert store.get_aggregation(agg_id)["similarity_granularity"] == 1