"""remainder 聚合类型：精确集合补集。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from modules.rss_aggregator.remainder import (
    REMAINDER_NAME,
    _LEGACY_SUFFIX,
    _SORT_ORDER_MAX,
    _find_remainder_child,
    sync_remainder_child,
)
from modules.rss_store.pure import _hash
from modules.rss_store.store import RssStore


def _make_store(tmp_path):
    return RssStore(str(tmp_path / "t.db"))


def _make_feed(store):
    """创建测试订阅源并返回 feed_id。"""
    store.add_feed("TestFeed", "http://test/rss", "test")
    return store.list_feeds()[0]["id"]


def _seed_items(store, entries, tag="t", feed_id=None):
    """通过 store.ingest 入库条目，返回 hash 列表（与 ingest 内部一致）。"""
    store.ingest(tag, entries, feed_id=feed_id)
    return [_hash(e["title"], e["link"]) for e in entries]


def _seed_torrent_items(store, entries, tag="t", feed_id=None):
    """入库条目并通过直接 DB 更新设置 torrent_hash，返回 hash 列表。"""
    hashes = _seed_items(store, entries, tag=tag, feed_id=feed_id)
    with store._conn() as conn:
        for h, e in zip(hashes, entries):
            th = e.get("torrent_hash", "")
            if th:
                conn.execute(
                    "UPDATE items SET torrent_hash = ? WHERE hash = ?",
                    (th, h),
                )
    return hashes


def _get_agg_hashes(store, agg_id):
    """获取聚合成员的 hash 集合（测试专用）。"""
    with store._conn() as conn:
        rows = conn.execute(
            "SELECT hash FROM aggregation_items WHERE agg_id = ?",
            (agg_id,),
        ).fetchall()
    return {r[0] for r in rows}


def _make_parent(store, feed_id, name="父聚合"):
    return store.add_aggregation(
        name=name, agg_type="mixed", feed_ids=[feed_id])


def _make_child(store, parent_id, name, agg_type="keyword", **kw):
    return store.add_aggregation(
        name=name, agg_type=agg_type, parent_id=parent_id, **kw)


def _make_remainder(store, parent_id, name="未分类条目"):
    return store.add_aggregation(
        name=name, agg_type="remainder", parent_id=parent_id,
        sort_order=2147483647)


def test_sibling_aggregation_ids_excludes_self(tmp_path):
    store = _make_store(tmp_path)
    feed_id = _make_feed(store)
    entries = [{"title": f"标题{i}", "link": f"http://x/{i}", "description": ""}
               for i in range(4)]
    _seed_items(store, entries, feed_id=feed_id)
    parent = _make_parent(store, feed_id)
    store.refresh_aggregation(parent)
    c1 = _make_child(store, parent, "子1")
    c2 = _make_child(store, parent, "子2")
    r = _make_remainder(store, parent)
    assert store.sibling_aggregation_ids(parent, r) == [c1, c2]
    assert store.sibling_aggregation_ids(parent, c1) == [c2, r]


def test_remainder_is_exact_complement_by_hash(tmp_path):
    store = _make_store(tmp_path)
    feed_id = _make_feed(store)
    entries = [{"title": f"标题{i}", "link": f"http://x/{i}", "description": ""}
               for i in range(6)]
    _seed_items(store, entries, feed_id=feed_id)
    parent = _make_parent(store, feed_id)
    store.refresh_aggregation(parent)
    child = _make_child(store, parent, "子1", agg_type="keyword",
                        kw_required=["标题"])
    store.refresh_aggregation(child)
    r = _make_remainder(store, parent)
    store.refresh_aggregation(r)
    # 子1 覆盖了全部 6 条（关键词「标题」命中所有），remainder 应为空
    assert store.get_aggregation_item_count(r) == 0
    assert _get_agg_hashes(store, r) == set()


def test_remainder_excludes_torrent_hash_and_exempts_empty(tmp_path):
    store = _make_store(tmp_path)
    feed_id = _make_feed(store)
    torrent_entries = [
        {"title": f"种子{i}", "link": f"http://x/t{i}",
         "description": "", "torrent_hash": f"a{i:039d}"}
        for i in range(3)
    ]
    regular_entries = [
        {"title": f"标题{i}", "link": f"http://x/r{i}", "description": ""}
        for i in range(2)
    ]
    _seed_torrent_items(store, torrent_entries, feed_id=feed_id)
    regular_hashes = _seed_items(store, regular_entries, feed_id=feed_id)
    parent = _make_parent(store, feed_id)
    store.refresh_aggregation(parent)
    child = _make_child(store, parent, "子1", agg_type="keyword",
                        kw_required=["种子"])
    store.refresh_aggregation(child)
    r = _make_remainder(store, parent)
    store.refresh_aggregation(r)
    # 3 条磁链被兄弟覆盖（torrent_hash 并集排除），2 条普通条目无 BTIH 应豁免保留
    assert _get_agg_hashes(store, r) == set(regular_hashes)


def test_remainder_stable_across_two_syncs(tmp_path):
    """自引用消除：连续两次同步结果稳定（回归 auto_exclude 漂移 bug）。"""
    store = _make_store(tmp_path)
    feed_id = _make_feed(store)
    entries = [
        {"title": "海贼王1000话下载", "link": "http://x/1", "description": ""},
        {"title": "海贼王1001话在线", "link": "http://x/2", "description": ""},
        {"title": "火影忍者完结篇", "link": "http://x/3", "description": ""},
        {"title": "火影忍者博人传", "link": "http://x/4", "description": ""},
        {"title": "龙珠超新番", "link": "http://x/5", "description": ""},
        {"title": "龙珠超漫画更新", "link": "http://x/6", "description": ""},
    ]
    _seed_items(store, entries, feed_id=feed_id)
    parent = _make_parent(store, feed_id)
    store.refresh_aggregation(parent)
    child = _make_child(store, parent, "海贼王", agg_type="keyword",
                        kw_required=["海贼王"])
    store.refresh_aggregation(child)
    r = _make_remainder(store, parent)
    store.refresh_aggregation(r)
    first = _get_agg_hashes(store, r)
    assert len(first) > 0, "remainder 应包含未被子聚合覆盖的条目"
    store.refresh_aggregation(r)
    second = _get_agg_hashes(store, r)
    assert first == second


# ── Task 2：remainder 生命周期（sync_remainder_child / _find_remainder_child）──

def test_sync_remainder_child_creates_when_sibling_exists(tmp_path):
    store = _make_store(tmp_path)
    feed_id = _make_feed(store)
    entries = [{"title": f"标题{i}", "link": f"http://x/{i}", "description": ""}
               for i in range(3)]
    _seed_items(store, entries, feed_id=feed_id)
    parent = _make_parent(store, feed_id)
    _make_child(store, parent, "子1", agg_type="keyword", kw_required=["标题"])
    rid = sync_remainder_child(store, parent)
    assert rid is not None
    agg = store.get_aggregation(rid)
    assert agg["agg_type"] == "remainder"
    assert agg["name"] == REMAINDER_NAME
    assert agg["sort_order"] == _SORT_ORDER_MAX


def test_sync_remainder_child_skips_without_siblings(tmp_path):
    store = _make_store(tmp_path)
    feed_id = _make_feed(store)
    parent = _make_parent(store, feed_id)
    assert sync_remainder_child(store, parent) is None


def test_sync_remainder_child_recreates_after_delete(tmp_path):
    store = _make_store(tmp_path)
    feed_id = _make_feed(store)
    entries = [{"title": f"标题{i}", "link": f"http://x/{i}", "description": ""}
               for i in range(3)]
    _seed_items(store, entries, feed_id=feed_id)
    parent = _make_parent(store, feed_id)
    _make_child(store, parent, "子1", agg_type="keyword", kw_required=["标题"])
    rid = sync_remainder_child(store, parent)
    store.remove_aggregation(rid)
    rid2 = sync_remainder_child(store, parent)
    assert rid2 is not None and rid2 != rid


def test_legacy_name_migration(tmp_path):
    store = _make_store(tmp_path)
    feed_id = _make_feed(store)
    entries = [{"title": f"标题{i}", "link": f"http://x/{i}", "description": ""}
               for i in range(3)]
    _seed_items(store, entries, feed_id=feed_id)
    parent = _make_parent(store, feed_id)
    _make_child(store, parent, "子1", agg_type="keyword", kw_required=["标题"])
    legacy = store.add_aggregation(
        name=f"{store.get_aggregation(parent)['name']}未分类条目",
        agg_type="keyword", parent_id=parent)
    rid = _find_remainder_child(store, parent)
    assert rid == legacy
    assert store.get_aggregation(rid)["name"] == REMAINDER_NAME
    assert store.get_aggregation(rid)["agg_type"] == "remainder"


def test_legacy_suffix_migration(tmp_path):
    store = _make_store(tmp_path)
    feed_id = _make_feed(store)
    entries = [{"title": f"标题{i}", "link": f"http://x/{i}", "description": ""}
               for i in range(3)]
    _seed_items(store, entries, feed_id=feed_id)
    parent = _make_parent(store, feed_id)
    _make_child(store, parent, "子1", agg_type="keyword", kw_required=["标题"])
    legacy = store.add_aggregation(
        name=f"{store.get_aggregation(parent)['name']}{_LEGACY_SUFFIX}",
        agg_type="keyword", parent_id=parent)
    rid = _find_remainder_child(store, parent)
    assert rid == legacy
    assert store.get_aggregation(rid)["name"] == REMAINDER_NAME
