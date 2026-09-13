"""RSS 数据层已确认缺陷（D5/D8/D17/D24 + D18/D20 级联）的 TDD 回归测试。

每个测试先写（RED），再改 modules/rss_store/store.py（GREEN）。
纯数据层测试，不依赖 Qt。
"""
import sqlite3
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from modules.rss_store import RssStore

_MAG_A = "magnet:?xt=urn:btih:" + "a" * 40 + "&dn=one"
_MAG_B = "magnet:?xt=urn:btih:" + "b" * 40 + "&dn=two"


# ── D5: FTS 索引无回填 ────────────────────────────────────────

def test_fts_backfill_on_old_db_upgrade(tmp_path, monkeypatch):
    """D5: 旧库（有存量 items、无 FTS 索引数据）升级后 search 能命中存量条目。

    模拟旧 schema：仅 items 表（无 items_fts / 无触发器），user_version=3。
    升级后 FTS 索引为空，再 ingest 一条同关键词新条目（触发器只对新行生效），
    若 FTS 未回填，search 部分命中时直接用 FTS id 不回退 → 存量条目被静默漏掉。
    """
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "old.db")
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA user_version = 3")
    conn.execute(
        """CREATE TABLE items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hash TEXT UNIQUE NOT NULL,
            title TEXT,
            link TEXT,
            published TEXT,
            description TEXT DEFAULT '',
            image_url TEXT DEFAULT '',
            read_time INTEGER DEFAULT 0
        )"""
    )
    conn.execute(
        "INSERT INTO items(hash,title,link,published,description) VALUES(?,?,?,?,?)",
        ("h_old", "Python 旧条目", "http://x/1", "2026-01-01", "旧库存量内容"),
    )
    conn.commit()
    conn.close()

    # 升级：打开 RssStore 触发迁移
    store = RssStore(db)
    # 升级后再 ingest 一条同关键词新条目（触发器只对新行生效）
    store.add_feed("tech", "http://tech/rss", "Tech")
    store.ingest("Tech", [{"title": "Python 新条目", "link": "http://x/2", "published": "2026-01-02"}])

    results = store.search("Python")
    titles = {r["title"] for r in results}
    assert "Python 旧条目" in titles, "存量条目必须被 FTS 回填命中"
    assert "Python 新条目" in titles


# ── D8: add_feed 用 INSERT OR REPLACE 静默重置源配置 ───────────

def test_add_feed_preserves_existing_config_on_duplicate_name(tmp_path, monkeypatch):
    """D8: 同名源重复 add_feed 不得重置 icon/etag/refresh_interval，且保留原 id（item_feeds 关联不丢）。"""
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    store.add_feed("站点A", "https://a.example/rss", tag="tA", refresh_interval=1800)
    fid = store.list_feeds()[0]["id"]
    store.set_feed_icon(fid, "base64:ICON")
    store.update_feed(fid, etag="etag-1", refresh_interval=3600)
    store.ingest("tA", [{"title": "文", "link": "https://a.example/p", "published": "2026",
                         "description": "", "image_url": ""}], feed_id=fid)

    # 同名重新 add_feed（模拟 OPML 重导入 / 重复添加）
    fid2 = store.add_feed("站点A", "https://a.example/rss", tag="tA")
    assert fid2 == fid, "同名 upsert 应保留原 id（item_feeds 关联不丢）"
    feed = store.get_feed_by_id(fid)
    assert feed is not None, "同名 upsert 后源应仍存在"
    assert feed["icon"] == "base64:ICON", "icon 不应被重置"
    assert feed["etag"] == "etag-1", "etag 不应被重置"
    assert feed["refresh_interval"] == 3600, "refresh_interval 不应被重置"
    assert len(store.recent(10, feed_ids=[fid])) == 1, "源范围查询仍应命中关联条目"


# ── D24: add_feed 无返回值 ────────────────────────────────────

def test_add_feed_returns_feed_id(tmp_path, monkeypatch):
    """D24: add_feed 返回新行 id（lastrowid），调用方可直接用作 feed_id。"""
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    fid = store.add_feed("站点A", "https://a.example/rss", tag="tA")
    assert isinstance(fid, int) and fid > 0, "add_feed 应返回 feed id"
    feed = store.get_feed_by_id(fid)
    assert feed is not None and feed["name"] == "站点A"
    # 同名 upsert 也返回同一 id
    fid2 = store.add_feed("站点A", "https://a.example/rss", tag="tA")
    assert fid2 == fid


# ── D17: record_item_torrent_links 只查首个链接 / 空 hash 覆盖 ─

def test_record_torrent_links_no_btih_preserves_existing_hash(tmp_path, monkeypatch):
    """D17: record_item_torrent_links 无 btih 时不得覆盖已有 torrent_hash，也不得置 hash_scan_state=2。"""
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    store.add_feed("f", "https://a.example/rss", tag="t")
    store.ingest("t", [{"title": "M", "link": _MAG_A, "published": "2026", "description": "", "image_url": ""}])
    h = store.recent(10)[0]["hash"]
    item = store.get_item(h)
    assert item is not None and item["torrent_hash"] == "a" * 40
    # 模拟待重扫状态（ingest 已置 state=2，重置为 0 表示条目仍可被再次扫描）
    store._conn().execute("UPDATE items SET hash_scan_state=0 WHERE hash=?", (h,))
    # 扫描到无 btih 的链接（如普通 .torrent 文件页）
    store.record_item_torrent_links(h, ["https://z.example/x.torrent", "https://z.example/y"])
    row = store._conn().execute(
        "SELECT torrent_hash, hash_scan_state FROM items WHERE hash=?", (h,)
    ).fetchone()
    assert row["torrent_hash"] == "a" * 40, "已有 torrent_hash 不应被空串覆盖"
    assert row["hash_scan_state"] == 0, "无 btih 时不应置 hash_scan_state=2（阻止重扫）"


def test_record_torrent_links_extracts_btih_from_any_link(tmp_path, monkeypatch):
    """D17: btih 在非首个链接时也应被提取（不只查 links[0]）。"""
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    store.add_feed("f", "https://a.example/rss", tag="t")
    store.ingest("t", [{"title": "M", "link": _MAG_A, "published": "2026", "description": "", "image_url": ""}])
    h = store.recent(10)[0]["hash"]
    # 首个链接无 btih，第二个链接有 btih
    store.record_item_torrent_links(h, ["https://z.example/x.torrent", _MAG_B])
    it = store.get_item(h)
    assert it is not None, "条目应存在"
    assert it["torrent_hash"] == "b" * 40, "应从非首个链接提取 btih"


# ── D20: remove_feed 级联清理 item_feeds ──────────────────────

def test_remove_feed_cleans_item_feeds(tmp_path, monkeypatch):
    """D20: remove_feed 须清理 item_feeds，删除后源范围查询不再含已删源条目。"""
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    store.add_feed("站点A", "https://a.example/rss", tag="tA")
    fid = store.list_feeds()[0]["id"]
    store.ingest("tA", [{"title": "文", "link": "https://a.example/p", "published": "2026",
                         "description": "", "image_url": ""}], feed_id=fid)
    assert len(store.recent(10, feed_ids=[fid])) == 1
    store.remove_feed(fid)
    assert store.get_feed_by_id(fid) is None
    assert len(store.recent(10, feed_ids=[fid])) == 0, "源范围查询不应再含已删源条目"
    row = store._conn().execute(
        "SELECT COUNT(*) AS c FROM item_feeds WHERE feed_id=?", (fid,)
    ).fetchone()
    assert row["c"] == 0, "item_feeds 关联行应被清理"


# ── D18: batch_delete 级联清理关联表 ──────────────────────────

def test_batch_delete_cleans_association_tables(tmp_path, monkeypatch):
    """D18: batch_delete 须清理 item_feeds / aggregation_items / item_torrent_links / item_related。"""
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    store.add_feed("站点A", "https://a.example/rss", tag="tA")
    fid = store.list_feeds()[0]["id"]
    store.ingest("tA", [{"title": "文", "link": "https://a.example/p", "published": "2026",
                         "description": "", "image_url": ""}], feed_id=fid)
    h = store.recent(10)[0]["hash"]
    # 建立各类关联
    store.record_item_torrent_links(h, [_MAG_A])
    store.add_related(h, "other-hash", 0.5)
    aid = store.add_aggregation("聚合", agg_type="mixed", feed_ids=[fid])
    store.refresh_aggregation(aid)
    store.add_category("Cat")
    cat_id = store.get_categories()[0]["id"]
    store.set_item_category(h, cat_id)
    store.toggle_favorite(h)
    store.mark_read(h)

    conn = store._conn()
    assert conn.execute("SELECT COUNT(*) AS c FROM item_feeds WHERE hash=?", (h,)).fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) AS c FROM aggregation_items WHERE hash=?", (h,)).fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) AS c FROM item_torrent_links WHERE hash=?", (h,)).fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) AS c FROM item_related WHERE hash1=? OR hash2=?", (h, h)).fetchone()["c"] == 1

    # 批量删除
    store.batch_delete([h])
    assert store.get_item(h) is None
    assert conn.execute("SELECT COUNT(*) AS c FROM item_feeds WHERE hash=?", (h,)).fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM aggregation_items WHERE hash=?", (h,)).fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM item_torrent_links WHERE hash=?", (h,)).fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM item_related WHERE hash1=? OR hash2=?", (h, h)).fetchone()["c"] == 0