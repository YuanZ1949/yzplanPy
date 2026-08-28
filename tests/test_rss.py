import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from modules.rss_store import RssStore


def test_dedup_and_tags(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    store.add_feed("a", "http://a/rss", "站点A")
    store.add_feed("b", "http://b/rss", "站点B")

    entry = [{"title": "Same news", "link": "http://x/1", "published": "2026-01-01"}]
    assert store.ingest("站点A", entry) == 1
    assert store.ingest("站点B", entry) == 0

    recs = store.recent(10)
    assert len(recs) == 1
    tags = recs[0]["tags"]
    assert "站点A" in tags
    assert "站点B" in tags

    store.ingest("站点A", [{"title": "Other", "link": "http://x/2"}])
    assert len(store.recent(10)) == 2


def test_search(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    store.add_feed("tech", "http://tech/rss", "Tech")
    store.ingest("Tech", [
        {"title": "Python Tutorial", "link": "http://x/1", "description": "Learn Python"},
        {"title": "JavaScript Guide", "link": "http://x/2", "description": "Learn JS"},
    ])
    results = store.search("Python")
    assert len(results) == 1
    assert results[0]["title"] == "Python Tutorial"


def test_search_by_field(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    store.add_feed("tech", "http://tech/rss", "Tech")
    store.ingest("Tech", [
        {"title": "Article", "link": "http://x/1", "description": "Python content"},
    ])
    assert len(store.search("Python", field="title")) == 0
    assert len(store.search("Python", field="description")) == 1


def test_search_by_date(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    store.add_feed("a", "http://a/rss", "A")
    store.ingest("A", [
        {"title": "Old", "link": "http://x/1", "published": "2020-01-01"},
        {"title": "New", "link": "http://x/2", "published": "2099-12-31"},
    ])
    assert len(store.search("Old", date_to="2025-01-01")) == 1
    assert len(store.search("New", date_from="2025-01-01")) == 1


def test_favorites(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    store.add_feed("a", "http://a/rss", "A")
    store.ingest("A", [{"title": "Test", "link": "http://x/1"}])
    h = store.recent(10)[0]["hash"]

    assert not store.is_favorite(h)
    store.toggle_favorite(h)
    assert store.is_favorite(h)
    store.toggle_favorite(h)
    assert not store.is_favorite(h)


def test_favorite_note(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    store.add_feed("a", "http://a/rss", "A")
    store.ingest("A", [{"title": "Test", "link": "http://x/1"}])
    h = store.recent(10)[0]["hash"]
    store.toggle_favorite(h)
    store.set_favorite_note(h, "important note")
    assert store.is_favorite(h)


def test_batch_operations(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    store.add_feed("a", "http://a/rss", "A")
    store.ingest("A", [
        {"title": "Item1", "link": "http://x/1"},
        {"title": "Item2", "link": "http://x/2"},
        {"title": "Item3", "link": "http://x/3"},
    ])
    hashes = [item["hash"] for item in store.recent(10)]

    store.batch_mark_read(hashes[:2])
    assert store.is_read(hashes[0])
    assert store.is_read(hashes[1])
    assert not store.is_read(hashes[2])

    store.batch_mark_unread([hashes[0]])
    assert not store.is_read(hashes[0])


def test_batch_delete(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    store.add_feed("a", "http://a/rss", "A")
    store.ingest("A", [
        {"title": "Item1", "link": "http://x/1"},
        {"title": "Item2", "link": "http://x/2"},
    ])
    hashes = [item["hash"] for item in store.recent(10)]
    assert store.get_item_count() == 2
    store.batch_delete(hashes[:1])
    assert store.get_item_count() == 1


def test_categories(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    store.add_category("Tech", "#ff0000")
    store.add_category("News", "#00ff00")
    cats = store.get_categories()
    assert len(cats) == 2

    store.update_category(cats[0]["id"], name="Technology")
    cats = store.get_categories()
    assert any(c["name"] == "Technology" for c in cats)


def test_item_categories(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    store.add_feed("a", "http://a/rss", "A")
    store.ingest("A", [{"title": "Test", "link": "http://x/1"}])
    h = store.recent(10)[0]["hash"]
    store.add_category("Tech")
    cat_id = store.get_categories()[0]["id"]
    store.set_item_category(h, cat_id)
    assert len(store.get_item_categories(h)) == 1
    store.remove_item_category(h, cat_id)
    assert len(store.get_item_categories(h)) == 0


def test_filter_rules(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    store.add_filter_rule("skip ads", "title", "contains", "advertisement", "skip")
    rules = store.get_filter_rules()
    assert len(rules) == 1
    assert rules[0]["action"] == "skip"

    store.update_filter_rule(rules[0]["id"], enabled=False)
    rules = store.get_filter_rules()
    assert rules[0]["enabled"] == 0


def test_apply_filter_rules(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    store.add_filter_rule("skip ads", "title", "contains", "buy", "skip")
    store.add_filter_rule("tag python", "title", "contains", "python", "tag", "Python")
    entries = [
        {"title": "Ad: Buy now", "link": "http://x/1"},
        {"title": "Python Tutorial", "link": "http://x/2"},
    ]
    result = store.apply_filter_rules(entries)
    assert result[0].get("_skip") == True
    assert result[1].get("extra_tag") == "Python"


def test_keywords(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    store.add_keyword("urgent", "#ff0000", 1)
    store.add_keyword("important", "#00ff00", 1)
    kws = store.get_keywords()
    assert len(kws) == 2

    matched = store.check_keywords("This is urgent news", "")
    assert len(matched) == 1
    assert matched[0]["keyword"] == "urgent"


def test_read_history(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    store.add_feed("a", "http://a/rss", "A")
    store.ingest("A", [{"title": "Test", "link": "http://x/1"}])
    h = store.recent(10)[0]["hash"]

    assert len(store.get_read_history()) == 0
    store.mark_read(h)
    history = store.get_read_history()
    assert len(history) == 1
    assert history[0]["hash"] == h
    assert "read_at" in history[0]


def test_opml_export_import(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    store.add_feed("Feed1", "http://feed1.xml", "Tag1", "Group1")
    store.add_feed("Feed2", "http://feed2.xml", "Tag2", "Group2")

    opml = store.export_opml()
    assert "Feed1" in opml
    assert "Feed2" in opml

    store2 = RssStore(str(tmp_path / "t2.db"))
    count = store2.import_opml(opml)
    assert count == 2
    feeds = store2.list_feeds()
    assert len(feeds) == 2


def test_unread_count(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    assert store.get_unread_count() == 0
    store.add_feed("a", "http://a/rss", "A")
    store.ingest("A", [
        {"title": "Item1", "link": "http://x/1"},
        {"title": "Item2", "link": "http://x/2"},
    ])
    assert store.get_unread_count() == 2
    h = store.recent(10)[0]["hash"]
    store.mark_read(h)
    assert store.get_unread_count() == 1


def test_cleanup_old(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    store.add_feed("a", "http://a/rss", "A")
    store.ingest("A", [{"title": "Old", "link": "http://x/1", "published": "2020-01-01"}])
    assert store.get_item_count() == 1
    store.cleanup_old(365)
    assert store.get_item_count() == 0


def test_feed_error_tracking(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    store.add_feed("a", "http://a/rss", "A")
    fid = store.list_feeds()[0]["id"]

    store.set_feed_error(fid, "Connection timeout")
    feed = store.get_feed_by_id(fid)
    assert feed["last_error"] == "Connection timeout"
    assert feed["error_count"] == 1

    store.clear_feed_error(fid)
    feed = store.get_feed_by_id(fid)
    assert feed["last_error"] == ""
    assert feed["error_count"] == 0


def test_feed_order(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    store.add_feed("a", "http://a/rss", "A")
    store.add_feed("b", "http://b/rss", "B")
    store.add_feed("c", "http://c/rss", "C")

    feeds = store.list_feeds()
    ids = [f["id"] for f in feeds]
    store.update_feed_order([ids[2], ids[0], ids[1]])

    feeds = store.list_feeds()
    assert feeds[0]["name"] == "c"
    assert feeds[1]["name"] == "a"
    assert feeds[2]["name"] == "b"


def test_recent_date_range(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    store.add_feed("a", "http://a/rss", "A")
    today = datetime.now().strftime("%Y-%m-%d")
    store.ingest("A", [
        {"title": "Today", "link": "http://x/1", "published": today},
        {"title": "Old", "link": "http://x/2", "published": "2020-01-01"},
    ])
    assert len(store.recent(10, date_range="today")) == 1
    assert len(store.recent(10)) == 2


def test_get_related(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    store.add_feed("a", "http://a/rss", "A")
    store.ingest("A", [
        {"title": "Item1", "link": "http://x/1"},
        {"title": "Item2", "link": "http://x/2"},
    ])
    hashes = [item["hash"] for item in store.recent(10)]
    store.add_related(hashes[0], hashes[1], 0.8)
    related = store.get_related(hashes[0])
    assert len(related) == 1
    assert related[0]["similarity"] == 0.8


def test_share_item(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "t.db")
    store = RssStore(db)
    store.add_feed("a", "http://a/rss", "A")
    store.ingest("A", [{"title": "Test Title", "link": "http://x/1"}])
    h = store.recent(10)[0]["hash"]
    text = store.share_item(h)
    assert "Test Title" in text
    assert "http://x/1" in text
