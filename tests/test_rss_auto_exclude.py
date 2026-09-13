"""Tests for auto_exclude: sync_auto_exclude_child."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
except Exception:
    pass

from modules.rss_store.store import RssStore
from modules.rss_aggregator.auto_exclude import (
    sync_auto_exclude_child, AUTO_EXCLUDE_SUFFIX, _find_auto_exclude_child,
)


def _temp_store():
    """创建一个基于临时文件的 RssStore（_init_schema 会建好所有表）。"""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="rss_test_")
    os.close(fd)
    return RssStore(path)


def _seed_items(store, titles):
    """插入一批测试条目并返回它们的 hash 列表。"""
    hashes = []
    conn = store._conn()
    for t in titles:
        h = f"h_{t.lower().replace(' ', '_')[:40]}"
        conn.execute(
            "INSERT OR IGNORE INTO items(hash,title,link,description,published) VALUES(?,?,?,?,?)",
            (h, t, f"https://example.com/{h}", t, "2026-01-01"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO item_sources(hash,tag) VALUES(?,?)",
            (h, "test"),
        )
        hashes.append(h)
    conn.commit()
    return hashes


def _link_items(store, agg_id, hashes):
    """把条目关联到聚合。"""
    conn = store._conn()
    for h in hashes:
        conn.execute("INSERT OR IGNORE INTO aggregation_items(agg_id,hash) VALUES(?,?)", (agg_id, h))
    conn.commit()


def _make_sim_agg(store, name="AI News", parent_id=0, threshold=0.55):
    """创建 similarity 类型聚合，返回 agg_id。"""
    return store.add_aggregation(name, agg_type="similarity", parent_id=parent_id, similarity_threshold=threshold)


class TestSyncAutoExcludeChild(unittest.TestCase):

    def test_no_supported_type_returns_none(self):
        """torrent 等非 similarity/mixed/keyword 类型 → 即使有子聚合条目也返回 None。"""
        store = _temp_store()
        aid = store.add_aggregation("Torrent", agg_type="torrent")
        cid = store.add_aggregation("Torrent子", agg_type="keyword", parent_id=aid)
        hashes = _seed_items(store, ["GPT-5 发布 性能全面提升"])
        _link_items(store, cid, hashes)
        self.assertIsNone(sync_auto_exclude_child(store, aid))

    def test_no_members_returns_none(self):
        """无任何子聚合 → covered 为空 → 不创建噪音，返回 None。"""
        store = _temp_store()
        aid = _make_sim_agg(store)
        self.assertIsNone(sync_auto_exclude_child(store, aid))

    def test_single_cluster_creates_child(self):
        """父聚合 + 一个子聚合（同主题条目）→ 创建 {name}未分类条目，kw_forbidden 含高频词。"""
        store = _temp_store()
        aid = _make_sim_agg(store)
        cid = store.add_aggregation("AI News官方", agg_type="keyword", parent_id=aid)
        hashes = _seed_items(store, [
            "GPT-5 发布 性能全面提升",
            "GPT-5 正式发布 带来重大改进",
            "OpenAI 发布 GPT-5 全新模型",
        ])
        _link_items(store, cid, hashes)
        result = sync_auto_exclude_child(store, aid)
        self.assertIsNotNone(result)
        child = store.get_aggregation(result)
        self.assertIsNotNone(child)
        self.assertEqual(child["parent_id"], aid)
        self.assertEqual(child["name"], "AI News" + AUTO_EXCLUDE_SUFFIX)
        forbidden = json.loads(child.get("kw_forbidden") or "[]")
        self.assertGreater(len(forbidden), 0)
        self.assertIn("gpt", forbidden)

    def test_mixed_clusters_creates_child(self):
        """mixed 父聚合 + 子聚合含两组不同主题条目 → 创建 {name}未分类条目，kw_forbidden 非空。"""
        store = _temp_store()
        aid = store.add_aggregation("汇总", agg_type="mixed")
        cid = store.add_aggregation("汇总子", agg_type="keyword", parent_id=aid)
        cluster1 = [
            "GPT-5 发布 性能全面提升",
            "OpenAI 发布 GPT-5 新模型",
            "GPT-5 正式上线 带来改进",
        ]
        cluster2 = [
            "Rust 入门教程 第一章",
            "Rust 入门教程 第二章",
            "Rust 入门教程 第三章",
        ]
        hashes = _seed_items(store, cluster1 + cluster2)
        _link_items(store, cid, hashes)

        result = sync_auto_exclude_child(store, aid)
        self.assertIsNotNone(result)
        child = store.get_aggregation(result)
        self.assertIsNotNone(child)
        self.assertEqual(child["parent_id"], aid)
        self.assertIn(AUTO_EXCLUDE_SUFFIX, child["name"])
        forbidden = json.loads(child.get("kw_forbidden") or "[]")
        self.assertGreater(len(forbidden), 0)

    def test_mixed_keyword_parent_create_child(self):
        """keyword 类型父聚合 + 子聚合条目 → 创建成功（gate 放宽覆盖 mixed/keyword）。"""
        store = _temp_store()
        aid = store.add_aggregation("关键词源", agg_type="keyword", kw_required=["GPT"])
        cid = store.add_aggregation("关键词源子", agg_type="keyword", parent_id=aid)
        hashes = _seed_items(store, [
            "GPT-5 发布 性能全面提升",
            "OpenAI 发布 GPT-5 新模型",
        ])
        _link_items(store, cid, hashes)

        result = sync_auto_exclude_child(store, aid)
        self.assertIsNotNone(result)
        child = store.get_aggregation(result)
        self.assertIsNotNone(child)
        self.assertEqual(child["parent_id"], aid)
        self.assertEqual(child["name"], "关键词源" + AUTO_EXCLUDE_SUFFIX)

    def test_idempotent_run(self):
        """多次调用不会重复创建子聚合。"""
        store = _temp_store()
        aid = _make_sim_agg(store)
        cid = store.add_aggregation("AI News官方", agg_type="keyword", parent_id=aid)
        hashes = _seed_items(store, [
            "GPT-5 发布 性能全面提升",
            "OpenAI 发布 GPT-5 新模型",
            "Rust 入门教程 第一章",
            "Rust 入门教程 第二章",
        ])
        _link_items(store, cid, hashes)

        id1 = sync_auto_exclude_child(store, aid)
        id2 = sync_auto_exclude_child(store, aid)
        self.assertEqual(id1, id2)
        children = [a for a in store.list_aggregations()
                    if a.get("parent_id") == aid and a.get("name", "").endswith(AUTO_EXCLUDE_SUFFIX)]
        self.assertEqual(len(children), 1)

    def test_legacy_suffix_migration(self):
        """旧 {name}_剩余 子聚合 → _find 命中后改名迁移，二次调用幂等。"""
        store = _temp_store()
        aid = _make_sim_agg(store)
        cid = store.add_aggregation("AI News_剩余", agg_type="keyword", parent_id=aid)
        hashes = _seed_items(store, ["GPT-5 发布 性能全面提升"])
        _link_items(store, cid, hashes)

        found = _find_auto_exclude_child(store, aid, "AI News")
        self.assertIsNotNone(found)
        self.assertEqual(found["id"], cid)
        self.assertEqual(found["name"], "AI News" + AUTO_EXCLUDE_SUFFIX)
        names = [a.get("name") for a in store.list_aggregations() if a.get("parent_id") == aid]
        self.assertNotIn("AI News_剩余", names)

        found2 = _find_auto_exclude_child(store, aid, "AI News")
        self.assertEqual(found2["id"], cid)
        self.assertEqual(found2["name"], "AI News" + AUTO_EXCLUDE_SUFFIX)

    def test_disabled_agg_returns_none(self):
        store = _temp_store()
        aid = _make_sim_agg(store)
        store.update_aggregation(aid, enabled=0)
        self.assertIsNone(sync_auto_exclude_child(store, aid))

    def test_find_auto_exclude_child(self):
        store = _temp_store()
        aid = _make_sim_agg(store)
        child_name = "AI News" + AUTO_EXCLUDE_SUFFIX
        cid = store.add_aggregation(child_name, agg_type="keyword", parent_id=aid)
        found = _find_auto_exclude_child(store, aid, "AI News")
        self.assertIsNotNone(found)
        self.assertEqual(found["id"], cid)

    def test_find_auto_exclude_child_not_found(self):
        store = _temp_store()
        aid = _make_sim_agg(store)
        self.assertIsNone(_find_auto_exclude_child(store, aid, "AI News"))


if __name__ == "__main__":
    unittest.main()